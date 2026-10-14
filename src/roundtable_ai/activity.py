"""What each AI is doing right now: its thinking, the commands it runs, the files it edits.

Three sources, all local and read-only:
- background runs (`rt run`): Roundtable reads the app's own event stream as it
  happens (claude -p --output-format stream-json, codex exec --json) and keeps
  the steps in .roundtable/activity/<seat>.jsonl;
- Claude Code chats: the session transcript (~/.claude/projects/...), found from
  the status line Roundtable gives the seat, or from its working copy;
- Codex chats: the session log (~/.codex/sessions/...) whose folder is the seat's
  working copy.

Every source is turned into the same small items:
    {"t": epoch, "kind": think|say|run|edit|read|tool|done|error|start, "text": "..."}
Nothing here ever raises: activity is a nice-to-have, never a reason to fail.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Iterable

MAX_TEXT = 4000            # one item's text (thinking can be long; the dashboard folds it)
ACTIVITY_MAX_BYTES = 1_500_000
TAIL_BYTES = 400_000
FRESH_SECONDS = 3 * 3600   # a chat transcript older than this is not "now"

_cache: dict[str, tuple[float, int, list[dict]]] = {}


def _clip(text: Any, n: int = MAX_TEXT) -> str:
    s = str(text or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _short_path(p: Any, root: str | None = None) -> str:
    s = str(p or "")
    if root and s.startswith(root.rstrip("/\\") + os.sep):
        s = s[len(root.rstrip("/\\")) + 1:]
    return s


def _ts(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value:
        from . import util

        try:
            return util.parse_time(value).timestamp()
        except Exception:
            return None
    return None


# ---------------------------------------------------------------- Claude Code (stream-json and transcripts share one shape)

def _claude_tool(name: str, inp: dict, root: str | None) -> dict:
    name = name or "tool"
    inp = inp if isinstance(inp, dict) else {}
    if name == "Bash":
        return {"kind": "run", "text": _clip(inp.get("command"), 600)}
    if name in ("Edit", "MultiEdit", "Write", "NotebookEdit"):
        return {"kind": "edit", "text": _short_path(inp.get("file_path") or inp.get("notebook_path"), root)}
    if name == "Read":
        return {"kind": "read", "text": _short_path(inp.get("file_path"), root)}
    if name in ("Grep", "Glob"):
        return {"kind": "read", "text": f"search {inp.get('pattern', '')}"}
    if name.startswith("mcp__"):
        tool = name.split("__")[-1]
        bits = [str(inp.get(k)) for k in ("action", "task", "draft", "id") if inp.get(k)]
        return {"kind": "tool", "text": " ".join([tool, *bits])}
    if name in ("TodoWrite", "TaskCreate", "TaskUpdate"):
        return {"kind": "think", "text": "updating its to-do list"}
    if name in ("WebSearch", "WebFetch"):
        return {"kind": "read", "text": f"{name}: {inp.get('query') or inp.get('url') or ''}"}
    return {"kind": "tool", "text": name}


def from_claude(ev: dict, root: str | None = None) -> list[dict]:
    """One line of Claude Code output (stream-json or transcript) -> items."""
    out: list[dict] = []
    t = ev.get("type")
    when = _ts(ev.get("timestamp"))
    if t == "system" and ev.get("subtype") == "init":
        out.append({"kind": "start", "text": f"started ({ev.get('model') or 'model'})"})
    elif t == "system" and ev.get("subtype") == "api_retry":
        out.append({"kind": "error", "text": f"the API is busy ({ev.get('error') or 'retrying'}); retrying"})
    elif t == "assistant":
        if ev.get("parent_tool_use_id"):
            return []
        for block in (ev.get("message") or {}).get("content") or []:
            if not isinstance(block, dict):
                continue
            bt = block.get("type")
            if bt == "thinking" and block.get("thinking"):
                out.append({"kind": "think", "text": _clip(block["thinking"])})
            elif bt == "text" and block.get("text", "").strip():
                out.append({"kind": "say", "text": _clip(block["text"])})
            elif bt == "tool_use":
                out.append(_claude_tool(block.get("name", ""), block.get("input") or {}, root))
    elif t == "user":
        for block in (ev.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error"):
                content = block.get("content")
                if isinstance(content, list):
                    content = " ".join(str(c.get("text", "")) for c in content if isinstance(c, dict))
                first = str(content or "").strip().splitlines()[:1]
                out.append({"kind": "error", "text": _clip(first[0] if first else "a step failed", 300)})
    elif t == "result":
        if ev.get("is_error") or (ev.get("subtype") and ev.get("subtype") != "success"):
            out.append({"kind": "error", "text": _clip(ev.get("result") or ev.get("subtype") or "the run failed", 400)})
        else:
            turns = ev.get("num_turns")
            out.append({"kind": "done", "text": _clip(ev.get("result") or "finished", 600) + (f" ({turns} steps)" if turns else "")})
    for item in out:
        if when:
            item["t"] = when
    return out


# ---------------------------------------------------------------- Codex (exec --json and session logs)

def _codex_command(cmd: Any) -> str:
    if isinstance(cmd, list):
        if len(cmd) >= 3 and cmd[0] in ("bash", "sh", "zsh", "/bin/bash", "/bin/sh") and cmd[1] in ("-lc", "-c"):
            return str(cmd[2])
        return " ".join(str(c) for c in cmd)
    return str(cmd or "")


def from_codex_exec(ev: dict, root: str | None = None) -> list[dict]:
    """One line of `codex exec --json` -> items."""
    t = ev.get("type")
    if t == "thread.started":
        return [{"kind": "start", "text": "started"}]
    if t in ("turn.failed", "error"):
        err = ev.get("error") if isinstance(ev.get("error"), dict) else {}
        return [{"kind": "error", "text": _clip(err.get("message") or ev.get("message") or "the run failed", 400)}]
    if t == "turn.completed":
        return [{"kind": "done", "text": "finished its turn"}]
    if t not in ("item.started", "item.completed"):
        return []
    item = ev.get("item") or {}
    it = item.get("type") or item.get("item_type")
    if it == "command_execution":
        if t == "item.started":
            return [{"kind": "run", "text": _clip(_codex_command(item.get("command")), 600)}]
        code = item.get("exit_code")
        return [{"kind": "error", "text": f"command failed (exit {code}): {_clip(_codex_command(item.get('command')), 200)}"}] if code not in (None, 0) else []
    if t != "item.completed":
        if it == "mcp_tool_call":
            return [{"kind": "tool", "text": " ".join(x for x in (str(item.get("tool") or ""), _mcp_args(item.get("arguments"))) if x)}]
        return []
    if it == "reasoning" and (item.get("text") or "").strip():
        return [{"kind": "think", "text": _clip(item["text"])}]
    if it in ("agent_message", "assistant_message") and (item.get("text") or "").strip():
        return [{"kind": "say", "text": _clip(item["text"])}]
    if it == "file_change":
        paths = [_short_path(c.get("path"), root) for c in item.get("changes") or [] if isinstance(c, dict)]
        return [{"kind": "edit", "text": ", ".join(paths) or "files"}]
    if it == "web_search":
        return [{"kind": "read", "text": f"web search: {item.get('query', '')}"}]
    if it in ("todo_list", "plan_update"):
        steps = item.get("items") or []
        now = next((s.get("text") for s in steps if isinstance(s, dict) and not s.get("completed")), None)
        return [{"kind": "think", "text": f"next on its list: {now}" if now else "updated its plan"}]
    if it == "error":
        return [{"kind": "error", "text": _clip(item.get("message"), 400)}]
    return []


def _mcp_args(args: Any) -> str:
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return ""
    if not isinstance(args, dict):
        return ""
    return " ".join(str(args[k]) for k in ("action", "task", "draft", "id") if args.get(k))


def from_codex_log(ev: dict, root: str | None = None) -> list[dict]:
    """One line of a Codex session log (~/.codex/sessions/.../rollout-*.jsonl) -> items."""
    when = _ts(ev.get("timestamp"))
    pl = ev.get("payload") or {}
    kind, out = ev.get("type"), []
    if kind == "event_msg":
        pt = pl.get("type")
        if pt == "agent_reasoning" and pl.get("text"):
            out.append({"kind": "think", "text": _clip(pl["text"])})
        elif pt == "agent_message" and pl.get("message"):
            out.append({"kind": "say", "text": _clip(pl["message"])})
        elif pt == "exec_command_begin":
            out.append({"kind": "run", "text": _clip(_codex_command(pl.get("command")), 600)})
        elif pt == "patch_apply_begin":
            changes = pl.get("changes") or {}
            out.append({"kind": "edit", "text": ", ".join(_short_path(p, root) for p in changes) or "files"})
        elif pt == "mcp_tool_call_begin":
            inv = pl.get("invocation") or {}
            out.append({"kind": "tool", "text": " ".join(x for x in (str(inv.get("tool") or ""), _mcp_args(inv.get("arguments"))) if x)})
        elif pt == "task_complete":
            out.append({"kind": "done", "text": _clip(pl.get("last_agent_message") or "finished its turn", 600)})
    for item in out:
        if when:
            item["t"] = when
    return out


# ---------------------------------------------------------------- files

def _tail(path: Path, max_bytes: int = TAIL_BYTES) -> list[str]:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes))
            data = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = data.splitlines()
    return lines[1:] if size > max_bytes else lines   # the first line may be cut


def _parse(lines: Iterable[str], fn, root: str | None) -> list[dict]:
    out: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict):
            try:
                out.extend(fn(ev, root))
            except Exception:
                continue
    return out


def _cached(path: Path, fn, root: str | None) -> tuple[float, list[dict]]:
    try:
        st = path.stat()
    except OSError:
        return 0.0, []
    key = f"{path}:{fn.__name__}"
    hit = _cache.get(key)
    if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
        return st.st_mtime, hit[2]
    items = _parse(_tail(path), fn, root)
    for it in items:
        it.setdefault("t", st.st_mtime)
    _cache[key] = (st.st_mtime, st.st_size, items)
    if len(_cache) > 64:
        _cache.pop(next(iter(_cache)))
    return st.st_mtime, items


def activity_file(home: Path, seat: str) -> Path:
    return Path(home) / "activity" / f"{seat}.jsonl"


def append(home: Path, seat: str, items: list[dict]) -> None:
    """Background runs write their steps here (rotated at ~1.5 MB)."""
    if not items:
        return
    path = activity_file(home, seat)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > ACTIVITY_MAX_BYTES:
            path.replace(path.with_suffix(".jsonl.1"))
        now = time.time()
        with open(path, "a", encoding="utf-8") as fh:
            for it in items:
                fh.write(json.dumps({"t": it.get("t") or now, "kind": it["kind"], "text": it.get("text", "")}) + "\n")
    except OSError:
        pass


def _own(ev: dict, root: str | None) -> list[dict]:
    if ev.get("kind") and "text" in ev:
        return [{"t": ev.get("t"), "kind": ev["kind"], "text": ev.get("text", "")}]
    return []


def claude_project_dir(folder: str | Path) -> Path:
    """Where Claude Code keeps transcripts of chats started in `folder`."""
    base = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
    return base / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(Path(folder).resolve()))


def _newest(folder: Path, pattern: str = "*.jsonl") -> Path | None:
    try:
        files = [p for p in folder.glob(pattern) if p.is_file()]
    except OSError:
        return None
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def _codex_log_for(folder: str) -> Path | None:
    try:
        from . import usage

        return usage.codex_session_file(folder)
    except Exception:
        return None


def recent(ctx, row, n: int = 40) -> dict[str, Any]:
    """The latest steps of one seat, from the freshest source."""
    try:
        return _recent(ctx, row, n)
    except Exception:
        return {"source": None, "items": [], "updated": None}


def _recent(ctx, row, n: int) -> dict[str, Any]:
    from . import runner, usage

    handle = row["handle"]
    root = row["worktree"] or str(ctx.root)
    candidates: list[tuple[float, str, list[dict]]] = []
    own = activity_file(ctx.home, handle)
    if own.exists():
        m, items = _cached(own, _own, root)
        if runner.is_running(ctx.home, handle):
            m = time.time()   # a live background run always wins
        candidates.append((m, "background run", items))
    if row["app"] in ("claude-code", "claude-vscode"):
        snap = usage.load_snapshot(ctx.home, handle) or {}
        path = Path(snap["transcript_path"]) if snap.get("transcript_path") else _newest(claude_project_dir(root))
        if path and path.exists():
            m, items = _cached(path, from_claude, root)
            candidates.append((m, "its Claude Code chat", items))
    if row["app"] in ("codex-cli", "codex-vscode", "codex-app") and row["worktree"]:
        path = _codex_log_for(row["worktree"])
        if path:
            m, items = _cached(path, from_codex_log, root)
            candidates.append((m, "its Codex chat", items))
    if not candidates:
        return {"source": None, "items": [], "updated": None}
    m, source, items = max(candidates, key=lambda c: c[0])
    if source != "background run" and time.time() - m > FRESH_SECONDS:
        return {"source": source, "items": items[-n:], "updated": m, "stale": True}
    return {"source": source, "items": items[-n:], "updated": m}

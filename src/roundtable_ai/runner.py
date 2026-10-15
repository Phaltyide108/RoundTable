"""Background runs: Roundtable starts a seat's app for it whenever there is work.

Models only act when something starts them. Instead of keeping a terminal open
and typing "check roundtable", `rt run <seat>` (or "Run in the background" in
the dashboard) watches the table for this seat and, whenever it has work, runs
its app headless with your own login:

    claude -p "<what to do>" --output-format stream-json --verbose ...
    codex exec --json ... "<what to do>"

It reads the app's event stream as it happens (thinking, commands, edits) into
.roundtable/activity/<seat>.jsonl for the dashboard, keeps the session so the
next run continues the same conversation, then waits for the next piece of work.

Safety and failure handling:
- one runner per seat (a heartbeat in .roundtable/runs/<seat>.json);
- nothing runs while the human has paused everyone, or this seat;
- a run that changes nothing on the table is not repeated at once: the wait
  doubles (1 min ... 30 min) and the dashboard says it is stuck and why;
- a run is stopped after runner.max_minutes; a stop request ends the current run;
- tools: by default the app may edit files in its own working copy, use the
  Roundtable tools, git and the project's own test commands; other commands are
  refused (runner.permissions = "all" lets it run anything).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from . import activity, util
from .errors import CONFLICT, INVALID, NOT_FOUND, STATE, RTError

HEARTBEAT_SECONDS = 4
ALIVE_SECONDS = 25
POLL_SECONDS = 3
BACKOFF_START = 60
BACKOFF_MAX = 30 * 60
CONTINUE_SECONDS = 20     # the same work is still open after a run that did something
SAME_WORK_RUNS = 3        # ... at most this many times in a row, then it counts as stuck
SUPPORTED = ("claude-code", "codex-cli", "opencode")

SAFE_TOOLS = ["mcp__roundtable", "Read", "Edit", "Write", "MultiEdit", "Glob", "Grep", "TodoWrite",
              "Bash(git status *)", "Bash(git diff *)", "Bash(git log *)", "Bash(git show *)", "Bash(git add *)",
              "Bash(git commit *)", "Bash(ls *)", "Bash(cat *)", "Bash(pwd)"]


# ---------------------------------------------------------------- state files

def runs_dir(home: Path) -> Path:
    return Path(home) / "runs"


def state_path(home: Path, seat: str) -> Path:
    return runs_dir(home) / f"{seat}.json"


def stop_path(home: Path, seat: str) -> Path:
    return runs_dir(home) / f"{seat}.stop"


def read_state(home: Path, seat: str) -> dict[str, Any]:
    try:
        return json.loads(state_path(home, seat).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_state(home: Path, seat: str, state: dict[str, Any]) -> None:
    path = state_path(home, seat)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".json.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def _pid_alive(pid: Any) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def is_running(home: Path, seat: str) -> bool:
    st = read_state(home, seat)
    if not st or st.get("state") == "stopped":
        return False
    beat = float(st.get("heartbeat") or 0)
    return time.time() - beat < ALIVE_SECONDS and _pid_alive(st.get("pid"))


def status(home: Path, seat: str) -> dict[str, Any]:
    """What the dashboard shows about a seat's background runner."""
    st = read_state(home, seat)
    if not st:
        return {"running": False}
    running = is_running(home, seat)
    out = {k: st.get(k) for k in ("state", "since", "message", "runs", "last_run", "work", "started", "tokens", "error", "limited_until")}
    out["running"] = running
    if not running and st.get("state") not in ("stopped", None):
        out["state"] = "stopped"
        out["message"] = st.get("message") or "the background runner is not running"
    return out


# ---------------------------------------------------------------- out of usage

# Only the apps' own "you are out of usage" messages: a model talking about a "turn rate limit" in its code is not one.
LIMIT_WORDS = re.compile(r"(?:you(?:'ve| have)|you've) (?:hit|reached|exceeded) (?:your|the) [\w -]{0,24}limit"
                         r"|(?:usage|session|weekly|daily|5-hour|hourly) limit (?:reached|exceeded|hit)"
                         r"|rate limit (?:reached|exceeded)|out of (?:credits|usage)|quota (?:exceeded|reached)"
                         r"|limit (?:reached|exceeded)[.;,]? (?:\w+ ){0,6}(?:resets?|try again)", re.I)


def limit_until(text: str | None, now: float | None = None) -> float | None:
    """When an app's "you've hit your limit" message says it resets (epoch seconds); None when it is not such a message.
    Understands "resets 9:20pm", "try again at 21:20", "try again in 2 hours 5 minutes"; otherwise assumes 30 minutes."""
    if not text or not LIMIT_WORDS.search(text):
        return None
    now = time.time() if now is None else now
    m = re.search(r"(?:resets?|try again|available again)\s+(?:at\s+|after\s+)?(\d{1,2})(?::(\d{2}))?\s*([ap]\.?m\.?)?(?![\d%])", text, re.I)
    if m and (m.group(2) or m.group(3)):
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        if m.group(3):
            hour = hour % 12 + (12 if m.group(3).lower().startswith("p") else 0)
        if hour < 24 and minute < 60:
            lt = time.localtime(now)
            target = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, hour, minute, 0, 0, 0, -1))
            return target + 86400 if target <= now else target
    for m in re.finditer(r"\bin\s+(?:(\d+)\s*(?:hours?|hrs?|h)\b)?\s*(?:and\s+)?(?:(\d+)\s*(?:minutes?|mins?|m)\b)?", text, re.I):
        if m.group(1) or m.group(2):
            return now + int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60
    return now + 30 * 60


# ---------------------------------------------------------------- what to do

def pending(ctx, handle: str, seen_note: str = "") -> list[tuple[str, str]]:
    """(key, sentence) for every piece of work waiting for this seat right now."""
    from . import inbox, seats

    row = ctx.db.one("SELECT * FROM seats WHERE handle = ?", (handle,))
    if row is None or row["status"] != "active" or ctx.db.meta_get("frozen", "0") == "1":
        return []
    c = inbox.counts(ctx, handle)
    out: list[tuple[str, str]] = []
    if c["plan"]:
        p = ctx.db.one("SELECT id, stage, version, goal FROM plans WHERE stage NOT IN ('done','cancelled') ORDER BY id DESC LIMIT 1")
        goal = f" for this goal (the human's words, in full): «{util.one_line(p['goal'], 1500)}»" if p else ""
        out.append((f"plan:{p['id'] if p else ''}:{p['stage'] if p else ''}:{p['version'] if p else ''}",
                    f"{c['plan']}{goal}; rt_plan view shows how"))
    for a in c["alerts"]:
        out.append((f"alert:{a['id']}", f"acknowledge problem {a['id']} (level {a['level']}): {a['title']}"))
    for key, label in (("reviews", "review"), ("critiques", "critique"), ("suggestions", "suggestion"),
                       ("comments", "open review comment"), ("votes", "vote")):
        if c[key]:
            out.append((f"{key}:{c[key]}:{_assign_sig(ctx, handle, key)}", f"{c[key]} {label}{'s' if c[key] != 1 else ''} for you"))
    roles = seats.roles_of(row)
    mine = ctx.db.all("SELECT id, status, title FROM tasks WHERE owner = ? AND status IN ('claimed','changes_requested') ORDER BY priority, seq", (handle,))
    for t in mine:
        if _waiting_on_others(ctx, handle, t["id"]):
            continue        # it asked for a change or raised a problem about this task: wake it when that is settled
        what = "fix the review notes on" if t["status"] == "changes_requested" else "finish"
        out.append((f"task:{t['id']}:{t['status']}", f"{what} {t['id']}: {t['title']}"))
    if "build" in roles and not mine:
        busy = ctx.db.one("SELECT 1 FROM tasks WHERE owner = ? AND status IN ('proving','in_review','merge_blocked')", (handle,))
        rows = ctx.db.all("SELECT t.id, t.title, t.owner, s.status AS owner_status FROM tasks t LEFT JOIN seats s ON s.handle = t.owner "
                          "WHERE t.status = 'ready' ORDER BY t.priority, t.seq, t.id")
        claimable = [r for r in rows if r["owner"] in (None, "", handle) or r["owner_status"] != "active"]
        if claimable and not busy:
            ids = ", ".join(r["id"] for r in claimable[:3])
            out.append((f"ready:{ids}", f"claim a ready task and build it ({ids})"))
    for n in _new_human_notes(ctx, seen_note):
        out.append((f"note:{n['id']}", f"the human wrote to the team: «{util.one_line(n['text'], 300)}»"))
    return out


def _waiting_on_others(ctx, handle: str, task_id: str) -> bool:
    if ctx.db.one("SELECT 1 FROM amendments WHERE task = ? AND proposed_by = ? AND status = 'pending'", (task_id, handle)):
        return True
    for a in ctx.db.all("SELECT tasks FROM alerts WHERE raised_by = ? AND status = 'open' AND level >= 3", (handle,)):
        if task_id in util.jload(a["tasks"], []):
            return True
    return False


def _assign_sig(ctx, handle: str, key: str) -> str:
    kind = {"reviews": "review", "critiques": "critique"}.get(key)
    if not kind:
        return ""
    rows = ctx.db.all("SELECT id FROM assignments WHERE seat = ? AND kind = ? AND status = 'open' ORDER BY id", (handle, kind))
    return ",".join(str(r["id"]) for r in rows)


def _new_human_notes(ctx, seen: str) -> list:
    rows = ctx.db.all("SELECT id, text, created_at FROM memories WHERE author = 'human' AND status = 'active' ORDER BY created_at")
    if not seen:
        return []
    return [r for r in rows if r["created_at"] > seen]


def latest_note_time(ctx) -> str:
    return ctx.db.scalar("SELECT MAX(created_at) FROM memories WHERE author = 'human'", default="") or ""


def prompt_for(handle: str, work: list[tuple[str, str]]) -> str:
    lines = [f"You are Roundtable seat {handle}, started in the background by Roundtable. No human is reading this chat.",
             "Roundtable woke you because:"]
    lines += [f"- {text}" for _key, text in work]
    lines += ["Call the rt_sync tool now and follow the Roundtable rules it returns. Do all of the above with the rt_* tools "
              "(draft, critique, propose, approve, claim, checkpoint, close, review, ack) until none of it is left or you are blocked.",
              "If the human asked a question, answer it in one short line with rt_memory add.",
              "Never wait for a reply in this chat. Finish with one line saying what you did."]
    return "\n".join(lines)


# ---------------------------------------------------------------- the command

def _proof_prefixes(ctx) -> list[str]:
    """Let the app run this project's own test commands (first two words), e.g. Bash(uv run *)."""
    out: list[str] = []
    for r in ctx.db.all("SELECT proof FROM tasks WHERE status NOT IN ('done','cancelled')"):
        for cmd in util.jload(r["proof"], []):
            words = str(cmd).split()
            if not words:
                continue
            prefix = " ".join(words[:2]) if len(words) > 1 and not words[1].startswith("-") else words[0]
            rule = f"Bash({prefix} *)"
            if rule not in out and all(ch not in prefix for ch in "|;&`$><"):
                out.append(rule)
    return out[:20]


def headless_command(ctx, row, prompt: str, session: str | None) -> tuple[list[str], Path]:
    from . import appsetup, launch

    handle, app, model = row["handle"], row["app"], row["model"]
    cwd = launch._workdir(ctx, row)
    effort = launch._effort(row)
    everything = ctx.setting("runner", "permissions") == "all"
    if app == "claude-code":
        cfg = appsetup.seat_mcp_file(ctx, handle)
        cmd = [launch._exe("claude"), "-p", prompt, "--output-format", "stream-json", "--verbose", "--model", model]
        if effort:
            cmd += ["--effort", effort]
        if session:
            cmd += ["--resume", session]
        cmd += ["--append-system-prompt", launch.system_note(handle)]
        if everything:
            cmd += ["--permission-mode", "bypassPermissions"]
        else:
            cmd += ["--permission-mode", "acceptEdits", "--allowedTools", ",".join(SAFE_TOOLS + _proof_prefixes(ctx))]
        return cmd + ["--mcp-config", str(cfg)], cwd
    if app == "codex-cli":
        from .config import toml_value

        # verified with codex-cli 0.162: `exec resume <id>` takes --json, -m, -c and --skip-git-repo-check but not -C or -s,
        # so the folder comes from the working directory and the sandbox from -c sandbox_mode
        sandbox = "danger-full-access" if everything else "workspace-write"
        cmd = [launch._exe("codex"), "exec"] + (["resume", session] if session else [])
        cmd += ["--json", "-m", model, "--skip-git-repo-check", "-c", f"sandbox_mode={toml_value(sandbox)}"]
        if not session:
            cmd += ["-C", str(cwd)]
        cmd += launch._codex_overrides(ctx, handle)
        if effort:
            cmd += ["-c", f"model_reasoning_effort={toml_value(effort)}"]
        return cmd + [prompt], cwd
    if app == "opencode":
        # opencode run has no system-prompt flag: the seat note leads the prompt. Roundtable's connection and the
        # permissions come in through OPENCODE_CONFIG_CONTENT (headless_env), so no file in the folder changes.
        cmd = [launch._exe("opencode"), "run", "--format", "json", "--thinking", "--dir", str(cwd), "-m", model]
        if effort:
            cmd += ["--variant", effort]
        if session:
            cmd += ["--session", session]
        if everything:
            cmd += ["--auto"]
        return cmd + [launch.system_note(handle) + "\n\n" + prompt], cwd
    raise RTError(INVALID, f"Roundtable can't run {app} in the background", "start it in its app instead (rt launch shows how)")


def headless_env(ctx, row) -> dict[str, str]:
    """Extra environment for a background run (opencode: Roundtable's MCP server and what it may do)."""
    if row["app"] != "opencode":
        return {}
    from . import appsetup

    cmd, args = appsetup.server_command()
    if ctx.setting("runner", "permissions") == "all":
        perms: dict[str, Any] = {"edit": "allow", "bash": "allow", "webfetch": "allow"}
    else:
        bash: dict[str, str] = {"*": "deny"}
        for rule in [r[5:-1] for r in SAFE_TOOLS + _proof_prefixes(ctx) if r.startswith("Bash(")]:
            bash[rule.replace(" *", "*")] = "allow"
        perms = {"edit": "allow", "bash": bash, "webfetch": "deny"}
    cfg = {"$schema": "https://opencode.ai/config.json",
           "mcp": {"roundtable": {"type": "local", "command": [cmd, *args], "enabled": True,
                                  "environment": {"RT_HOME": str(ctx.home), "RT_SEAT": row["handle"]}}},
           "permission": perms}
    return {"OPENCODE_CONFIG_CONTENT": json.dumps(cfg)}


# ---------------------------------------------------------------- one run

KEEP_ENV = {"CLAUDE_CONFIG_DIR", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
            "CLAUDE_CODE_USE_FOUNDRY", "CLAUDE_CODE_GIT_BASH_PATH", "CLAUDE_CODE_MAX_OUTPUT_TOKENS"}


def clean_env(base) -> dict[str, str]:
    """The environment for an app Roundtable starts: without the variables of a Claude Code session
    that `rt ui` itself may have been started from (they would tie the new run to that session)."""
    return {k: v for k, v in base.items()
            if k in KEEP_ENV or not (k.startswith("CLAUDE_") or k == "CLAUDECODE" or k.startswith("RT_SEAT"))}


def _parse_line(app: str, line: str, root: str) -> tuple[list[dict], dict]:
    """(activity items, facts) for one line of the app's output."""
    try:
        ev = json.loads(line)
    except ValueError:
        return [], {}
    if not isinstance(ev, dict):
        return [], {}
    facts: dict[str, Any] = {}
    if app == "claude-code":
        if ev.get("session_id"):
            facts["session"] = ev["session_id"]
        if ev.get("type") == "result":
            u = ev.get("usage") or {}
            # new tokens only: cache reads repeat the same context on every step and would count it many times over
            facts["tokens"] = int(u.get("input_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0) + int(u.get("output_tokens") or 0)
            facts["cost"] = ev.get("total_cost_usd")
            facts["error"] = bool(ev.get("is_error"))
        if ev.get("type") == "rate_limit_event":
            facts["limit"] = ev.get("rate_limit_info") or {}
        return activity.from_claude(ev, root), facts
    if app == "opencode":
        if ev.get("sessionID"):
            facts["session"] = ev["sessionID"]
        if ev.get("type") == "step_finish":
            tk = ((ev.get("part") or {}).get("tokens") or {})
            cache = tk.get("cache") if isinstance(tk.get("cache"), dict) else {}
            facts["tokens_add"] = sum(int(tk.get(k) or 0) for k in ("input", "output", "reasoning")) + int(cache.get("write") or 0)
        if ev.get("type") == "error":
            facts["error"] = True
        return activity.from_opencode(ev, root), facts
    if ev.get("type") == "thread.started" and ev.get("thread_id"):
        facts["session"] = ev["thread_id"]
    if ev.get("type") == "turn.completed":
        u = ev.get("usage") or {}
        fresh = max(0, int(u.get("input_tokens") or 0) - int(u.get("cached_input_tokens") or 0))
        facts["tokens"] = fresh + int(u.get("output_tokens") or 0)
    if ev.get("type") in ("turn.failed", "error"):
        facts["error"] = True
    return activity.from_codex_exec(ev, root), facts


def _seat_events(ctx, handle: str) -> int:
    return ctx.db.scalar("SELECT COUNT(*) FROM events WHERE actor = ?", (handle,), 0)


def _kill(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        else:
            os.killpg(proc.pid, signal.SIGTERM)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    try:
        proc.wait(timeout=10)
    except Exception:
        pass


def run_once(ctx, row, work: list[tuple[str, str]], state: dict[str, Any], *, should_stop=lambda: False) -> dict[str, Any]:
    """Run the seat's app once for `work`. Returns facts about the run."""
    handle, app = row["handle"], row["app"]
    session = state.get("session") if state.get("resume_ok", True) else None
    prompt = prompt_for(handle, work)
    cmd, cwd = headless_command(ctx, row, prompt, session)
    env = clean_env(os.environ)
    env.update({"RT_SEAT": handle, "RT_HOME": str(ctx.home)})
    env.update(headless_env(ctx, row))
    log = ctx.home / "logs" / f"run-{handle}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {"cwd": str(cwd), "env": env, "stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000200 | 0x08000000   # new process group, no window
    else:
        kwargs["start_new_session"] = True
    activity.append(ctx.home, handle, [{"kind": "start", "text": "woke up: " + "; ".join(t for _k, t in work)[:600]}])
    facts: dict[str, Any] = {"lines": 0}
    started = time.time()
    limit = max(1, int(ctx.setting("runner", "max_minutes"))) * 60
    with open(log, "ab") as errlog:
        errlog.write(f"\n--- {util.now()} {' '.join(cmd[:3])} ...\n".encode())
        errlog.flush()
        proc = subprocess.Popen(cmd, stderr=errlog, **kwargs)
        state["child"] = proc.pid
        timer = threading.Timer(limit, lambda: _kill(proc))
        timer.daemon = True
        timer.start()
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                facts["lines"] += 1
                items, f = _parse_line(app, line, str(cwd))
                if "tokens_add" in f:
                    facts["tokens"] = int(facts.get("tokens") or 0) + int(f.pop("tokens_add") or 0)
                facts.update({k: v for k, v in f.items() if v is not None})
                if items:
                    activity.append(ctx.home, handle, items)
                    said = [i["text"] for i in items if i.get("kind") in ("say", "done") and i.get("text")]
                    if said:
                        facts["last_say"] = said[-1]
                    for i in items:
                        if i.get("kind") in ("say", "done", "error") and not facts.get("limit_until"):
                            facts["limit_until"] = limit_until(i.get("text"))
                            if facts["limit_until"]:
                                facts["limit_text"] = util.one_line(i.get("text") or "", 200)
                if should_stop():
                    _kill(proc)
                    facts["stopped"] = True
                    break
            proc.wait()
        finally:
            timer.cancel()
    facts["exit"] = proc.returncode
    facts["seconds"] = round(time.time() - started, 1)
    if time.time() - started >= limit:
        facts["timed_out"] = True
        activity.append(ctx.home, handle, [{"kind": "error", "text": f"stopped after {limit // 60} minutes (runner.max_minutes)"}])
    if proc.returncode not in (0, None) and not facts.get("stopped"):
        tail = _log_tail(log)
        facts["error_text"] = tail
        if not facts.get("limit_until") and limit_until(tail):
            facts["limit_until"], facts["limit_text"] = limit_until(tail), util.one_line(tail, 200)
        if facts["lines"] == 0:
            activity.append(ctx.home, handle, [{"kind": "error", "text": "the app did not start: " + (tail or f"exit {proc.returncode}")}])
    state.pop("child", None)
    return facts


def _log_tail(path: Path, n: int = 3) -> str:
    try:
        lines = [x for x in path.read_text(encoding="utf-8", errors="replace").splitlines() if x.strip() and not x.startswith("---")]
    except OSError:
        return ""
    return util.one_line(" / ".join(lines[-n:]), 400)


# ---------------------------------------------------------------- the loop

def run_seat(home: str | Path | None, handle: str, *, once: bool = False, max_runs: int | None = None) -> int:
    """`rt run <seat>`: wait for work, run, repeat. Returns an exit code."""
    from .context import open_ctx

    ctx = open_ctx(home, client="runner")
    handle = util.check_handle(handle)
    try:
        row = ctx.db.one("SELECT * FROM seats WHERE handle = ? AND status != 'removed'", (handle,))
        if row is None:
            raise RTError(NOT_FOUND, f"no seat {handle}", "rt seat list")
        if row["app"] not in SUPPORTED:
            raise RTError(INVALID, f"Roundtable can run only Claude Code, Codex and opencode in the background; {handle} uses {row['app']}",
                          "start it in its own app (rt launch shows how)")
        if is_running(ctx.home, handle) and read_state(ctx.home, handle).get("pid") != os.getpid():
            raise RTError(CONFLICT, f"{handle} already runs in the background", f"stop it first: rt run {handle} --stop")
        home_path = ctx.home
    finally:
        ctx.close()
    try:
        stop_path(home_path, handle).unlink()
    except OSError:
        pass
    prev = read_state(home_path, handle)
    state: dict[str, Any] = {"pid": os.getpid(), "state": "waiting", "since": time.time(), "started": time.time(),
                             "heartbeat": time.time(), "runs": 0, "session": prev.get("session"), "resume_ok": prev.get("resume_ok", True),
                             "seen_note": prev.get("seen_note") or "", "tokens": prev.get("tokens") or 0, "message": "waiting for work"}
    if float(prev.get("limited_until") or 0) > time.time():      # still out of usage from an earlier run
        state["limited_until"], state["limit_text"] = prev["limited_until"], prev.get("limit_text") or ""
    stop = threading.Event()

    def beat():
        while not stop.is_set():
            state["heartbeat"] = time.time()
            write_state(home_path, handle, state)
            stop.wait(HEARTBEAT_SECONDS)

    def stop_requested() -> bool:
        return stop_path(home_path, handle).exists()

    def on_signal(_sig, _frame):
        raise KeyboardInterrupt

    try:
        signal.signal(signal.SIGTERM, on_signal)
    except (ValueError, OSError):
        pass
    beater = threading.Thread(target=beat, daemon=True)
    beater.start()
    print(f"running {handle} in the background; Ctrl+C or `rt run {handle} --stop` ends it", flush=True)
    backoff, last_sig, next_try = 0, "", 0.0
    code = 0
    try:
        ctx = open_ctx(home_path, client="runner")
        if not state["seen_note"]:
            state["seen_note"] = latest_note_time(ctx)
        ctx.close()
        while not stop_requested():
            ctx = open_ctx(home_path, client="runner")
            try:
                row = ctx.db.one("SELECT * FROM seats WHERE handle = ?", (handle,))
                if row is None or row["status"] == "removed":
                    state.update(state="stopped", message="the seat was removed")
                    break
                limited = float(state.get("limited_until") or 0)
                if limited and time.time() < limited:
                    _set(state, "limited", f"out of usage until {_hm(limited)}" + (f" ({state.get('limit_text')})" if state.get("limit_text") else ""))
                    if once:
                        break
                    time.sleep(POLL_SECONDS)
                    continue
                if limited:
                    from . import seats as seats_mod

                    with ctx.tx():
                        seats_mod.set_limited(ctx, handle, None)
                    state.pop("limited_until", None)
                    state.pop("limit_text", None)
                    backoff, last_sig = 0, ""
                if ctx.db.meta_get("frozen", "0") == "1" or row["status"] == "paused":
                    _set(state, "paused", "paused: " + ("you paused everyone" if row["status"] != "paused" else "you paused this AI"))
                    work = []
                else:
                    work = pending(ctx, handle, state["seen_note"])
                if not work:
                    if state["state"] not in ("paused",):
                        _set(state, "waiting", "waiting for work")
                    backoff, last_sig = 0, ""
                    if once:
                        break
                    time.sleep(POLL_SECONDS)
                    continue
                sig = hashlib.sha1("|".join(sorted(k for k, _t in work)).encode()).hexdigest()
                if sig == last_sig and time.time() < next_try:
                    time.sleep(POLL_SECONDS)
                    continue
                before = _seat_events(ctx, handle)
                note_mark = latest_note_time(ctx)
                _set(state, "working", "working: " + "; ".join(t for _k, t in work)[:300])
                state["work"] = [t for _k, t in work]
                facts = run_once(ctx, row, work, state, should_stop=stop_requested)
                state["runs"] = int(state.get("runs") or 0) + 1
                state["last_run"] = {"at": time.time(), "exit": facts.get("exit"), "seconds": facts.get("seconds"), "tokens": facts.get("tokens")}
                state["tokens"] = int(state.get("tokens") or 0) + int(facts.get("tokens") or 0)
                if facts.get("session"):
                    state["session"] = facts["session"]
                if facts.get("exit") not in (0, None) and facts.get("lines", 0) == 0 and state.get("session") and state.get("resume_ok", True):
                    state["resume_ok"] = False          # could not continue the old session: start fresh next time
                    state["session"] = None
                    _set(state, "waiting", "starting a fresh session")
                    continue
                state["resume_ok"] = True if facts.get("lines") else state.get("resume_ok", True)
                state["seen_note"] = note_mark
                _save_usage(home_path, handle, row, facts)
                if facts.get("limit_until"):
                    # the app is out of its plan's usage: wait for the reset, and let the others carry on with its work
                    from . import seats as seats_mod
                    from . import tasks as tasks_mod

                    until = float(facts["limit_until"])
                    state["limited_until"], state["limit_text"] = until, facts.get("limit_text") or ""
                    with ctx.tx():
                        seats_mod.set_limited(ctx, handle, until)
                    moved, reviews = tasks_mod.hand_over(ctx, handle, f"is out of usage until {_hm(until)}")
                    extra = (f"; {', '.join(moved)} handed to the others" if moved else "") + (f"; {len(reviews)} review(s) handed over" if reviews else "")
                    _set(state, "limited", f"out of usage until {_hm(until)}{extra}")
                    state["error"] = facts.get("limit_text") or "out of usage"
                    backoff, last_sig = 0, ""
                    if max_runs and state["runs"] >= max_runs or once:
                        break
                    continue
                after = pending(ctx, handle, state["seen_note"])
                changed = hashlib.sha1("|".join(sorted(k for k, _t in after)).encode()).hexdigest() != sig
                acted = _seat_events(ctx, handle) > before
                if changed or all(k.startswith("note:") for k, _t in work):
                    backoff, last_sig, state["same_runs"] = 0, "", 0
                    _set(state, "waiting", "waiting for work")
                elif acted and int(state.get("same_runs") or 0) < SAME_WORK_RUNS:
                    # it did something but the same work is still open (a long task): continue shortly, not at once
                    state["same_runs"] = int(state.get("same_runs") or 0) + 1
                    last_sig, next_try = sig, time.time() + CONTINUE_SECONDS
                    _set(state, "waiting", "continuing shortly")
                else:
                    state["same_runs"] = 0
                    backoff = BACKOFF_START if not backoff else min(BACKOFF_MAX, backoff * 2)
                    last_sig, next_try = sig, time.time() + backoff
                    why = facts.get("error_text") or facts.get("last_say") or "the run ended without doing anything on the table"
                    state["error"] = util.one_line(why, 300)
                    _set(state, "stuck", f"stuck: {util.one_line(why, 160)} · trying again in {backoff // 60} min")
                if max_runs and state["runs"] >= max_runs:
                    break
                if once:
                    break
            finally:
                ctx.close()
    except KeyboardInterrupt:
        code = 130
    except RTError as exc:
        _set(state, "stopped", exc.message)
        state["error"] = exc.message + (f" · {exc.hint}" if exc.hint else "")
        code = 1
    except Exception as exc:  # noqa: BLE001 - recorded for the dashboard, then re-raised
        _set(state, "stopped", f"the runner failed: {exc}")
        state["error"] = repr(exc)
        stop.set()
        write_state(home_path, handle, state)
        raise
    finally:
        stop.set()
        child = state.pop("child", None)
        if child and _pid_alive(child):
            try:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(child), "/T", "/F"], capture_output=True)
                else:
                    os.killpg(int(child), signal.SIGTERM)
            except Exception:
                pass
        if state.get("state") != "stopped" or not state.get("message"):
            _set(state, "stopped", "stopped")
        state["state"] = "stopped"
        write_state(home_path, handle, state)
        try:
            stop_path(home_path, handle).unlink()
        except OSError:
            pass
    return code


def _hm(epoch: float) -> str:
    return time.strftime("%H:%M", time.localtime(epoch))


def _set(state: dict, name: str, message: str) -> None:
    if state.get("state") != name:
        state["since"] = time.time()
    state["state"], state["message"] = name, message


def _save_usage(home: Path, handle: str, row, facts: dict) -> None:
    """Keep what a background run reports (Claude Code limit events) where the dashboard reads usage."""
    info = facts.get("limit")
    if not isinstance(info, dict) or row["app"] != "claude-code":
        return
    from . import usage

    snap = usage.load_snapshot(home, handle) or {"source": "background run"}
    kind = str(info.get("rateLimitType") or info.get("type") or "")
    used = info.get("utilization")
    if used is not None and float(used) <= 1:
        used = float(used) * 100
    key = "limit_5h" if "five" in kind or "5" in kind else "limit_7d" if "seven" in kind or "7" in kind else None
    if key and used is not None:
        snap[key] = {"pct": round(float(used), 1), "resets_at": info.get("resetsAt") or info.get("resets_at")}
        usage.save_snapshot(home, handle, snap)


# ---------------------------------------------------------------- start / stop from elsewhere

def start_detached(home: Path, handle: str) -> int:
    """Start `rt run <seat>` as its own process (the dashboard's Run in the background). Returns its pid."""
    from .context import open_ctx

    ctx = open_ctx(home, client="dashboard")
    try:
        row = ctx.db.one("SELECT * FROM seats WHERE handle = ? AND status != 'removed'", (handle,))
        if row is None:
            raise RTError(NOT_FOUND, f"no seat {handle}")
        if row["app"] not in SUPPORTED:
            raise RTError(INVALID, f"Roundtable can run only Claude Code, Codex and opencode in the background; {handle} uses {row['app']}",
                          "start it in its own app")
        from . import launch

        launch._exe({"claude-code": "claude", "codex-cli": "codex"}.get(row["app"], row["app"]))
        launch._workdir(ctx, row)
        if is_running(ctx.home, handle):
            raise RTError(CONFLICT, f"{handle} already runs in the background")
        home = ctx.home
    finally:
        ctx.close()
    cmd = [sys.executable, "-m", "roundtable_ai", "--home", str(home), "run", handle]
    log = Path(home) / "logs" / f"runner-{handle}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL, "cwd": str(Path(home).parent)}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000
    else:
        kwargs["start_new_session"] = True
    env = dict(os.environ)
    env.pop("RT_SEAT", None)
    with open(log, "ab") as fh:
        p = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, env=env, **kwargs)
    write_state(home, handle, {"pid": p.pid, "state": "starting", "since": time.time(), "heartbeat": time.time(),
                               "message": "starting", **{k: v for k, v in read_state(home, handle).items() if k in ("session", "resume_ok", "seen_note", "tokens", "limited_until", "limit_text")}})
    return p.pid


def request_stop(home: Path, handle: str, *, wait: float = 6.0) -> bool:
    """Ask a seat's runner to stop (it ends the current run too). True when it has stopped."""
    path = stop_path(home, handle)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass
    st = read_state(home, handle)
    deadline = time.time() + wait
    while time.time() < deadline:
        if not is_running(home, handle):
            break
        time.sleep(0.2)
    if is_running(home, handle):
        for pid in (st.get("child"), st.get("pid")):
            try:
                if pid and _pid_alive(pid):
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
                    else:
                        os.kill(int(pid), signal.SIGTERM)
            except Exception:
                pass
    st = read_state(home, handle)
    if st:
        st.update(state="stopped", message="stopped")
        write_state(home, handle, st)
    return True


def require_supported(row) -> None:
    if row["app"] not in SUPPORTED:
        raise RTError(STATE, f"{row['handle']} runs in {row['app']}", "background runs work for Claude Code, Codex and opencode")

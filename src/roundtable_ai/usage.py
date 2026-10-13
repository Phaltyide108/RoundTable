"""Per-seat usage: context window, session tokens, plan limits, and the cost
of talking to Roundtable itself.

Where the numbers come from (all local, read-only):
- Roundtable exchange: every MCP call is measured as it happens (characters in
  and out, about 4 characters per token). Exact for Roundtable's own traffic.
- Claude Code seats started with `rt launch`: Claude Code's status line hands
  Roundtable context size, session tokens and, on Pro/Max plans, the 5-hour
  and 7-day limit percentages with reset times (`rt _statusline`).
- Codex seats: Codex writes token counts, the context window and its limit
  windows into its session logs (~/.codex/sessions). Roundtable reads only the
  newest token-count line of the session whose folder is the seat's working copy.
- Desktop chat apps (Claude app, ChatGPT app) do not expose these numbers, so
  only the exchange cost is shown for them.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import util
from .registry import HUMAN, Param, Result, op


CHARS_PER_TOKEN = 4


def tokens(chars: int) -> int:
    return (int(chars) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


# ---------------------------------------------------------------- exchange metering

def record_exchange(ctx, seat: str, op_name: str, chars_in: int, chars_out: int, ok: bool) -> None:
    """Called by dispatch for every MCP call made by a seat. Never raises."""
    try:
        with ctx.tx():
            ctx.db.execute("INSERT INTO exchange(at, seat, op, chars_in, chars_out, ok) VALUES (?,?,?,?,?,?)",
                           (util.now(), seat, op_name, int(chars_in), int(chars_out), 1 if ok else 0))
    except Exception:
        pass


def exchange_totals(ctx, seat: str) -> dict[str, int]:
    since = (datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    total = ctx.db.one("SELECT COUNT(*) n, COALESCE(SUM(chars_in),0) i, COALESCE(SUM(chars_out),0) o FROM exchange WHERE seat = ?", (seat,))
    today = ctx.db.one("SELECT COUNT(*) n, COALESCE(SUM(chars_in),0) i, COALESCE(SUM(chars_out),0) o FROM exchange WHERE seat = ? AND at >= ?", (seat, since))
    return {"calls": total["n"], "tokens": tokens(total["i"] + total["o"]), "tokens_in": tokens(total["i"]), "tokens_out": tokens(total["o"]),
            "calls_today": today["n"], "tokens_today": tokens(today["i"] + today["o"])}


def tool_overhead_tokens() -> int:
    """Tokens the 8 tool definitions take in each seat's context, once per session."""
    from .mcp_server import build_tools

    tools, _ = build_tools()
    return tokens(len(json.dumps(tools)))


# ---------------------------------------------------------------- snapshots

def _usage_dir(home: Path) -> Path:
    d = Path(home) / "usage"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_snapshot(home: Path, seat: str, snap: dict[str, Any]) -> None:
    path = _usage_dir(home) / f"{seat}.json"
    snap = dict(snap, updated_at=time.time())
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snap), encoding="utf-8")
    tmp.replace(path)


def load_snapshot(home: Path, seat: str) -> dict[str, Any] | None:
    path = Path(home) / "usage" / f"{seat}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def from_claude_statusline(data: dict) -> dict[str, Any]:
    """Normalize Claude Code's status line JSON."""
    cw = data.get("context_window") or {}
    rl = data.get("rate_limits") or {}
    snap: dict[str, Any] = {
        "source": "claude-code status line",
        "model": (data.get("model") or {}).get("display_name") or (data.get("model") or {}).get("id"),
        "context_pct": cw.get("used_percentage"),
        "context_size": cw.get("context_window_size"),
        "session_tokens": (cw.get("total_input_tokens") or 0) + (cw.get("total_output_tokens") or 0) or None,
        "cost_usd": (data.get("cost") or {}).get("total_cost_usd"),
    }
    for key, name in (("five_hour", "limit_5h"), ("seven_day", "limit_7d")):
        w = rl.get(key) or {}
        if w.get("used_percentage") is not None:
            snap[name] = {"pct": w.get("used_percentage"), "resets_at": w.get("resets_at")}
    return snap


def _codex_home() -> Path:
    base = os.environ.get("CODEX_HOME")
    return Path(base) if base else Path.home() / ".codex"


def _tail_lines(path: Path, max_bytes: int = 512_000) -> list[str]:
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - max_bytes))
        return fh.read().decode("utf-8", errors="replace").splitlines()


def _first_line(path: Path) -> str:
    with open(path, "rb") as fh:
        return fh.readline(2_000_000).decode("utf-8", errors="replace")


def from_codex_logs(folder: str | Path, *, max_files: int = 200, max_age_days: int = 8) -> dict[str, Any] | None:
    """Newest token-count data of the Codex session that ran in `folder`."""
    root = _codex_home() / "sessions"
    if not root.is_dir():
        return None
    want = str(Path(folder).resolve())
    cutoff = time.time() - max_age_days * 86400
    files = []
    try:
        for dirpath, _dirs, names in os.walk(root):
            for n in names:
                if n.endswith(".jsonl"):
                    p = Path(dirpath) / n
                    try:
                        m = p.stat().st_mtime
                    except OSError:
                        continue
                    if m >= cutoff:
                        files.append((m, p))
    except OSError:
        return None
    files.sort(reverse=True)
    for _m, p in files[:max_files]:
        try:
            meta = json.loads(_first_line(p) or "{}")
        except ValueError:
            continue
        payload = meta.get("payload") or meta
        cwd = payload.get("cwd") or (payload.get("session_meta") or {}).get("cwd")
        if not cwd or str(Path(cwd).resolve()) != want:
            continue
        for line in reversed(_tail_lines(p)):
            if "token_count" not in line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            pl = ev.get("payload") or ev
            if pl.get("type") != "token_count":
                continue
            return _codex_snapshot(pl, p)
        return {"source": f"codex log {p.name}", "note": "no token counts yet in this session"}
    return None


def _codex_snapshot(pl: dict, path: Path) -> dict[str, Any]:
    info = pl.get("info") or {}
    total = info.get("total_token_usage") or {}
    last = info.get("last_token_usage") or {}
    window = info.get("model_context_window")
    snap: dict[str, Any] = {"source": f"codex log {path.name}", "context_size": window,
                            "session_tokens": total.get("total_tokens")}
    used_now = last.get("input_tokens")
    if window and used_now is not None:
        snap["context_pct"] = round(100.0 * used_now / window, 1)
    for w in (pl.get("rate_limits") or {}).values():
        if not isinstance(w, dict) or w.get("used_percent") is None:
            continue
        minutes = w.get("window_minutes") or 0
        resets = w.get("resets_at")
        if resets is None and w.get("resets_in_seconds") is not None:
            resets = time.time() + float(w["resets_in_seconds"])
        key = "limit_5h" if minutes and minutes <= 360 else ("limit_7d" if minutes and minutes >= 7 * 1440 - 60 else None)
        if key:
            snap[key] = {"pct": w.get("used_percent"), "resets_at": resets}
    return snap


def seat_snapshot(ctx, row) -> dict[str, Any] | None:
    if row["app"] == "claude-code":
        return load_snapshot(ctx.home, row["handle"])
    if row["app"] in ("codex-cli", "codex-app") and row["worktree"]:
        try:
            snap = from_codex_logs(row["worktree"])
        except Exception:
            snap = None
        if snap:
            snap["updated_at"] = snap.get("updated_at") or time.time()
        return snap
    return None


# ---------------------------------------------------------------- formatting

def _resets(epoch: Any) -> str:
    try:
        secs = int(float(epoch) - time.time())
    except (TypeError, ValueError):
        return ""
    if secs <= 0:
        return "resetting"
    h, m = divmod(secs // 60, 60)
    d, h = divmod(h, 24)
    return f"resets in {d}d {h}h" if d else (f"resets in {h}h {m}m" if h else f"resets in {m}m")


def _pct(v: Any) -> str:
    try:
        return f"{float(v):.0f}%"
    except (TypeError, ValueError):
        return "?"


def describe(snap: dict | None, *, short: bool = False) -> str:
    if not snap:
        return "app usage: not available" if not short else ""
    parts = []
    if snap.get("context_pct") is not None:
        size = snap.get("context_size")
        parts.append(f"context {_pct(snap['context_pct'])}" + (f" of {int(size) // 1000}k" if size and not short else ""))
    if snap.get("session_tokens"):
        parts.append(f"session {int(snap['session_tokens']):,} tokens" if not short else f"{int(snap['session_tokens']) // 1000}k tok")
    for key, label in (("limit_5h", "5h"), ("limit_7d", "7d")):
        w = snap.get(key)
        if w:
            parts.append(f"{label} {_pct(w.get('pct'))}" + ("" if short else f" ({_resets(w.get('resets_at'))})"))
    if snap.get("cost_usd") and not short:
        parts.append(f"~${float(snap['cost_usd']):.2f} at list price")
    if snap.get("note") and not short:
        parts.append(snap["note"])
    age = time.time() - float(snap.get("updated_at") or time.time())
    if age > 900 and not short:
        parts.append(f"as of {int(age // 60)} min ago")
    return " · ".join(parts) or ("app usage: no data yet" if not short else "")


@op("admin.usage", who=HUMAN, desc="Context, tokens and plan limits per seat, plus Roundtable's own token cost")
def usage_report(ctx) -> Result:
    rows = ctx.db.all("SELECT * FROM seats WHERE status != 'removed' ORDER BY created_at")
    if not rows:
        return Result("no seats yet")
    lines, data = [], {}
    overhead = tool_overhead_tokens()
    for r in rows:
        snap = seat_snapshot(ctx, r)
        ex = exchange_totals(ctx, r["handle"])
        lines.append(f"{r['handle']} ({r['model']}, {r['app']})")
        lines.append("  " + describe(snap))
        lines.append(f"  Roundtable exchange: {ex['calls']} calls, ~{ex['tokens']:,} tokens (today {ex['calls_today']} calls, ~{ex['tokens_today']:,})"
                     f" + ~{overhead:,} tokens of tool definitions per session")
        data[r["handle"]] = {"app": snap, "exchange": ex}
    by_company: dict[str, list[str]] = {}
    for r in rows:
        by_company.setdefault(r["company"], []).append(r["handle"])
    shared = [f"{', '.join(v)} ({k})" for k, v in by_company.items() if len(v) > 1]
    if shared:
        lines.append("note: seats from the same company usually share one plan's limits: " + "; ".join(shared))
    lines.append("sources: Claude Code status line (seats started with rt launch), Codex session logs; desktop chat apps don't share these numbers")
    return Result("\n".join(lines), {"seats": data, "tool_overhead_tokens": overhead})


# ---------------------------------------------------------------- Claude Code status line

def statusline_main(argv: list[str]) -> int:
    """`rt _statusline <seat>`: receives Claude Code's status line JSON on stdin,
    saves the usage snapshot, prints one line. Must never fail loudly."""
    seat = argv[0] if argv else (os.environ.get("RT_SEAT") or "")
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except (ValueError, OSError):
        data = {}
    line = f"rt {seat}"
    try:
        from .context import open_ctx
        from .inbox import line as inbox_line

        snap = from_claude_statusline(data) if data else None
        ctx = open_ctx(os.environ.get("RT_HOME") or None, client="statusline")
        try:
            if snap and seat:
                save_snapshot(ctx.home, seat, snap)
            box = inbox_line(ctx, seat) if seat else ""
        finally:
            ctx.close()
        usage = describe(snap, short=True) if snap else ""
        line = " · ".join(x for x in (f"rt {seat}", usage, box.replace("[rt: ", "").rstrip("]")) if x)
    except Exception:
        pass
    print(line)
    return 0

"""Usage: Roundtable's own token cost, Claude Code status line data, Codex session logs."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from test_mcp import INIT, call, rpc

CLAUDE_STATUS = {
    "model": {"id": "claude-opus-5-5", "display_name": "Opus 5.5"},
    "cost": {"total_cost_usd": 0.42},
    "context_window": {"total_input_tokens": 15234, "total_output_tokens": 4521, "context_window_size": 200000, "used_percentage": 8},
    "rate_limits": {"five_hour": {"used_percentage": 23.5, "resets_at": int(time.time()) + 3600},
                    "seven_day": {"used_percentage": 41.2, "resets_at": int(time.time()) + 3 * 86400}},
}


def test_exchange_is_metered(rt):
    rt.add_seat("opus")
    r = rpc([INIT, call("rt_sync", {"join": "opus"}, 2)], {"RT_HOME": str(rt.home)})
    key = r[1]["result"]["content"][0]["text"].split('key="', 1)[1].split('"', 1)[0]
    rpc([INIT, call("rt_task", {"action": "ready", "key": key}, 2), call("rt_task", {"action": "claim", "task": "T9", "key": key}, 3)],
        {"RT_HOME": str(rt.home)})
    rows = rt.q("SELECT op, ok, chars_out FROM exchange WHERE seat='opus' ORDER BY id")
    assert [r["op"] for r in rows] == ["seat.join", "sync", "task.ready", "task.claim"]
    assert rows[-1]["ok"] == 0 and all(r["chars_out"] > 0 for r in rows)
    out = rt.human("admin.usage").text
    assert "Roundtable exchange: 4 calls" in out and "tool definitions per session" in out
    assert "app usage: not available" in out or "no data" in out


def test_claude_statusline(rt):
    rt.add_seat("opus")
    out = subprocess.run([sys.executable, "-m", "roundtable_ai", "_statusline", "opus"], input=json.dumps(CLAUDE_STATUS),
                         capture_output=True, text=True, env=dict(os.environ, RT_HOME=str(rt.home)), timeout=60)
    assert out.returncode == 0
    line = out.stdout.strip()
    assert line.startswith("rt opus") and "context 8%" in line and "5h 24%" in line and "7d 41%" in line
    report = rt.human("admin.usage").text
    assert "context 8% of 200k" in report and "5h 24% (resets in" in report and "session 19,755 tokens" in report
    bad = subprocess.run([sys.executable, "-m", "roundtable_ai", "_statusline", "opus"], input="not json",
                         capture_output=True, text=True, env=dict(os.environ, RT_HOME=str(rt.home)), timeout=60)
    assert bad.returncode == 0 and bad.stdout.startswith("rt opus")


def test_codex_logs(rt, tmp_path, monkeypatch):
    rt.add_seat("sol", model="gpt-6.1-sol", app="codex-cli", worktree=True)
    wt = rt.q("SELECT worktree FROM seats")[0]["worktree"]
    codex_home = tmp_path / "codex"
    day = codex_home / "sessions" / "2026" / "10" / "13"
    day.mkdir(parents=True)
    now = int(time.time())
    lines = [
        {"timestamp": "t", "type": "session_meta", "payload": {"id": "abc", "cwd": wt}},
        {"timestamp": "t", "type": "event_msg", "payload": {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": 50000, "output_tokens": 3000, "total_tokens": 53000},
            "last_token_usage": {"input_tokens": 27200, "total_tokens": 28000}, "model_context_window": 272000},
            "rate_limits": {"primary": {"used_percent": 12.0, "window_minutes": 300, "resets_at": now + 7200},
                            "secondary": {"used_percent": 93.0, "window_minutes": 10080, "resets_at": now + 86400}}}},
    ]
    (day / "rollout-2026-10-13-abc.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    other = {"type": "session_meta", "payload": {"cwd": "/somewhere/else"}}
    (day / "rollout-other.jsonl").write_text(json.dumps(other) + "\n")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    report = rt.human("admin.usage").text
    assert "context 10% of 272k" in report and "5h 12%" in report and "7d 93%" in report and "53,000 tokens" in report
    from roundtable_ai import notify, watch

    sent = []
    monkeypatch.setattr(notify, "send", lambda t, b, home=None: sent.append(t) or True)
    watch.watch(str(rt.home), once=True)
    watch.watch(str(rt.home), once=True)
    assert sum("near its 7-day limit" in s for s in sent) == 1
    assert not any("5-hour" in s for s in sent)


def test_launch_adds_statusline(rt, tmp_path, monkeypatch):
    if os.name == "nt":
        return
    b = tmp_path / "bin"
    b.mkdir()
    (b / "claude").write_text("#!/bin/sh\n")
    (b / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", f"{b}{os.pathsep}{os.environ['PATH']}")
    rt.add_seat("opus", worktree=True)
    from roundtable_ai import launch
    from roundtable_ai.context import open_ctx

    ctx = open_ctx(rt.home)
    try:
        cmd, _ = launch.command_for(ctx, ctx.db.one("SELECT * FROM seats"))
    finally:
        ctx.close()
    settings = json.loads(cmd[cmd.index("--settings") + 1])
    assert "_statusline opus" in settings["statusLine"]["command"]
    assert cmd.index("--settings") < cmd.index("--mcp-config")
    rt.human("admin.config_set", key="usage.statusline", value="false")
    ctx = open_ctx(rt.home)
    try:
        cmd, _ = launch.command_for(ctx, ctx.db.one("SELECT * FROM seats"))
    finally:
        ctx.close()
    assert "--settings" not in cmd

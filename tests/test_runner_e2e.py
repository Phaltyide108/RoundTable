"""End to end: two stand-in AIs (a fake `claude` and a fake `codex`) are run in the
background by Roundtable, exactly as the real apps would be, and take a goal all
the way through planning, building, tests, review and merge. Also: quick mode,
starting without approval, effort and model flags, a failing app, and starting
and stopping a runner from outside."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

from roundtable_ai import activity, runner, ui_state

pytestmark = pytest.mark.skipif(os.name == "nt", reason="the stand-in apps are POSIX scripts")

FAKE = Path(__file__).with_name("fake_agent.py")


@pytest.fixture
def fake_apps(tmp_path, monkeypatch):
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    for name in ("claude", "codex"):
        script = bin_dir / name
        script.write_text(f"#!/bin/sh\nexec {sys.executable!r} {str(FAKE)!r} \"$@\"\n")
        script.chmod(0o755)
    (bin_dir / "python").symlink_to(sys.executable)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("RT_PROOF_INLINE", "1")
    return bin_dir


def team(rt):
    rt.add_seat("opus", model="claude-opus-5-5", app="claude-code", worktree=True)
    rt.add_seat("sol", model="gpt-6.1-sol", app="codex-cli", worktree=True)


def rounds(rt, until, n=14):
    for _ in range(n):
        if until():
            return True
        for h in ("opus", "sol"):
            runner.run_seat(rt.home, h, once=True)
    return until()


def calls(rt):
    path = rt.home / "fake-calls.log"
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def stage(rt):
    return rt.q("SELECT stage FROM plans ORDER BY id DESC LIMIT 1")[0]["stage"]


def test_full_plan_to_merged_work_with_background_runs(rt, fake_apps):
    team(rt)
    rt.human("seat.set", handle="opus", effort="high")
    rt.human("seat.set", handle="sol", effort="xhigh")
    rt.human("plan.goal", goal="Add a greeting module per seat, with tests", review="mid")

    assert rounds(rt, lambda: stage(rt) == "awaiting_human"), rt.q("SELECT type, actor, text FROM events")
    events = [e["type"] for e in rt.q("SELECT type FROM events ORDER BY id")]
    for t in ("plan.draft", "plan.critique", "plan.proposed", "plan.approved", "plan.awaiting_human"):
        assert t in events, t
    rt.human("plan.lock")

    def all_done():
        rows = rt.q("SELECT status FROM tasks WHERE kind != 'epic'")
        return rows and all(r["status"] == "done" for r in rows)

    assert rounds(rt, all_done), rt.q("SELECT id, status, owner FROM tasks")
    assert (rt.root / "greet_opus.py").exists() and (rt.root / "greet_sol.py").exists()   # merged into the main folder
    assert {e["type"] for e in rt.q("SELECT type FROM events")} >= {"review.submitted", "task.done"}

    seen = calls(rt)
    assert any(c["seat"] == "opus" and c["effort"] == "high" and c["app"] == "claude" for c in seen)
    assert any(c["seat"] == "sol" and c["effort"] == "xhigh" and c["app"] == "codex" for c in seen)
    assert any(c["resume"] for c in seen if c["seat"] == "opus"), "later runs continue the same session"
    assert all(c["permission"] in ("acceptEdits", "workspace-write") for c in seen)

    ctx = rt.ctx()
    try:
        row = ctx.db.one("SELECT * FROM seats WHERE handle = 'opus'")
        act = activity.recent(ctx, row, 50)
        kinds = {i["kind"] for i in act["items"]}
        assert act["source"] == "background run" and {"think", "tool", "edit", "done"} <= kinds, act
        st = ui_state.build(ctx)
    finally:
        ctx.close()
    opus = next(s for s in st["seats"] if s["handle"] == "opus")
    assert opus["effort"] == "high" and "max" in opus["efforts"] and opus["can_run"]
    assert runner.read_state(rt.home, "opus")["state"] == "stopped"


def test_quick_mode_without_approval_goes_straight_to_work(rt, fake_apps):
    team(rt)
    rt.human("plan.goal", goal="opus does its greeting and sol does its greeting", mode="quick", auto=True)
    p = rt.q("SELECT * FROM plans")[0]
    assert p["mode"] == "quick" and p["auto_lock"] == 1 and p["stage"] == "merging"
    assert rounds(rt, lambda: stage(rt) in ("locked", "done"), n=3)
    types = [e["type"] for e in rt.q("SELECT type FROM events ORDER BY id")]
    assert "plan.draft" not in types and "plan.critique" not in types and "plan.locked" in types
    assert rounds(rt, lambda: stage(rt) == "done")


def test_nothing_running_is_reported_with_a_way_out(rt):
    team(rt)
    rt.human("plan.goal", goal="something")
    ctx = rt.ctx()
    try:
        st = ui_state.build(ctx)
    finally:
        ctx.close()
    idle = next(n for n in st["needs"] if n["key"].startswith("idle:"))
    assert "aren't running" in idle["title"]
    assert idle["actions"][0]["run"] == ["opus", "sol"]


def test_a_failing_app_backs_off_and_says_why(rt, fake_apps, monkeypatch):
    team(rt)
    rt.human("plan.goal", goal="something")
    monkeypatch.setenv("FAKE_AGENT_FAIL", "opus")
    runner.run_seat(rt.home, "opus", once=True)
    st = runner.read_state(rt.home, "opus")
    assert "not signed in" in (st.get("error") or ""), st
    ctx = rt.ctx()
    try:
        items = activity.recent(ctx, ctx.db.one("SELECT * FROM seats WHERE handle = 'opus'"))["items"]
    finally:
        ctx.close()
    assert any(i["kind"] == "error" and "not signed in" in i["text"] for i in items)


def test_start_and_stop_a_runner_from_outside(rt, fake_apps):
    team(rt)
    pid = runner.start_detached(rt.home, "opus")
    try:
        for _ in range(100):
            if runner.is_running(rt.home, "opus"):
                break
            time.sleep(0.1)
        assert runner.is_running(rt.home, "opus"), (rt.home / "logs" / "runner-opus.log").read_text()
        assert runner.status(rt.home, "opus")["state"] in ("waiting", "working", "starting")
        with pytest.raises(Exception):
            runner.start_detached(rt.home, "opus")
    finally:
        runner.request_stop(rt.home, "opus")
    for _ in range(50):
        if not runner._pid_alive(pid):
            break
        time.sleep(0.1)
    assert not runner.is_running(rt.home, "opus")
    assert runner.status(rt.home, "opus")["state"] == "stopped"


def test_stream_lines_become_readable_steps():
    claude = [
        {"type": "system", "subtype": "init", "model": "claude-opus-5-5", "session_id": "s"},
        {"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "First I read the usage code."},
                                                      {"type": "tool_use", "name": "Bash", "input": {"command": "pytest -q"}},
                                                      {"type": "tool_use", "name": "Edit", "input": {"file_path": "/w/src/a.py"}},
                                                      {"type": "tool_use", "name": "mcp__roundtable__rt_task", "input": {"action": "close", "task": "T2"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "is_error": True, "content": "Permission denied\nmore"}]}},
        {"type": "result", "subtype": "success", "result": "Closed T2", "num_turns": 4},
    ]
    items = [i for ev in claude for i in activity.from_claude(ev, "/w")]
    assert [i["kind"] for i in items] == ["start", "think", "run", "edit", "tool", "error", "done"]
    assert items[3]["text"] == "src/a.py" and items[4]["text"] == "rt_task close T2" and items[5]["text"] == "Permission denied"
    codex = [
        {"type": "thread.started", "thread_id": "t"},
        {"type": "item.completed", "item": {"type": "reasoning", "text": "Look at usage.py"}},
        {"type": "item.started", "item": {"type": "command_execution", "command": ["bash", "-lc", "ls -la"]}},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "false", "exit_code": 1}},
        {"type": "item.completed", "item": {"type": "file_change", "changes": [{"path": "/w/b.py", "kind": "update"}]}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Done."}},
        {"type": "turn.failed", "error": {"message": "usage limit reached"}},
    ]
    items = [i for ev in codex for i in activity.from_codex_exec(ev, "/w")]
    assert [i["kind"] for i in items] == ["start", "think", "run", "error", "edit", "say", "error"]
    assert items[2]["text"] == "ls -la" and items[4]["text"] == "b.py" and "usage limit" in items[6]["text"]
    log = [{"timestamp": "2026-10-14T06:00:00.000Z", "type": "event_msg", "payload": {"type": "agent_reasoning", "text": "**Planning**"}},
           {"type": "event_msg", "payload": {"type": "exec_command_begin", "command": ["bash", "-lc", "git status"]}}]
    items = [i for ev in log for i in activity.from_codex_log(ev)]
    assert [i["kind"] for i in items] == ["think", "run"] and items[0]["t"] > 1.7e9


def test_expired_limit_windows_are_not_shown_as_current():
    from roundtable_ai import usage

    snap = {"limit_5h": {"pct": 75, "resets_at": time.time() - 60}, "limit_7d": {"pct": 32, "resets_at": time.time() + 3600}}
    out = usage.freshen(dict(snap))
    assert out["limit_5h"]["pct"] is None and out["limit_5h"]["reset"] and out["limit_5h"]["was"] == 75
    assert out["limit_7d"]["pct"] == 32
    assert "5h reset since" in usage.describe(dict(out, updated_at=time.time()))


def test_benchmark_scores_alone_and_team_with_hidden_tests(tmp_path, fake_apps, monkeypatch):
    from roundtable_ai import bench

    monkeypatch.setenv("FAKE_SOLO_ANSWER", str(Path(__file__).with_name("bench_reference") / "sheet.py"))
    cs = bench.contenders_from(["claude:high", "codex"], ["claude,codex"])
    assert [c.label for c in cs] == ["Claude Opus 5.5 (high) alone", "GPT-6.1 Sol alone", "Team: Claude Opus 5.5 + GPT-6.1 Sol"]
    lines = []
    report = bench.run("sheet", cs, tmp_path / "bench", minutes=2, mode="quick", review="low", log=lines.append)
    solo_claude, solo_codex, team_ = report["results"]
    total = bench.count_hidden("sheet")
    assert solo_claude["passed"] == total and solo_claude["tokens"] > 0         # the prepared answer passes every hidden test
    assert team_["outcome"] == "done" and team_["passed"] == 0                  # the stand-in team builds greetings, not a spreadsheet
    assert "could not be imported" in team_["failed"][0]
    md = (tmp_path / "bench" / "report.md").read_text()
    assert f"| Claude Opus 5.5 (high) alone | {total} of {total} (100%)" in md
    assert (tmp_path / "bench" / "report.json").exists()
    # the hidden tests never enter a contender's folder
    assert not list((tmp_path / "bench").rglob("test_hidden.py"))


def test_benchmark_task_is_well_formed():
    from roundtable_ai import bench

    assert "sheet" in bench.tasks()
    assert bench.parse_member("codex:gpt-6.1-sol:xhigh").effort == "xhigh"
    with pytest.raises(Exception):
        bench.parse_member("gemini")
    ref = Path(__file__).with_name("bench_reference")
    sc = bench.score("sheet", ref)
    assert sc["passed"] == sc["total"] == bench.count_hidden("sheet") >= 50, sc


def test_sql_task_hidden_tests_agree_with_sqlite_and_forbid_it():
    from roundtable_ai import bench

    ref = Path(__file__).with_name("bench_reference")
    assert "sql" in bench.tasks() and bench.meta("sql")["module"] == "minisql.py"
    assert bench.count_hidden("sql") >= 100
    sc = bench.score("sql", ref, check_forbidden=False)          # SQLite itself passes every hidden test
    assert sc["passed"] == sc["total"] == bench.count_hidden("sql"), sc["failed"][:5]
    banned = bench.score("sql", ref)                              # ...but a contender may not hand the work to SQLite
    assert banned["passed"] == 0 and "sqlite3" in banned["failed"][0]
    assert "python" in bench._test_command()

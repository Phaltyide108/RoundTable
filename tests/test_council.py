"""Ask the table (councils), second opinions on failing tasks, and opencode as a background AI.

Stand-in apps (tests/fake_agent.py) answer, rank and combine the way the real ones are asked to,
and print the real apps' event streams, so the parsing is exercised too.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from roundtable_ai import activity, apps, council, runner
from roundtable_ai.errors import RTError

pytestmark = pytest.mark.skipif(os.name == "nt", reason="the stand-in apps are POSIX scripts")

FAKE = Path(__file__).with_name("fake_agent.py")


@pytest.fixture
def fake_apps(tmp_path, monkeypatch):
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    for name in ("claude", "codex", "opencode"):
        script = bin_dir / name
        script.write_text(f"#!/bin/sh\nexec {sys.executable!r} {str(FAKE)!r} \"$@\"\n")
        script.chmod(0o755)
    (bin_dir / "python").symlink_to(sys.executable)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("RT_PROOF_INLINE", "1")
    monkeypatch.setenv("RT_COUNCIL_INLINE", "1")
    monkeypatch.setenv("FAKE_COUNCIL_LOG", str(tmp_path / "council-calls.log"))
    return tmp_path / "council-calls.log"


def team(rt, *extra):
    rt.add_seat("opus", model="claude-opus-5-5", app="claude-code", worktree=True)
    rt.add_seat("sol", model="gpt-6.1-sol", app="codex-cli", worktree=True)
    for handle, model in extra:
        rt.add_seat(handle, model=model, app="opencode", worktree=True)


def calls(log: Path) -> list[dict]:
    return [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []


# ---------------------------------------------------------------- a council

def test_two_ais_answer_rank_and_the_best_writes_the_final_answer(rt, fake_apps, monkeypatch):
    team(rt)
    monkeypatch.setenv("FAKE_BEST_MODEL", "gpt-6.1-sol")
    res = rt.human("council.ask", question="What is six times seven?")
    assert res.data["seats"] == ["opus", "sol"]
    c = rt.q("SELECT * FROM councils")[0]
    assert c["stage"] == "done" and c["chair"] == "sol"
    assert c["final"].startswith("Final answer by gpt-6.1-sol")
    ranking = json.loads(c["ranking"])
    assert ranking[0]["seat"] == "sol" and ranking[0]["avg"] == 1.0 and ranking[0]["firsts"] == 2
    parts = rt.q("SELECT seat, stage, status, label FROM council_parts ORDER BY stage, seat")
    assert [(p["seat"], p["stage"], p["status"]) for p in parts] == [
        ("opus", "answer", "done"), ("sol", "answer", "done"), ("sol", "final", "done"), ("opus", "rank", "done"), ("sol", "rank", "done")]
    assert sorted(p["label"] for p in parts if p["stage"] == "answer") == ["A", "B"]
    kinds = [(x["app"], x["kind"], x["permission"]) for x in calls(fake_apps)]
    assert ("claude", "answer", "default") in kinds and ("codex", "answer", "read-only") in kinds     # read-only, both
    assert [x["kind"] for x in calls(fake_apps)].count("final") == 1
    types = [e["type"] for e in rt.q("SELECT type FROM events ORDER BY id")]
    assert types.index("council.asked") < types.index("council.ranking") < types.index("council.combining") < types.index("council.done")
    shown = rt.human("council.show", id=c["id"], all=True).text
    assert "Final answer by gpt-6.1-sol" in shown and "gpt-6.1-sol says 42. BEST" in shown
    # the activity of each AI shows what it was doing
    acts = (rt.home / "activity" / "opus.jsonl").read_text()
    assert "answering question Q1" in acts and "ranking the answers to Q1" in acts


def test_three_ais_with_opencode_and_a_failing_one(rt, fake_apps, monkeypatch):
    team(rt, ("oc", "opencode/big-pickle"))
    monkeypatch.setenv("FAKE_BEST_MODEL", "opencode/big-pickle")
    monkeypatch.setenv("FAKE_COUNCIL_FAIL", "claude-opus-5-5")
    rt.human("council.ask", question="Which is better?")
    c = rt.q("SELECT * FROM councils")[0]
    assert c["stage"] == "done" and c["chair"] == "oc"
    failed = rt.q("SELECT seat, error FROM council_parts WHERE status = 'failed'")
    assert failed[0]["seat"] == "opus" and "not signed in" in failed[0]["error"]
    assert len(json.loads(c["ranking"])) == 2                     # only the two answers that came in are ranked


def test_one_answer_is_the_final_answer_and_none_is_a_failure(rt, fake_apps, monkeypatch):
    team(rt)
    monkeypatch.setenv("FAKE_COUNCIL_FAIL", "claude-opus-5-5")
    rt.human("council.ask", question="q1")
    c = rt.q("SELECT * FROM councils WHERE id = 'Q1'")[0]
    assert c["stage"] == "done" and c["chair"] == "sol" and c["final"] == "gpt-6.1-sol says 42." and "only sol answered" in c["error"]
    rt.human("council.ask", question="q2", seats=["opus"])
    c = rt.q("SELECT * FROM councils WHERE id = 'Q2'")[0]
    assert c["stage"] == "failed" and "not signed in" in c["error"]


def test_follow_up_carries_the_earlier_answer(rt, fake_apps):
    team(rt)
    rt.human("council.ask", question="first")
    rt.human("council.ask", question="and then?", follow_up="Q1")
    c = rt.q("SELECT context FROM councils WHERE id = 'Q2'")[0]
    assert "Earlier question: «first»" in c["context"] and "Final answer" in c["context"]


def test_only_ais_roundtable_can_run_sit_on_a_council(rt):
    rt.add_seat("fable", model="claude-fable-5-1", app="claude-app")
    e = rt.error(rt.human, "council.ask", question="q")
    assert "no AI here can answer" in e.message
    e = rt.error(rt.human, "council.ask", question="q", seats=["fable"])
    assert "can't answer here" in e.message


def test_cancel_a_running_question(rt, monkeypatch):
    rt.add_seat("opus", model="claude-opus-5-5", app="claude-code")
    monkeypatch.setattr(council, "spawn", lambda ctx, cid: None)
    rt.human("council.ask", question="slow one")
    rt.human("council.cancel", id="Q1")
    assert rt.q("SELECT stage FROM councils")[0]["stage"] == "cancelled"
    e = rt.error(rt.human, "council.cancel", id="Q1")
    assert "already cancelled" in e.message


def test_ranking_parse_and_aggregate():
    text = "A is wrong.\nFINAL RANKING:\n1. Answer C\n2. Answer A\n3. Answer B\n"
    assert council.parse_ranking(text, ["A", "B", "C"]) == ["C", "A", "B"]
    assert council.parse_ranking("no ranking here", ["A", "B"]) == []
    assert council.parse_ranking("1. Answer B\n2. Answer A", ["A", "B"]) == ["B", "A"]
    table = council.aggregate([["C", "A", "B"], ["A", "C", "B"], ["C", "B", "A"]], ["A", "B", "C"])
    assert [r["label"] for r in table] == ["C", "A", "B"] and table[0]["avg"] == 1.33 and table[0]["firsts"] == 2


def test_rt_ask_follows_the_council_to_the_end(rt, fake_apps, capsys, monkeypatch):
    from roundtable_ai import cli

    team(rt)
    monkeypatch.chdir(rt.root)
    assert cli.main(["ask", "What is six times seven?"]) == 0
    out = capsys.readouterr().out
    assert "Q1 asked" in out and "final answer (by" in out and "ranked by the others" in out
    assert cli.main(["ask", "--list"]) == 0
    assert "Q1 [done]" in capsys.readouterr().out


def test_dashboard_state_has_the_councils(rt, fake_apps):
    from roundtable_ai import ui_state

    team(rt)
    rt.human("council.ask", question="q")
    ctx = rt.ctx()
    try:
        st = ui_state.build(ctx)
        d = ui_state.council_detail(ctx, "Q1")
    finally:
        ctx.close()
    assert st["councils"][0]["id"] == "Q1" and st["councils"][0]["stage"] == "done"
    assert {m["seat"] for m in st["councils"][0]["members"]} == {"opus", "sol"}
    assert st["can_ask"] == ["opus", "sol"]
    assert len(d["parts"]) == 5 and d["final"]


# ---------------------------------------------------------------- second opinion on a failing task

def test_second_failure_in_a_row_gets_a_second_opinion(rt, fake_apps):
    team(rt)
    rt.human("plan.goal", goal="g", mode="quick", planners="opus")
    rt.seat("opus", "plan.propose", text="t", tasks=[{"ref": "1", "title": "Greet", "files": ["greet.py"], "proof": ["python -c 'raise SystemExit(1)'"], "owner": "opus"}])
    rt.human("plan.lock")
    rt.seat("opus", "sync")
    rt.seat("opus", "task.claim", task="T1")
    ctx = rt.ctx()
    try:
        for i in (1, 2):
            with ctx.tx():
                ctx.db.execute("INSERT INTO proof_runs(id, task, seat, commands, status, output_tail, failed_cmd, workdir, created_at) "
                               "VALUES (?, 'T1', 'opus', '[]', 'failed', 'AssertionError: Hi != hi', 'python -c ...', ?, ?)",
                               (f"PRX{i}", rt.q("SELECT worktree FROM seats WHERE handle='opus'")[0]["worktree"], f"2026-10-14T10:0{i}:00Z"))
            cid = council.maybe_rescue(ctx, "T1")
            assert (cid is None) == (i == 1)                          # only from the second failure in a row
        assert council.maybe_rescue(ctx, "T1") is None                # one second opinion per losing streak
    finally:
        ctx.close()
    c = rt.q("SELECT * FROM councils WHERE kind = 'rescue'")[0]
    assert c["members"] == '["sol"]' and c["stage"] == "done" and "Diagnosis from gpt-6.1-sol" in c["final"]
    s = rt.q("SELECT * FROM suggestions")[0]
    assert s["from_seat"] == "sol" and s["to_seat"] == "opus" and s["task"] == "T1" and "Second opinion" in s["text"]
    assert [x["kind"] for x in calls(fake_apps)] == ["rescue"]


def test_rescue_can_be_turned_off(rt, fake_apps):
    team(rt)
    rt.human("admin.config_set", key="council.rescue", value="false")
    ctx = rt.ctx()
    try:
        assert council.maybe_rescue(ctx, "T1") is None
    finally:
        ctx.close()


# ---------------------------------------------------------------- opencode as a background AI

def test_opencode_runs_in_the_background_with_its_own_permissions(rt, fake_apps):
    rt.add_seat("oc", model="opencode/big-pickle", app="opencode", worktree=True)
    rt.human("seat.set", handle="oc", effort="high")
    ctx = rt.ctx()
    try:
        row = ctx.db.one("SELECT * FROM seats WHERE handle = 'oc'")
        cmd, cwd = runner.headless_command(ctx, row, "do it", "ses_1")
        env = runner.headless_env(ctx, row)
    finally:
        ctx.close()
    assert cmd[1:4] == ["run", "--format", "json"] and ["-m", "opencode/big-pickle"] == cmd[cmd.index("-m"):cmd.index("-m") + 2]
    assert ["--variant", "high"] == cmd[cmd.index("--variant"):cmd.index("--variant") + 2] and "--session" in cmd and "--auto" not in cmd
    cfg = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    assert cfg["mcp"]["roundtable"]["environment"]["RT_SEAT"] == "oc" and cfg["permission"]["bash"]["*"] == "deny"
    assert cfg["permission"]["bash"]["git commit*"] == "allow" and cfg["permission"]["edit"] == "allow"


def test_claude_and_opencode_build_a_quick_plan_together(rt, fake_apps):
    rt.add_seat("opus", model="claude-opus-5-5", app="claude-code", worktree=True)
    rt.add_seat("oc", model="opencode/glm-5.3", app="opencode", worktree=True)
    assert rt.q("SELECT company FROM seats WHERE handle = 'oc'")[0]["company"] == "zhipu"
    rt.human("plan.goal", goal="opus does its greeting and oc does its greeting", mode="quick", auto=True)
    for _ in range(14):
        if rt.q("SELECT stage FROM plans")[0]["stage"] == "done":
            break
        for h in ("opus", "oc"):
            runner.run_seat(rt.home, h, once=True)
    assert rt.q("SELECT stage FROM plans")[0]["stage"] == "done"
    st = runner.read_state(rt.home, "oc")
    assert st["session"] and st["tokens"] > 0
    acts = (rt.home / "activity" / "oc.jsonl").read_text()
    assert "rt_task" in acts and "greet_oc.py" in acts


def test_opencode_stream_lines_become_steps():
    tool = {"type": "tool_use", "timestamp": 1791900000000, "sessionID": "s", "part": {"tool": "bash", "state": {"status": "completed", "input": {"command": "git status"}}}}
    assert activity.from_opencode(tool) == [{"kind": "run", "text": "git status", "t": 1791900000.0}]
    edit = {"type": "tool_use", "part": {"tool": "edit", "state": {"status": "completed", "input": {"filePath": "/w/src/a.py"}}}}
    assert activity.from_opencode(edit, "/w") == [{"kind": "edit", "text": "src/a.py"}]
    mcp = {"type": "tool_use", "part": {"tool": "roundtable_rt_task", "state": {"status": "completed", "input": {"action": "claim", "task": "T2"}}}}
    assert activity.from_opencode(mcp) == [{"kind": "tool", "text": "rt_task claim T2"}]
    bad = {"type": "tool_use", "part": {"tool": "bash", "state": {"status": "error", "error": "permission denied: rm"}}}
    assert activity.from_opencode(bad)[0] == {"kind": "error", "text": "permission denied: rm"}
    err = {"type": "error", "error": {"name": "ProviderAuthError", "data": {"message": "no credentials"}}}
    assert activity.from_opencode(err) == [{"kind": "error", "text": "no credentials"}]


def test_who_makes_a_model():
    assert apps.company_of_model("opencode/kimi-k3") == "moonshot"
    assert apps.company_of_model("opencode/claude-sonnet-5-5") == "anthropic"
    assert apps.company_of_model("openrouter/qwen/qwen3.8-max") == "alibaba"
    assert apps.company_of_model("opencode/big-pickle") is None
    from roundtable_ai import seats

    assert seats.company_for("opencode", "opencode/big-pickle") == "other"


def test_rt_error_import():
    assert RTError

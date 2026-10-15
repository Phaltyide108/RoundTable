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


# ---------------------------------------------------------------- out of usage: the others carry on

def test_limit_messages_are_understood():
    import time

    now = time.mktime((2026, 10, 14, 19, 40, 0, 0, 0, -1))
    hm = lambda t: time.strftime("%d %H:%M", time.localtime(t))  # noqa: E731
    assert hm(runner.limit_until("You've hit your session limit · resets 9:20pm (Asia/Kolkata)", now)) == "14 21:20"
    assert hm(runner.limit_until("Usage limit reached. Your limit will reset at 3am", now)) == "15 03:00"
    assert hm(runner.limit_until("You've hit your usage limit. Try again in 2 hours 5 minutes.", now)) == "14 21:45"
    assert hm(runner.limit_until("rate limit exceeded", now)) == "14 20:10"
    assert runner.limit_until("the tests hit a limit of 3 retries", now) is None
    assert runner.limit_until("Fish obey the 3 rad/s turn rate limit; usage of the grid keeps it fast.", now) is None
    assert runner.limit_until("Claude usage limit reached. Your limit will reset at 3am", now) is not None
    assert runner.limit_until("", now) is None


def test_an_ai_out_of_usage_hands_its_task_over_with_the_work(rt, fake_apps, monkeypatch):
    from conftest import git

    team(rt)
    rt.human("plan.goal", goal="g", mode="quick", planners="opus")
    rt.seat("opus", "plan.propose", text="t", tasks=[{"ref": "1", "title": "Greet", "files": ["greet_opus.py"], "proof": ["python -c 'pass'"], "owner": "opus"},
                                                     {"ref": "2", "title": "Later", "files": ["later.py"], "proof": ["python -c 'pass'"], "owner": "opus", "depends_on": ["1"]}])
    rt.human("plan.lock")
    rt.seat("opus", "sync")
    rt.seat("opus", "task.claim", task="T1")
    wt_opus = Path(rt.q("SELECT worktree FROM seats WHERE handle = 'opus'")[0]["worktree"])
    (wt_opus / "greet_opus.py").write_text("def hello():\n    return 'opus'\n")
    git(wt_opus, "add", "greet_opus.py")
    git(wt_opus, "commit", "-q", "-m", "half of T1")
    monkeypatch.setenv("FAKE_LIMIT", "opus")
    runner.run_seat(rt.home, "opus", once=True)
    st = runner.read_state(rt.home, "opus")
    assert st["state"] == "stopped" and st["limited_until"] > 0 and "session limit" in st["limit_text"]
    t = rt.q("SELECT status, owner FROM tasks WHERE id = 'T1'")[0]
    assert t == {"status": "ready", "owner": None}
    assert rt.q("SELECT owner FROM tasks WHERE id = 'T2'")[0]["owner"] is None        # its planned task is freed too
    assert any(e["type"] == "task.handoff" for e in rt.q("SELECT type FROM events"))
    ctx = rt.ctx()
    try:
        from roundtable_ai import seats

        assert seats.limited_until(ctx, "opus") > 0
        assert [r["handle"] for r in council.eligible(ctx)] == ["sol"]          # councils skip it until the reset
    finally:
        ctx.close()
    rt.seat("sol", "sync")
    reply = rt.seat("sol", "task.claim", task="T1").text
    assert "take over from opus" in reply
    wt_sol = Path(rt.q("SELECT worktree FROM seats WHERE handle = 'sol'")[0]["worktree"])
    assert (wt_sol / "greet_opus.py").read_text() == "def hello():\n    return 'opus'\n"     # opus's work came along
    # while limited, its runner waits instead of retrying
    monkeypatch.delenv("FAKE_LIMIT")
    before = len(calls_log(rt))
    runner.run_seat(rt.home, "opus", once=True)
    assert len(calls_log(rt)) == before and runner.read_state(rt.home, "opus")["limited_until"] > 0


def test_reviews_of_an_ai_out_of_usage_go_to_another(rt):
    rt.add_seat("opus", model="claude-opus-5-5", app="claude-code", worktree=True)
    rt.add_seat("sol", model="gpt-6.1-sol", app="codex-cli", worktree=True)
    rt.add_seat("oc", model="opencode/glm-5.3", app="opencode", worktree=True)
    rt.human("plan.goal", goal="g", mode="quick", planners="opus")
    rt.seat("opus", "plan.propose", text="t", tasks=[{"ref": "1", "title": "A", "files": ["a.py"], "proof": ["true"], "owner": "opus"}])
    rt.human("plan.lock")
    ctx = rt.ctx()
    try:
        with ctx.tx():
            ctx.db.execute("UPDATE tasks SET status = 'in_review', review_round = 1 WHERE id = 'T1'")
            ctx.db.execute("INSERT INTO reviews(id, task, reviewer, level, round, verdict, created_at) VALUES ('R9', 'T1', 'sol', 'mid', 1, 'pending', '2026-10-14T10:00:00Z')")
            ctx.db.execute("INSERT INTO assignments(kind, seat, target, round, status, created_at) VALUES ('review', 'sol', 'T1', 1, 'open', '2026-10-14T10:00:00Z')")
        from roundtable_ai import seats, tasks

        with ctx.tx():
            seats.set_limited(ctx, "sol", 9999999999)
        moved, reviews = tasks.hand_over(ctx, "sol", "is out of usage until 21:20")
    finally:
        ctx.close()
    assert moved == [] and reviews == ["T1->oc"]
    open_ = rt.q("SELECT seat FROM assignments WHERE kind = 'review' AND status = 'open'")
    assert open_ == [{"seat": "oc"}]


def calls_log(rt):
    path = rt.home / "fake-calls.log"
    return path.read_text().splitlines() if path.exists() else []


def test_a_cold_session_is_not_resumed(rt, fake_apps):
    import time as _t

    rt.add_seat("opus", model="claude-opus-5-5", app="claude-code", worktree=True)
    ctx = rt.ctx()
    try:
        row = ctx.db.one("SELECT * FROM seats WHERE handle = 'opus'")
        seen = []
        orig = runner.headless_command
        runner.headless_command = lambda c, r, p, session: (seen.append(session), orig(c, r, p, session))[1]
        try:
            runner.run_once(ctx, row, [("note:x", "hello")], {"session": "s-old", "last_run": {"at": _t.time() - 3600}})
            runner.run_once(ctx, row, [("note:x", "hello")], {"session": "s-warm", "last_run": {"at": _t.time() - 30}})
        finally:
            runner.headless_command = orig
    finally:
        ctx.close()
    assert seen == [None, "s-warm"]


def test_numbered_answers_point_out_where_they_disagree():
    a = ("A", "1: 734\n2: 31\n3: friday\n4: 91")
    b = ("B", "1: 734\n2: 31.\n3: Friday\n4: 99")
    assert council.disagreements([a, b]) == ["4"]
    assert council.disagreements([("A", "free text"), ("B", "other text")]) == []
    c = {"question": "q", "workdir": "/tmp", "context": ""}
    assert "disagree on item 4" in council.rank_prompt(c, [a, b])
    assert "disagree on item 4" in council.final_prompt(c, [a, b], ["r"], "A")


def test_offline_council_runs_use_no_tools(monkeypatch, tmp_path):
    monkeypatch.setenv("RT_COUNCIL_OFFLINE", "1")
    monkeypatch.setattr(council.launch if hasattr(council, "launch") else __import__("roundtable_ai.launch", fromlist=["x"]), "_exe", lambda name: name, raising=False)
    from roundtable_ai import launch
    monkeypatch.setattr(launch, "_exe", lambda name: name)
    cmd, _env = council.command({"handle": "h", "app": "claude-code", "model": "claude-haiku-5-5", "effort": "low"}, "q", tmp_path)
    assert "--allowedTools" not in cmd and "WebSearch" in cmd[cmd.index("--disallowedTools") + 1] and "Bash" in cmd[cmd.index("--disallowedTools") + 1]
    _cmd, env = council.command({"handle": "o", "app": "opencode", "model": "opencode/big-pickle", "effort": None}, "q", tmp_path)
    assert json.loads(env["OPENCODE_PERMISSION"]) == {"edit": "deny", "webfetch": "deny", "bash": "deny"}
    assert "no tools" in council._project_line(tmp_path)
    # Codex too: no shell (so no python), no browser, no web search, no MCP, and an empty folder instead of the project
    cmd, _env = council.command({"handle": "x", "app": "codex-cli", "model": "gpt-6-luna", "effort": "low"}, "q", tmp_path)
    disabled = {cmd[i + 1] for i, a in enumerate(cmd) if a == "--disable"}
    assert {"shell_tool", "browser_use", "computer_use", "apps", "in_app_browser"} <= disabled
    assert 'web_search="disabled"' in cmd and "mcp_servers={}" in cmd
    folder = Path(cmd[cmd.index("-C") + 1])
    assert folder != tmp_path and folder.is_dir() and not any(folder.iterdir())

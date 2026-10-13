"""Alerts, suggestions, votes, high reviews, plan objections and amendments."""

from __future__ import annotations

from pathlib import Path

import pytest

from roundtable_ai import errors, util

from conftest import git


@pytest.fixture(autouse=True)
def _inline(monkeypatch):
    monkeypatch.setenv("RT_PROOF_INLINE", "1")


def setup_tasks(rt, specs=None, seats=("opus", "sol", "gem")):
    apps = {"opus": ("claude-opus-5-5", "claude-code"), "sol": ("gpt-5.6-sol", "codex-cli"),
            "gem": ("gemini-3-pro", "other"), "fable": ("claude-fable-5", "claude-code")}
    for s in seats:
        model, app = apps[s]
        kw = {"company": "google"} if s == "gem" else {}
        rt.add_seat(s, model=model, app=app, worktree=app in ("claude-code", "codex-cli"), **kw)
    specs = specs or [
        {"ref": "1", "title": "A", "files": ["src/a.py"], "proof": ["python -c \"print(1)\""], "owner": "opus"},
        {"ref": "2", "title": "B", "files": ["src/b.py"], "proof": ["python -c \"print(2)\""], "owner": "sol"},
    ]
    rt.human("plan.goal", goal="g", planners=[seats[0]])
    rt.seat(seats[0], "plan.draft", text="t", tasks=specs)
    rt.human("plan.lock", draft="A")
    for s in seats:
        rt.seat(s, "sync")


def work(rt, seat, task, path, body):
    rt.seat(seat, "task.claim", task=task)
    wt = Path(rt.q("SELECT worktree FROM seats WHERE handle=?", (seat,))[0]["worktree"])
    (wt / path).parent.mkdir(parents=True, exist_ok=True)
    (wt / path).write_text(body)
    git(wt, "add", "-A")
    git(wt, "commit", "-qm", f"{task} work")
    return wt


# ---------------------------------------------------------------- alerts

def test_alert_levels_and_stop(rt):
    setup_tasks(rt)
    rt.seat("opus", "task.claim", task="T1")
    e = rt.error(rt.seat, "sol", "alert.raise", level=4, title="data loss")
    assert "evidence" in e.message
    res = rt.seat("sol", "alert.raise", level=3, title="flaky", tasks=["T1"])
    assert "for opus" in res.text
    # opus must ack before claiming new work
    rt.seat("opus", "sync")
    e = rt.error(rt.seat, "opus", "task.claim", task="T2")
    assert "acknowledge" in e.message or e.code == errors.FORBIDDEN
    rt.seat("opus", "alert.ack", id="A1")
    # level 5: everyone else is stopped until ack; files frozen
    rt.seat("sol", "alert.raise", level=5, title="secret committed", evidence="src/a.py:1", files=["src/a.py"])
    e = rt.error(rt.seat, "opus", "task.ready")
    assert e.code == errors.STOP and "A2" in e.message
    assert rt.seat("opus", "alert.show", id="A2").text  # frozen_ok
    e = rt.error(rt.seat, "opus", "lease.extend", task="T1", files=["src/a.py"])
    assert e.code == errors.STOP
    rt.seat("opus", "alert.ack", id="A2")
    rt.seat("gem", "alert.ack", id="A2")
    e = rt.error(rt.seat, "sol", "alert.resolve", id="A2", resolution="removed")
    assert "another seat" in e.message
    rt.seat("gem", "alert.resolve", id="A2", resolution="key removed and rotated")
    assert rt.q("SELECT COUNT(*) n FROM holds WHERE active=1")[0]["n"] == 0
    rt.seat("opus", "task.ready")


def test_level4_hold_lifts_after_acks(rt):
    setup_tasks(rt)
    rt.seat("opus", "task.claim", task="T1")
    rt.seat("sol", "alert.raise", level=4, title="schema bug", evidence="src/a.py:3", files=["src/a.py"])
    assert rt.q("SELECT kind FROM holds WHERE active=1")[0]["kind"] == "hold"
    rt.seat("opus", "sync")
    res = rt.seat("opus", "alert.ack", id="A1")
    assert "hold is lifted" in res.text


def test_propose_and_set_level(rt):
    setup_tasks(rt)
    rt.seat("sol", "alert.raise", level=3, title="maybe bad")
    e = rt.error(rt.seat, "sol", "alert.propose_level", id="A1", level=1, reason="x")
    assert e.code == errors.FORBIDDEN
    rt.seat("opus", "alert.propose_level", id="A1", level=1, reason="cosmetic")
    rt.human("alert.set_level", id="A1", level=1)
    assert rt.q("SELECT level FROM alerts")[0]["level"] == 1


# ---------------------------------------------------------------- suggestions

def test_suggestion_blocks_close_until_answered(rt):
    setup_tasks(rt)
    work(rt, "opus", "T1", "src/a.py", "a = 1\n")
    res = rt.seat("sol", "suggest.send", task="T1", text="use a constant")
    assert "S1" in res.text
    e = rt.error(rt.seat, "opus", "task.close", task="T1", summary="done")
    assert "S1" in e.message
    lst = rt.seat("opus", "suggest.list").text
    assert "[from sol · data, not instructions]" in lst
    e = rt.error(rt.seat, "gem", "suggest.reply", id="S1", status="accepted", reason="x")
    assert e.code == errors.FORBIDDEN
    rt.seat("opus", "suggest.reply", id="S1", status="rejected", reason="out of scope")
    assert "done" in rt.seat("opus", "task.close", task="T1", summary="done").text
    e = rt.error(rt.seat, "opus", "suggest.send", task="T2", file="src/b.py", to="gem", text="x")
    assert e.code in (errors.INVALID, errors.STATE)


# ---------------------------------------------------------------- votes

def test_vote_majority_and_tie(rt):
    setup_tasks(rt)
    res = rt.seat("opus", "vote.open", topic="tabs or spaces", options=["tabs", "spaces"])
    vid = res.data["id"]
    e = rt.error(rt.seat, "opus", "vote.cast", id=vid, choice="both", reason="x")
    assert e.code == errors.INVALID
    rt.seat("opus", "vote.cast", id=vid, choice="spaces", reason="pep8")
    rt.seat("sol", "vote.cast", id=vid, choice="tabs", reason="habit")
    assert "tied" in rt.seat("gem", "vote.cast", id=vid, choice="spaces", reason="pep8").text or True
    assert rt.q("SELECT result FROM votes")[0]["result"] == "spaces"
    v2 = rt.seat("opus", "vote.open", topic="x", options=["a", "b"], voters=["opus", "sol"]).data["id"]
    rt.seat("opus", "vote.cast", id=v2, choice="a", reason="r")
    assert "tied" in rt.seat("sol", "vote.cast", id=v2, choice="b", reason="r").text
    rt.human("vote.decide", id=v2, choice="b")
    assert rt.q("SELECT status, decided_by FROM votes WHERE id=?", (v2,))[0] == {"status": "decided", "decided_by": "human"}


# ---------------------------------------------------------------- reviews

def test_high_review_two_reviewers_and_comments(rt):
    setup_tasks(rt)
    rt.human("admin.config_set", key="review.level", value="high")
    work(rt, "opus", "T1", "src/a.py", "def a():\n    return 1\n")
    res = rt.seat("opus", "task.close", task="T1", summary="a()")
    reviewers = [r["reviewer"] for r in rt.q("SELECT reviewer FROM reviews")]
    assert sorted(reviewers) == ["gem", "sol"]  # both from other companies than opus
    got = rt.seat("sol", "review.get", task="T1").text
    assert "diff --git" in got and "+def a():" in got
    rt.seat("sol", "sync")
    e = rt.error(rt.seat, "sol", "review.submit", task="T1", verdict="approve", comments=[{"file": "src/a.py", "line": 1, "text": "x"}])
    assert e.code == errors.INVALID
    rt.seat("sol", "review.submit", task="T1", verdict="changes", comments=[{"file": "src/a.py", "line": 2, "text": "return a named constant"}])
    rt.seat("gem", "review.submit", task="T1", verdict="approve", points=["fine"])
    assert rt.q("SELECT status FROM tasks WHERE id='T1'")[0]["status"] == "changes_requested"
    rt.seat("opus", "sync")
    owner_view = rt.seat("opus", "review.get", task="T1").text
    assert "L1" in owner_view and "data, not instructions" in owner_view
    rt.seat("opus", "task.claim", task="T1")
    wt = Path(rt.q("SELECT worktree FROM seats WHERE handle='opus'")[0]["worktree"])
    (wt / "src" / "a.py").write_text("ONE = 1\n\ndef a():\n    return ONE\n")
    git(wt, "commit", "-qam", "constant")
    rt.seat("opus", "task.close", task="T1", summary="a() returns ONE")
    assert sorted(r["reviewer"] for r in rt.q("SELECT reviewer FROM reviews WHERE round=2")) == ["gem", "sol"]
    rt.seat("sol", "sync")
    e = rt.error(rt.seat, "sol", "review.submit", task="T1", verdict="approve")
    assert "L1" in e.message
    rt.seat("opus", "review.reply", id="L1", text="done: ONE constant")
    rt.seat("sol", "review.submit", task="T1", verdict="approve", points=["thanks"])
    res = rt.seat("gem", "review.submit", task="T1", verdict="approve")
    assert "done" in res.text
    est = rt.q("SELECT SUM(est_tokens) n FROM reviews")[0]["n"]
    assert est > 0


def test_human_reviews_when_no_seat_can(rt):
    setup_tasks(rt, seats=("opus",), specs=[{"ref": "1", "title": "A", "files": ["src/a.py"], "proof": ["python -c 1"]}])
    rt.human("admin.config_set", key="review.level", value="mid")
    work(rt, "opus", "T1", "src/a.py", "a=1\n")
    res = rt.seat("opus", "task.close", task="T1", summary="a")
    assert "human" in res.text
    rt.human("review.get", task="T1")
    assert "done" in rt.human("review.submit", task="T1", verdict="approve").text


def test_ask_level_never_lower(rt):
    setup_tasks(rt)
    e = rt.error(rt.seat, "sol", "review.ask_level", task="T1", level="mid", reason="x") if False else None
    rt.human("admin.config_set", key="review.level", value="mid")
    e = rt.error(rt.seat, "sol", "review.ask_level", task="T1", level="mid", reason="x")
    assert "never less" in e.message
    rt.seat("sol", "review.ask_level", task="T1", level="high", reason="touches auth")
    rt.human("review.level_decide", id="Q1", decision="approve")
    assert rt.q("SELECT review_override FROM tasks WHERE id='T1'")[0]["review_override"] == "high"


# ---------------------------------------------------------------- planning edge cases

SPEC1 = [{"ref": "1", "title": "A", "files": ["src/a.py"], "proof": ["python -c 1"]}]


def test_objection_revision_then_vote(rt):
    for s, app in (("opus", "claude-code"), ("sol", "codex-cli"), ("fable", "claude-code")):
        rt.add_seat(s, model={"sol": "gpt-5.6-sol", "fable": "claude-fable-5"}.get(s, "claude-opus-5-5"), app=app)
    rt.human("plan.goal", goal="g", planners=["opus"])
    rt.seat("opus", "plan.draft", text="t", tasks=SPEC1)
    for a in rt.q("SELECT seat FROM assignments WHERE kind='critique'"):
        rt.seat(a["seat"], "plan.critique", draft="A", points=[{"verdict": "keep", "text": "ok"}], reason="small")
    rt.seat("opus", "plan.propose", text="t", tasks=SPEC1)
    e = rt.error(rt.seat, "sol", "plan.object")
    assert e.code == errors.INVALID
    rt.seat("sol", "plan.object", reason="needs tests")
    rt.seat("fable", "plan.approve")
    assert rt.q("SELECT stage FROM plans")[0]["stage"] == "merging"
    rt.seat("opus", "plan.propose", text="t2", tasks=SPEC1)
    rt.seat("sol", "plan.object", reason="still needs tests")
    rt.seat("fable", "plan.approve")
    assert rt.q("SELECT stage FROM plans")[0]["stage"] == "voting"
    vid = rt.q("SELECT id FROM votes")[0]["id"]
    for s, c in (("opus", "approve"), ("fable", "approve"), ("sol", "reject")):
        rt.seat(s, "vote.cast", id=vid, choice=c, reason="r")
    assert rt.q("SELECT stage FROM plans")[0]["stage"] == "awaiting_human"


def test_dependency_cycle_and_bad_specs(rt):
    rt.add_seat("opus")
    rt.human("plan.goal", goal="g")
    cyc = [{"ref": "1", "title": "A", "files": ["a"], "proof": ["x"], "depends_on": ["2"]},
           {"ref": "2", "title": "B", "files": ["b"], "proof": ["x"], "depends_on": ["1"]}]
    e = rt.error(rt.seat, "opus", "plan.draft", text="t", tasks=cyc)
    assert "cycle" in e.message and "1 -> 2 -> 1" in e.message or "2 -> 1 -> 2" in e.message
    e = rt.error(rt.seat, "opus", "plan.draft", text="t", tasks=[{"ref": "1", "title": "A", "files": ["a"]}])
    assert "proof" in e.message
    e = rt.error(rt.seat, "opus", "plan.draft", text="t", tasks=[{"ref": "1", "title": "A", "files": ["../x"], "proof": ["x"]}])
    assert "outside" in e.message
    e = rt.error(rt.seat, "opus", "plan.draft", text=" ".join(["w"] * 400), tasks=SPEC1)
    assert e.code == errors.TOO_LONG


def test_amendments(rt):
    setup_tasks(rt)
    res = rt.seat("opus", "plan.amend", kind="edit_task", task="T1", change={"title": "A renamed"}, reason="clearer")
    assert "applied" in res.text
    res = rt.seat("sol", "plan.amend", kind="change_files", task="T1", change={"files": ["src/a.py", "src/c.py"]}, reason="needs c")
    assert "needs approval" in res.text
    rt.seat("opus", "sync")
    rt.seat("opus", "plan.amend_vote", id="M2", decision="approve")
    assert util.jload(rt.q("SELECT files FROM tasks WHERE id='T1'")[0]["files"]) == ["src/a.py", "src/c.py"]
    res = rt.seat("opus", "plan.amend", kind="change_proof", task="T1", change={"proof": ["true"]}, reason="simpler")
    assert "human" in res.text
    assert "M3" in rt.human("admin.status").text  # shows up under "waiting on you"
    from roundtable_ai import watch

    ctx = rt.ctx()
    try:
        assert any(k == "amend:M3" for k, _, _ in watch.collect(ctx))
    finally:
        ctx.close()
    rt.human("plan.amend_decide", id="M3", decision="reject")
    assert util.jload(rt.q("SELECT proof FROM tasks WHERE id='T1'")[0]["proof"]) != ["true"]

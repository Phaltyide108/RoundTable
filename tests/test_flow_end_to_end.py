"""A whole project, start to finish: plan blind, critique, lock, build, proof, review, merge."""

from __future__ import annotations

import subprocess

import pytest

from roundtable_ai import errors

from conftest import git


@pytest.fixture(autouse=True)
def _inline_proofs(monkeypatch):
    monkeypatch.setenv("RT_PROOF_INLINE", "1")


def three_seats(rt):
    rt.add_seat("opus", worktree=True)
    rt.add_seat("sol", model="gpt-5.6-sol", app="codex-cli", worktree=True)
    rt.add_seat("fable", model="claude-fable-5", app="claude-app")


SPECS = [
    {"ref": "1", "title": "Add greet()", "files": ["src/greet.py"], "proof": ["python -c \"import src.greet\""], "owner": "opus"},
    {"ref": "2", "title": "Add farewell()", "files": ["src/bye.py"], "proof": ["python -c \"import src.bye\""], "owner": "sol", "depends_on": ["1"]},
]


def plan_and_lock(rt):
    rt.human("plan.goal", goal="Add greeting helpers", planners=["opus", "sol"])
    rt.seat("opus", "plan.draft", text="Two small modules, greet first.", tasks=SPECS)
    view = rt.seat("sol", "plan.view").text
    assert "greet first" not in view  # blind: sol cannot see opus's draft yet
    res = rt.seat("sol", "plan.draft", text="Same idea, keep it simple.", tasks=SPECS)
    assert "drafting closed" in res.text
    # critiques: every assignment, never one's own, labels not authors
    rows = rt.q("SELECT a.seat, d.author, d.label FROM assignments a JOIN drafts d ON d.id = a.target WHERE a.kind='critique'")
    assert rows and all(r["seat"] != r["author"] for r in rows)
    for r in rows:
        v = rt.seat(r["seat"], "plan.view").text
        assert "by opus" not in v and "by sol" not in v
        rt.seat(r["seat"], "plan.critique", draft=r["label"], points=[{"verdict": "change", "text": "add docstrings"}])
    chair = rt.q("SELECT chair, stage FROM plans")[0]
    assert chair["stage"] == "merging"
    rt.seat(chair["chair"], "plan.propose", text="Merged: greet then farewell.", tasks=SPECS)
    for s in ("opus", "sol", "fable"):
        if s != chair["chair"]:
            rt.seat(s, "plan.approve")
    assert rt.q("SELECT stage FROM plans")[0]["stage"] == "awaiting_human"
    out = rt.human("plan.lock").text
    assert "T1:" in out and "import src.greet" in out
    return chair["chair"]


def test_full_flow_low_review(rt, repo):
    three_seats(rt)
    plan_and_lock(rt)
    tasks = rt.q("SELECT id, status, owner FROM tasks ORDER BY id")
    assert [(t["id"], t["status"]) for t in tasks] == [("T1", "ready"), ("T2", "open")]
    # must sync before claiming (plan.locked was addressed to every seat)
    e = rt.error(rt.seat, "opus", "task.claim", task="T1")
    assert e.code == errors.STATE and "rt_sync" in e.hint
    rt.seat("opus", "sync")
    e = rt.error(rt.seat, "sol", "task.claim", task="T1")
    assert e.code in (errors.STATE, errors.FORBIDDEN)
    res = rt.seat("opus", "task.claim", task="T1")
    assert "rt/opus/T1" in res.text
    wt = rt.q("SELECT worktree FROM seats WHERE handle='opus'")[0]["worktree"]
    from pathlib import Path

    (Path(wt) / "src" / "greet.py").write_text("def greet():\n    return 'hello'\n")
    e = rt.error(rt.seat, "opus", "task.close", task="T1", summary="added greet")
    assert "commit" in e.message
    git(Path(wt), "add", "-A")
    git(Path(wt), "commit", "-q", "-m", "greet")
    rt.seat("opus", "task.checkpoint", task="T1", summary="greet() returns hello")
    res = rt.seat("opus", "task.close", task="T1", summary="added greet()")
    assert "done and merged" in res.text, res.text
    assert (repo / "src" / "greet.py").exists()  # merged into main
    assert rt.q("SELECT status FROM tasks WHERE id='T2'")[0]["status"] == "ready"
    log = git(repo, "log", "--oneline", "-3")
    assert "Roundtable T1" in log


def test_mid_review_cross_company_and_changes(rt, repo):
    from pathlib import Path

    three_seats(rt)
    plan_and_lock(rt)
    rt.human("admin.config_set", key="review.level", value="mid")
    rt.seat("opus", "sync")
    rt.seat("opus", "task.claim", task="T1")
    wt = Path(rt.q("SELECT worktree FROM seats WHERE handle='opus'")[0]["worktree"])
    (wt / "src" / "greet.py").write_text("def greet():\n    return 'hello'\n")
    git(wt, "add", "-A")
    git(wt, "commit", "-q", "-m", "greet")
    res = rt.seat("opus", "task.close", task="T1", summary="added greet()")
    assert "in review" in res.text and "sol" in res.text  # other company preferred
    got = rt.seat("sol", "review.get", task="T1").text
    assert "src/greet.py" in got and "diff --git" not in got  # mid: no full code (T1 is not a spot check)
    rt.seat("sol", "sync")
    res = rt.seat("sol", "review.submit", task="T1", verdict="changes", points=["add a docstring"])
    assert "sent back" in res.text
    rt.seat("opus", "sync")
    rt.seat("opus", "task.claim", task="T1")  # resume
    (wt / "src" / "greet.py").write_text('def greet():\n    """Say hello."""\n    return "hello"\n')
    git(wt, "commit", "-qam", "docstring")
    res = rt.seat("opus", "task.close", task="T1", summary="added greet() with docstring")
    assert "in review" in res.text and "sol" in res.text
    rt.seat("sol", "sync")
    res = rt.seat("sol", "review.submit", task="T1", verdict="approve", points=["good"])
    assert "done" in res.text


def test_failing_proof_returns_task(rt, repo):
    from pathlib import Path

    three_seats(rt)
    rt.human("plan.goal", goal="x", planners=["opus"])
    bad = [{"ref": "1", "title": "Broken", "files": ["src/x.py"], "proof": ["python -c \"import sys; print('boom'); sys.exit(3)\""]}]
    rt.seat("opus", "plan.draft", text="t", tasks=bad)
    # sol and fable critique opus's draft, then opus (chair) proposes
    for a in rt.q("SELECT seat, target FROM assignments WHERE kind='critique'"):
        rt.seat(a["seat"], "plan.critique", draft="A", points=[{"verdict": "keep", "text": "fine"}], reason="small task")
    rt.seat("opus", "plan.propose", text="t", tasks=bad)
    rt.human("plan.lock", force=True)
    rt.seat("opus", "sync")
    rt.seat("opus", "task.claim", task="T1")
    wt = Path(rt.q("SELECT worktree FROM seats WHERE handle='opus'")[0]["worktree"])
    (wt / "src" / "x.py").write_text("x = 1\n")
    git(wt, "add", "-A")
    git(wt, "commit", "-qm", "x")
    res = rt.seat("opus", "task.close", task="T1", summary="x")
    assert "proof failed (exit 3)" in res.text and "boom" in res.text
    assert rt.q("SELECT status FROM tasks WHERE id='T1'")[0]["status"] == "claimed"


def test_unleased_change_refused(rt, repo):
    from pathlib import Path

    three_seats(rt)
    plan_and_lock(rt)
    rt.seat("opus", "sync")
    rt.seat("opus", "task.claim", task="T1")
    wt = Path(rt.q("SELECT worktree FROM seats WHERE handle='opus'")[0]["worktree"])
    (wt / "src" / "greet.py").write_text("x=1\n")
    (wt / "README.md").write_text("changed\n")
    git(wt, "add", "src/greet.py")
    git(wt, "commit", "-qm", "ok")
    # the guard hook stops committing README.md (not leased)
    git(wt, "add", "README.md")
    out = subprocess.run(["git", "-C", str(wt), "commit", "-qm", "readme"], capture_output=True, text=True)
    assert out.returncode != 0 and "not in your leases" in out.stderr
    # bypassing the hook does not help: close refuses
    git(wt, "commit", "-qm", "readme", "--no-verify")
    e = rt.error(rt.seat, "opus", "task.close", task="T1", summary="x")
    assert e.code == errors.FORBIDDEN and "README.md" in e.message


def test_shared_folder_mode(rt_nogit):
    rt = rt_nogit
    rt.add_seat("opus")
    rt.add_seat("sol", model="gpt-5.6-sol", app="codex-cli")
    rt.human("plan.goal", goal="notes", planners=["opus"])
    specs = [{"ref": "1", "title": "Write notes", "files": ["notes.txt"], "proof": ["python -c \"print(1)\""]}]
    rt.seat("opus", "plan.draft", text="t", tasks=specs)
    rt.human("plan.lock", draft="A")
    rt.seat("opus", "sync")
    rt.seat("opus", "task.claim", task="T1")
    e = rt.error(rt.seat, "sol", "lease.extend", task="T1", files=["notes.txt"])
    assert e.code in (errors.FORBIDDEN, errors.CONFLICT)
    res = rt.seat("opus", "task.close", task="T1", summary="wrote notes")
    assert "done" in res.text


def test_roundtable_commits_for_sandboxed_seat(rt, repo):
    """Codex's sandbox keeps .git read-only, so a seat can ask Roundtable to commit its leased files."""
    from pathlib import Path

    three_seats(rt)
    plan_and_lock(rt)
    rt.seat("opus", "sync")
    rt.seat("opus", "task.claim", task="T1")
    wt = Path(rt.q("SELECT worktree FROM seats WHERE handle='opus'")[0]["worktree"])
    (wt / "src" / "greet.py").write_text("def greet():\n    return 'hello'\n")
    (wt / "README.md").write_text("not mine\n")
    (wt / "__pycache__").mkdir()
    (wt / "__pycache__" / "x.pyc").write_bytes(b"0")
    res = rt.seat("opus", "task.checkpoint", task="T1", summary="greet() returns hello", commit=True)
    assert "committed 1 file(s)" in res.text and "README.md" in res.text
    log = git(wt, "log", "-1", "--format=%an|%s|%H")
    assert log.startswith("opus (claude-opus-5-5)|T1: greet() returns hello")
    assert git(wt, "show", "--name-only", "--format=", "HEAD").split() == ["src/greet.py"]
    again = rt.seat("opus", "task.checkpoint", task="T1", summary="no changes", commit=True)
    assert "nothing new to commit" in again.text
    # README.md is still uncommitted and not leased; close must not sweep it in
    git(wt, "checkout", "--", "README.md")
    (wt / "src" / "greet.py").write_text("def greet():\n    return 'hello!'\n")
    res = rt.seat("opus", "task.close", task="T1", summary="added greet()", commit=True)
    assert "committed 1 file(s)" in res.text and "done and merged" in res.text, res.text

"""Concurrency, leases, background proofs, merges and the digest."""

from __future__ import annotations

import multiprocessing as mp
import subprocess
import sys
import time
from pathlib import Path

import pytest

from roundtable_ai import errors, gitops, util
from roundtable_ai.context import open_ctx

from conftest import git

SPECS = [
    {"ref": str(i), "title": f"Task {i}", "files": [f"src/m{i}.py"], "proof": ["python -c \"print('ok')\""]}
    for i in range(1, 4)
]


def ready_project(rt, seats=("opus", "sol"), specs=SPECS, worktree=True):
    models = {"opus": ("claude-opus-5-5", "claude-code"), "sol": ("gpt-5.6-sol", "codex-cli"),
              "fable": ("claude-fable-5", "claude-code"), "o3": ("gpt-o3", "codex-cli")}
    for s in seats:
        m, a = models[s]
        rt.add_seat(s, model=m, app=a, worktree=worktree)
    rt.human("plan.goal", goal="g", planners=[seats[0]])
    rt.seat(seats[0], "plan.draft", text="t", tasks=specs)
    rt.human("plan.lock", draft="A")
    for s in seats:
        rt.seat(s, "sync")


def _claim(home, seat, q):
    from roundtable_ai import dispatch
    from roundtable_ai.errors import RTError

    try:
        dispatch.call("task.claim", {"task": "T1"}, home=home, seat=seat, pinned=True, as_human=False)
        q.put((seat, "won"))
    except RTError as e:
        q.put((seat, e.code))


def test_concurrent_claims_one_winner(rt):
    ready_project(rt, seats=("opus", "sol", "fable", "o3"), worktree=False)
    rt.human("admin.config_set", key="git.worktrees", value="false")
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    procs = [ctx.Process(target=_claim, args=(str(rt.home), s, q)) for s in ("opus", "sol", "fable", "o3")]
    for p in procs:
        p.start()
    for p in procs:
        p.join(60)
    results = [q.get(timeout=5) for _ in procs]
    winners = [s for s, r in results if r == "won"]
    assert len(winners) == 1, results
    assert rt.q("SELECT owner FROM tasks WHERE id='T1'")[0]["owner"] == winners[0]


def test_lease_conflict_and_expiry(rt, monkeypatch):
    specs = [{"ref": "1", "title": "A", "files": ["src/**"], "proof": ["python -c 1"]},
             {"ref": "2", "title": "B", "files": ["src/api/x.py"], "proof": ["python -c 1"]}]
    ready_project(rt, specs=specs)
    rt.seat("opus", "task.claim", task="T1")
    e = rt.error(rt.seat, "sol", "task.claim", task="T2")
    assert e.code == errors.CONFLICT and "opus" in e.message and "rt_suggest" in e.hint
    assert rt.q("SELECT status, owner FROM tasks WHERE id='T2'")[0] == {"status": "ready", "owner": None}  # nothing half-done
    # opus goes quiet: its leases expire, then sol can claim
    ctx = open_ctx(rt.home)
    with ctx.tx():
        ctx.db.execute("UPDATE leases SET expires_at = ? WHERE seat = 'opus'", (util.add_seconds(util.now(), -5),))
    ctx.close()
    rt.seat("sol", "task.claim", task="T2")
    assert rt.q("SELECT state FROM leases WHERE seat='opus'")[0]["state"] == "expired"
    ev = rt.q("SELECT text FROM events WHERE type='lease.expired'")
    assert ev and "opus" in ev[0]["text"]


def test_background_proof_end_to_end(rt, monkeypatch):
    monkeypatch.delenv("RT_PROOF_INLINE", raising=False)
    ready_project(rt)
    rt.human("admin.config_set", key="proof.wait_seconds", value="0")
    rt.seat("opus", "task.claim", task="T1")
    wt = Path(rt.q("SELECT worktree FROM seats WHERE handle='opus'")[0]["worktree"])
    (wt / "src" / "m1.py").write_text("x = 1\n")
    git(wt, "add", "-A")
    git(wt, "commit", "-qm", "m1")
    res = rt.seat("opus", "task.close", task="T1", summary="m1")
    assert "still running" in res.text or "proof passed" in res.text
    deadline = time.time() + 60
    while time.time() < deadline:
        if rt.q("SELECT status FROM tasks WHERE id='T1'")[0]["status"] == "done":
            break
        time.sleep(0.3)
    assert rt.q("SELECT status FROM tasks WHERE id='T1'")[0]["status"] == "done"
    assert rt.q("SELECT status FROM proof_runs")[0]["status"] == "passed"
    digest = rt.seat("opus", "sync").text
    assert "T1" in digest


def test_proof_timeout_and_output_cap(rt, monkeypatch):
    monkeypatch.setenv("RT_PROOF_INLINE", "1")
    loud = "python -c \"import time; [print(i) for i in range(500)]; time.sleep(30)\""
    ready_project(rt, specs=[{"ref": "1", "title": "A", "files": ["src/a.py"], "proof": [loud]}])
    rt.human("admin.config_set", key="proof.timeout_seconds", value="2")
    rt.seat("opus", "task.claim", task="T1")
    wt = Path(rt.q("SELECT worktree FROM seats WHERE handle='opus'")[0]["worktree"])
    (wt / "src" / "a.py").write_text("a = 1\n")
    git(wt, "add", "-A")
    git(wt, "commit", "-qm", "a")
    t0 = time.time()
    res = rt.seat("opus", "task.close", task="T1", summary="a")
    assert time.time() - t0 < 20
    assert "timed out" in res.text
    tail = rt.q("SELECT output_tail FROM proof_runs")[0]["output_tail"]
    assert len(tail.splitlines()) <= 40 and "499" in tail


def test_dead_runner_detected(rt):
    ready_project(rt)
    ctx = open_ctx(rt.home)
    with ctx.tx():
        ctx.db.execute("UPDATE tasks SET status='proving', owner='opus' WHERE id='T1'")
        ctx.db.execute("INSERT INTO proof_runs(id, task, seat, commands, status, workdir, pid, started_at, created_at) VALUES "
                       "('PR9','T1','opus','[\"x\"]','running','.', 999999, ?, ?)", (util.add_seconds(util.now(), -60), util.now()))
    from roundtable_ai import proofs

    assert proofs.check_stale(ctx) == ["PR9"]
    ctx.close()
    assert rt.q("SELECT status FROM tasks WHERE id='T1'")[0]["status"] == "claimed"


def _finish(rt, seat, task, rel, body, msg="work"):
    rt.seat(seat, "task.claim", task=task)
    wt = Path(rt.q("SELECT worktree FROM seats WHERE handle=?", (seat,))[0]["worktree"])
    (wt / rel).write_text(body)
    git(wt, "add", "-A")
    git(wt, "commit", "-qm", msg)
    return rt.seat(seat, "task.close", task=task, summary=msg)


def test_merge_blocked_by_dirty_main_then_retry(rt, repo, monkeypatch):
    monkeypatch.setenv("RT_PROOF_INLINE", "1")
    ready_project(rt)
    (repo / "README.md").write_text("human is editing\n")
    res = _finish(rt, "opus", "T1", "src/m1.py", "x=1\n")
    assert "waits to merge" in res.text
    assert rt.q("SELECT status FROM tasks WHERE id='T1'")[0]["status"] == "merge_blocked"
    assert (repo / "README.md").read_text() == "human is editing\n"  # never touched
    git(repo, "checkout", "README.md")
    assert "done" in rt.human("task.merge").text
    assert (repo / "src" / "m1.py").exists()


def test_merge_conflict_alerts_owner(rt, repo, monkeypatch):
    monkeypatch.setenv("RT_PROOF_INLINE", "1")
    ready_project(rt, specs=[{"ref": "1", "title": "A", "files": ["src/app.py"], "proof": ["python -c 1"]}])
    rt.seat("opus", "task.claim", task="T1")
    (repo / "src" / "app.py").write_text("def hello():\n    return 'human'\n")
    git(repo, "commit", "-qam", "human change after the claim")
    res = _finish(rt, "opus", "T1", "src/app.py", "def hello():\n    return 'opus'\n")
    assert "waits to merge" in res.text and rt.q("SELECT status FROM tasks")[0]["status"] == "merge_blocked"
    alert = rt.q("SELECT level, must_ack FROM alerts")[0]
    assert alert["level"] == 3 and "opus" in alert["must_ack"]
    assert git(repo, "status", "--porcelain").strip() == ""  # merge aborted cleanly


def test_digest_folding_and_cap(rt):
    ready_project(rt, seats=("opus", "sol", "fable"))
    rt.human("admin.config_set", key="limits.digest_lines", value="3")
    rt.seat("sol", "task.claim", task="T2")
    for i in range(6):
        rt.seat("sol", "task.checkpoint", task="T2", summary=f"step {i}")
    rt.seat("fable", "task.now", text="reading")
    d = rt.seat("opus", "sync").text
    assert "other seats: sol" in d and "none touch your work" in d
    rt.seat("opus", "task.claim", task="T1")
    rt.seat("sol", "suggest.send", task="T1", text="idea")
    d = rt.seat("opus", "sync").text
    assert "S1" in d and "reply to suggestion S1" in d
    assert "no changes" in rt.seat("opus", "sync").text


def test_guard_never_breaks_git_when_uninstalled(rt, repo):
    ready_project(rt)
    rt.seat("opus", "task.claim", task="T1")
    wt = Path(rt.q("SELECT worktree FROM seats WHERE handle='opus'")[0]["worktree"])
    hook = Path(gitops.ok(repo, "rev-parse", "--git-common-dir").strip())
    hook = (repo / hook if not hook.is_absolute() else hook) / "hooks" / "pre-commit"
    hook.write_text(hook.read_text().replace(Path(sys.executable).as_posix(), "/nonexistent/python"))
    (wt / "README.md").write_text("x\n")
    git(wt, "add", "-A")
    out = subprocess.run(["git", "-C", str(wt), "commit", "-qm", "x"], capture_output=True, text=True)
    assert out.returncode == 0 and "guard skipped" in out.stderr


def test_existing_hook_is_chained(tmp_path, monkeypatch):
    from conftest import Harness, make_repo
    from roundtable_ai import project

    root = make_repo(tmp_path / "p")
    monkeypatch.chdir(root)
    (root / ".git" / "hooks" / "pre-commit").write_text("#!/bin/sh\necho CHAINED >&2\n")
    home, _ = project.init_project(root)
    rt = Harness(home)
    rt.add_seat("opus", worktree=True)
    assert (root / ".git" / "hooks" / "pre-commit.rt-chained").exists()
    (root / "x.txt").write_text("x")
    git(root, "add", "x.txt")
    out = subprocess.run(["git", "-C", str(root), "commit", "-qm", "x"], capture_output=True, text=True)
    assert out.returncode == 0 and "CHAINED" in out.stderr


def test_seat_removed_returns_work(rt):
    ready_project(rt)
    rt.seat("opus", "task.claim", task="T1")
    rt.human("seat.remove", handle="opus")
    t = rt.q("SELECT status FROM tasks WHERE id='T1'")[0]
    assert t["status"] == "ready"
    assert rt.q("SELECT COUNT(*) n FROM leases WHERE state='active'")[0]["n"] == 0
    rt.seat("sol", "sync")
    rt.seat("sol", "task.claim", task="T1")


def test_cli_inside_worktree_acts_as_seat(rt, monkeypatch):
    ready_project(rt)
    wt = rt.q("SELECT worktree FROM seats WHERE handle='opus'")[0]["worktree"]
    monkeypatch.chdir(wt)
    out = subprocess.run([sys.executable, "-m", "roundtable_ai", "freeze", "x"], capture_output=True, text=True)
    assert out.returncode == 1 and "only the human" in out.stderr
    out = subprocess.run([sys.executable, "-m", "roundtable_ai", "call", "task.ready"], capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout.startswith("[rt:")

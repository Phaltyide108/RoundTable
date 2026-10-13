"""Proof runs: Roundtable itself runs a task's checks before review.

Proofs run in a separate, detached process so a long test suite never
times out a model's tool call (Codex allows about 60 s per call) and keeps
running if the chat closes. `close` waits proof.wait_seconds and otherwise
answers "running"; the result arrives in the digest.

Commands come ONLY from the task's stored proof list, which the human
approved when locking the plan. Never from a message or a parameter.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

from . import events, util
from .errors import PROOF, RTError

FINAL = ("passed", "failed", "timeout", "error")
INLINE_ENV = "RT_PROOF_INLINE"  # tests: run in-process instead of detaching


def _workdir(ctx, task_row) -> Path:
    from . import gitops, seats

    if gitops.uses_worktrees(ctx) and task_row["owner"]:
        wt = seats.get(ctx, task_row["owner"], include_removed=True)["worktree"]
        if wt and Path(wt).exists():
            return Path(wt)
        raise RTError(PROOF, f"the working copy of {task_row['owner']} is missing", f"the human runs: rt seat worktree {task_row['owner']}")
    return ctx.root


def _package_parent() -> str:
    return str(Path(__file__).resolve().parent.parent)


def start(ctx, task_row) -> str:
    """Queue a proof run for the task and start the runner. Returns the run id."""
    from . import gitops

    commands = util.jload(task_row["proof"], [])
    if not commands:
        raise RTError(PROOF, f"{task_row['id']} has no proof commands", "the human adds one with a plan amendment")
    workdir = _workdir(ctx, task_row)
    commit = gitops.head(workdir) if gitops.is_git(ctx) else None
    with ctx.tx():
        busy = ctx.db.one("SELECT id FROM proof_runs WHERE task = ? AND status IN ('queued','running')", (task_row["id"],))
        if busy:
            raise RTError(PROOF, f"a proof for {task_row['id']} is already running ({busy['id']})", "wait for it: rt_sync shows the result")
        run_id = util.next_id(ctx.db, "proof", "PR")
        ctx.db.execute(
            "INSERT INTO proof_runs(id, task, seat, commands, status, commit_sha, workdir, created_at) VALUES (?,?,?,?, 'queued', ?,?,?)",
            (run_id, task_row["id"], task_row["owner"] or ctx.actor, util.jdump(commands), commit, str(workdir), util.now()),
        )
        ctx.db.execute("UPDATE tasks SET status = 'proving', commit_sha = ?, updated_at = ? WHERE id = ?", (commit, util.now(), task_row["id"]))
        events.emit(ctx, "task.proving", f"{task_row['id']} proof started ({run_id})", ref=run_id, task=task_row["id"])
    if os.environ.get(INLINE_ENV) == "1":
        run(ctx.home, run_id)
        return run_id
    try:
        pid = _spawn(ctx.home, run_id, workdir)
    except OSError as exc:
        finish_with(ctx, run_id, "error", None, None, f"could not start the proof runner: {exc}")
        raise RTError(PROOF, f"could not start the proof runner: {exc}", "run `rt doctor`, then close again") from None
    with ctx.tx():
        ctx.db.execute("UPDATE proof_runs SET pid = COALESCE(pid, ?) WHERE id = ?", (pid, run_id))
    return run_id


def _spawn(home: Path, run_id: str, workdir: Path) -> int:
    logdir = Path(home) / "proofs"
    logdir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = _package_parent() + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.pop(INLINE_ENV, None)
    kwargs: dict = {"stdin": subprocess.DEVNULL, "cwd": str(workdir), "env": env, "close_fds": True}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    with open(logdir / f"{run_id}.log", "ab") as log:
        p = subprocess.Popen([sys.executable, "-m", "roundtable_ai.proofrun", str(home), run_id], stdout=log, stderr=subprocess.STDOUT, **kwargs)
    return p.pid


# ---------------------------------------------------------------- the runner (separate process)

def _kill_tree(p: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True, timeout=30)
        else:
            import signal

            os.killpg(p.pid, signal.SIGKILL)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass


def _run_one(cmd: str, workdir: Path, timeout: int, tail: deque) -> tuple[str, int | None]:
    """Run one shell command; returns (status, exit code)."""
    env = dict(os.environ)
    for var in ("RT_HOME", "RT_SEAT", "RT_SEAT_KEY"):  # the project's tests must not act as the seat that started them
        env.pop(var, None)
    env.update({"RT_PROOF": "1", "CI": "1", "PYTHONDONTWRITEBYTECODE": "1"})  # CI=1: no interactive test runners; no .pyc litter
    kwargs: dict = {"cwd": str(workdir), "env": env, "stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE,
                    "stderr": subprocess.STDOUT, "shell": True}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000200 | 0x08000000
    else:
        kwargs["start_new_session"] = True
    tail.append(f"$ {cmd}")
    try:
        p = subprocess.Popen(cmd, **kwargs)
    except OSError as exc:
        tail.append(f"could not start: {exc}")
        return "error", None
    timed_out = threading.Event()
    finished = threading.Event()

    def watchdog():
        if finished.wait(timeout):
            return
        timed_out.set()
        _kill_tree(p)

    t = threading.Thread(target=watchdog, daemon=True)
    t.start()
    assert p.stdout is not None
    for raw in iter(p.stdout.readline, b""):
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        tail.append(line[:500])
    code = p.wait()
    finished.set()
    if timed_out.is_set():
        tail.append(f"stopped: took longer than {timeout}s")
        return "timeout", code
    return ("passed" if code == 0 else "failed"), code


def run(home: Path | str, run_id: str) -> str:
    """Execute a queued proof run. Used by the detached runner and by tests."""
    from .context import open_ctx

    ctx = open_ctx(home, actor="system", client="proofrun")
    try:
        row = ctx.db.one("SELECT * FROM proof_runs WHERE id = ?", (run_id,))
        if row is None or row["status"] not in ("queued", "running"):
            return row["status"] if row else "missing"
        with ctx.tx():
            ctx.db.execute("UPDATE proof_runs SET status = 'running', pid = ?, started_at = ? WHERE id = ?", (os.getpid(), util.now(), run_id))
        tail: deque = deque(maxlen=max(5, ctx.setting("proof", "output_lines")))
        status, code, failed = "passed", 0, None
        try:
            for cmd in util.jload(row["commands"], []):
                status, code = _run_one(cmd, Path(row["workdir"]), ctx.setting("proof", "timeout_seconds"), tail)
                if status != "passed":
                    failed = cmd
                    break
        except Exception as exc:  # never leave a run hanging
            status, failed = "error", failed
            tail.append(f"runner error: {type(exc).__name__}: {exc}")
        output = "\n".join(tail)[-8000:]
        finish_with(ctx, run_id, status, code, failed, output)
        return status
    finally:
        ctx.close()


def finish_with(ctx, run_id: str, status: str, code: int | None, failed_cmd: str | None, output: str | None) -> None:
    with ctx.tx():
        ctx.db.execute(
            "UPDATE proof_runs SET status = ?, exit_code = ?, failed_cmd = ?, output_tail = ?, finished_at = ? WHERE id = ?",
            (status, code, failed_cmd, output, util.now(), run_id),
        )
    finish(ctx, run_id)


def finish(ctx, run_id: str) -> str:
    """Move the task after a proof result. Idempotent."""
    from . import tasks

    row = ctx.db.one("SELECT * FROM proof_runs WHERE id = ?", (run_id,))
    if row is None or row["status"] not in FINAL:
        return "pending"
    t = ctx.db.one("SELECT * FROM tasks WHERE id = ?", (row["task"],))
    latest = ctx.db.one("SELECT id FROM proof_runs WHERE task = ? ORDER BY created_at DESC, id DESC LIMIT 1", (row["task"],))
    if t is None or t["status"] != "proving" or (latest and latest["id"] != run_id):
        return "stale"  # task was cancelled or moved meanwhile: just keep the record
    if row["status"] == "passed":
        with ctx.tx():
            ctx.db.execute("UPDATE tasks SET status = 'in_review', updated_at = ? WHERE id = ?", (util.now(), t["id"]))
            events.emit(ctx, "task.proof_passed", f"{t['id']} proof passed ({run_id})", ref=run_id, task=t["id"],
                        audience=[t["owner"]] if t["owner"] else None, actor="system")
        from . import reviews

        return reviews.start_gate(ctx, t["id"])
    back = "changes_requested" if t["review_round"] > 0 else "claimed"
    first = (row["output_tail"] or "").strip().splitlines()[-1:] or [""]
    with ctx.tx():
        ctx.db.execute("UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?", (back, util.now(), t["id"]))
        events.emit(ctx, "task.proof_failed",
                    f"{t['id']} proof {row['status']}" + (f" at `{util.one_line(row['failed_cmd'], 60)}`" if row["failed_cmd"] else "") + f": {util.one_line(first[0], 80)}",
                    ref=run_id, task=t["id"], audience=[t["owner"]] if t["owner"] else None, level=2, actor="system")
    return f"{t['id']} back to {back}"


# ---------------------------------------------------------------- waiting / health

def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        try:
            import ctypes

            k = ctypes.windll.kernel32  # type: ignore[attr-defined]
            h = k.OpenProcess(0x1000, False, int(pid))
            if not h:
                return False
            code = ctypes.c_ulong()
            k.GetExitCodeProcess(h, ctypes.byref(code))
            k.CloseHandle(h)
            return code.value == 259
        except Exception:
            return True
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def check_stale(ctx) -> list[str]:
    """Mark runs whose runner process died as errors. Returns their ids."""
    stale = []
    for r in ctx.db.all("SELECT * FROM proof_runs WHERE status IN ('queued','running')"):
        age = util.seconds_since(r["started_at"] or r["created_at"]) or 0
        if r["status"] == "queued" and age < 30:
            continue
        if r["status"] == "running" and (pid_alive(r["pid"]) or age < 3):
            continue
        if r["status"] == "queued" and r["pid"] and pid_alive(r["pid"]):
            continue
        finish_with(ctx, r["id"], "error", None, None, (r["output_tail"] or "") + "\nthe proof runner stopped unexpectedly (computer restarted or process killed)")
        stale.append(r["id"])
    return stale


def wait(ctx, run_id: str, seconds: float):
    deadline = time.monotonic() + max(0.0, float(seconds))
    while True:
        row = ctx.db.one("SELECT * FROM proof_runs WHERE id = ?", (run_id,))
        if row is None or row["status"] in FINAL or time.monotonic() >= deadline:
            if row is not None and row["status"] not in FINAL:
                check_stale(ctx)
                row = ctx.db.one("SELECT * FROM proof_runs WHERE id = ?", (run_id,))
            return row
        time.sleep(0.25)


def describe(ctx, row) -> str:
    t = ctx.db.one("SELECT * FROM tasks WHERE id = ?", (row["task"],))
    cmds = " && ".join(util.jload(row["commands"], []))
    if row["status"] == "passed":
        status = t["status"] if t else "?"
        if status == "done":
            return f"proof passed ({cmds}) · {t['id']} is done and merged"
        if status == "merge_blocked":
            return f"proof passed · {t['id']} passed review but waits to merge (the human is told)"
        reviewers = [r["seat"] for r in ctx.db.all("SELECT seat FROM assignments WHERE kind = 'review' AND target = ? AND status = 'open'", (row["task"],))]
        who = f" by {', '.join(reviewers)}" if reviewers else ""
        return f"proof passed ({cmds}) · {row['task']} is in review{who}. Claim another task meanwhile (rt_task ready)."
    if row["status"] in ("queued", "running"):
        return (f"proof {row['id']} is still running (started {util.local_hm(row['started_at'] or row['created_at'])}). "
                "The result will show in rt_sync; you can work on something else meanwhile.")
    tail = (row["output_tail"] or "").strip()
    what = {"failed": f"failed (exit {row['exit_code']})", "timeout": "timed out", "error": "could not run"}[row["status"]]
    head = f"proof {what}" + (f" at: {row['failed_cmd']}" if row["failed_cmd"] else "")
    return f"{head}\nlast output:\n{tail}\n{row['task']} is back with you: fix, commit, then close again."

"""Tasks: claim, checkpoint, close with proof, complete with merge.

State machine (see dev/DESIGN.md):
open -> ready -> claimed -> proving -> in_review -> done
                   ^          |            |
                   +--(fail)--+            +-> changes_requested -> (close) -> proving
                                           +-> merge_blocked -> (task.merge) -> done
"""

from __future__ import annotations

from typing import Any

from . import events, fmt, util
from .errors import CONFLICT, FORBIDDEN, INVALID, NOT_FOUND, STATE, RTError
from .registry import ANY, HUMAN, Param, Result, op

STATUSES = ("open", "ready", "claimed", "proving", "in_review", "changes_requested", "merge_blocked", "done", "cancelled")
WORKING = ("claimed", "changes_requested")
LIVE = ("claimed", "proving", "in_review", "changes_requested", "merge_blocked")
MAX_TASKS = 60


def norm_id(task_id: Any) -> str:
    s = str(task_id or "").strip().upper()
    if not s:
        raise RTError(INVALID, "task id is required", "e.g. T3")
    if s[0].isdigit():
        s = "T" + s
    return s


def get(ctx, task_id):
    tid = norm_id(task_id)
    row = ctx.db.one("SELECT * FROM tasks WHERE id = ?", (tid,))
    if row is None:
        raise RTError(NOT_FOUND, f"no task {tid}", "list tasks with rt_task ready (seats) or rt status (human)")
    return row


def deps_of(ctx, task_id: str) -> list[str]:
    return [r["depends_on"] for r in ctx.db.all("SELECT depends_on FROM deps WHERE task = ? AND kind = 'blocks'", (task_id,))]


# ---------------------------------------------------------------- plan -> tasks

def validate_specs(ctx, specs) -> list[dict]:
    """Normalize a plan's task list; refuse anything that would cause trouble later."""
    from . import seats as seats_mod

    if not isinstance(specs, list) or not specs:
        raise RTError(INVALID, "the plan needs at least one task", 'tasks: [{"title": ..., "files": [...], "proof": [...]}]')
    if len(specs) > MAX_TASKS:
        raise RTError(INVALID, f"{len(specs)} tasks is too many (max {MAX_TASKS})", "group small steps into bigger tasks")
    title_cap = ctx.setting("limits", "title_chars")
    words_cap = ctx.setting("limits", "summary_words")
    text_cap = ctx.setting("limits", "text_chars")
    builders = {r["handle"] for r in seats_mod.active(ctx, "build")}
    out, refs = [], set()
    for i, raw in enumerate(specs, 1):
        if not isinstance(raw, dict):
            raise RTError(INVALID, f"task {i} must be an object with title, files and proof")
        where = f"task {raw.get('ref', i)}"
        ref = str(raw.get("ref") or i).strip()
        if ref in refs:
            raise RTError(INVALID, f"two tasks use ref {ref!r}", "give every task a unique ref")
        refs.add(ref)
        title = util.cap_chars(util.require_text(raw.get("title"), f"{where} title"), title_cap, f"{where} title")
        summary = util.cap_words(util.require_text(raw.get("summary"), f"{where} summary", allow_empty=True), words_cap, f"{where} summary")
        detail = util.cap_chars(util.require_text(raw.get("detail"), f"{where} detail", allow_empty=True), text_cap, f"{where} detail")
        files = [util.norm_path(ctx.root, str(f)) for f in util.as_list(raw.get("files"), f"{where} files")]
        if not files:
            raise RTError(INVALID, f"{where} lists no files", "list the files or globs it may edit, e.g. [\"src/auth/**\"]")
        proof = [util.require_text(c, f"{where} proof command") for c in util.as_list(raw.get("proof"), f"{where} proof")]
        if not proof:
            raise RTError(INVALID, f"{where} has no proof command",
                          'add a command that shows it works, e.g. "pytest tests/test_auth.py" or "npm test"')
        for c in proof:
            util.cap_chars(c, 500, f"{where} proof command")
        owner = raw.get("owner")
        owner = util.check_handle(owner) if owner else None
        if owner and owner not in builders:
            raise RTError(INVALID, f"{where}: owner {owner!r} is not an active seat with the build role",
                          f"builders: {', '.join(sorted(builders)) or 'none'}; or leave owner empty")
        risk = str(raw.get("risk") or "normal").lower()
        if risk not in ("low", "normal", "high"):
            raise RTError(INVALID, f"{where}: risk must be low, normal or high")
        deps = [str(d).strip() for d in util.as_list(raw.get("depends_on"), f"{where} depends_on")]
        out.append({"ref": ref, "title": title, "summary": summary, "detail": detail, "files": files,
                    "proof": proof, "owner": owner, "risk": risk, "depends_on": deps})
    for s in out:
        for d in s["depends_on"]:
            if d not in refs:
                raise RTError(INVALID, f"task {s['ref']} depends on {d!r}, which is not in the plan", f"refs in the plan: {', '.join(sorted(refs))}")
            if d == s["ref"]:
                raise RTError(INVALID, f"task {s['ref']} depends on itself")
    cycle = _find_cycle({s["ref"]: s["depends_on"] for s in out})
    if cycle:
        raise RTError(INVALID, "dependency cycle: " + " -> ".join(cycle), "remove one of those dependencies")
    return out


def _find_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    WHITE, GREY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}
    stack: list[str] = []

    def visit(n: str) -> list[str] | None:
        color[n] = GREY
        stack.append(n)
        for m in graph.get(n, []):
            if color.get(m) == GREY:
                return stack[stack.index(m):] + [m]
            if color.get(m) == WHITE:
                found = visit(m)
                if found:
                    return found
        stack.pop()
        color[n] = BLACK
        return None

    for n in graph:
        if color[n] == WHITE:
            found = visit(n)
            if found:
                return found
    return None


def materialize(ctx, plan_id: int, specs: list[dict]) -> list[str]:
    """Create task rows from validated specs (plan lock)."""
    ids: dict[str, str] = {}
    now = util.now()
    with ctx.tx():
        for seq, s in enumerate(specs, 1):
            tid = util.next_id(ctx.db, "task", "T")
            ids[s["ref"]] = tid
            ctx.db.execute(
                "INSERT INTO tasks(id, plan_id, seq, title, summary, detail, owner, status, risk, files, proof, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?, 'open', ?,?,?,?,?)",
                (tid, plan_id, seq, s["title"], s["summary"], s["detail"], s["owner"], s["risk"],
                 util.jdump(s["files"]), util.jdump(s["proof"]), now, now),
            )
        for s in specs:
            for d in s["depends_on"]:
                ctx.db.execute("INSERT OR IGNORE INTO deps(task, depends_on, kind) VALUES (?,?, 'blocks')", (ids[s["ref"]], ids[d]))
        events.emit(ctx, "task.created", f"{len(ids)} tasks created from plan P{plan_id}: {', '.join(ids.values())}", ref=f"P{plan_id}")
        refresh_ready(ctx)
    return list(ids.values())


def refresh_ready(ctx) -> list[str]:
    """open -> ready for tasks whose blocking dependencies are all done."""
    changed = []
    with ctx.tx():
        for t in ctx.db.all("SELECT * FROM tasks WHERE status = 'open' ORDER BY seq, id"):
            if t["plan_id"] is not None:
                plan = ctx.db.one("SELECT stage FROM plans WHERE id = ?", (t["plan_id"],))
                if plan is None or plan["stage"] not in ("locked", "done"):
                    continue
            pending = ctx.db.scalar(
                "SELECT COUNT(*) FROM deps d JOIN tasks x ON x.id = d.depends_on WHERE d.task = ? AND d.kind = 'blocks' AND x.status != 'done'",
                (t["id"],), 0,
            )
            if pending:
                continue
            ctx.db.execute("UPDATE tasks SET status = 'ready', updated_at = ? WHERE id = ?", (util.now(), t["id"]))
            changed.append(t["id"])
            events.emit(ctx, "task.ready", f"{t['id']} is ready: {util.one_line(t['title'], 70)}", ref=t["id"], task=t["id"],
                        audience=[t["owner"]] if t["owner"] else None)
    return changed


# ---------------------------------------------------------------- lifecycle used by reviews / proofs

def complete(ctx, task_id: str) -> str:
    """Review gate passed: merge, mark done, free files, unlock dependents."""
    from . import gitops, leases

    t = get(ctx, task_id)
    if t["status"] == "done":
        return f"{t['id']} is already done"
    if t["status"] not in ("in_review", "merge_blocked", "proving"):
        raise RTError(STATE, f"{t['id']} is {t['status']}, not ready to complete")
    merged, msg = gitops.merge_task(ctx, t)
    with ctx.tx():
        if merged:
            ctx.db.execute(
                "UPDATE tasks SET status = 'done', done_at = ?, merge_commit = ?, updated_at = ? WHERE id = ?",
                (util.now(), msg if len(msg) == 40 else None, util.now(), t["id"]),
            )
            leases.release_task(ctx, t["id"])
            events.emit(ctx, "task.done", f"{t['id']} done: {util.one_line(t['title'], 70)}", ref=t["id"], task=t["id"],
                        files=util.jload(t["files"], []), audience=[t["owner"]] if t["owner"] else None)
            refresh_ready(ctx)
            try:
                from . import plans

                plans.maybe_done(ctx, t["plan_id"])
            except (ImportError, AttributeError):
                pass
            return f"{t['id']} done" + (f" · merged into {gitops.main_branch(ctx)}" if gitops.uses_worktrees(ctx) else "")
        first_time = t["status"] != "merge_blocked"
        ctx.db.execute("UPDATE tasks SET status = 'merge_blocked', updated_at = ? WHERE id = ?", (util.now(), t["id"]))
        if first_time:
            events.emit(ctx, "task.merge_blocked", f"{t['id']} passed review but cannot merge yet: {msg}", ref=t["id"], task=t["id"],
                        audience=[t["owner"]] if t["owner"] else None, level=3 if "conflict" in msg else 2)
    if first_time and "conflict" in msg and t["owner"]:
        from . import alerts

        alerts.system_alert(ctx, 3, f"{t['id']} has a merge conflict", msg, files=util.jload(t["files"], []), tasks=[t["id"]], must_ack=[t["owner"]])
    return f"{t['id']} is waiting to merge: {msg}"


def request_changes(ctx, task_id: str, reviewer: str) -> None:
    t = get(ctx, task_id)
    with ctx.tx():
        ctx.db.execute("UPDATE tasks SET status = 'changes_requested', updated_at = ? WHERE id = ?", (util.now(), t["id"]))
        events.emit(ctx, "task.changes_requested", f"{reviewer} requested changes on {t['id']}", ref=t["id"], task=t["id"],
                    audience=[t["owner"]] if t["owner"] else None)


# ---------------------------------------------------------------- seat ops

def _may_claim(ctx, seat: str, t) -> None:
    if t["status"] == "changes_requested" and t["owner"] == seat:
        return
    if t["status"] == "claimed" and t["owner"] == seat:
        return
    if t["status"] != "ready":
        who = f" by {t['owner']}" if t["owner"] and t["status"] in LIVE else ""
        if t["status"] != "open":
            hint = "pick a ready task: rt_task ready"
        else:
            hint = "it is waiting for: " + (", ".join(deps_of(ctx, t["id"])) or "the plan lock")
        raise RTError(STATE, f"{t['id']} is {t['status']}{who}", hint)
    if t["owner"] and t["owner"] != seat:
        owner = ctx.db.one("SELECT status FROM seats WHERE handle = ?", (t["owner"],))
        if owner is not None and owner["status"] == "active":
            raise RTError(FORBIDDEN, f"{t['id']} belongs to {t['owner']} in the plan", "pick one of yours or an unowned one: rt_task ready")


@op("task.ready", tool="rt_task", action="ready", desc="Tasks you can claim, and your current ones")
def ready(ctx) -> Result:
    seat = ctx.actor
    mine = ctx.db.all(f"SELECT * FROM tasks WHERE owner = ? AND status IN ({','.join('?' * len(LIVE))}) ORDER BY seq, id", (seat, *LIVE))
    rows = ctx.db.all("SELECT t.*, s.status AS owner_status FROM tasks t LEFT JOIN seats s ON s.handle = t.owner WHERE t.status = 'ready' ORDER BY t.seq, t.id")
    claimable = [r for r in rows if r["owner"] in (None, seat) or r["owner_status"] != "active"]
    lines = []
    if mine:
        lines.append("yours: " + "; ".join(fmt.task_line(r, with_owner=False) for r in mine))
    if claimable:
        lines.append("ready to claim:")
        lines += [f"  {fmt.task_line(r)}" for r in claimable[:15]]
        if len(claimable) > 15:
            lines.append(f"  … {len(claimable) - 15} more")
    if not lines:
        waiting = ctx.db.scalar("SELECT COUNT(*) FROM tasks WHERE status = 'open'", default=0)
        lines.append("nothing to claim right now" + (f" ({waiting} tasks wait on dependencies or the plan lock)" if waiting else ""))
    return Result("\n".join(lines), {"mine": [r["id"] for r in mine], "ready": [r["id"] for r in claimable]})


@op("task.claim", tool="rt_task", action="claim", desc="Claim a ready task (leases its files) or resume your own",
    params=[Param("task", required=True, desc="task id, e.g. T3")])
def claim(ctx, task) -> Result:
    from . import alerts, gitops, leases, seats

    seat = ctx.actor
    srow = seats.get(ctx, seat)
    if "build" not in seats.roles_of(srow):
        raise RTError(FORBIDDEN, f"seat {seat} plans and reviews only (no build role)", "review or suggest instead")
    behind = ctx.db.scalar(
        "SELECT COUNT(*) FROM events WHERE id > ? AND actor != ? AND audience LIKE ?", (srow["bookmark"], seat, f'%"{seat}"%'), 0
    )
    if behind:
        raise RTError(STATE, f"you have {behind} unread update(s) meant for you", "call rt_sync first, then claim")
    blocking = alerts.blocking_for(ctx, seat)
    if blocking:
        ids = ", ".join(f"{a['id']} (L{a['level']})" for a in blocking)
        raise RTError(STATE, f"acknowledge these alerts before claiming new work: {ids}", f'rt_alert show id="{blocking[0]["id"]}", then rt_alert ack')
    use_git = gitops.uses_worktrees(ctx)
    if use_git and not (srow["worktree"]):
        raise RTError(STATE, f"seat {seat} has no working copy yet", f"the human runs: rt seat worktree {seat}")
    with ctx.tx():
        t = get(ctx, task)
        _may_claim(ctx, seat, t)
        prev_status, prev_owner = t["status"], t["owner"]
        files = util.jload(t["files"], [])
        leases.acquire(ctx, seat, t["id"], files)
        new_status = "changes_requested" if t["status"] == "changes_requested" else "claimed"
        ctx.db.execute(
            "UPDATE tasks SET status = ?, owner = ?, claimed_at = COALESCE(claimed_at, ?), updated_at = ? WHERE id = ?",
            (new_status, seat, util.now(), util.now(), t["id"]),
        )
    base = None
    if use_git:
        try:
            base = gitops.switch_to_task(ctx, srow, t, create=True)
        except RTError:
            with ctx.tx():  # undo the claim: nothing half-done
                if prev_status not in WORKING:
                    leases.release_task(ctx, t["id"])
                ctx.db.execute("UPDATE tasks SET status = ?, owner = ?, updated_at = ? WHERE id = ?", (prev_status, prev_owner, util.now(), t["id"]))
            raise
    with ctx.tx():
        if base and not t["base_commit"]:
            ctx.db.execute("UPDATE tasks SET base_commit = ? WHERE id = ?", (base, t["id"]))
        verb = "resumed" if prev_status in WORKING else "claimed"
        events.emit(ctx, "task.claimed", f"{seat} {verb} {t['id']}: {util.one_line(t['title'], 60)}", ref=t["id"], task=t["id"], files=files)
    lines = [f"{verb} {t['id']}: {t['title']}"]
    if use_git:
        lines.append(f"work in {srow['worktree']} on branch {gitops.task_branch(seat, t['id'])}")
    lines.append(f"files leased to you: {', '.join(files)}")
    lines.append(f"proof (run on close): {' && '.join(util.jload(t['proof'], []))}")
    if t["summary"]:
        lines.append(f"summary: {t['summary']}")
    if t["status"] == "changes_requested":
        lines.append(f"open review comments: rt_review get task=\"{t['id']}\"")
    deps = deps_of(ctx, t["id"])
    if deps:
        lines.append(f"builds on: {', '.join(deps)}")
    return Result("\n".join(lines), {"task": t["id"], "files": files, "branch": gitops.task_branch(seat, t["id"]) if use_git else None})


def _own_working(ctx, seat: str, task):
    t = get(ctx, task)
    if t["owner"] != seat:
        raise RTError(FORBIDDEN, f"{t['id']} is not yours" + (f" (owner: {t['owner']})" if t["owner"] else ""))
    if t["status"] not in WORKING:
        raise RTError(STATE, f"{t['id']} is {t['status']}", "claim it first" if t["status"] == "ready" else "wait for its proof/review, then check rt_sync")
    return t


@op("task.checkpoint", tool="rt_task", action="checkpoint", desc="Save progress with a short summary",
    params=[Param("task", required=True), Param("summary", required=True, desc="<= 80 words: what changed and why"),
            Param("line", desc="one-line headline (defaults to the start of the summary)")])
def checkpoint(ctx, task, summary, line=None) -> Result:
    from . import gitops, seats

    seat = ctx.actor
    t = _own_working(ctx, seat, task)
    summary = util.cap_words(util.require_text(summary, "summary"), ctx.setting("limits", "summary_words"), "summary")
    l0 = util.cap_chars(util.one_line(line or summary, ctx.setting("limits", "title_chars")), ctx.setting("limits", "title_chars"), "line")
    commit, files, added, removed = None, [], 0, 0
    if gitops.uses_worktrees(ctx):
        wt = seats.get(ctx, seat)["worktree"]
        if wt and gitops.current_branch(wt) == gitops.task_branch(seat, t["id"]):
            commit = gitops.head(wt)
            stats = gitops.changed_files(ctx, t)
            files = [f["path"] for f in stats]
            added, removed = sum(f["added"] for f in stats), sum(f["removed"] for f in stats)
    with ctx.tx():
        cid = util.next_id(ctx.db, "checkpoint", "C")
        ctx.db.execute(
            "INSERT INTO checkpoints(id, task, seat, l0, l1, commit_sha, files, added, removed, at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (cid, t["id"], seat, l0, summary, commit, util.jdump(files), added, removed, util.now()),
        )
        stat = f" [{', '.join(files[:3])}{' …' if len(files) > 3 else ''} +{added} -{removed}]" if files else ""
        events.emit(ctx, "task.checkpoint", f"{t['id']} checkpoint: {l0}{stat}", ref=cid, task=t["id"], files=files or None)
    return Result(f"saved {cid} for {t['id']}" + (f" at {commit[:8]}" if commit else ""), {"id": cid, "commit": commit})


@op("task.close", tool="rt_task", action="close", desc="Finish: Roundtable runs the task's proof, then review",
    params=[Param("task", required=True), Param("summary", required=True, desc="<= 80 words: what you did")])
def close(ctx, task, summary) -> Result:
    from . import gitops, leases, proofs, seats, suggestions

    seat = ctx.actor
    t = _own_working(ctx, seat, task)
    summary = util.cap_words(util.require_text(summary, "summary"), ctx.setting("limits", "summary_words"), "summary")
    open_s = suggestions.open_for_task(ctx, t["id"])
    if open_s:
        ids = ", ".join(s["id"] for s in open_s)
        raise RTError(STATE, f"answer the open suggestions on {t['id']} first: {ids}", f'rt_suggest reply id="{open_s[0]["id"]}" status=accepted|rejected|later reason="..."')
    if gitops.uses_worktrees(ctx):
        wt = seats.get(ctx, seat)["worktree"]
        branch = gitops.task_branch(seat, t["id"])
        cur = gitops.current_branch(wt)
        if cur != branch:
            raise RTError(STATE, f"your working copy is on {cur or 'a detached commit'}, not {branch}", f'rt_task claim task="{t["id"]}" switches back to it')
        mine_now = [r["pattern"] for r in leases.active(ctx, seat)]
        dirty = gitops.tracked_dirty(wt) + [f for f in gitops.untracked_files(wt)
                                             if util.files_covered(mine_now, f) and not gitops.is_artifact(f)]
        if dirty:
            listed = ", ".join(dirty[:8]) + (" …" if len(dirty) > 8 else "")
            raise RTError(STATE, f"commit your changes first (uncommitted: {listed})",
                          "git add the files and git commit; the proof checks exactly what gets merged")
        changed = [f["path"] for f in gitops.changed_files(ctx, t)]
        if not changed:
            raise RTError(STATE, f"{t['id']} has no committed changes on {branch}", "commit your work, then close")
        mine = [r["pattern"] for r in leases.active(ctx, seat)]
        outside = [f for f in changed if not util.files_covered(mine, f)]
        if outside:
            raise RTError(FORBIDDEN, f"these changed files are not leased to you: {', '.join(outside[:8])}",
                          "lease them (rt_lease extend) or revert those changes on your branch")
    with ctx.tx():
        ctx.db.execute("UPDATE tasks SET summary = ?, closed_at = ?, updated_at = ? WHERE id = ?", (summary, util.now(), util.now(), t["id"]))
        t = get(ctx, t["id"])
    run_id = proofs.start(ctx, t)
    row = proofs.wait(ctx, run_id, ctx.setting("proof", "wait_seconds"))
    return Result(proofs.describe(ctx, row), {"task": t["id"], "proof_run": run_id, "status": row["status"]})


@op("task.show", who=ANY, tool="rt_task", action="show", frozen_ok=True, desc="Read a task at zoom L0, L1 or L2",
    params=[Param("task", required=True), Param("zoom", enum=("L0", "L1", "L2"), default="L1")])
def show(ctx, task, zoom="L1") -> Result:
    from . import gitops

    t = get(ctx, task)
    lines = [fmt.task_line(t)]
    data: dict[str, Any] = {k: t[k] for k in t.keys()}
    data["files"], data["proof"] = util.jload(t["files"], []), util.jload(t["proof"], [])
    if zoom in ("L1", "L2"):
        if t["summary"]:
            lines.append(fmt.quoted(t["owner"] or "plan", t["summary"]) if ctx.actor not in (t["owner"], "human") else f"summary: {t['summary']}")
        lines.append(f"files: {', '.join(data['files'])}")
        lines.append(f"proof: {' && '.join(data['proof'])}")
        deps = deps_of(ctx, t["id"])
        if deps:
            states = {r["id"]: r["status"] for r in ctx.db.all(f"SELECT id, status FROM tasks WHERE id IN ({','.join('?' * len(deps))})", deps)}
            lines.append("depends on: " + ", ".join(f"{d} ({states.get(d, '?')})" for d in deps))
        cp = ctx.db.one("SELECT * FROM checkpoints WHERE task = ? ORDER BY at DESC LIMIT 1", (t["id"],))
        if cp:
            lines.append(f"last checkpoint {util.local_hm(cp['at'])}: {cp['l0']}")
        pr = ctx.db.one("SELECT * FROM proof_runs WHERE task = ? ORDER BY created_at DESC LIMIT 1", (t["id"],))
        if pr:
            lines.append(f"last proof: {pr['status']}" + (f" (exit {pr['exit_code']})" if pr["exit_code"] not in (None, 0) else ""))
        revs = ctx.db.all("SELECT reviewer, verdict, round FROM reviews WHERE task = ? ORDER BY created_at", (t["id"],))
        if revs:
            lines.append("reviews: " + ", ".join(f"{r['reviewer']} {r['verdict']} (round {r['round']})" for r in revs))
    if zoom == "L2":
        if t["detail"]:
            lines.append("detail: " + t["detail"])
        for cp in ctx.db.all("SELECT * FROM checkpoints WHERE task = ? ORDER BY at", (t["id"],)):
            lines.append(f"  {cp['id']} {util.local_hm(cp['at'])} {cp['seat']}: {cp['l1']}")
        changed = gitops.changed_files(ctx, t) if gitops.is_git(ctx) else []
        if changed:
            lines.append("changed: " + ", ".join(f"{c['path']} +{c['added']} -{c['removed']}" for c in changed[:20]))
        pr = ctx.db.one("SELECT * FROM proof_runs WHERE task = ? ORDER BY created_at DESC LIMIT 1", (t["id"],))
        if pr and pr["status"] not in ("passed", "running", "queued") and pr["output_tail"]:
            lines.append("last proof output:\n" + pr["output_tail"])
    return Result("\n".join(lines), data)


@op("task.now", tool="rt_task", action="now", desc="Set your one-line 'now doing' (others see it)",
    params=[Param("text", required=True, desc="e.g. 'writing tests for T3'")])
def now_doing(ctx, text) -> Result:
    text = util.cap_chars(util.one_line(util.require_text(text, "text"), 200), ctx.setting("limits", "title_chars"), "text")
    with ctx.tx():
        ctx.db.execute("UPDATE seats SET now_doing = ? WHERE handle = ?", (text, ctx.actor))
    return Result(f"now doing: {text}")


# ---------------------------------------------------------------- human ops

@op("task.cancel", who=HUMAN, desc="Cancel a task", params=[Param("task", required=True), Param("reason", required=True)])
def cancel(ctx, task, reason) -> Result:
    from . import leases

    with ctx.tx():
        t = get(ctx, task)
        if t["status"] in ("done", "cancelled"):
            raise RTError(STATE, f"{t['id']} is already {t['status']}")
        ctx.db.execute("UPDATE tasks SET status = 'cancelled', updated_at = ? WHERE id = ?", (util.now(), t["id"]))
        leases.release_task(ctx, t["id"])
        ctx.db.execute("UPDATE assignments SET status = 'cancelled', done_at = ? WHERE kind = 'review' AND target = ? AND status = 'open'", (util.now(), t["id"]))
        events.emit(ctx, "task.cancelled", f"{t['id']} cancelled by the human: {util.one_line(reason, 80)}", ref=t["id"], task=t["id"],
                    audience=[t["owner"]] if t["owner"] else None)
        blocked = [r["task"] for r in ctx.db.all("SELECT task FROM deps WHERE depends_on = ? AND kind = 'blocks'", (t["id"],))]
    note = f"\nnote: {', '.join(blocked)} depended on it and will not start until you remove that dependency (plan amend) or cancel them" if blocked else ""
    return Result(f"{t['id']} cancelled" + note)


@op("task.reassign", who=HUMAN, desc="Give a task to another seat (or none)",
    params=[Param("task", required=True), Param("owner", desc="seat, or empty for unowned")])
def reassign(ctx, task, owner=None) -> Result:
    from . import leases, seats

    with ctx.tx():
        t = get(ctx, task)
        new = util.check_handle(owner) if owner else None
        if new:
            s = seats.get(ctx, new)
            if "build" not in seats.roles_of(s):
                raise RTError(INVALID, f"{new} has no build role")
        if t["status"] in ("proving", "in_review", "merge_blocked", "done", "cancelled"):
            raise RTError(STATE, f"{t['id']} is {t['status']} and cannot change owner now")
        if t["status"] in WORKING:
            leases.release_task(ctx, t["id"])
            ctx.db.execute("UPDATE tasks SET status = 'ready', base_commit = NULL WHERE id = ?", (t["id"],))
        ctx.db.execute("UPDATE tasks SET owner = ?, updated_at = ? WHERE id = ?", (new, util.now(), t["id"]))
        events.emit(ctx, "task.reassigned", f"{t['id']} reassigned to {new or 'nobody'} by the human", ref=t["id"], task=t["id"],
                    audience=[x for x in (t["owner"], new) if x])
    extra = f"\nnote: earlier work stays on branch rt/{t['owner']}/{t['id']}" if t["owner"] and t["status"] in WORKING else ""
    return Result(f"{t['id']} now belongs to {new or 'nobody'}" + extra)


@op("task.merge", who=HUMAN, desc="Retry merging tasks waiting to merge", params=[Param("task", desc="one task, or all waiting")])
def merge(ctx, task=None) -> Result:
    rows = [get(ctx, task)] if task else ctx.db.all("SELECT * FROM tasks WHERE status = 'merge_blocked' ORDER BY seq, id")
    if not rows:
        return Result("no tasks are waiting to merge")
    out = []
    for t in rows:
        if t["status"] != "merge_blocked":
            out.append(f"{t['id']} is {t['status']}, not waiting to merge")
            continue
        out.append(complete(ctx, t["id"]))
    return Result("\n".join(out))


@op("task.set_review", who=HUMAN, desc="Set one task's review depth",
    params=[Param("task", required=True), Param("level", required=True, enum=("low", "mid", "high", "default"))])
def set_review(ctx, task, level) -> Result:
    with ctx.tx():
        t = get(ctx, task)
        ctx.db.execute("UPDATE tasks SET review_override = ?, updated_at = ? WHERE id = ?",
                       (None if level == "default" else level, util.now(), t["id"]))
        events.emit(ctx, "task.review_level", f"{t['id']} review depth set to {level} by the human", ref=t["id"], task=t["id"])
    return Result(f"{t['id']} review depth: {level}")

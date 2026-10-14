"""Tasks: claim, checkpoint, close with proof, complete with merge.

State machine (see dev/DESIGN.md):
open -> ready -> claimed -> proving -> in_review -> done
                   ^          |            |
                   +--(fail)--+            +-> changes_requested -> (close) -> proving
                                           +-> merge_blocked -> (task.merge) -> done
"""

from __future__ import annotations

from typing import Any

from . import events, fmt, proofs, util
from .errors import CONFLICT, FORBIDDEN, INVALID, NOT_FOUND, STATE, RTError
from .registry import ANY, HUMAN, Param, Result, op

STATUSES = ("backlog", "open", "ready", "claimed", "proving", "in_review", "changes_requested", "merge_blocked", "done", "cancelled")
KINDS = ("task", "feature", "bug", "chore", "docs", "test", "epic")
PRIORITIES = (0, 1, 2, 3, 4)  # 0 urgent, 1 high, 2 normal, 3 low, 4 someday
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


def check_kind(value, where: str = "kind") -> str:
    kind = str(value or "task").strip().lower()
    if kind not in KINDS:
        raise RTError(INVALID, f"{where} must be one of {', '.join(KINDS)} (got {value!r})")
    return kind


def check_priority(value, where: str = "priority") -> int:
    if value in (None, ""):
        return 2
    try:
        p = int(str(value).strip().upper().lstrip("P"))
    except ValueError:
        raise RTError(INVALID, f"{where} must be 0-4 (0 urgent, 2 normal, 4 someday)") from None
    if p not in PRIORITIES:
        raise RTError(INVALID, f"{where} must be 0-4 (0 urgent, 2 normal, 4 someday)")
    return p


def check_labels(values, where: str = "labels") -> list[str]:
    out = []
    for v in util.as_list(values, where):
        lab = "-".join(str(v).strip().lower().split())
        if not lab:
            continue
        if len(lab) > 30:
            raise RTError(INVALID, f"label {lab[:30]}… is too long (30 characters max)")
        if lab not in out:
            out.append(lab)
    if len(out) > 8:
        raise RTError(INVALID, f"{where}: 8 labels at most")
    return out


ORDER = "priority, seq, id"


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
        kind = check_kind(raw.get("kind"), f"{where} kind")
        priority = check_priority(raw.get("priority"), f"{where} priority")
        labels = check_labels(raw.get("labels"), f"{where} labels")
        files = [util.norm_path(ctx.root, str(f)) for f in util.as_list(raw.get("files"), f"{where} files")]
        proof = [util.require_text(c, f"{where} proof command") for c in util.as_list(raw.get("proof"), f"{where} proof")]
        if kind == "epic":
            if files or proof or raw.get("owner"):
                raise RTError(INVALID, f"{where} is an epic: it groups other tasks and has no files, proof or owner",
                              'give its tasks "parent": "<this ref>" instead')
        elif not files:
            raise RTError(INVALID, f"{where} lists no files", "list the files or globs it may edit, e.g. [\"src/auth/**\"]")
        elif not proof:
            raise RTError(INVALID, f"{where} has no proof command",
                          'add a command that shows it works, e.g. "pytest tests/test_auth.py" or "npm test"')
        for c in proof:
            util.cap_chars(c, 500, f"{where} proof command")
            why = proofs.proof_problem(c)
            if why:
                raise RTError(INVALID, f"{where}: its proof command can't run here: {why}",
                              "give a proof command that runs on this computer (the error says what to change)")
        owner = raw.get("owner")
        owner = util.check_handle(owner) if owner else None
        if owner and owner not in builders:
            raise RTError(INVALID, f"{where}: owner {owner!r} is not an active seat with the build role",
                          f"builders: {', '.join(sorted(builders)) or 'none'}; or leave owner empty")
        risk = str(raw.get("risk") or "normal").lower()
        if risk not in ("low", "normal", "high"):
            raise RTError(INVALID, f"{where}: risk must be low, normal or high")
        deps = [str(d).strip() for d in util.as_list(raw.get("depends_on"), f"{where} depends_on")]
        parent = str(raw.get("parent")).strip() if raw.get("parent") not in (None, "") else None
        out.append({"ref": ref, "title": title, "summary": summary, "detail": detail, "files": files,
                    "proof": proof, "owner": owner, "risk": risk, "depends_on": deps,
                    "kind": kind, "priority": priority, "labels": labels, "parent": parent})
    kinds = {s["ref"]: s["kind"] for s in out}
    for s in out:
        for d in s["depends_on"]:
            if d not in refs:
                raise RTError(INVALID, f"task {s['ref']} depends on {d!r}, which is not in the plan", f"refs in the plan: {', '.join(sorted(refs))}")
            if d == s["ref"]:
                raise RTError(INVALID, f"task {s['ref']} depends on itself")
        if s["parent"] is not None:
            if s["parent"] not in refs or kinds[s["parent"]] != "epic":
                raise RTError(INVALID, f"task {s['ref']}: parent {s['parent']!r} must be the ref of an epic in this plan",
                              'add a task with "kind": "epic" and use its ref as "parent"')
            if s["kind"] == "epic":
                raise RTError(INVALID, f"task {s['ref']}: epics cannot be nested")
    empty = [r for r, k in kinds.items() if k == "epic" and not any(x["parent"] == r for x in out)]
    if empty:
        raise RTError(INVALID, f"epic {empty[0]} has no tasks", 'give some tasks "parent": "' + empty[0] + '"')
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
                "INSERT INTO tasks(id, plan_id, seq, title, summary, detail, owner, status, risk, files, proof, kind, priority, labels, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?, 'open', ?,?,?,?,?,?,?,?)",
                (tid, plan_id, seq, s["title"], s["summary"], s["detail"], s["owner"], s["risk"],
                 util.jdump(s["files"]), util.jdump(s["proof"]), s.get("kind", "task"), s.get("priority", 2),
                 util.jdump(s.get("labels") or []), now, now),
            )
        for s in specs:
            if s.get("parent"):
                ctx.db.execute("UPDATE tasks SET parent = ? WHERE id = ?", (ids[s["parent"]], ids[s["ref"]]))
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
        for e in ctx.db.all("SELECT * FROM tasks WHERE status = 'open' AND kind = 'epic'"):
            kids = ctx.db.all("SELECT status FROM tasks WHERE parent = ?", (e["id"],))
            if kids and all(k["status"] in ("done", "cancelled") for k in kids) and any(k["status"] == "done" for k in kids):
                ctx.db.execute("UPDATE tasks SET status = 'done', done_at = ?, updated_at = ? WHERE id = ?", (util.now(), util.now(), e["id"]))
                events.emit(ctx, "task.done", f"epic {e['id']} done: {util.one_line(e['title'], 70)}", ref=e["id"], task=e["id"])
        for t in ctx.db.all(f"SELECT * FROM tasks WHERE status = 'open' AND kind != 'epic' ORDER BY {ORDER}"):
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
    if t["kind"] == "epic":
        raise RTError(STATE, f"{t['id']} is an epic: it groups tasks and is done when they are", "claim one of its tasks: rt_task ready")
    if t["status"] == "backlog":
        raise RTError(STATE, f"{t['id']} is in the backlog: the human has not accepted it as work yet", "pick a ready task: rt_task ready")
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
    mine = ctx.db.all(f"SELECT * FROM tasks WHERE owner = ? AND status IN ({','.join('?' * len(LIVE))}) ORDER BY {ORDER}", (seat, *LIVE))
    rows = ctx.db.all("SELECT t.*, s.status AS owner_status FROM tasks t LEFT JOIN seats s ON s.handle = t.owner WHERE t.status = 'ready' ORDER BY t.priority, t.seq, t.id")
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
    first = get(ctx, task)  # unknown task ids, epics and backlog items get the clearest error first
    if first["kind"] == "epic" or first["status"] == "backlog":
        _may_claim(ctx, seat, first)
    srow = seats.get(ctx, seat)
    if "build" not in seats.roles_of(srow):
        raise RTError(FORBIDDEN, f"seat {seat} plans and reviews only (no build role)", "review or suggest instead")
    behind = ctx.db.scalar(
        "SELECT COUNT(*) FROM events WHERE id > ? AND actor != ? AND instr(audience, ?) > 0", (srow["bookmark"], seat, f'"{seat}"'), 0
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
            Param("line", desc="one-line headline (defaults to the start of the summary)"),
            Param("commit", type="bool", default=False, desc="Roundtable commits your leased changes first (use when your app cannot run git commit)")])
def checkpoint(ctx, task, summary, line=None, commit=False) -> Result:
    from . import gitops, seats

    seat = ctx.actor
    t = _own_working(ctx, seat, task)
    summary = util.cap_words(util.require_text(summary, "summary"), ctx.setting("limits", "summary_words"), "summary")
    l0 = util.cap_chars(util.one_line(line or summary, ctx.setting("limits", "title_chars")), ctx.setting("limits", "title_chars"), "line")
    note = _commit_for_seat(ctx, seat, t, l0) if commit else ""
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
    return Result(note + f"saved {cid} for {t['id']}" + (f" at {commit[:8]}" if commit else ""), {"id": cid, "commit": commit})


def _commit_for_seat(ctx, seat, t, message) -> str:
    """Commit the seat's leased changes for it; returns a short note for the reply."""
    from . import gitops, seats

    if not gitops.uses_worktrees(ctx):
        raise RTError(STATE, "this project has no per-seat working copies, so Roundtable does not commit for you", "commit with git yourself")
    sha, files, skipped = gitops.commit_leased(ctx, seats.get(ctx, seat), t, f"{t['id']}: {message}")
    note = f"committed {len(files)} file(s) at {sha[:8]}. " if sha else "nothing new to commit. "
    if skipped:
        note += f"Not committed (not leased to you): {', '.join(skipped[:6])}{' …' if len(skipped) > 6 else ''}. "
    return note


@op("task.close", tool="rt_task", action="close", desc="Finish: Roundtable runs the task's proof, then review",
    params=[Param("task", required=True), Param("summary", required=True, desc="<= 80 words: what you did"),
            Param("commit", type="bool", default=False, desc="Roundtable commits your leased changes first (use when your app cannot run git commit)")])
def close(ctx, task, summary, commit=False) -> Result:
    from . import gitops, leases, proofs, seats, suggestions

    seat = ctx.actor
    t = _own_working(ctx, seat, task)
    summary = util.cap_words(util.require_text(summary, "summary"), ctx.setting("limits", "summary_words"), "summary")
    open_s = suggestions.open_for_task(ctx, t["id"])
    if open_s:
        ids = ", ".join(s["id"] for s in open_s)
        raise RTError(STATE, f"answer the open suggestions on {t['id']} first: {ids}", f'rt_suggest reply id="{open_s[0]["id"]}" status=accepted|rejected|later reason="..."')
    note = _commit_for_seat(ctx, seat, t, util.one_line(summary, 72)) if commit else ""
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
                          f'git add + git commit, or let Roundtable commit them: rt_task close task="{t["id"]}" commit=true summary="..."')
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
    return Result(note + proofs.describe(ctx, row), {"task": t["id"], "proof_run": run_id, "status": row["status"]})


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
        links = links_of(ctx, t["id"])
        data["links"] = links
        other = [f"{l['kind'].replace('_', ' ')} {l['other']}" for l in links if l["kind"] not in ("waits_for",)]
        if other:
            lines.append("links: " + ", ".join(other))
        labels = util.jload(t["labels"], [])
        if labels:
            lines.append("labels: " + ", ".join(labels))
        if t["parent"]:
            lines.append(f"part of epic {t['parent']}")
        kids = ctx.db.all("SELECT id, status FROM tasks WHERE parent = ? ORDER BY priority, seq, id", (t["id"],))
        if kids:
            lines.append("tasks in this epic: " + ", ".join(f"{k['id']} ({k['status']})" for k in kids))
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


# ---------------------------------------------------------------- backlog, links, lists (Beads-style tracking)

def links_of(ctx, task_id: str) -> list[dict]:
    """Every link touching this task, from its point of view."""
    out = []
    for r in ctx.db.all("SELECT depends_on, kind FROM deps WHERE task = ?", (task_id,)):
        out.append({"kind": {"blocks": "waits_for", "discovered_from": "found_while"}.get(r["kind"], r["kind"]), "other": r["depends_on"]})
    for r in ctx.db.all("SELECT task, kind FROM deps WHERE depends_on = ?", (task_id,)):
        out.append({"kind": {"blocks": "blocks", "discovered_from": "led_to"}.get(r["kind"], r["kind"]), "other": r["task"]})
    return out


def _norm_title(t: str) -> str:
    return " ".join("".join(c for c in t.lower() if c.isalnum() or c.isspace()).split())


@op("task.file", who=ANY, tool="rt_task", action="file",
    desc="File work you found outside your task (a bug, a missing test...). It goes to the human's backlog; keep doing your own task",
    params=[Param("title", required=True, desc="<= 80 characters"),
            Param("kind", enum=KINDS, default="bug"),
            Param("priority", type="int", default=2, desc="0 urgent, 1 high, 2 normal, 3 low, 4 someday"),
            Param("summary", desc="what is wrong or missing, and where (<= 80 words)"),
            Param("files", type="list", desc="files a fix would touch, if you know"),
            Param("proof", type="list", desc="a test command that would show it is fixed, if you know"),
            Param("found_in", desc="the task you were working on when you found it"),
            Param("parent", desc="an epic this belongs to"),
            Param("labels", type="list")])
def file_task(ctx, title, kind="bug", priority=2, summary=None, files=None, proof=None, found_in=None, parent=None, labels=None) -> Result:
    title = util.cap_chars(util.require_text(title, "title"), ctx.setting("limits", "title_chars"), "title")
    kind = check_kind(kind)
    priority = check_priority(priority)
    labels = check_labels(labels)
    summary = util.cap_words(util.require_text(summary, "summary", allow_empty=True), ctx.setting("limits", "summary_words"), "summary")
    files = [util.norm_path(ctx.root, str(f)) for f in util.as_list(files, "files")]
    proof = [util.cap_chars(util.require_text(c, "proof command"), 500, "proof command") for c in util.as_list(proof, "proof")]
    human = ctx.actor == "human"
    with ctx.tx():
        src = get(ctx, found_in) if found_in else None
        par = get(ctx, parent) if parent else None
        if par is not None and par["kind"] != "epic":
            raise RTError(INVALID, f"{par['id']} is not an epic", "parent must be a task of kind epic")
        dup = next((r for r in ctx.db.all("SELECT id, title FROM tasks WHERE status IN ('backlog','open','ready')")
                    if _norm_title(r["title"]) == _norm_title(title)), None)
        if dup:
            return Result(f"already filed as {dup['id']}: {dup['title']}", {"task": dup["id"], "duplicate": True})
        ready_now = human and (kind == "epic" or (files and proof))
        tid = util.next_id(ctx.db, "task", "T")
        seq = ctx.db.scalar("SELECT COALESCE(MAX(seq), 0) + 1 FROM tasks", default=1)
        now = util.now()
        ctx.db.execute(
            "INSERT INTO tasks(id, seq, title, summary, status, files, proof, kind, priority, labels, parent, filed_by, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (tid, seq, title, summary, "open" if ready_now else "backlog", util.jdump(files), util.jdump(proof), kind, priority,
             util.jdump(labels), par["id"] if par is not None else None, ctx.actor, now, now))
        if src is not None:
            ctx.db.execute("INSERT OR IGNORE INTO deps(task, depends_on, kind) VALUES (?,?, 'discovered_from')", (tid, src["id"]))
        where = f" (found while doing {src['id']})" if src is not None else ""
        events.emit(ctx, "task.filed", f"{ctx.actor} filed {tid} [{kind}, P{priority}]: {util.one_line(title, 60)}{where}", ref=tid, task=tid)
        if ready_now:
            refresh_ready(ctx)
    if ready_now:
        return Result(f"{tid} created and accepted", {"task": tid})
    return Result(f"filed {tid} in the backlog; the human decides whether it becomes work. Carry on with your own task."
                  if not human else f"filed {tid} in the backlog (accept it once it has files and a test command)", {"task": tid})


@op("task.accept", who=HUMAN, desc="Turn a backlog item into work (its files and test command are final here)",
    params=[Param("task", required=True), Param("files", type="list", desc="default: the files suggested when it was filed"),
            Param("proof", type="list", desc="default: the test command suggested when it was filed"),
            Param("owner", desc="seat, or empty for whoever claims it"), Param("priority", type="int")])
def accept(ctx, task, files=None, proof=None, owner=None, priority=None) -> Result:
    from . import seats as seats_mod

    with ctx.tx():
        t = get(ctx, task)
        if t["status"] != "backlog":
            raise RTError(STATE, f"{t['id']} is {t['status']}, not in the backlog")
        files = [util.norm_path(ctx.root, str(f)) for f in util.as_list(files, "files")] if files else util.jload(t["files"], [])
        proof = [util.cap_chars(util.require_text(c, "proof command"), 500, "proof command") for c in util.as_list(proof, "proof")] if proof else util.jload(t["proof"], [])
        if t["kind"] != "epic":
            if not files:
                raise RTError(INVALID, f"{t['id']} needs the files it may change", f"rt task accept {t['id']} --files src/x.py")
            if not proof:
                raise RTError(INVALID, f"{t['id']} needs a test command that proves it works", f'rt task accept {t["id"]} --proof "pytest tests/test_x.py"')
        new_owner = util.check_handle(owner) if owner else None
        if new_owner and "build" not in seats_mod.roles_of(seats_mod.get(ctx, new_owner)):
            raise RTError(INVALID, f"{new_owner} has no build role")
        prio = check_priority(priority) if priority not in (None, "") else t["priority"]
        ctx.db.execute("UPDATE tasks SET status = 'open', files = ?, proof = ?, owner = ?, priority = ?, updated_at = ? WHERE id = ?",
                       (util.jdump(files), util.jdump(proof), new_owner, prio, util.now(), t["id"]))
        events.emit(ctx, "task.accepted", f"the human accepted {t['id']} as work: {util.one_line(t['title'], 60)}", ref=t["id"], task=t["id"],
                    audience=[x for x in (new_owner, t["filed_by"]) if x and x != "human"] or None)
        ready_ids = refresh_ready(ctx)
    state = "ready to claim" if t["id"] in ready_ids else "waiting on its dependencies"
    return Result(f"{t['id']} accepted: {state}" + (f" (owner {new_owner})" if new_owner else ""), {"task": t["id"]})


@op("task.edit", who=HUMAN, desc="Change a task's title, kind, priority, labels, summary, files or test command",
    params=[Param("task", required=True), Param("title"), Param("kind", enum=KINDS), Param("priority", type="int"),
            Param("labels", type="list", desc="replaces the labels"), Param("summary"),
            Param("files", type="list", desc="only before work starts"), Param("proof", type="list", desc="only before work starts")])
def edit(ctx, task, title=None, kind=None, priority=None, labels=None, summary=None, files=None, proof=None) -> Result:
    changes: dict[str, Any] = {}
    with ctx.tx():
        t = get(ctx, task)
        if t["status"] in ("done", "cancelled"):
            raise RTError(STATE, f"{t['id']} is {t['status']}")
        if title is not None:
            changes["title"] = util.cap_chars(util.require_text(title, "title"), ctx.setting("limits", "title_chars"), "title")
        if kind is not None:
            changes["kind"] = check_kind(kind)
            if (changes["kind"] == "epic") != (t["kind"] == "epic"):
                raise RTError(INVALID, "a task cannot become an epic or stop being one", "file a new epic and set parent on its tasks")
        if priority not in (None, ""):
            changes["priority"] = check_priority(priority)
        if labels is not None:
            changes["labels"] = util.jdump(check_labels(labels))
        if summary is not None:
            changes["summary"] = util.cap_words(util.require_text(summary, "summary", allow_empty=True), ctx.setting("limits", "summary_words"), "summary")
        if files is not None or proof is not None:
            if t["status"] not in ("backlog", "open", "ready"):
                raise RTError(STATE, f"{t['id']} is {t['status']}: its files and test command are fixed while work is under way",
                              "cancel and refile it, or let the owner propose an amendment")
            if files is not None:
                changes["files"] = util.jdump([util.norm_path(ctx.root, str(f)) for f in util.as_list(files, "files")])
            if proof is not None:
                changes["proof"] = util.jdump([util.cap_chars(util.require_text(c, "proof command"), 500, "proof command") for c in util.as_list(proof, "proof")])
        if not changes:
            raise RTError(INVALID, "nothing to change", "pass at least one of title, kind, priority, labels, summary, files, proof")
        sets = ", ".join(f"{k} = ?" for k in changes)
        ctx.db.execute(f"UPDATE tasks SET {sets}, updated_at = ? WHERE id = ?", (*changes.values(), util.now(), t["id"]))
        events.emit(ctx, "task.edited", f"the human changed {t['id']}: {', '.join(changes)}", ref=t["id"], task=t["id"],
                    audience=[t["owner"]] if t["owner"] else None)
    return Result(f"{t['id']} updated: {', '.join(changes)}")


@op("task.link", who=ANY, tool="rt_task", action="link",
    desc="Link two tasks: related or discovered_from (anyone); waits_for or parent (the human)",
    params=[Param("task", required=True),
            Param("relation", required=True, enum=("waits_for", "related", "discovered_from", "parent"),
                  desc="task waits_for other; task related other; task discovered_from other; task's parent is the epic other"),
            Param("other", required=True), Param("remove", type="bool", default=False)])
def link(ctx, task, relation, other, remove=False) -> Result:
    kind = relation
    human = ctx.actor == "human"
    if kind in ("waits_for", "parent") and not human:
        raise RTError(FORBIDDEN, f"only the human adds {kind} links (they change what can start)", "use related, or raise it in an alert or suggestion")
    db_kind = "blocks" if kind == "waits_for" else kind
    with ctx.tx():
        a, b = get(ctx, task), get(ctx, other)
        if a["id"] == b["id"]:
            raise RTError(INVALID, "a task cannot link to itself")
        if kind == "parent":
            if b["kind"] != "epic":
                raise RTError(INVALID, f"{b['id']} is not an epic", "parent must be a task of kind epic")
            if a["kind"] == "epic":
                raise RTError(INVALID, "epics cannot be nested")
            ctx.db.execute("UPDATE tasks SET parent = ?, updated_at = ? WHERE id = ?", (None if remove else b["id"], util.now(), a["id"]))
            text = f"{a['id']} " + (f"removed from epic {b['id']}" if remove else f"is now part of epic {b['id']}")
        else:
            if remove:
                ctx.db.execute("DELETE FROM deps WHERE task = ? AND depends_on = ? AND kind = ?", (a["id"], b["id"], db_kind))
            else:
                if db_kind == "blocks":
                    graph: dict[str, list[str]] = {}
                    for r in ctx.db.all("SELECT task, depends_on FROM deps WHERE kind = 'blocks'"):
                        graph.setdefault(r["task"], []).append(r["depends_on"])
                    graph.setdefault(a["id"], []).append(b["id"])
                    for targets in list(graph.values()):
                        for n in targets:
                            graph.setdefault(n, [])
                    cycle = _find_cycle(graph)
                    if cycle:
                        raise RTError(INVALID, "that would make a cycle: " + " -> ".join(cycle))
                    if a["status"] in LIVE:
                        raise RTError(STATE, f"{a['id']} is already {a['status']}; it cannot wait for {b['id']} now")
                ctx.db.execute("INSERT OR IGNORE INTO deps(task, depends_on, kind) VALUES (?,?,?)", (a["id"], b["id"], db_kind))
                if db_kind == "blocks" and a["status"] == "ready" and b["status"] != "done":
                    ctx.db.execute("UPDATE tasks SET status = 'open', updated_at = ? WHERE id = ?", (util.now(), a["id"]))
            label = {"blocks": "waits for", "related": "is related to", "discovered_from": "was found while doing"}[db_kind]
            text = f"{a['id']} {label} {b['id']}" + (" (removed)" if remove else "")
        events.emit(ctx, "task.linked", f"{ctx.actor}: {text}", ref=a["id"], task=a["id"])
        if remove or db_kind == "blocks":
            refresh_ready(ctx)
    return Result(text)


@op("task.list", who=ANY, tool="rt_task", action="list", frozen_ok=True, desc="List tasks, most urgent first",
    params=[Param("status", desc="backlog, open, ready, working, review, done, all (default: everything not finished)"),
            Param("kind", enum=KINDS), Param("label"), Param("priority", type="int", desc="this priority or more urgent"),
            Param("owner"), Param("limit", type="int", default=30)])
def list_tasks(ctx, status=None, kind=None, label=None, priority=None, owner=None, limit=30) -> Result:
    groups = {"working": ("claimed", "changes_requested"), "review": ("proving", "in_review", "merge_blocked"),
              "all": STATUSES, None: tuple(x for x in STATUSES if x not in ("done", "cancelled"))}
    st = groups.get(status, (status,))
    if any(x not in STATUSES for x in st):
        raise RTError(INVALID, f"unknown status {status!r}", "backlog, open, ready, working, review, done, cancelled or all")
    q = f"SELECT * FROM tasks WHERE status IN ({','.join('?' * len(st))})"
    args: list[Any] = list(st)
    if kind:
        q += " AND kind = ?"
        args.append(check_kind(kind))
    if priority not in (None, ""):
        q += " AND priority <= ?"
        args.append(check_priority(priority))
    if owner:
        q += " AND owner = ?"
        args.append(util.check_handle(owner))
    rows = ctx.db.all(q + f" ORDER BY {ORDER}", tuple(args))
    if label:
        lab = check_labels([label])[0]
        rows = [r for r in rows if lab in util.jload(r["labels"], [])]
    limit = max(1, min(int(limit or 30), 200))
    lines = [fmt.task_line(r) for r in rows[:limit]]
    if len(rows) > limit:
        lines.append(f"… {len(rows) - limit} more")
    return Result("\n".join(lines) or "no tasks match", {"tasks": [r["id"] for r in rows]})

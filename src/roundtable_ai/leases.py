"""File leases: which seat may edit which files.

A lease covers a path or glob for one task. Other seats can read those files
and send suggestions, but cannot lease or commit them. Leases renew on every
call by their seat and expire after leases.ttl_minutes of inactivity while
the task is being worked on (dispatch.housekeeping).
"""

from __future__ import annotations

from . import events, util
from .errors import CONFLICT, FORBIDDEN, INVALID, STATE, RTError
from .registry import Param, Result, op


def active(ctx, seat: str | None = None) -> list:
    if seat:
        return ctx.db.all("SELECT * FROM leases WHERE state = 'active' AND seat = ? ORDER BY id", (seat,))
    return ctx.db.all("SELECT * FROM leases WHERE state = 'active' ORDER BY id")


def covering(ctx, path: str) -> list:
    return [r for r in active(ctx) if util.glob_match(r["pattern"], path)]


def holder(ctx, path: str):
    rows = covering(ctx, path)
    return rows[0] if rows else None


def _holds(ctx) -> list[dict]:
    from . import alerts

    return alerts.holds(ctx)


def normalize(ctx, patterns) -> list[str]:
    out: list[str] = []
    for p in util.as_list(patterns, "files"):
        n = util.norm_path(ctx.root, str(p))
        if n not in out:
            out.append(n)
    return out


def conflicts(ctx, seat: str, patterns: list[str]) -> list[str]:
    """Plain-language reasons these patterns cannot be leased by `seat`."""
    from . import gitops

    known = gitops.known_files(ctx)
    problems = []
    for p in patterns:
        for h in _holds(ctx):
            if util.patterns_overlap(p, h["pattern"], known):
                problems.append(f"{p}: held by alert {h['alert_id']} ({h['kind']})")
        for r in active(ctx):
            if r["seat"] != seat and util.patterns_overlap(p, r["pattern"], known):
                problems.append(f"{p}: leased to {r['seat']} for {r['task'] or 'a task'} ({r['pattern']})")
    return problems


def acquire(ctx, seat: str, task_id: str, patterns) -> list[str]:
    """Lease all patterns to seat for task, or nothing. Call inside ctx.tx()."""
    pats = normalize(ctx, patterns)
    with ctx.tx():
        problems = conflicts(ctx, seat, pats)
        if problems:
            raise RTError(
                CONFLICT,
                "cannot lease: " + "; ".join(problems[:5]) + (" …" if len(problems) > 5 else ""),
                "wait for those to finish, or send the holder a suggestion (rt_suggest send) instead of editing",
                {"problems": problems},
            )
        now = util.now()
        expires = util.add_seconds(now, ctx.setting("leases", "ttl_minutes") * 60)
        for p in pats:
            existing = ctx.db.one(
                "SELECT id FROM leases WHERE state = 'active' AND seat = ? AND task IS ? AND pattern = ?", (seat, task_id, p)
            )
            if existing:
                ctx.db.execute("UPDATE leases SET renewed_at = ?, expires_at = ? WHERE id = ?", (now, expires, existing["id"]))
            else:
                ctx.db.execute(
                    "INSERT INTO leases(pattern, seat, task, state, acquired_at, renewed_at, expires_at) VALUES (?,?,?, 'active', ?,?,?)",
                    (p, seat, task_id, now, now, expires),
                )
    return pats


def release_task(ctx, task_id: str) -> int:
    with ctx.tx():
        cur = ctx.db.execute(
            "UPDATE leases SET state = 'released', ended_at = ? WHERE task = ? AND state = 'active'", (util.now(), task_id)
        )
        return cur.rowcount


def release_all(ctx, seat: str) -> int:
    with ctx.tx():
        cur = ctx.db.execute(
            "UPDATE leases SET state = 'released', ended_at = ? WHERE seat = ? AND state = 'active'", (util.now(), seat)
        )
        return cur.rowcount


def check_edit(ctx, seat: str, path: str) -> None:
    """Raise unless `seat` may edit `path` right now."""
    p = util.norm_path(ctx.root, path)
    for h in _holds(ctx):
        if util.glob_match(h["pattern"], p):
            raise RTError(CONFLICT, f"{p} is held by alert {h['alert_id']}", f'read it: rt_alert show id="{h["alert_id"]}"')
    rows = covering(ctx, p)
    others = [r for r in rows if r["seat"] != seat]
    if others:
        r = others[0]
        raise RTError(CONFLICT, f"{p} is leased to {r['seat']} for {r['task']}", "send a suggestion instead: rt_suggest send")
    if not rows:
        raise RTError(FORBIDDEN, f"{p} is not in your leases", "rt_lease extend with your task id and this file")


def _own_task(ctx, seat: str, task_id: str):
    from . import tasks

    t = tasks.get(ctx, task_id)
    if t["owner"] != seat or t["status"] not in ("claimed", "changes_requested", "proving", "in_review", "merge_blocked"):
        raise RTError(FORBIDDEN, f"{t['id']} is not a task you are working on", "claim a task first: rt_task claim")
    return t


@op(
    "lease.extend",
    tool="rt_lease",
    action="extend",
    desc="Lease more files for your task",
    params=[
        Param("task", required=True, desc="your task id"),
        Param("files", type="list", required=True, desc="paths or globs"),
        Param("reason", desc="why the task needs them"),
    ],
)
def extend(ctx, task, files, reason=None) -> Result:
    seat = ctx.actor
    with ctx.tx():
        t = _own_task(ctx, seat, task)
        if t["status"] not in ("claimed", "changes_requested"):
            raise RTError(STATE, f"{t['id']} is {t['status']}; leases can change only while you work on it")
        pats = acquire(ctx, seat, t["id"], files)
        current = util.jload(t["files"], [])
        added = [p for p in pats if p not in current]
        if added:
            ctx.db.execute(
                "UPDATE tasks SET files = ?, updated_at = ? WHERE id = ?", (util.jdump(current + added), util.now(), t["id"])
            )
        events.emit(
            ctx, "lease.extended", f"{seat} leased {', '.join(pats)} for {t['id']}" + (f" ({util.one_line(reason, 60)})" if reason else ""),
            ref=t["id"], task=t["id"], files=pats,
        )
    return Result(f"leased to you for {t['id']}: {', '.join(pats)}", {"task": t["id"], "files": pats})


@op(
    "lease.release",
    tool="rt_lease",
    action="release",
    desc="Give files back early",
    params=[Param("task", desc="release all leases of this task"), Param("files", type="list", desc="or just these patterns")],
)
def release(ctx, task=None, files=None) -> Result:
    seat = ctx.actor
    if not task and not files:
        raise RTError(INVALID, "say which leases to release", "pass task, files, or both")
    with ctx.tx():
        rows = active(ctx, seat)
        if task:
            rows = [r for r in rows if r["task"] == task.strip().upper()]
        if files:
            wanted = set(normalize(ctx, files))
            rows = [r for r in rows if r["pattern"] in wanted]
        if not rows:
            return Result("nothing to release: no matching leases of yours")
        ids = [r["id"] for r in rows]
        ctx.db.execute(
            f"UPDATE leases SET state = 'released', ended_at = ? WHERE id IN ({','.join('?' * len(ids))})", (util.now(), *ids)
        )
        pats = [r["pattern"] for r in rows]
        events.emit(ctx, "lease.released", f"{seat} released {', '.join(pats)}", files=pats)
    return Result(f"released: {', '.join(pats)}", {"released": pats})

"""Seats: one model in one chat.

A seat is registered once by the human (`rt seat add`). A chat takes the
seat by joining (rt_sync with join=<handle>) and gets a short key that it
passes on every call. Processes started by `rt launch` are pinned to their
seat through the RT_SEAT environment variable instead.
"""

from __future__ import annotations

from typing import Any

from . import events, rules, util
from .context import HUMAN, SYSTEM
from .errors import CONFLICT, FORBIDDEN, INVALID, NEED_JOIN, NOT_FOUND, STATE, RTError
from .registry import ANY, HUMAN as WHO_HUMAN, Param, Result, op

from . import apps as apps_mod

APPS = tuple(apps_mod.APPS)
CODING_APPS = tuple(k for k, a in apps_mod.APPS.items() if a.coding)
ROLES = ("plan", "build", "review")
RESERVED = {HUMAN, SYSTEM, "all", "everyone", "any", "none", "me"}


def company_for(app: str, model: str) -> str | None:
    implied = apps_mod.APPS[app].company if app in apps_mod.APPS else None
    if implied:
        return implied
    found = apps_mod.company_of_model(model)
    if found:
        return found
    return "other" if app == "opencode" else None   # opencode's own stealth / free models


# ---------------------------------------------------------------- lookups

def get(ctx, handle: str, *, include_removed: bool = False):
    row = ctx.db.one("SELECT * FROM seats WHERE handle = ?", (handle,))
    if row is None or (row["status"] == "removed" and not include_removed):
        known = [r["handle"] for r in active(ctx)]
        raise RTError(NOT_FOUND, f"no seat named {handle!r}", f"seats: {', '.join(known) or 'none yet - the human adds them with `rt seat add`'}")
    return row


def active(ctx, role: str | None = None) -> list:
    rows = ctx.db.all("SELECT * FROM seats WHERE status = 'active' ORDER BY created_at, handle")
    if role:
        rows = [r for r in rows if role in r["roles"].split(",")]
    return rows


def roles_of(row) -> list[str]:
    return [r for r in (row["roles"] or "").split(",") if r]


def is_live(ctx, row) -> bool:
    """A chat holds this seat and was active recently."""
    if not row["session_key"]:
        return False
    secs = util.seconds_since(row["last_seen"])
    return secs is not None and secs < ctx.setting("seats", "live_minutes") * 60


def resolve(ctx, handle: str | None, key: str | None, *, pinned: bool = False) -> str:
    """Work out which seat is calling. Raises NEED_JOIN / FORBIDDEN on doubt.

    pinned: the process was started for this seat (RT_SEAT), so no key is needed.
    """
    if pinned and handle:
        row = get(ctx, util.check_handle(handle))
        return row["handle"]
    if key:
        row = ctx.db.one("SELECT * FROM seats WHERE session_key = ? AND status != 'removed'", (key.strip().lower(),))
        if row is None:
            raise RTError(
                NEED_JOIN,
                "that seat key is not valid any more (the seat was released or joined from another chat)",
                'join again: rt_sync with join="<your seat name>"',
            )
        if handle and util.check_handle(handle) != row["handle"]:
            raise RTError(FORBIDDEN, f"the key belongs to seat {row['handle']!r}, not {handle!r}")
        return row["handle"]
    seats = ", ".join(r["handle"] for r in active(ctx)) or "none yet"
    raise RTError(
        NEED_JOIN,
        "this chat has not joined a seat yet",
        f'call rt_sync with join="<your seat name>" first (seats: {seats}). Ask the human which seat you are if unsure.',
    )


def touch(ctx, handle: str) -> None:
    ctx.db.execute("UPDATE seats SET last_seen = ? WHERE handle = ?", (util.now(), handle))


# ---------------------------------------------------------------- human ops

@op(
    "seat.add",
    who=WHO_HUMAN,
    desc="Register a model as a seat",
    params=[
        Param("handle", required=True, desc="short seat name, e.g. opus"),
        Param("model", required=True, desc="model id passed to the app, e.g. claude-opus-5-5"),
        Param("app", required=True, enum=APPS, desc="where this seat runs"),
        Param("company", desc="model maker (anthropic, openai, google...); guessed when omitted"),
        Param("roles", type="list", desc="plan, build, review (default: all)"),
        Param("worktree", type="bool", default=None, desc="give it a working copy (default: yes for coding apps with git)"),
    ],
)
def add(ctx, handle, model, app, company=None, roles=None, worktree=None) -> Result:
    handle = util.check_handle(handle)
    if handle in RESERVED:
        raise RTError(INVALID, f"{handle!r} is reserved", "pick another seat name")
    model = util.require_text(model, "model")
    company = (company or company_for(app, model) or "").strip().lower()
    if not company:
        raise RTError(INVALID, f"cannot tell which company makes {model!r}", "pass --company (e.g. anthropic, openai, google)")
    roles = [r.strip().lower() for r in (roles or list(ROLES))]
    bad = [r for r in roles if r not in ROLES]
    if bad or not roles:
        raise RTError(INVALID, f"unknown role(s): {', '.join(bad) or '(none)'}", "roles are plan, build, review")
    if app == "claude-app" and "build" in roles:
        roles = [r for r in roles if r != "build"]
        ctx.notes.append("note: the Claude app cannot edit project files, so this seat plans and reviews only")
    with ctx.tx():
        existing = ctx.db.one("SELECT status FROM seats WHERE handle = ?", (handle,))
        if existing and existing["status"] != "removed":
            raise RTError(CONFLICT, f"seat {handle!r} already exists", "pick another name, or `rt seat remove` it first")
        if existing:
            ctx.db.execute("DELETE FROM seats WHERE handle = ?", (handle,))
        ctx.db.execute(
            "INSERT INTO seats(handle, model, company, app, roles, status, created_at) VALUES (?,?,?,?,?, 'active', ?)",
            (handle, model, company, app, ",".join(roles), util.now()),
        )
        events.emit(ctx, "seat.added", f"seat {handle} added ({model}, {app})", ref=handle)
    lines = [f"seat {handle} added: {model} · {company} · {app} · roles {', '.join(roles)}"]
    want_wt = worktree if worktree is not None else (app in CODING_APPS and "build" in roles and ctx.setting("git", "worktrees"))
    if want_wt:
        try:
            from . import gitops

            path, branch = gitops.ensure_worktree(ctx, handle)
            lines.append(f"working copy: {path} (branch {branch})")
            if apps_mod.get(app).folder:
                from . import appsetup

                lines.append(appsetup.seat_folder_config(ctx, handle))
        except RTError as exc:
            lines.append(f"no working copy yet: {exc.message}")
            if exc.hint:
                lines.append(f"next: {exc.hint}")
    lines.append(f"next: rt launch {handle}  (or open the app and say: join Roundtable as {handle})"
                 if apps_mod.get(app).start == "terminal" else f"next: rt launch {handle} shows how to start it")
    lines.extend(ctx.notes)
    ctx.notes.clear()
    return Result("\n".join(lines), {"handle": handle, "company": company, "roles": roles})


@op("seat.set", who=WHO_HUMAN, desc="Change a seat's model or how hard it thinks (takes effect the next time it starts)",
    params=[Param("handle", required=True), Param("model", desc="model id the app accepts"),
            Param("effort", desc="thinking effort: claude-code low|medium|high|xhigh|max, codex-cli minimal..xhigh|max|ultra, opencode the model's variants; 'default' clears it")])
def set_seat(ctx, handle, model=None, effort=None) -> Result:
    handle = util.check_handle(handle)
    if model is None and effort is None:
        raise RTError(INVALID, "nothing to change", "pass --model and/or --effort")
    with ctx.tx():
        row = get(ctx, handle)
        changes = []
        if model is not None:
            model = util.require_text(model, "model")
            if model != row["model"]:
                ctx.db.execute("UPDATE seats SET model = ? WHERE handle = ?", (model, handle))
                changes.append(f"model {model}")
        if effort is not None:
            effort = str(effort).strip().lower()
            if effort in ("", "default", "none"):
                effort = None
            else:
                allowed = apps_mod.EFFORTS.get(row["app"])
                if not allowed:
                    raise RTError(INVALID, f"Roundtable can't set the thinking effort of {apps_mod.label(row['app'])}",
                                  "set it in the app itself")
                if effort not in allowed:
                    raise RTError(INVALID, f"effort must be one of {', '.join(allowed)} for {row['app']}")
            if effort != row["effort"]:
                ctx.db.execute("UPDATE seats SET effort = ? WHERE handle = ?", (effort, handle))
                changes.append(f"effort {effort or 'app default'}")
        if not changes:
            return Result(f"seat {handle}: nothing changed")
        events.emit(ctx, "seat.changed", f"seat {handle}: {', '.join(changes)}", ref=handle)
    return Result(f"seat {handle}: {', '.join(changes)} · takes effect the next time it starts (background runs pick it up at once)",
                  {"handle": handle})


@op("seat.worktree", who=WHO_HUMAN, desc="Create (or repair) a seat's working copy", params=[Param("handle", required=True)])
def make_worktree(ctx, handle) -> Result:
    row = get(ctx, util.check_handle(handle))
    from . import gitops

    path, branch = gitops.ensure_worktree(ctx, row["handle"])
    return Result(f"working copy for {row['handle']}: {path} (branch {branch})", {"path": str(path), "branch": branch})


@op("seat.list", who=ANY, desc="List seats", tool="rt_sync", action="seats", frozen_ok=True)
def list_seats(ctx) -> Result:
    rows = ctx.db.all("SELECT * FROM seats WHERE status != 'removed' ORDER BY created_at, handle")
    if not rows:
        return Result("no seats yet. add one: rt seat add opus --model claude-opus-5-5 --app claude-code", {"seats": []})
    lines, data = [], []
    for r in rows:
        live = "live" if is_live(ctx, r) else ("paused" if r["status"] == "paused" else "idle")
        doing = f" · now: {r['now_doing']}" if r["now_doing"] else ""
        folder = f" · folder {r['worktree']}" if r["worktree"] and ctx.is_human else ""
        lines.append(f"{r['handle']:<10} {r['model']} · {r['company']} · {r['app']} · {r['roles']} · {live} · seen {util.human_ago(r['last_seen'])}{folder}{doing}")
        data.append({k: r[k] for k in ("handle", "model", "company", "app", "roles", "status", "worktree", "branch", "last_seen", "now_doing")} | {"live": live == "live"})
    return Result("\n".join(lines), {"seats": data})


def _return_tasks(ctx, handle: str, why: str) -> list[str]:
    """Hand back a seat's in-progress tasks and release its leases."""
    moved = []
    rows = ctx.db.all("SELECT id FROM tasks WHERE owner = ? AND status IN ('claimed','changes_requested')", (handle,))
    for r in rows:
        ctx.db.execute("UPDATE tasks SET status = 'ready', updated_at = ? WHERE id = ?", (util.now(), r["id"]))
        moved.append(r["id"])
    ctx.db.execute(
        "UPDATE leases SET state = 'released', ended_at = ? WHERE seat = ? AND state = 'active'", (util.now(), handle)
    )
    if moved:
        events.emit(
            ctx, "task.returned", f"{', '.join(moved)} returned to ready ({why}); unmerged work stays on its rt/{handle}/... branches",
            ref=handle, data={"tasks": moved},
        )
    return moved


@op("seat.pause", who=WHO_HUMAN, desc="Pause a seat: its in-progress tasks return to ready", params=[Param("handle", required=True)])
def pause(ctx, handle) -> Result:
    handle = util.check_handle(handle)
    with ctx.tx():
        row = get(ctx, handle)
        if row["status"] == "paused":
            return Result(f"seat {handle} is already paused")
        ctx.db.execute("UPDATE seats SET status = 'paused', session_key = NULL WHERE handle = ?", (handle,))
        moved = _return_tasks(ctx, handle, f"{handle} paused")
        events.emit(ctx, "seat.paused", f"seat {handle} paused by the human", ref=handle)
    return Result(f"seat {handle} paused" + (f"; tasks back to ready: {', '.join(moved)}" if moved else ""), {"returned": moved})


@op("seat.resume", who=WHO_HUMAN, desc="Resume a paused seat", params=[Param("handle", required=True)])
def resume(ctx, handle) -> Result:
    handle = util.check_handle(handle)
    with ctx.tx():
        row = get(ctx, handle)
        if row["status"] != "paused":
            return Result(f"seat {handle} is not paused")
        ctx.db.execute("UPDATE seats SET status = 'active' WHERE handle = ?", (handle,))
        events.emit(ctx, "seat.resumed", f"seat {handle} resumed", ref=handle)
    return Result(f"seat {handle} resumed")


@op("seat.remove", who=WHO_HUMAN, desc="Remove a seat (history is kept)", params=[Param("handle", required=True)])
def remove(ctx, handle) -> Result:
    handle = util.check_handle(handle)
    with ctx.tx():
        get(ctx, handle)
        moved = _return_tasks(ctx, handle, f"{handle} removed")
        ctx.db.execute(
            "UPDATE tasks SET owner = NULL, updated_at = ? WHERE owner = ? AND status IN ('open','ready')", (util.now(), handle)
        )
        ctx.db.execute(
            "UPDATE assignments SET status = 'cancelled', done_at = ? WHERE seat = ? AND status = 'open'", (util.now(), handle)
        )
        ctx.db.execute("UPDATE seats SET status = 'removed', session_key = NULL WHERE handle = ?", (handle,))
        events.emit(ctx, "seat.removed", f"seat {handle} removed by the human", ref=handle)
    note = " Its open review/critique assignments were cancelled; run `rt status` to see what needs reassigning."
    return Result(f"seat {handle} removed." + note, {"returned": moved})


@op("seat.release", who=WHO_HUMAN, desc="Free a seat whose chat was closed, so a new chat can join it", params=[Param("handle", required=True)])
def release(ctx, handle) -> Result:
    handle = util.check_handle(handle)
    with ctx.tx():
        get(ctx, handle)
        ctx.db.execute("UPDATE seats SET session_key = NULL, session_started = NULL WHERE handle = ?", (handle,))
        events.emit(ctx, "seat.released", f"seat {handle} released; a new chat can join it", ref=handle)
    return Result(f"seat {handle} released: a new chat can now join it")


# ---------------------------------------------------------------- join (no seat yet)

@op(
    "seat.join",
    who=ANY,
    desc="Take a seat in this chat; returns your key and the rules",
    params=[Param("handle", required=True, desc="your seat name, as the human told you")],
    frozen_ok=True,
    housekeeping=False,
)
def join(ctx, handle) -> Result:
    handle = util.check_handle(handle)
    with ctx.tx():
        row = get(ctx, handle)
        if row["status"] == "paused":
            raise RTError(STATE, f"seat {handle} is paused by the human", "ask the human to run `rt seat resume " + handle + "`")
        if is_live(ctx, row):
            raise RTError(
                CONFLICT,
                f"seat {handle} is live in another chat (active {util.human_ago(row['last_seen'])})",
                f"if that chat is closed, the human runs `rt seat release {handle}`; otherwise use that chat",
            )
        key = util.new_key()
        now = util.now()
        ctx.db.execute(
            "UPDATE seats SET session_key = ?, session_started = ?, last_seen = ? WHERE handle = ?", (key, now, now, handle)
        )
        events.emit(ctx, "seat.joined", f"{handle} joined from {ctx.client}", ref=handle, actor=handle)
    others = [r["handle"] for r in active(ctx) if r["handle"] != handle]
    from . import memory

    text = rules.card(handle, key, worktree=row["worktree"], review_level=ctx.setting("review", "level"), others=others,
                      memory=memory.join_lines(ctx, handle))
    return Result(text, {"handle": handle, "key": key, "worktree": row["worktree"]})


def pinned_card(ctx, handle: str) -> str:
    row = get(ctx, handle)
    others = [r["handle"] for r in active(ctx) if r["handle"] != handle]
    from . import memory

    return rules.card(handle, None, worktree=row["worktree"], review_level=ctx.setting("review", "level"), others=others,
                      memory=memory.join_lines(ctx, handle))


def seat_summary(row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys() if k != "session_key"}

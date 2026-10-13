"""Suggestions: advice to the seat that owns a task or file.

The owner must answer every suggestion (accepted / rejected / later, with a
reason) before closing the task, so nothing is silently ignored.
"""

from __future__ import annotations

from . import events, fmt, util
from .errors import FORBIDDEN, INVALID, NOT_FOUND, STATE, RTError
from .registry import Param, Result, op


def get(ctx, sid):
    s = str(sid or "").strip().upper()
    if s and s[0].isdigit():
        s = "S" + s
    row = ctx.db.one("SELECT * FROM suggestions WHERE id = ?", (s,))
    if row is None:
        raise RTError(NOT_FOUND, f"no suggestion {s}", "rt_suggest list")
    return row


def open_for_task(ctx, task_id: str) -> list:
    return ctx.db.all("SELECT * FROM suggestions WHERE task = ? AND status = 'open' ORDER BY id", (task_id,))


@op("suggest.send", tool="rt_suggest", action="send", desc="Advise the owner of a task or file (instead of editing it)",
    params=[Param("text", required=True, desc="what you suggest and why"), Param("task", desc="task id"),
            Param("file", desc="or a file path (goes to whoever leases it)"), Param("to", desc="or a seat name"),
            Param("patch", desc="optional unified diff")])
def send(ctx, text, task=None, file=None, to=None, patch=None) -> Result:
    from . import leases, seats, tasks

    sender = ctx.actor
    text = util.cap_chars(util.require_text(text, "text"), ctx.setting("limits", "text_chars"), "text")
    if patch is not None:
        util.cap_chars(patch, 20_000, "patch")
    task_id, path, recipient = None, None, None
    if task:
        t = tasks.get(ctx, task)
        task_id = t["id"]
        recipient = t["owner"]
        if not recipient:
            raise RTError(STATE, f"{t['id']} has no owner yet", "suggest a plan amendment instead (rt_plan amend)")
    if file:
        path = util.norm_path(ctx.root, file)
        h = leases.holder(ctx, path)
        if recipient is None:
            if h is None:
                raise RTError(STATE, f"nobody leases {path} right now", "if it should change, it needs a task: rt_plan amend kind=add_task")
            recipient, task_id = h["seat"], task_id or h["task"]
    if to:
        target = seats.get(ctx, util.check_handle(to))["handle"]
        if recipient and recipient != target:
            raise RTError(INVALID, f"{task_id or path} belongs to {recipient}, not {target}")
        recipient = target
    if not recipient:
        raise RTError(INVALID, "say who it is for", "pass task, file or to")
    if recipient == sender:
        raise RTError(INVALID, "that is your own work", "just make the change yourself")
    with ctx.tx():
        sid = util.next_id(ctx.db, "suggestion", "S")
        ctx.db.execute(
            "INSERT INTO suggestions(id, from_seat, to_seat, task, file, text, patch, status, created_at) VALUES (?,?,?,?,?,?,?, 'open', ?)",
            (sid, sender, recipient, task_id, path, text, patch, util.now()),
        )
        events.emit(ctx, "suggestion.sent", f"{sid} from {sender} for {recipient}" + (f" on {task_id}" if task_id else "") + f": {util.one_line(text, 60)}",
                    ref=sid, task=task_id, files=[path] if path else None, audience=[recipient])
    return Result(f"sent {sid} to {recipient}; they must answer it before closing {task_id or 'their task'}", {"id": sid, "to": recipient})


@op("suggest.reply", tool="rt_suggest", action="reply", desc="Answer a suggestion sent to you",
    params=[Param("id", required=True), Param("status", required=True, enum=("accepted", "rejected", "later")),
            Param("reason", required=True, desc="one or two sentences")])
def reply(ctx, id, status, reason) -> Result:
    reason = util.cap_chars(util.require_text(reason, "reason"), ctx.setting("limits", "text_chars"), "reason")
    with ctx.tx():
        s = get(ctx, id)
        if s["to_seat"] != ctx.actor:
            raise RTError(FORBIDDEN, f"{s['id']} was sent to {s['to_seat']}, not you")
        if s["status"] != "open":
            raise RTError(STATE, f"{s['id']} was already answered ({s['status']})")
        ctx.db.execute("UPDATE suggestions SET status = ?, reply = ?, replied_at = ? WHERE id = ?", (status, reason, util.now(), s["id"]))
        events.emit(ctx, "suggestion.replied", f"{ctx.actor} {status} {s['id']}: {util.one_line(reason, 70)}", ref=s["id"], task=s["task"], audience=[s["from_seat"]])
    return Result(f"{s['id']} marked {status}")


@op("suggest.list", tool="rt_suggest", action="list", frozen_ok=True, desc="Suggestions to you (open) and your sent ones",
    params=[Param("all", type="bool", default=False, desc="include answered ones")])
def list_suggestions(ctx, all=False) -> Result:
    me = ctx.actor
    cond = "" if all else " AND status = 'open'"
    inbox = ctx.db.all(f"SELECT * FROM suggestions WHERE to_seat = ?{cond} ORDER BY id", (me,))
    sent = ctx.db.all("SELECT * FROM suggestions WHERE from_seat = ? ORDER BY id DESC LIMIT 10", (me,))
    lines = []
    for s in inbox:
        where = s["task"] or s["file"] or ""
        lines.append(f"{s['id']} [{s['status']}] for you on {where}: " + fmt.quoted(s["from_seat"], s["text"], 600))
        if s["patch"]:
            lines.append("  patch:\n" + fmt.quoted(s["from_seat"], s["patch"], 4000))
    if sent:
        lines.append("sent by you: " + "; ".join(f"{s['id']} to {s['to_seat']} [{s['status']}]" + (f" ({util.one_line(s['reply'], 40)})" if s["reply"] else "") for s in sent))
    return Result("\n".join(lines) if lines else "no suggestions", {"open": [s["id"] for s in inbox]})

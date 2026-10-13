"""Project memory: short notes the whole table keeps across sessions.

Seats and the human add notes ("tests need DATABASE_URL set", "we chose
argon2 for passwords"). Every seat sees the pinned notes and the newest
others when it joins, so a fresh chat starts with what earlier chats learned.
Notes written by seats are shown as data, never as instructions.
"""

from __future__ import annotations

from . import events, fmt, util
from .errors import FORBIDDEN, INVALID, NOT_FOUND, STATE, RTError
from .registry import ANY, HUMAN, Param, Result, op

MAX_WORDS = 60
JOIN_CHARS = 1500


def _get(ctx, mid):
    mid = str(mid or "").strip().upper()
    if mid and mid[0].isdigit():
        mid = "N" + mid
    row = ctx.db.one("SELECT * FROM memories WHERE id = ?", (mid,))
    if row is None:
        raise RTError(NOT_FOUND, f"no memory {mid or '(empty id)'}", "rt_memory list shows them")
    return row


def _line(row, viewer: str) -> str:
    tags = util.jload(row["tags"], [])
    t = f" [{', '.join(tags)}]" if tags else ""
    pin = " (pinned)" if row["pinned"] else ""
    if row["author"] == "human" or row["author"] == viewer:
        return f"{row['id']}{pin}{t} {row['author']}: {row['text']}"
    return f"{row['id']}{pin}{t} " + fmt.quoted(row["author"], row["text"])


@op("memory.add", who=ANY, tool="rt_memory", action="add",
    desc="Remember something every seat should know in later sessions: a convention, a decision, a gotcha",
    params=[Param("text", required=True, desc=f"<= {MAX_WORDS} words, one fact"), Param("tags", type="list", desc="e.g. tests, auth")])
def add(ctx, text, tags=None) -> Result:
    text = util.cap_words(util.require_text(text, "text"), MAX_WORDS, "memory")
    from .tasks import check_labels

    tags = check_labels(tags, "tags")
    with ctx.tx():
        same = ctx.db.one("SELECT id FROM memories WHERE status = 'active' AND lower(text) = lower(?)", (text,))
        if same:
            return Result(f"already remembered as {same['id']}", {"id": same["id"], "duplicate": True})
        mid = util.next_id(ctx.db, "memory", "N")
        now = util.now()
        pinned = 1 if ctx.actor == "human" else 0
        ctx.db.execute("INSERT INTO memories(id, text, author, tags, pinned, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                       (mid, text, ctx.actor, util.jdump(tags), pinned, now, now))
        events.emit(ctx, "memory.added", f"{ctx.actor} remembered {mid}: {util.one_line(text, 70)}", ref=mid)
    return Result(f"remembered {mid}" + (" (pinned: every seat sees it when joining)" if pinned else ""), {"id": mid})


@op("memory.list", who=ANY, tool="rt_memory", action="list", frozen_ok=True, desc="Project memory, pinned first",
    params=[Param("query", desc="only notes containing this text or tag"), Param("all", type="bool", default=False, desc="include forgotten ones")])
def list_(ctx, query=None, all=False) -> Result:  # noqa: A002 - matches the tool parameter name
    rows = ctx.db.all("SELECT * FROM memories" + ("" if all else " WHERE status = 'active'") + " ORDER BY pinned DESC, created_at DESC")
    if query:
        q = str(query).lower()
        rows = [r for r in rows if q in r["text"].lower() or q in r["tags"].lower()]
    lines = [_line(r, ctx.actor) + ("" if r["status"] == "active" else " (forgotten)") for r in rows[:50]]
    return Result("\n".join(lines) or "no project memory yet", {"ids": [r["id"] for r in rows]})


@op("memory.forget", who=ANY, tool="rt_memory", action="forget", desc="Forget a note that is wrong or outdated (yours; the human can forget any)",
    params=[Param("id", required=True), Param("reason", desc="why it no longer holds")])
def forget(ctx, id, reason=None) -> Result:  # noqa: A002
    with ctx.tx():
        row = _get(ctx, id)
        if row["status"] != "active":
            raise RTError(STATE, f"{row['id']} is already forgotten")
        if ctx.actor not in ("human", row["author"]):
            raise RTError(FORBIDDEN, f"{row['id']} was written by {row['author']}", "suggest the change to them, or raise it with the human")
        ctx.db.execute("UPDATE memories SET status = 'forgotten', pinned = 0, updated_at = ? WHERE id = ?", (util.now(), row["id"]))
        events.emit(ctx, "memory.forgotten", f"{ctx.actor} forgot {row['id']}" + (f": {util.one_line(reason, 60)}" if reason else ""), ref=row["id"])
    return Result(f"forgot {row['id']}")


@op("memory.pin", who=HUMAN, desc="Pin a note so every seat sees it when it joins (or unpin it)",
    params=[Param("id", required=True), Param("pinned", type="bool", default=True)])
def pin(ctx, id, pinned=True) -> Result:  # noqa: A002
    with ctx.tx():
        row = _get(ctx, id)
        if row["status"] != "active":
            raise RTError(STATE, f"{row['id']} is forgotten")
        ctx.db.execute("UPDATE memories SET pinned = ?, updated_at = ? WHERE id = ?", (1 if pinned else 0, util.now(), row["id"]))
        events.emit(ctx, "memory.pinned", f"the human {'pinned' if pinned else 'unpinned'} {row['id']}", ref=row["id"])
    return Result(f"{row['id']} {'pinned' if pinned else 'unpinned'}")


def join_lines(ctx, viewer: str) -> list[str]:
    """What a seat sees about memory when it joins: pinned notes, then the newest others."""
    try:
        rows = ctx.db.all("SELECT * FROM memories WHERE status = 'active' ORDER BY pinned DESC, created_at DESC LIMIT 30")
    except Exception:  # very old database without the table
        return []
    out, used = [], 0
    for r in rows:
        line = _line(r, viewer)
        if used + len(line) > JOIN_CHARS:
            out.append(f"… more: rt_memory list ({len(rows) - len(out)} not shown)")
            break
        out.append(line)
        used += len(line)
    return out


def validate_text(text) -> str:  # used by the dashboard form
    if not str(text or "").strip():
        raise RTError(INVALID, "write the note first")
    return str(text).strip()

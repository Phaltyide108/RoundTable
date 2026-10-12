"""Append-only event log. Every state change writes exactly one event.

Digests, the dashboard, STATUS.md and exports are all built from events, so
always emit inside the same transaction as the change it describes.
"""

from __future__ import annotations

from typing import Any, Iterable

from . import util


def emit(
    ctx,
    type: str,
    text: str,
    *,
    ref: str | None = None,
    task: str | None = None,
    files: Iterable[str] | None = None,
    audience: Iterable[str] | None = None,
    level: int = 0,
    data: dict[str, Any] | None = None,
    actor: str | None = None,
) -> int:
    """Record one event and return its id.

    audience: seats this event is FOR (shown in full in their digest and
              counted in their inbox). None = everyone (shown folded unless
              relevant to the reader's tasks or files).
    """
    with ctx.tx():
        cur = ctx.db.execute(
            "INSERT INTO events(at, actor, type, ref, task, files, audience, level, text, data) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                util.now(),
                actor or ctx.actor,
                type,
                ref,
                task,
                util.jdump(list(files)) if files else None,
                util.jdump(sorted(set(audience))) if audience else None,
                int(level or 0),
                util.one_line(text, 300),
                util.jdump(data) if data else None,
            ),
        )
        return int(cur.lastrowid)


def last_id(ctx) -> int:
    return int(ctx.db.scalar("SELECT COALESCE(MAX(id), 0) FROM events", default=0))

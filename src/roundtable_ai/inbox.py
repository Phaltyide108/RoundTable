"""The one-line inbox that starts every reply to a seat.

Example: [rt: 3 new · 1 review for you · 1 suggestion for you · A4 L3 needs your ack]

Computed with a few cheap COUNT queries, never with model tokens.
"""

from __future__ import annotations

from . import util


def _relevant_new_events(ctx, handle: str, bookmark: int) -> int:
    rows = ctx.db.all("SELECT audience FROM events WHERE id > ? AND actor != ?", (bookmark, handle))
    return len(rows)


def unacked_alerts(ctx, handle: str, min_level: int = 3) -> list:
    """Open alerts at or above min_level that this seat must acknowledge and has not."""
    rows = ctx.db.all(
        "SELECT id, level, title, must_ack FROM alerts WHERE status != 'resolved' AND level >= ? ORDER BY level DESC, id",
        (min_level,),
    )
    out = []
    for r in rows:
        must = util.jload(r["must_ack"], [])
        if handle not in must:
            continue
        acked = ctx.db.one("SELECT 1 FROM alert_acks WHERE alert_id = ? AND seat = ?", (r["id"], handle))
        if not acked:
            out.append(r)
    return out


def counts(ctx, handle: str) -> dict:
    seat = ctx.db.one("SELECT bookmark FROM seats WHERE handle = ?", (handle,))
    bookmark = int(seat["bookmark"]) if seat else 0
    new = _relevant_new_events(ctx, handle, bookmark)
    reviews = ctx.db.scalar(
        "SELECT COUNT(*) FROM assignments WHERE seat = ? AND status = 'open' AND kind = 'review'", (handle,), 0
    )
    critiques = ctx.db.scalar(
        "SELECT COUNT(*) FROM assignments WHERE seat = ? AND status = 'open' AND kind = 'critique'", (handle,), 0
    )
    suggestions = ctx.db.scalar("SELECT COUNT(*) FROM suggestions WHERE to_seat = ? AND status = 'open'", (handle,), 0)
    replies = ctx.db.scalar(
        "SELECT COUNT(*) FROM line_comments lc JOIN tasks t ON t.id = lc.task WHERE t.owner = ? AND lc.resolved = 0", (handle,), 0
    )
    # (no SQLite JSON functions: some older Python builds lack them)
    votes = 0
    for v in ctx.db.all("SELECT id, voters FROM votes WHERE status = 'open'"):
        if handle in util.jload(v["voters"], []) and not ctx.db.one(
            "SELECT 1 FROM ballots WHERE vote_id = ? AND seat = ?", (v["id"], handle)
        ):
            votes += 1
    plan_action = _plan_action(ctx, handle)
    alerts = unacked_alerts(ctx, handle, 1)
    frozen = ctx.db.meta_get("frozen", "0") == "1"
    return {
        "new": new,
        "reviews": reviews,
        "critiques": critiques,
        "suggestions": suggestions,
        "comments": replies,
        "votes": votes,
        "plan": plan_action,
        "alerts": [{"id": a["id"], "level": a["level"], "title": a["title"]} for a in alerts],
        "frozen": frozen,
    }


def _plan_action(ctx, handle: str) -> str | None:
    """What the active plan needs from this seat right now, if anything."""
    plan = ctx.db.one(
        "SELECT * FROM plans WHERE stage IN ('drafting','merging','proposed') ORDER BY id DESC LIMIT 1"
    )
    if plan is None:
        return None
    if plan["stage"] == "drafting":
        planners = util.jload(plan["planners"], [])
        if handle in planners and not ctx.db.one("SELECT 1 FROM drafts WHERE plan_id = ? AND author = ?", (plan["id"], handle)):
            return "draft the plan"
    elif plan["stage"] == "merging" and plan["chair"] == handle:
        return "merge the plan (you chair)"
    elif plan["stage"] == "proposed":
        if not ctx.db.one(
            "SELECT 1 FROM approvals WHERE plan_id = ? AND version = ? AND seat = ?", (plan["id"], plan["version"], handle)
        ):
            return "approve or object to the plan"
    return None


def line(ctx, handle: str) -> str:
    c = counts(ctx, handle)
    parts: list[str] = []
    if c["frozen"]:
        parts.append("STOPPED by the human")
    for a in c["alerts"]:
        parts.append(f"{a['id']} L{a['level']} needs your ack")
    if c["plan"]:
        parts.append(c["plan"])
    if c["new"]:
        parts.append(f"{c['new']} new")
    for key, label in (
        ("reviews", "review"),
        ("critiques", "critique"),
        ("suggestions", "suggestion"),
        ("comments", "open review comment"),
        ("votes", "vote"),
    ):
        n = c[key]
        if n:
            parts.append(f"{n} {label}{'s' if n != 1 else ''} for you")
    return "[rt: " + (" · ".join(parts) if parts else "up to date") + "]"

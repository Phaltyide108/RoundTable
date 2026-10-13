"""rt_sync: what changed since this seat last looked.

Built from the event log by plain code (zero model tokens). Full lines only
for what touches the reader; everything else folds to one line per seat.
"""

from __future__ import annotations

from . import inbox, util
from .registry import Param, Result, op


def _my_context(ctx, handle: str) -> tuple[set[str], list[str], set[str]]:
    from .tasks import LIVE

    mine = {r["id"] for r in ctx.db.all(
        f"SELECT id FROM tasks WHERE owner = ? AND status IN ({','.join('?' * len(LIVE))})", (handle, *LIVE))}
    patterns = [r["pattern"] for r in ctx.db.all("SELECT pattern FROM leases WHERE state = 'active' AND seat = ?", (handle,))]
    upstream = set()
    if mine:
        upstream = {r["depends_on"] for r in ctx.db.all(
            f"SELECT depends_on FROM deps WHERE task IN ({','.join('?' * len(mine))})", tuple(mine))}
    return mine, patterns, upstream


def _relevant(ev, handle: str, mine: set[str], patterns: list[str], upstream: set[str]) -> bool:
    audience = util.jload(ev["audience"], None)
    if audience and handle in audience:
        return True
    if ev["task"] and (ev["task"] in mine or ev["task"] in upstream):
        return True
    if ev["level"] and ev["level"] >= 4:
        return True
    if ev["type"].startswith(("plan.", "human.", "vote.decided")):
        return True
    files = util.jload(ev["files"], None) or []
    return any(util.patterns_overlap(p, f) for p in patterns for f in files)


def digest(ctx, handle: str, move_bookmark: bool = True, full: bool = False) -> Result:
    from . import proofs

    proofs.check_stale(ctx)
    seat = ctx.db.one("SELECT * FROM seats WHERE handle = ?", (handle,))
    bookmark = int(seat["bookmark"])
    evs = ctx.db.all("SELECT * FROM events WHERE id > ? ORDER BY id", (bookmark,))
    top = evs[-1]["id"] if evs else bookmark
    others = [e for e in evs if e["actor"] != handle]
    mine, patterns, upstream = _my_context(ctx, handle)
    shown, folded = [], {}
    for e in others:
        if full or _relevant(e, handle, mine, patterns, upstream):
            shown.append(e)
        else:
            folded[e["actor"]] = folded.get(e["actor"], 0) + 1
    since_row = ctx.db.one("SELECT at FROM events WHERE id = ?", (bookmark,)) if bookmark else None
    since = util.local_hm(since_row["at"]) if since_row else "the start"
    lines = []
    if others:
        lines.append(f"since {since} · {len(others)} change{'s' if len(others) != 1 else ''}, {len(shown)} for you")
    else:
        lines.append(f"no changes from other seats since {since}")
    cap = ctx.setting("limits", "digest_lines")
    for e in shown[:cap]:
        lines.append(f"{util.local_hm(e['at'])} {e['actor']:<8} {e['text']}")
    if len(shown) > cap:
        lines.append(f"… {len(shown) - cap} more for you (rt_sync full=true, or the human's `rt log`)")
    if folded:
        parts = ", ".join(f"{a} {n} change{'s' if n != 1 else ''}" for a, n in sorted(folded.items()))
        lines.append(f"other seats: {parts} (none touch your work)")

    c = inbox.counts(ctx, handle)
    todo = []
    if c["frozen"]:
        todo.append("STOP: the human paused all work")
    for a in c["alerts"]:
        todo.append(f"ack alert {a['id']} L{a['level']}: {a['title']}")
    if c["plan"]:
        todo.append(c["plan"])
    for s in ctx.db.all("SELECT id, task, from_seat FROM suggestions WHERE to_seat = ? AND status = 'open' ORDER BY id", (handle,)):
        todo.append(f"reply to suggestion {s['id']} from {s['from_seat']}" + (f" on {s['task']}" if s["task"] else ""))
    for a in ctx.db.all("SELECT kind, target FROM assignments WHERE seat = ? AND status = 'open' ORDER BY id", (handle,)):
        todo.append(f"{a['kind']} {a['target']}")
    if c["comments"]:
        todo.append(f"{c['comments']} review comment(s) on your tasks to answer (rt_review reply)")
    if c["votes"]:
        todo.append(f"{c['votes']} vote(s) to cast (rt_vote show)")
    lines.append("for you: " + ("; ".join(todo) if todo else "nothing pending"))
    alerts = ctx.db.all("SELECT id, level, title FROM alerts WHERE status != 'resolved' AND level >= 3 ORDER BY level DESC, id LIMIT 5")
    lines.append("open alerts: " + ("; ".join(f"{a['id']} L{a['level']} {util.one_line(a['title'], 50)}" for a in alerts) if alerts else "none"))
    current = ctx.db.all("SELECT id, status FROM tasks WHERE owner = ? AND status NOT IN ('done','cancelled','open','ready') ORDER BY seq, id", (handle,))
    if current:
        lines.append("your tasks: " + ", ".join(f"{t['id']} {t['status']}" for t in current))
    ready = ctx.db.all(
        "SELECT t.id, t.owner, s.status AS os FROM tasks t LEFT JOIN seats s ON s.handle = t.owner WHERE t.status = 'ready' ORDER BY t.seq, t.id"
    )
    if "build" in (seat["roles"] or ""):
        claimable = [r["id"] for r in ready if r["owner"] == handle] + [r["id"] for r in ready if r["owner"] is None or (r["owner"] != handle and r["os"] != "active")]
        if claimable:
            lines.append("ready for you: " + ", ".join(claimable[:10]) + (" …" if len(claimable) > 10 else ""))
    if move_bookmark and top > bookmark:
        with ctx.tx():
            ctx.db.execute("UPDATE seats SET bookmark = ? WHERE handle = ? AND bookmark < ?", (top, handle, top))
    return Result("\n".join(lines), {"since_event": bookmark, "to_event": top, "shown": [e["id"] for e in shown], "folded": folded, "todo": todo})


@op("sync", tool="rt_sync", action="sync", frozen_ok=True, desc="What changed since you last looked, and what needs you",
    params=[Param("full", type="bool", default=False, desc="show every change, not just yours")])
def sync(ctx, full=False) -> Result:
    return digest(ctx, ctx.actor, move_bookmark=True, full=full)

"""Votes for decisions the seats cannot settle by discussion.

A vote decides when every expected voter has cast a ballot: most votes
wins; a tie goes to the human. Votes opened by plans/reviews call back
plans.on_vote_decided / reviews.on_vote_decided.
"""

from __future__ import annotations

import builtins
from collections import Counter

from . import events, fmt, util
from .context import HUMAN
from .errors import FORBIDDEN, INVALID, NOT_FOUND, STATE, RTError
from .registry import ANY, HUMAN as WHO_HUMAN, Param, Result, op


def get(ctx, vid):
    v = str(vid or "").strip().upper()
    if v and v[0].isdigit():
        v = "V" + v
    row = ctx.db.one("SELECT * FROM votes WHERE id = ?", (v,))
    if row is None:
        raise RTError(NOT_FOUND, f"no vote {v}")
    return row


def open(ctx, topic: str, options: list[str], voters: list[str], kind: str = "general", ref: str | None = None) -> str:  # noqa: A001
    topic = util.cap_chars(util.require_text(topic, "topic"), 300, "topic")
    opts = [util.require_text(o, "option") for o in options]
    if len(opts) < 2 or len(set(opts)) != len(opts) or len(opts) > 6:
        raise RTError(INVALID, "a vote needs 2-6 different options")
    with ctx.tx():
        vid = util.next_id(ctx.db, "vote", "V")
        ctx.db.execute(
            "INSERT INTO votes(id, topic, options, kind, ref, opened_by, voters, status, created_at) VALUES (?,?,?,?,?,?,?, 'open', ?)",
            (vid, topic, util.jdump(opts), kind, ref, ctx.actor, util.jdump(sorted(set(voters))), util.now()),
        )
        events.emit(ctx, "vote.opened", f"{vid}: {util.one_line(topic, 80)} ({' / '.join(opts)})", ref=vid, audience=voters or None)
        if not voters:
            ctx.db.execute("UPDATE votes SET status = 'tied' WHERE id = ?", (vid,))
            events.emit(ctx, "vote.tied", f"{vid} has no voters; the human decides", ref=vid)
    return vid


def _expected(ctx, v) -> list[str]:
    active = {r["handle"] for r in ctx.db.all("SELECT handle FROM seats WHERE status = 'active'")}
    return [s for s in util.jload(v["voters"], []) if s in active]


def _maybe_decide(ctx, vid: str) -> str | None:
    v = get(ctx, vid)
    if v["status"] != "open":
        return None
    ballots = ctx.db.all("SELECT seat, choice FROM ballots WHERE vote_id = ?", (vid,))
    cast = {b["seat"] for b in ballots}
    if not set(_expected(ctx, v)) <= cast:
        return None
    counts = Counter(b["choice"] for b in ballots).most_common()
    if not counts or (len(counts) > 1 and counts[0][1] == counts[1][1]):
        ctx.db.execute("UPDATE votes SET status = 'tied' WHERE id = ?", (vid,))
        events.emit(ctx, "vote.tied", f"{vid} is tied; the human decides", ref=vid)
        return "tied"
    _decide(ctx, v, counts[0][0], "majority")
    return counts[0][0]


def _decide(ctx, v, result: str, by: str) -> None:
    ctx.db.execute("UPDATE votes SET status = 'decided', result = ?, decided_by = ?, decided_at = ? WHERE id = ?",
                   (result, by, util.now(), v["id"]))
    events.emit(ctx, "vote.decided", f"{v['id']} decided ({by}): {result}", ref=v["id"], audience=util.jload(v["voters"], []) or None)
    v = get(ctx, v["id"])
    if v["kind"] == "plan":
        from . import plans

        plans.on_vote_decided(ctx, v)
    elif v["kind"] == "review":
        from . import reviews

        reviews.on_vote_decided(ctx, v)


@op("vote.open", tool="rt_vote", action="open", desc="Put a stuck decision to all seats",
    params=[Param("topic", required=True), Param("options", type="list", required=True, desc="2-6 choices"),
            Param("voters", type="list", desc="default: every active seat")])
def open_vote(ctx, topic, options, voters=None) -> Result:
    from . import seats

    active = [r["handle"] for r in seats.active(ctx)]
    vs = [util.check_handle(v) for v in voters] if voters else active
    unknown = [v for v in vs if v not in active]
    if unknown:
        raise RTError(INVALID, f"not active seats: {', '.join(unknown)}")
    vid = open(ctx, topic, options, vs)
    return Result(f"opened {vid} for {', '.join(vs)}; cast with rt_vote cast", {"id": vid})


@op("vote.cast", tool="rt_vote", action="cast", desc="Vote, with your reason (your argument)",
    params=[Param("id", required=True), Param("choice", required=True), Param("reason", required=True)])
def cast(ctx, id, choice, reason) -> Result:
    reason = util.cap_chars(util.require_text(reason, "reason"), ctx.setting("limits", "text_chars"), "reason")
    with ctx.tx():
        v = get(ctx, id)
        if v["status"] != "open":
            raise RTError(STATE, f"{v['id']} is {v['status']}")
        if ctx.actor not in util.jload(v["voters"], []):
            raise RTError(FORBIDDEN, f"you are not a voter on {v['id']}")
        opts = util.jload(v["options"], [])
        if choice not in opts:
            raise RTError(INVALID, f"choice must be one of: {' / '.join(opts)}")
        ctx.db.execute("INSERT OR REPLACE INTO ballots(vote_id, seat, choice, reason, at) VALUES (?,?,?,?,?)",
                       (v["id"], ctx.actor, choice, reason, util.now()))
        events.emit(ctx, "vote.cast", f"{ctx.actor} voted on {v['id']}", ref=v["id"])
        outcome = _maybe_decide(ctx, v["id"])
    tail = f" · decided: {outcome}" if outcome and outcome != "tied" else (" · tied: the human decides" if outcome == "tied" else "")
    return Result(f"vote recorded on {v['id']}: {choice}{tail}")


@op("vote.show", who=ANY, tool="rt_vote", action="show", frozen_ok=True, desc="Read a vote and the arguments",
    params=[Param("id", desc="vote id (default: open votes)")])
def show(ctx, id=None) -> Result:
    rows = [get(ctx, id)] if id else ctx.db.all("SELECT * FROM votes WHERE status IN ('open','tied') ORDER BY id")
    if not rows:
        return Result("no open votes")
    lines = []
    for v in rows:
        lines.append(f"{v['id']} [{v['status']}] {v['topic']} · options: {' / '.join(util.jload(v['options'], []))}" +
                     (f" · result: {v['result']} ({v['decided_by']})" if v["result"] else ""))
        for b in ctx.db.all("SELECT * FROM ballots WHERE vote_id = ? ORDER BY at", (v["id"],)):
            body = f"{b['choice']} because {b['reason']}"
            lines.append("  " + (body if ctx.actor in (b["seat"], HUMAN) else fmt.quoted(b["seat"], body, 600)))
        waiting = [s for s in _expected(ctx, v) if not ctx.db.one("SELECT 1 FROM ballots WHERE vote_id = ? AND seat = ?", (v["id"], s))]
        if v["status"] == "open" and waiting:
            lines.append(f"  waiting for: {', '.join(waiting)}")
    return Result("\n".join(lines), {"votes": [v["id"] for v in rows]})


@op("vote.decide", who=WHO_HUMAN, desc="Decide a vote (ties, or overrule)",
    params=[Param("id", required=True), Param("choice", required=True)])
def decide(ctx, id, choice) -> Result:
    with ctx.tx():
        v = get(ctx, id)
        if v["status"] == "decided":
            raise RTError(STATE, f"{v['id']} was already decided: {v['result']}")
        if choice not in util.jload(v["options"], []):
            raise RTError(INVALID, f"choice must be one of: {' / '.join(util.jload(v['options'], []))}")
        _decide(ctx, v, choice, "human")
    return Result(f"{v['id']} decided: {choice}")


_ = builtins  # keep the builtin `open` reachable as builtins.open in this module

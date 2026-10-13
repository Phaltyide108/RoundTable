"""Reviews at the depth the human chose.

low  - 0 reviewers; summaries only; the proof is the gate.
mid  - 1 reviewer; summary + which functions changed (hunk map); full code
       only for risky tasks or a 1-in-N spot check.
high - 2 reviewers; full code; line comments that must be resolved.

Reviewers come from a different company than the author first. When no seat
can review, the review goes to the human.
"""

from __future__ import annotations

import re

from . import events, fmt, util
from .context import HUMAN
from .errors import FORBIDDEN, INVALID, NOT_FOUND, STATE, RTError
from .registry import ANY, HUMAN as WHO_HUMAN, Param, Result, op

LEVELS = ("low", "mid", "high")
REVIEWERS = {"low": 0, "mid": 1, "high": 2}
FULL_DIFF_CAP = 3000  # lines; protects a reviewer's context even at high


def task_number(task_id: str) -> int:
    m = re.match(r"T(\d+)", task_id or "")
    return int(m.group(1)) if m else 0


def effective_level(ctx, task_row) -> str:
    if task_row["review_override"] in LEVELS:
        return task_row["review_override"]
    files = util.jload(task_row["files"], [])
    for pat in ctx.setting("review", "always_high"):
        if any(util.patterns_overlap(pat, f) for f in files):
            return "high"
    return ctx.setting("review", "level")


def full_code_at_mid(ctx, task_row) -> str | None:
    """Why a mid review shows full code, or None."""
    if task_row["risk"] == "high":
        return "risky task"
    every = ctx.setting("review", "spot_check_every")
    if every and task_number(task_row["id"]) % every == 0:
        return f"spot check (1 in {every})"
    return None


def choose_reviewers(ctx, task_row, n: int, exclude: list[str] | None = None) -> list[str]:
    from . import seats

    exclude = list(exclude or [])
    n -= len(exclude)
    if n <= 0:
        return []
    owner = task_row["owner"]
    owner_row = ctx.db.one("SELECT company FROM seats WHERE handle = ?", (owner,)) if owner else None
    owner_company = owner_row["company"] if owner_row else None
    load = {r["seat"]: r["n"] for r in ctx.db.all(
        "SELECT seat, COUNT(*) AS n FROM assignments WHERE status = 'open' GROUP BY seat")}
    cands = [r for r in seats.active(ctx, "review") if r["handle"] != owner and r["handle"] not in exclude]
    cands.sort(key=lambda r: (r["company"] == owner_company, load.get(r["handle"], 0), r["handle"]))
    chosen = [r["handle"] for r in cands[:n]]
    if len(chosen) < n and HUMAN not in exclude:
        chosen.append(HUMAN)  # the human fills in once, however many are missing
    return chosen


def start_gate(ctx, task_id: str) -> str:
    """Proof passed: assign reviewers for this round (0 -> complete now)."""
    from . import tasks

    t = tasks.get(ctx, task_id)
    level = effective_level(ctx, t)
    n = REVIEWERS[level]
    with ctx.tx():
        rnd = t["review_round"] + 1
        ctx.db.execute("UPDATE tasks SET review_round = ?, updated_at = ? WHERE id = ?", (rnd, util.now(), t["id"]))
        if n == 0:
            events.emit(ctx, "review.skipped", f"{t['id']} review depth low: no review, the passed proof is the gate", ref=t["id"], task=t["id"])
    if n == 0:
        return tasks.complete(ctx, t["id"])
    reviewers: list[str] = []
    if rnd > 1:  # same reviewers as last round, so they check their own requests
        for r in ctx.db.all("SELECT DISTINCT reviewer FROM reviews WHERE task = ? AND round = ?", (t["id"], rnd - 1)):
            if r["reviewer"] == HUMAN or ctx.db.one("SELECT 1 FROM seats WHERE handle = ? AND status = 'active'", (r["reviewer"],)):
                reviewers.append(r["reviewer"])
    if len(reviewers) < n:
        for who in choose_reviewers(ctx, t, n, exclude=reviewers):
            if len(reviewers) >= n or who in reviewers:
                continue
            reviewers.append(who)
    with ctx.tx():
        for who in reviewers:
            rid = util.next_id(ctx.db, "review", "R")
            ctx.db.execute("INSERT INTO reviews(id, task, reviewer, level, round, verdict, created_at) VALUES (?,?,?,?,?, 'pending', ?)",
                           (rid, t["id"], who, level, rnd, util.now()))
            ctx.db.execute("INSERT INTO assignments(kind, seat, target, round, status, created_at) VALUES ('review', ?, ?, ?, 'open', ?)",
                           (who, t["id"], rnd, util.now()))
        events.emit(ctx, "review.assigned", f"{t['id']} needs review ({level}, round {rnd}) by {', '.join(reviewers)}",
                    ref=t["id"], task=t["id"], audience=[r for r in reviewers if r != HUMAN] or None)
    return f"{t['id']} in review ({level}) by {', '.join(reviewers)}"


def _open_assignment(ctx, who: str, task_id: str):
    return ctx.db.one("SELECT * FROM assignments WHERE kind = 'review' AND seat = ? AND target = ? AND status = 'open'", (who, task_id))


def _current_review(ctx, who: str, t):
    return ctx.db.one("SELECT * FROM reviews WHERE task = ? AND reviewer = ? AND round = ?", (t["id"], who, t["review_round"]))


def _unresolved(ctx, task_id: str, reviewer: str | None = None) -> list:
    sql = "SELECT lc.* FROM line_comments lc JOIN reviews r ON r.id = lc.review_id WHERE lc.task = ? AND lc.resolved = 0"
    args: tuple = (task_id,)
    if reviewer:
        sql += " AND r.reviewer = ?"
        args += (reviewer,)
    return ctx.db.all(sql + " ORDER BY lc.id", args)


# ---------------------------------------------------------------- ops

@op("review.queue", tool="rt_review", action="queue", frozen_ok=True, desc="Reviews assigned to you")
def queue(ctx) -> Result:
    rows = ctx.db.all("SELECT a.target, a.round, t.title, t.owner FROM assignments a JOIN tasks t ON t.id = a.target "
                      "WHERE a.kind = 'review' AND a.seat = ? AND a.status = 'open' ORDER BY a.id", (ctx.actor,))
    if not rows:
        return Result("no reviews assigned to you", {"tasks": []})
    lines = []
    for r in rows:
        t = ctx.db.one("SELECT * FROM tasks WHERE id = ?", (r["target"],))
        lines.append(f"{r['target']} round {r['round']} · {effective_level(ctx, t)} · by {r['owner']} · {util.one_line(r['title'], 60)}")
    lines.append('read one: rt_review get task="<id>"')
    return Result("\n".join(lines), {"tasks": [r["target"] for r in rows]})


@op("review.get", who=ANY, tool="rt_review", action="get", desc="What you may read for a review, at the chosen depth",
    params=[Param("task", required=True)])
def get(ctx, task) -> Result:
    from . import gitops, tasks

    t = tasks.get(ctx, task)
    who = ctx.actor
    is_owner = who == t["owner"]
    assigned = _open_assignment(ctx, who, t["id"])
    if not assigned and not is_owner and who != HUMAN:
        raise RTError(FORBIDDEN, f"you are not reviewing {t['id']}", "rt_review queue lists yours")
    level = effective_level(ctx, t)
    lines = [fmt.task_line(t) + f" · review {level} · round {t['review_round']}"]
    if t["summary"]:
        lines.append("summary: " + (t["summary"] if is_owner or who == HUMAN else fmt.quoted(t["owner"] or "?", t["summary"])))
    cps = ctx.db.all("SELECT l0 FROM checkpoints WHERE task = ? ORDER BY at", (t["id"],))
    if cps:
        lines.append("checkpoints: " + " | ".join(util.one_line(c["l0"], 60) for c in cps[-5:]))
    pr = ctx.db.one("SELECT status, id FROM proof_runs WHERE task = ? ORDER BY created_at DESC LIMIT 1", (t["id"],))
    lines.append(f"proof: {pr['status']} ({pr['id']}) · {' && '.join(util.jload(t['proof'], []))}" if pr else "proof: not run yet")
    if is_owner and not assigned:
        for c in _unresolved(ctx, t["id"]):
            lines.append(f"comment {c['id']} {c['file']}:{c['line'] or '-'} " + fmt.quoted("reviewer", c["text"], 600))
        for r in ctx.db.all("SELECT * FROM reviews WHERE task = ? AND verdict = 'changes' ORDER BY created_at DESC LIMIT 2", (t["id"],)):
            for p in util.jload(r["points"], []):
                lines.append("change: " + fmt.quoted(r["reviewer"], p, 600))
        return Result("\n".join(lines), {"task": t["id"], "level": level})
    files = util.jload(t["files"], [])
    if level == "low":
        lines.append("files: " + ", ".join(files))
        lines.append("(review depth low: no code is shown)")
    else:
        hm = gitops.hunk_map(ctx, t) if gitops.is_git(ctx) else []
        if hm:
            lines.append("changed:")
            for h in hm[:40]:
                fns = f" · {', '.join(h['functions'][:6])}" if h["functions"] else ""
                lines.append(f"  {h['path']} +{h['added']} -{h['removed']}{fns}")
        else:
            lines.append("files: " + ", ".join(files) + " (no diff available)")
        total = sum(h["added"] + h["removed"] for h in hm)
        why = "high review" if level == "high" else full_code_at_mid(ctx, t)
        if why and gitops.is_git(ctx):
            lines.append(f"full diff ({why}):")
            lines.append(gitops.diff_text(ctx, t, FULL_DIFF_CAP))
        elif level == "mid" and total > ctx.setting("review", "max_diff_lines"):
            lines.append(f"(large change: {total} lines; summary review only. The human was asked whether to review it in full.)")
            with ctx.tx():
                key = f"bigdiff:{t['id']}:{t['review_round']}"
                if not ctx.db.one("SELECT 1 FROM notices WHERE key = ?", (key,)):
                    ctx.db.execute("INSERT INTO notices(key, at) VALUES (?, ?)", (key, util.now()))
                    ctx.db.execute("INSERT INTO level_requests(id, task, seat, level, reason, status, created_at) VALUES (?,?,?,?,?, 'pending', ?)",
                                   (util.next_id(ctx.db, "levelreq", "Q"), t["id"], "system", "high", f"{total} changed lines at mid", util.now()))
                    events.emit(ctx, "review.level_requested", f"{t['id']} has {total} changed lines; full review? (human decides)", ref=t["id"], task=t["id"])
        if level == "high":
            for c in _unresolved(ctx, t["id"]):
                lines.append(f"open comment {c['id']} {c['file']}:{c['line'] or '-'}: {util.one_line(c['text'], 100)}" + (f" · reply: {util.one_line(c['reply'], 60)}" if c["reply"] else ""))
    text = "\n".join(lines)
    if assigned:
        rv = _current_review(ctx, who, t)
        if rv:
            with ctx.tx():
                ctx.db.execute("UPDATE reviews SET est_tokens = est_tokens + ? WHERE id = ?", (len(text) // 4, rv["id"]))
        text += '\nsubmit: rt_review submit task="%s" verdict=approve|changes points=[...]%s' % (t["id"], " comments=[{file,line,text}]" if level == "high" else "")
    return Result(text, {"task": t["id"], "level": level, "est_tokens": len(text) // 4})


@op("review.submit", who=ANY, tool="rt_review", action="submit", desc="Approve or request changes",
    params=[Param("task", required=True), Param("verdict", required=True, enum=("approve", "changes")),
            Param("points", type="list", desc="short points: what is good / what must change"),
            Param("comments", type="objects", desc="high only: [{file, line, text}]")])
def submit(ctx, task, verdict, points=None, comments=None) -> Result:
    from . import tasks

    who = ctx.actor
    t = tasks.get(ctx, task)
    if t["status"] != "in_review":
        raise RTError(STATE, f"{t['id']} is {t['status']}, not in review")
    a = _open_assignment(ctx, who, t["id"])
    if not a:
        raise RTError(FORBIDDEN, f"you have no open review of {t['id']}", "rt_review queue")
    level = effective_level(ctx, t)
    points = [util.cap_chars(util.require_text(p, "point"), 600, "point") for p in (points or [])]
    if len(points) > ctx.setting("limits", "critique_points"):
        raise RTError(INVALID, f"at most {ctx.setting('limits', 'critique_points')} points")
    comments = comments or []
    if comments and level != "high":
        raise RTError(INVALID, f"line comments are for high reviews; this one is {level}", "put them in points instead")
    clean = []
    for c in comments:
        f = util.norm_path(ctx.root, str(c.get("file", "")))
        line = c.get("line")
        try:
            line = int(line) if line not in (None, "") else None
        except (TypeError, ValueError):
            raise RTError(INVALID, f"comment line must be a number (got {line!r})") from None
        clean.append((f, line, util.cap_chars(util.require_text(c.get("text"), "comment text"), 1000, "comment text")))
    if verdict == "changes" and not points and not clean:
        raise RTError(INVALID, "say what must change", "add points (and comments at high)")
    if verdict == "approve" and clean:
        raise RTError(INVALID, "approving with new line comments is contradictory", "request changes, or move them to points")
    if verdict == "approve" and level == "high":
        mine = _unresolved(ctx, t["id"], who)
        if mine:
            raise RTError(STATE, f"your comments are still open: {', '.join(c['id'] for c in mine)}",
                          "wait for the owner to answer them (rt_review reply), or request changes")
    with ctx.tx():
        rv = _current_review(ctx, who, t)
        if rv is None:
            raise RTError(STATE, f"no review record for {who} on {t['id']} this round")
        ctx.db.execute("UPDATE reviews SET verdict = ?, points = ?, submitted_at = ? WHERE id = ?",
                       (verdict, util.jdump(points), util.now(), rv["id"]))
        for f, line, text in clean:
            ctx.db.execute("INSERT INTO line_comments(id, review_id, task, file, line, text) VALUES (?,?,?,?,?,?)",
                           (util.next_id(ctx.db, "comment", "L"), rv["id"], t["id"], f, line, text))
        ctx.db.execute("UPDATE assignments SET status = 'done', done_at = ? WHERE id = ?", (util.now(), a["id"]))
        events.emit(ctx, "review.submitted", f"{who} {'approved' if verdict == 'approve' else 'requested changes on'} {t['id']}" +
                    (f" ({len(clean)} comments)" if clean else ""), ref=rv["id"], task=t["id"], audience=[t["owner"]] if t["owner"] else None)
    return Result(f"review recorded ({verdict}) · " + _evaluate(ctx, t["id"]))


def _evaluate(ctx, task_id: str) -> str:
    """Decide the gate once every reviewer of this round has answered."""
    from . import tasks, votes

    t = tasks.get(ctx, task_id)
    if t["status"] != "in_review":
        return f"{t['id']} is {t['status']}"
    rows = ctx.db.all("SELECT * FROM reviews WHERE task = ? AND round = ?", (t["id"], t["review_round"]))
    pending = [r["reviewer"] for r in rows if r["verdict"] == "pending"]
    if pending:
        return f"waiting for {', '.join(pending)}"
    if any(r["verdict"] == "changes" for r in rows):
        if t["review_round"] >= ctx.setting("review", "max_rounds"):
            if ctx.db.one("SELECT 1 FROM votes WHERE kind = 'review' AND ref = ? AND status IN ('open','tied')", (t["id"],)):
                return "a vote on this task is already open"
            from . import seats

            voters = [r["handle"] for r in seats.active(ctx) if r["handle"] != t["owner"]]
            vid = votes.open(ctx, f"{t['id']} has gone {t['review_round']} review rounds. Approve as is, or more changes?",
                             ["approve as is", "more changes"], voters, kind="review", ref=t["id"])
            return f"{t['review_round']} rounds reached: vote {vid} opened (tie goes to the human)"
        tasks.request_changes(ctx, t["id"], ", ".join(r["reviewer"] for r in rows if r["verdict"] == "changes"))
        return f"{t['id']} sent back to {t['owner']} for changes"
    if effective_level(ctx, t) == "high":
        open_c = _unresolved(ctx, t["id"])
        if open_c:
            return f"approved, but comments still open: {', '.join(c['id'] for c in open_c)}"
    return tasks.complete(ctx, t["id"])


def on_vote_decided(ctx, vote_row) -> None:
    from . import tasks

    t = tasks.get(ctx, vote_row["ref"])
    if t["status"] != "in_review":
        return
    if vote_row["result"] == "approve as is":
        with ctx.tx():
            ctx.db.execute("UPDATE line_comments SET resolved = 1, resolved_by = 'vote', resolved_at = ? WHERE task = ? AND resolved = 0",
                           (util.now(), t["id"]))
        tasks.complete(ctx, t["id"])
    else:
        tasks.request_changes(ctx, t["id"], f"vote {vote_row['id']}")


@op("review.reply", tool="rt_review", action="reply", desc="Owner: answer a line comment (resolves it)",
    params=[Param("id", required=True, desc="comment id, e.g. L4"), Param("text", required=True), Param("resolve", type="bool", default=True)])
def reply(ctx, id, text, resolve=True) -> Result:
    cid = str(id).strip().upper()
    text = util.cap_chars(util.require_text(text, "text"), 1000, "text")
    with ctx.tx():
        c = ctx.db.one("SELECT lc.*, r.reviewer FROM line_comments lc JOIN reviews r ON r.id = lc.review_id WHERE lc.id = ?", (cid,))
        if c is None:
            raise RTError(NOT_FOUND, f"no comment {cid}")
        t = ctx.db.one("SELECT owner FROM tasks WHERE id = ?", (c["task"],))
        if t["owner"] != ctx.actor:
            raise RTError(FORBIDDEN, f"only {t['owner']} (the task owner) answers comments on {c['task']}")
        ctx.db.execute("UPDATE line_comments SET reply = ?, resolved = ?, resolved_by = ?, resolved_at = ? WHERE id = ?",
                       (text, 1 if resolve else 0, ctx.actor if resolve else None, util.now() if resolve else None, cid))
        events.emit(ctx, "review.reply", f"{ctx.actor} answered {cid} on {c['task']}" + (" (resolved)" if resolve else ""),
                    ref=cid, task=c["task"], audience=[c["reviewer"]] if c["reviewer"] != HUMAN else None)
    tail = ""
    tk = ctx.db.one("SELECT status FROM tasks WHERE id = ?", (c["task"],))
    if resolve and tk and tk["status"] == "in_review":
        tail = " · " + _evaluate(ctx, c["task"])
    return Result(f"{cid} {'resolved' if resolve else 'answered'}{tail}")


@op("review.ask_level", tool="rt_review", action="ask_level", desc="Ask the human for a deeper review of one task",
    params=[Param("task", required=True), Param("level", required=True, enum=("mid", "high")), Param("reason", required=True)])
def ask_level(ctx, task, level, reason) -> Result:
    from . import tasks

    t = tasks.get(ctx, task)
    cur = effective_level(ctx, t)
    if LEVELS.index(level) <= LEVELS.index(cur):
        raise RTError(INVALID, f"{t['id']} is already reviewed at {cur}; you can only ask for more, never less")
    reason = util.cap_chars(util.require_text(reason, "reason"), 500, "reason")
    with ctx.tx():
        qid = util.next_id(ctx.db, "levelreq", "Q")
        ctx.db.execute("INSERT INTO level_requests(id, task, seat, level, reason, status, created_at) VALUES (?,?,?,?,?, 'pending', ?)",
                       (qid, t["id"], ctx.actor, level, reason, util.now()))
        events.emit(ctx, "review.level_requested", f"{ctx.actor} asks for {level} review on {t['id']}: {util.one_line(reason, 70)}", ref=qid, task=t["id"])
    return Result(f"asked the human ({qid}) for {level} review on {t['id']}")


@op("review.level_decide", who=WHO_HUMAN, desc="Approve or deny a request for deeper review",
    params=[Param("id", required=True), Param("decision", required=True, enum=("approve", "deny"))])
def level_decide(ctx, id, decision) -> Result:
    from . import tasks

    qid = str(id).strip().upper()
    q = ctx.db.one("SELECT * FROM level_requests WHERE id = ?", (qid,))
    if q is None:
        raise RTError(NOT_FOUND, f"no request {qid}")
    if q["status"] != "pending":
        raise RTError(STATE, f"{qid} was already {q['status']}")
    with ctx.tx():
        ctx.db.execute("UPDATE level_requests SET status = ?, decided_at = ? WHERE id = ?",
                       ("approved" if decision == "approve" else "denied", util.now(), qid))
        if decision == "approve":
            ctx.db.execute("UPDATE tasks SET review_override = ?, updated_at = ? WHERE id = ?", (q["level"], util.now(), q["task"]))
        events.emit(ctx, "review.level_decided", f"the human {'approved' if decision == 'approve' else 'denied'} {q['level']} review for {q['task']}",
                    ref=qid, task=q["task"], audience=[q["seat"]] if q["seat"] not in ("system", HUMAN) else None)
    msg = f"{qid} {decision}d"
    t = tasks.get(ctx, q["task"])
    if decision == "approve" and t["status"] == "in_review":
        # restart this round at the new depth
        with ctx.tx():
            ctx.db.execute("UPDATE assignments SET status = 'cancelled', done_at = ? WHERE kind = 'review' AND target = ? AND status = 'open'", (util.now(), t["id"]))
            ctx.db.execute("DELETE FROM reviews WHERE task = ? AND round = ? AND verdict = 'pending'", (t["id"], t["review_round"]))
            ctx.db.execute("UPDATE tasks SET review_round = review_round - 1 WHERE id = ?", (t["id"],))
        msg += " · " + start_gate(ctx, t["id"])
    return Result(msg)

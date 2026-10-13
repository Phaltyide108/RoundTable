"""Alerts, severity 1-5.

1 note · 2 heads-up · 3 problem (must ack before claiming new work)
4 blocking (files held until acked) · 5 critical (files frozen; every other
seat must ack before doing anything; the human is notified)
"""

from __future__ import annotations

from . import events, fmt, util
from .context import HUMAN, SYSTEM
from .errors import FORBIDDEN, INVALID, NOT_FOUND, STATE, RTError
from .registry import ANY, HUMAN as WHO_HUMAN, Param, Result, op

NAMES = {1: "note", 2: "heads-up", 3: "problem", 4: "blocking", 5: "critical"}


def get(ctx, alert_id):
    aid = str(alert_id or "").strip().upper()
    if aid and aid[0].isdigit():
        aid = "A" + aid
    row = ctx.db.one("SELECT * FROM alerts WHERE id = ?", (aid,))
    if row is None:
        raise RTError(NOT_FOUND, f"no alert {aid or '(empty id)'}", "list them: rt_alert list")
    return row


def holds(ctx) -> list[dict]:
    return [dict(pattern=r["pattern"], alert_id=r["alert_id"], kind=r["kind"])
            for r in ctx.db.all("SELECT pattern, alert_id, kind FROM holds WHERE active = 1")]


def blocking_for(ctx, seat: str) -> list:
    """Unacknowledged level >= 3 alerts this seat must acknowledge."""
    from .inbox import unacked_alerts

    return unacked_alerts(ctx, seat, 3)


def _must_ack(ctx, raiser: str, level: int, files: list[str], tasks: list[str]) -> list[str]:
    from . import gitops, seats

    active = [r["handle"] for r in seats.active(ctx)]
    if level >= 5:
        return [h for h in active if h != raiser]
    who: set[str] = set()
    for t in tasks:
        row = ctx.db.one("SELECT owner FROM tasks WHERE id = ?", (t,))
        if row and row["owner"]:
            who.add(row["owner"])
    if files:
        known = gitops.known_files(ctx)
        for lease in ctx.db.all("SELECT seat, pattern FROM leases WHERE state = 'active'"):
            if any(util.patterns_overlap(f, lease["pattern"], known) for f in files):
                who.add(lease["seat"])
    who.discard(raiser)
    who &= set(active)
    if not who and level >= 3:
        who = {h for h in active if h != raiser}
    return sorted(who)


def _set_holds(ctx, alert_id: str, level: int, files: list[str]) -> None:
    ctx.db.execute("UPDATE holds SET active = 0 WHERE alert_id = ?", (alert_id,))
    if level >= 4:
        kind = "freeze" if level == 5 else "hold"
        for f in files:
            ctx.db.execute("INSERT INTO holds(pattern, alert_id, kind, active, at) VALUES (?,?,?,1,?)", (f, alert_id, kind, util.now()))


def create(ctx, *, level: int, title: str, description: str = "", evidence: str = "", files=None, tasks=None,
           raised_by: str, must_ack: list[str] | None = None) -> str:
    level = int(level)
    if level not in NAMES:
        raise RTError(INVALID, f"level must be 1-5 (got {level})", "1 note, 2 heads-up, 3 problem, 4 blocking, 5 critical")
    title = util.cap_chars(util.require_text(title, "title"), ctx.setting("limits", "title_chars"), "title")
    description = util.cap_chars(util.require_text(description, "description", allow_empty=True), ctx.setting("limits", "text_chars"), "description")
    evidence = util.cap_chars(util.require_text(evidence, "evidence", allow_empty=True), ctx.setting("limits", "text_chars"), "evidence")
    if level >= 4 and not evidence:
        raise RTError(INVALID, f"a level-{level} alert needs evidence", "add evidence: file:line, or the command and its output")
    files = [util.norm_path(ctx.root, f) for f in util.as_list(files, "files")]
    from .tasks import norm_id

    task_ids = [norm_id(t) for t in util.as_list(tasks, "tasks")]
    for t in task_ids:
        if not ctx.db.one("SELECT 1 FROM tasks WHERE id = ?", (t,)):
            raise RTError(NOT_FOUND, f"no task {t}")
    with ctx.tx():
        must = must_ack if must_ack is not None else _must_ack(ctx, raised_by, level, files, task_ids)
        aid = util.next_id(ctx.db, "alert", "A")
        ctx.db.execute(
            "INSERT INTO alerts(id, level, title, description, evidence, files, tasks, must_ack, raised_by, status, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?, 'open', ?)",
            (aid, level, title, description, evidence, util.jdump(files), util.jdump(task_ids), util.jdump(must), raised_by, util.now()),
        )
        _set_holds(ctx, aid, level, files)
        events.emit(ctx, "alert.raised", f"{aid} L{level} {NAMES[level]}: {title}", ref=aid, files=files or None,
                    task=task_ids[0] if task_ids else None, audience=must or None, level=level, actor=raised_by)
    return aid


def system_alert(ctx, level, title, description="", *, files=None, tasks=None, must_ack=None) -> str:
    return create(ctx, level=level, title=title, description=description, evidence="raised by Roundtable", files=files,
                  tasks=tasks, raised_by=SYSTEM, must_ack=must_ack)


def _affected_owners(ctx, a) -> set[str]:
    owners = set()
    for t in util.jload(a["tasks"], []):
        row = ctx.db.one("SELECT owner FROM tasks WHERE id = ?", (t,))
        if row and row["owner"]:
            owners.add(row["owner"])
    return owners


def describe(ctx, a, viewer: str) -> str:
    acks = {r["seat"] for r in ctx.db.all("SELECT seat FROM alert_acks WHERE alert_id = ?", (a["id"],))}
    must = util.jload(a["must_ack"], [])
    lines = [f"{a['id']} L{a['level']} {NAMES[a['level']]} [{a['status']}] raised by {a['raised_by']} {util.human_ago(a['created_at'])}: {a['title']}"]
    own = viewer in (a["raised_by"], HUMAN)
    if a["description"]:
        lines.append(a["description"] if own else fmt.quoted(a["raised_by"], a["description"]))
    if a["evidence"]:
        lines.append("evidence: " + (a["evidence"] if own else fmt.quoted(a["raised_by"], a["evidence"])))
    files, tasks = util.jload(a["files"], []), util.jload(a["tasks"], [])
    if files:
        lines.append(("frozen" if a["level"] == 5 else "held" if a["level"] == 4 else "files") + ": " + ", ".join(files))
    if tasks:
        lines.append("tasks: " + ", ".join(tasks))
    if must:
        lines.append("must acknowledge: " + ", ".join(f"{m}{' ✓' if m in acks else ''}" for m in must))
    if a["proposed_level"]:
        lines.append(f"{a['proposed_by']} proposed level {a['proposed_level']} (the human decides)")
    if a["status"] == "resolved":
        lines.append(f"resolved by {a['resolved_by']}: {a['resolution']}")
    return "\n".join(lines)


# ---------------------------------------------------------------- ops

@op("alert.raise", who=ANY, tool="rt_alert", action="raise", frozen_ok=True, desc="Raise a problem, level 1-5",
    params=[Param("level", type="int", required=True, desc="1 note · 2 heads-up · 3 problem · 4 blocking · 5 critical"),
            Param("title", required=True, desc="<= 80 characters"),
            Param("description", desc="what is wrong and what it affects"),
            Param("evidence", desc="file:line or command + output (required for 4 and 5)"),
            Param("files", type="list"), Param("tasks", type="list")])
def raise_alert(ctx, level, title, description=None, evidence=None, files=None, tasks=None) -> Result:
    aid = create(ctx, level=level, title=title, description=description or "", evidence=evidence or "", files=files, tasks=tasks, raised_by=ctx.actor)
    a = get(ctx, aid)
    must = util.jload(a["must_ack"], [])
    extra = {1: "", 2: "", 3: " They must acknowledge before claiming new work.", 4: " The files are held until they acknowledge.",
             5: " Files are frozen and every other seat must acknowledge before doing anything; the human is notified."}[a["level"]]
    who = f" for {', '.join(must)}" if must else ""
    return Result(f"raised {aid} (L{a['level']} {NAMES[a['level']]}){who}.{extra}", {"id": aid, "must_ack": must})


@op("alert.ack", tool="rt_alert", action="ack", frozen_ok=True, desc="Acknowledge an alert you have read",
    params=[Param("id", required=True), Param("note", desc="optional: what you will do")])
def ack(ctx, id, note=None) -> Result:
    seat = ctx.actor
    with ctx.tx():
        a = get(ctx, id)
        if a["status"] == "resolved":
            return Result(f"{a['id']} is already resolved; nothing to acknowledge")
        ctx.db.execute("INSERT OR IGNORE INTO alert_acks(alert_id, seat, at) VALUES (?,?,?)", (a["id"], seat, util.now()))
        must = util.jload(a["must_ack"], [])
        acked = {r["seat"] for r in ctx.db.all("SELECT seat FROM alert_acks WHERE alert_id = ?", (a["id"],))}
        all_in = set(must) <= acked
        if all_in and a["status"] == "open":
            ctx.db.execute("UPDATE alerts SET status = 'acknowledged' WHERE id = ?", (a["id"],))
            if a["level"] == 4:
                ctx.db.execute("UPDATE holds SET active = 0 WHERE alert_id = ?", (a["id"],))
        text = f"{seat} acknowledged {a['id']}" + (f": {util.one_line(note, 80)}" if note else "")
        events.emit(ctx, "alert.acked", text, ref=a["id"], audience=[a["raised_by"]] if a["raised_by"] not in (SYSTEM, HUMAN) else None)
    lifted = " Its file hold is lifted." if all_in and a["level"] == 4 else ""
    return Result(f"acknowledged {a['id']}.{lifted}" + ("" if all_in else f" Waiting on: {', '.join(sorted(set(must) - acked))}"))


@op("alert.resolve", who=ANY, tool="rt_alert", action="resolve", frozen_ok=True, desc="Close an alert with what fixed it",
    params=[Param("id", required=True), Param("resolution", required=True, desc="what fixed it")])
def resolve(ctx, id, resolution) -> Result:
    actor = ctx.actor
    resolution = util.cap_chars(util.require_text(resolution, "resolution"), ctx.setting("limits", "text_chars"), "resolution")
    with ctx.tx():
        a = get(ctx, id)
        if a["status"] == "resolved":
            return Result(f"{a['id']} is already resolved")
        if actor != HUMAN:
            if a["level"] == 5 and actor == a["raised_by"]:
                raise RTError(FORBIDDEN, "a level-5 alert must be checked by another seat (or the human), not the one that raised it",
                              "ask another seat to verify the fix and resolve it")
            allowed = {a["raised_by"]} | _affected_owners(ctx, a) | set(util.jload(a["must_ack"], []))
            if a["level"] < 5 and actor not in allowed:
                raise RTError(FORBIDDEN, f"only {', '.join(sorted(allowed))} or the human can resolve {a['id']}")
        ctx.db.execute("UPDATE alerts SET status = 'resolved', resolved_at = ?, resolved_by = ?, resolution = ? WHERE id = ?",
                       (util.now(), actor, resolution, a["id"]))
        ctx.db.execute("UPDATE holds SET active = 0 WHERE alert_id = ?", (a["id"],))
        events.emit(ctx, "alert.resolved", f"{a['id']} resolved by {actor}: {util.one_line(resolution, 80)}", ref=a["id"],
                    files=util.jload(a["files"], []) or None, level=a["level"] if a["level"] >= 4 else 0)
    return Result(f"{a['id']} resolved" + (" · files unfrozen" if a["level"] >= 4 and util.jload(a["files"], []) else ""))


@op("alert.propose_level", tool="rt_alert", action="propose_level", frozen_ok=True, desc="Suggest a different level; the human decides",
    params=[Param("id", required=True), Param("level", type="int", required=True), Param("reason", required=True)])
def propose_level(ctx, id, level, reason) -> Result:
    with ctx.tx():
        a = get(ctx, id)
        if a["status"] == "resolved":
            raise RTError(STATE, f"{a['id']} is already resolved")
        if ctx.actor == a["raised_by"]:
            raise RTError(FORBIDDEN, "you raised it; ask the human to change the level", "or resolve it if the problem is gone")
        if level not in NAMES or level == a["level"]:
            raise RTError(INVALID, f"pick a level 1-5 other than {a['level']}")
        ctx.db.execute("UPDATE alerts SET proposed_level = ?, proposed_by = ? WHERE id = ?", (level, ctx.actor, a["id"]))
        events.emit(ctx, "alert.level_proposed", f"{ctx.actor} proposes {a['id']} become L{level}: {util.one_line(reason, 80)}",
                    ref=a["id"], audience=[a["raised_by"]] if a["raised_by"] not in (SYSTEM, HUMAN) else None)
    return Result(f"proposed L{level} for {a['id']}; the human decides (rt alert set-level)")


@op("alert.set_level", who=WHO_HUMAN, desc="Change an alert's level",
    params=[Param("id", required=True), Param("level", type="int", required=True)])
def set_level(ctx, id, level) -> Result:
    with ctx.tx():
        a = get(ctx, id)
        if level not in NAMES:
            raise RTError(INVALID, "level must be 1-5")
        files, tasks = util.jload(a["files"], []), util.jload(a["tasks"], [])
        if level >= 4 and not a["evidence"]:
            raise RTError(INVALID, f"level {level} needs evidence on the alert", "raise a new alert with evidence instead")
        must = _must_ack(ctx, a["raised_by"], level, files, tasks)
        ctx.db.execute("UPDATE alerts SET level = ?, must_ack = ?, proposed_level = NULL, proposed_by = NULL WHERE id = ?",
                       (level, util.jdump(must), a["id"]))
        if a["status"] != "resolved":
            _set_holds(ctx, a["id"], level, files)
        events.emit(ctx, "alert.level_changed", f"the human set {a['id']} to L{level}", ref=a["id"], audience=must or None, level=level)
    return Result(f"{a['id']} is now L{level} {NAMES[level]}")


@op("alert.show", who=ANY, tool="rt_alert", action="show", frozen_ok=True, desc="Read one alert", params=[Param("id", required=True)])
def show(ctx, id) -> Result:
    a = get(ctx, id)
    return Result(describe(ctx, a, ctx.actor), {k: a[k] for k in a.keys()})


@op("alert.list", who=ANY, tool="rt_alert", action="list", frozen_ok=True, desc="Open alerts (all=true includes resolved)",
    params=[Param("all", type="bool", default=False)])
def list_alerts(ctx, all=False) -> Result:
    rows = ctx.db.all("SELECT * FROM alerts" + ("" if all else " WHERE status != 'resolved'") + " ORDER BY level DESC, id")
    if not rows:
        return Result("no open alerts" if not all else "no alerts yet", {"alerts": []})
    lines = [f"{a['id']} L{a['level']} [{a['status']}] {util.one_line(a['title'], 60)} · by {a['raised_by']}" for a in rows]
    return Result("\n".join(lines), {"alerts": [a["id"] for a in rows]})

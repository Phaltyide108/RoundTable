"""Planning together.

goal (human) -> drafting: up to N planners write blind drafts
-> critique: drafts shown as A/B/C without authors; each seat critiques up
   to K drafts (never its own; another company first)
-> merging: the chair merges drafts + critiques into one task graph
-> proposed: every other seat approves or objects (objection needs a reason)
   - an objection gets one revision round; still objections -> a vote
-> awaiting_human -> the human locks it (sees every proof command) -> tasks
"""

from __future__ import annotations

import random

from . import events, fmt, proofs, util
from .context import HUMAN
from .errors import CONFLICT, FORBIDDEN, INVALID, NOT_FOUND, STATE, RTError
from .registry import ANY, HUMAN as WHO_HUMAN, Param, Result, op

OPEN_STAGES = ("drafting", "critique", "merging", "proposed", "voting", "awaiting_human")
# Found in a benchmark: tasks started together whose proofs each ran the whole test suite waited on each other forever.
PROOF_RULE = ("Each task's proof must pass with only that task's work plus the tasks it depends_on merged: test just its own part "
              "(for example its own test file), and add depends_on for every task whose code it imports or needs. "
              "Tasks that don't need each other's code run at the same time; a whole-suite check belongs in a last task that depends on the others. "
              "Keep tasks few and substantial, about one per builder: every task costs its builder a run and a reviewer another.")

AMEND_KINDS = ("edit_task", "add_task", "change_files", "change_owner", "cancel_task", "change_proof", "remove_dep")


def active(ctx):
    return ctx.db.one("SELECT * FROM plans WHERE stage NOT IN ('done','cancelled') ORDER BY id DESC LIMIT 1")


def _plan(ctx, stages: tuple[str, ...] | None = None):
    p = active(ctx)
    if p is None:
        raise RTError(NOT_FOUND, "there is no active plan", 'the human starts one: rt goal "what to build"')
    if stages and p["stage"] not in stages:
        raise RTError(STATE, f"plan P{p['id']} is in stage {p['stage']}, not {' / '.join(stages)}", "rt_plan view shows what it needs now")
    return p


def _set_stage(ctx, plan_id: int, stage: str, text: str, audience=None) -> None:
    ctx.db.execute("UPDATE plans SET stage = ?, stage_changed_at = ? WHERE id = ?", (stage, util.now(), plan_id))
    events.emit(ctx, f"plan.{stage}", text, ref=f"P{plan_id}", audience=audience or None)


def _voters(ctx) -> list[str]:
    from . import seats

    return [r["handle"] for r in seats.active(ctx) if {"plan", "review"} & set(seats.roles_of(r))]


def maybe_done(ctx, plan_id) -> None:
    if plan_id is None:
        return
    left = ctx.db.scalar("SELECT COUNT(*) FROM tasks WHERE plan_id = ? AND status NOT IN ('done','cancelled')", (plan_id,), 0)
    p = ctx.db.one("SELECT stage FROM plans WHERE id = ?", (plan_id,))
    if not left and p and p["stage"] == "locked":
        with ctx.tx():
            _set_stage(ctx, plan_id, "done", f"plan P{plan_id} is done: every task finished")


# ---------------------------------------------------------------- start

def _pick_planners(ctx, wanted, limit: int) -> list[str]:
    from . import seats

    pool = seats.active(ctx, "plan")
    if wanted:
        names = [util.check_handle(w) for w in wanted]
        handles = {r["handle"] for r in pool}
        bad = [n for n in names if n not in handles]
        if bad:
            raise RTError(INVALID, f"not active seats with the plan role: {', '.join(bad)}", f"planners: {', '.join(sorted(handles)) or 'none'}")
        return names
    by_company: dict[str, list[str]] = {}
    for r in pool:
        by_company.setdefault(r["company"], []).append(r["handle"])
    picked: list[str] = []
    while len(picked) < limit and any(by_company.values()):
        for comp in list(by_company):
            if by_company[comp] and len(picked) < limit:
                picked.append(by_company[comp].pop(0))
    return picked


@op("plan.goal", who=WHO_HUMAN, desc="Start a plan for a goal",
    params=[Param("goal", required=True), Param("planners", type="list", desc="default: up to 3, spread across companies"),
            Param("review", enum=("low", "mid", "high"), desc="also set the review depth"),
            Param("mode", enum=("full", "quick"), default="full",
                  desc="full: blind drafts, critique, agreement; quick: one AI splits the goal into tasks at once"),
            Param("auto", type="bool", default=False, desc="start building without waiting for you to approve the plan")])
def goal(ctx, goal, planners=None, review=None, mode="full", auto=False) -> Result:
    goal = util.cap_chars(util.require_text(goal, "goal"), 4000, "goal")
    mode = mode or "full"
    cur = active(ctx)
    if cur is not None:
        raise RTError(CONFLICT, f"plan P{cur['id']} is still {cur['stage']}", "finish it, or cancel it: rt plan cancel")
    chosen = _pick_planners(ctx, planners, 1 if mode == "quick" else ctx.setting("planning", "max_planners"))
    if not chosen:
        raise RTError(STATE, "no active seat can plan", "add seats first: rt seat add <name> --model <id> --app <app>")
    if review:
        from . import config

        config.set_value(ctx.cfg.path, "review.level", review)
        ctx.cfg.data["review"]["level"] = review
    prev = ctx.db.one("SELECT chair FROM plans WHERE chair IS NOT NULL ORDER BY id DESC LIMIT 1")
    chair = chosen[0]
    if prev and prev["chair"] in chosen:
        chair = chosen[(chosen.index(prev["chair"]) + 1) % len(chosen)]
    if mode == "quick":
        chair, chosen = chosen[0], chosen[:1]
    with ctx.tx():
        now = util.now()
        cur = ctx.db.execute(
            "INSERT INTO plans(goal, stage, chair, planners, created_by, created_at, stage_changed_at, mode, auto_lock) "
            "VALUES (?, ?, ?, ?, 'human', ?, ?, ?, ?)",
            (goal, "merging" if mode == "quick" else "drafting", chair, util.jdump(chosen), now, now, mode, 1 if auto else 0))
        pid = int(cur.lastrowid)
        how = f"quick: {chair} splits it into tasks" if mode == "quick" else f"planners {', '.join(chosen)} draft blind · chair {chair}"
        events.emit(ctx, "plan.goal", f"P{pid} goal: {util.one_line(goal, 90)} · {how}" + (" · starts without approval" if auto else ""),
                    ref=f"P{pid}", audience=chosen)
    if mode == "quick":
        lines = [f"plan P{pid} started in quick mode · {chair} breaks the goal into tasks now · review depth: {ctx.setting('review', 'level')}"
                 + (" · work starts without your approval" if auto else "")]
    else:
        lines = [f"plan P{pid} started · planners: {', '.join(chosen)} (blind drafts) · chair: {chair} · review depth: {ctx.setting('review', 'level')}"
                 + (" · work starts without your approval" if auto else "")]
    lines.append("each planner: open its app and say 'check Roundtable', start it in the background (rt run <seat>), or rt launch <seat>")
    return Result("\n".join(lines), {"plan": pid, "planners": chosen, "chair": chair, "mode": mode})


# ---------------------------------------------------------------- drafting

@op("plan.draft", tool="rt_plan", action="draft", desc="Submit your blind plan draft (others cannot see it until all are in)",
    params=[Param("text", required=True, desc="approach in <= 300 words"),
            Param("tasks", type="objects", required=True, desc='[{"ref":"1","title","summary","files":[...],"proof":[...],"depends_on":["2"],"owner","risk"}]')])
def draft(ctx, text, tasks) -> Result:
    from . import tasks as tasks_mod

    p = _plan(ctx, ("drafting",))
    me = ctx.actor
    if me not in util.jload(p["planners"], []):
        raise RTError(FORBIDDEN, f"you are not a planner for P{p['id']}", "wait for the plan to be proposed, then review it")
    text = util.cap_words(util.require_text(text, "text"), ctx.setting("limits", "draft_words"), "text")
    specs = tasks_mod.validate_specs(ctx, tasks)
    with ctx.tx():
        old = ctx.db.one("SELECT id FROM drafts WHERE plan_id = ? AND author = ?", (p["id"], me))
        if old:
            ctx.db.execute("UPDATE drafts SET text = ?, tasks = ?, submitted_at = ? WHERE id = ?", (text, util.jdump(specs), util.now(), old["id"]))
            did = old["id"]
        else:
            did = util.next_id(ctx.db, "draft", "D")
            ctx.db.execute("INSERT INTO drafts(id, plan_id, author, text, tasks, submitted_at) VALUES (?,?,?,?,?,?)",
                           (did, p["id"], me, text, util.jdump(specs), util.now()))
        events.emit(ctx, "plan.draft", f"{me} submitted a draft for P{p['id']}" + (" (updated)" if old else ""), ref=f"P{p['id']}")
        done = ctx.db.scalar("SELECT COUNT(*) FROM drafts WHERE plan_id = ?", (p["id"],), 0)
        planners = util.jload(p["planners"], [])
        closed = ""
        if done >= len(planners):
            closed = " · " + _close_drafting(ctx, p["id"])
    waiting = [x for x in util.jload(p["planners"], []) if not ctx.db.one("SELECT 1 FROM drafts WHERE plan_id = ? AND author = ?", (p["id"], x))]
    tail = closed or (f" · waiting for: {', '.join(waiting)}" if waiting else "")
    return Result(f"draft {did} saved ({len(specs)} tasks){tail}", {"draft": did})


def _close_drafting(ctx, plan_id: int) -> str:
    """Label drafts anonymously and hand out critiques (or go straight to merging)."""
    from . import seats

    drafts = ctx.db.all("SELECT * FROM drafts WHERE plan_id = ? ORDER BY id", (plan_id,))
    if not drafts:
        raise RTError(STATE, "no drafts yet", "wait for at least one planner")
    order = [d["id"] for d in drafts]
    seed = f"{ctx.db.meta_get('project_id', '')}:{plan_id}"
    random.Random(seed).shuffle(order)
    for i, did in enumerate(order):
        ctx.db.execute("UPDATE drafts SET label = ? WHERE id = ?", (chr(ord("A") + i), did))
    critics = [r for r in seats.active(ctx) if {"plan", "review"} & set(seats.roles_of(r))]
    company = {r["handle"]: r["company"] for r in ctx.db.all("SELECT handle, company FROM seats")}
    author_of = {d["id"]: d["author"] for d in drafts}
    author_company = {d["id"]: company.get(d["author"]) for d in drafts}
    k = max(1, ctx.setting("planning", "critiques_per_seat"))
    load: dict[str, list[str]] = {c["handle"]: [] for c in critics}
    cover: dict[str, list[str]] = {d["id"]: [] for d in drafts}

    def can(c: str, did: str) -> bool:
        return author_of[did] != c and did not in load[c] and len(load[c]) < k

    def give(c: str, did: str) -> None:
        load[c].append(did)
        cover[did].append(c)

    ids = sorted(cover)
    for did in ids:  # 1) one critic from another company per draft
        options = [c for c in load if can(c, did) and company[c] != author_company[did]]
        if options:
            give(min(options, key=lambda c: (len(load[c]), c)), did)
    for did in ids:  # 2) every draft gets someone
        if not cover[did]:
            options = [c for c in load if can(c, did)]
            if options:
                give(min(options, key=lambda c: (len(load[c]), c)), did)
    for c in sorted(load):  # 3) fill each critic up to k, least-covered drafts first
        while len(load[c]) < k:
            options = [d for d in ids if can(c, d)]
            if not options:
                break
            give(c, min(options, key=lambda d: (len(cover[d]), d)))
    n = sum(len(v) for v in load.values())
    if n == 0:
        _set_stage(ctx, plan_id, "merging", f"P{plan_id}: drafting closed; no one else to critique, chair merges", audience=[_chair(ctx, plan_id)])
        return "drafting closed · chair merges next"
    labels = {d["id"]: chr(ord("A") + order.index(d["id"])) for d in drafts}
    for c, dids in load.items():
        for did in dids:
            ctx.db.execute("INSERT INTO assignments(kind, seat, target, status, created_at) VALUES ('critique', ?, ?, 'open', ?)", (c, did, util.now()))
    _set_stage(ctx, plan_id, "critique",
               f"P{plan_id}: drafting closed; critiques: " + "; ".join(f"{c} -> {', '.join(labels[d] for d in v)}" for c, v in load.items() if v),
               audience=[c for c, v in load.items() if v])
    return f"drafting closed · {n} critiques assigned"


def _chair(ctx, plan_id: int) -> str:
    return ctx.db.scalar("SELECT chair FROM plans WHERE id = ?", (plan_id,))


@op("plan.continue", who=WHO_HUMAN, desc="Move on without missing drafts or critiques")
def proceed(ctx) -> Result:
    p = _plan(ctx, ("drafting", "critique"))
    with ctx.tx():
        if p["stage"] == "drafting":
            missing = [x for x in util.jload(p["planners"], []) if not ctx.db.one("SELECT 1 FROM drafts WHERE plan_id = ? AND author = ?", (p["id"], x))]
            msg = _close_drafting(ctx, p["id"])
            return Result(f"P{p['id']}: continued without {', '.join(missing) or 'nobody'} · {msg}")
        cancelled = ctx.db.execute(
            "UPDATE assignments SET status = 'cancelled', done_at = ? WHERE kind = 'critique' AND status = 'open' AND target IN (SELECT id FROM drafts WHERE plan_id = ?)",
            (util.now(), p["id"])).rowcount
        _set_stage(ctx, p["id"], "merging", f"P{p['id']}: the human skipped {cancelled} pending critique(s); chair merges", audience=[p["chair"]])
    return Result(f"P{p['id']}: skipped {cancelled} critique(s) · chair {p['chair']} merges next")


# ---------------------------------------------------------------- viewing

def _draft_by_label(ctx, plan_id: int, label: str):
    row = ctx.db.one("SELECT * FROM drafts WHERE plan_id = ? AND label = ?", (plan_id, str(label).strip().upper()))
    if row is None:
        raise RTError(NOT_FOUND, f"no draft {label} in P{plan_id}", "rt_plan view lists the drafts")
    return row


def _spec_lines(specs: list[dict], indent: str = "  ") -> list[str]:
    out = []
    for s in specs:
        deps = f" after {','.join(s['depends_on'])}" if s.get("depends_on") else ""
        owner = f" @{s['owner']}" if s.get("owner") else ""
        out.append(f"{indent}{s['ref']}. {s['title']}{owner}{deps} · files {', '.join(s['files'])} · proof: {' && '.join(s['proof'])}" +
                   (f" · risk {s['risk']}" if s.get("risk") and s["risk"] != "normal" else ""))
    return out


def _show_draft(ctx, d, viewer: str, *, with_author: bool) -> list[str]:
    who = d["author"] if with_author else f"Draft {d['label']}"
    mine = " (yours)" if viewer == d["author"] else ""
    lines = [f"Draft {d['label'] or '?'}{mine}" + (f" by {d['author']}" if with_author else "") + ":"]
    body = d["text"] if viewer in (d["author"], HUMAN) else fmt.quoted(who, d["text"])
    lines.append("  " + body.replace("\n", "\n  "))
    lines += _spec_lines(util.jload(d["tasks"], []), "    ")
    return lines


@op("plan.view", who=ANY, tool="rt_plan", action="view", frozen_ok=True, desc="See the plan as far as you are allowed right now",
    params=[Param("draft", desc="a draft label (A, B, C) to read in full")])
def view(ctx, draft=None) -> Result:
    p = active(ctx) or ctx.db.one("SELECT * FROM plans ORDER BY id DESC LIMIT 1")
    if p is None:
        return Result('no plan yet; the human starts one with: rt goal "..."')
    me = ctx.actor
    human = me == HUMAN
    planners = util.jload(p["planners"], [])
    lines = [f"P{p['id']} [{p['stage']}] goal: {p['goal']}", f"planners: {', '.join(planners)} · chair: {p['chair']} · version {p['version']}"]
    drafts = ctx.db.all("SELECT * FROM drafts WHERE plan_id = ? ORDER BY label, id", (p["id"],))
    if p["stage"] == "drafting":
        lines.append("drafts in: " + (", ".join(d["author"] for d in drafts) if human else f"{len(drafts)} of {len(planners)}"))
        for d in drafts:
            if human or d["author"] == me:
                lines += _show_draft(ctx, d, me, with_author=human)
        if not human and me in planners and not any(d["author"] == me for d in drafts):
            lines.append("you have not drafted yet: rt_plan draft text=... tasks=[...]. " + PROOF_RULE)
        return Result("\n".join(lines), {"plan": p["id"], "stage": p["stage"]})
    if draft:
        d = _draft_by_label(ctx, p["id"], draft)
        lines += _show_draft(ctx, d, me, with_author=human)
    elif p["stage"] in ("critique", "merging") or (p["stage"] in ("proposed", "voting") and me == p["chair"]):
        mine_to_do = {a["target"] for a in ctx.db.all("SELECT target FROM assignments WHERE kind = 'critique' AND seat = ? AND status = 'open'", (me,))}
        for d in drafts:
            if human or me == p["chair"] or d["id"] in mine_to_do or d["author"] == me:
                lines += _show_draft(ctx, d, me, with_author=human)
        if mine_to_do:
            labels = [d["label"] for d in drafts if d["id"] in mine_to_do]
            lines.append(f"you critique: {', '.join(labels)} -> rt_plan critique draft=<label> points=[{{verdict: keep|change|drop, text}}]")
    if p["stage"] in ("merging", "proposed", "voting", "awaiting_human") and (human or me == p["chair"]):
        for c in ctx.db.all("SELECT c.*, d.label FROM critiques c JOIN drafts d ON d.id = c.draft_id WHERE c.plan_id = ? ORDER BY d.label", (p["id"],)):
            pts = util.jload(c["points"], [])
            critic = c["critic"] if human else "a critic"
            lines.append(f"critique of {c['label']} by {critic}:")
            lines += [f"  {pt['verdict']}: " + (pt["text"] if human else fmt.quoted("critic", pt["text"], 400)) for pt in pts]
    if p["proposal_tasks"]:
        lines.append(f"proposal v{p['version']} by chair {p['chair']}:")
        lines.append("  " + (p["proposal_text"] if me in (p["chair"], HUMAN) else fmt.quoted(p["chair"], p["proposal_text"])))
        lines += _spec_lines(util.jload(p["proposal_tasks"], []), "    ")
        votes = ctx.db.all("SELECT * FROM approvals WHERE plan_id = ? AND version = ?", (p["id"], p["version"]))
        if votes:
            lines.append("responses: " + "; ".join(f"{v['seat']} {v['decision']}" + (f" ({util.one_line(v['reason'], 60)})" if v["reason"] else "") for v in votes))
    if p["stage"] == "merging" and me == p["chair"]:
        if _mode(p) == "quick":
            from . import seats as seats_mod

            builders = ", ".join(r["handle"] for r in seats_mod.active(ctx, "build")) or "none"
            lines.append("quick mode: you alone break the goal into tasks now -> rt_plan propose text=... tasks=[...]. "
                         "Cover the WHOLE goal: every part of it becomes a task, including parts meant for other seats. "
                         "A part the goal gives to a seat (e.g. 'sol: ...') is a task with that seat as owner: never drop it or take it yourself. "
                         "Use the file names the goal gives. Other work is spread across the builders: " + builders + ". "
                         "Proof commands must run on this computer as they are (check what is installed, e.g. python3 vs python, pytest). " + PROOF_RULE)
        else:
            lines.append("you chair: merge the drafts and critiques -> rt_plan propose text=... tasks=[...]")
    if p["stage"] == "proposed" and not human and me != p["chair"]:
        if not ctx.db.one("SELECT 1 FROM approvals WHERE plan_id = ? AND version = ? AND seat = ?", (p["id"], p["version"], me)):
            lines.append("respond: rt_plan approve, or rt_plan object reason=...")
    return Result("\n".join(lines), {"plan": p["id"], "stage": p["stage"]})


# ---------------------------------------------------------------- critique / propose / approve

@op("plan.critique", tool="rt_plan", action="critique", desc="Critique a draft assigned to you",
    params=[Param("draft", required=True, desc="label A, B, C"),
            Param("points", type="objects", required=True, desc='[{"verdict":"keep|change|drop","text":"..."}]'),
            Param("reason", desc="required when you have no change/drop points: why it needs nothing")])
def critique(ctx, draft, points, reason=None) -> Result:
    p = _plan(ctx, ("critique",))
    me = ctx.actor
    d = _draft_by_label(ctx, p["id"], draft)
    a = ctx.db.one("SELECT * FROM assignments WHERE kind = 'critique' AND seat = ? AND target = ? AND status = 'open'", (me, d["id"]))
    if a is None:
        raise RTError(FORBIDDEN, f"draft {d['label']} is not assigned to you for critique", "rt_plan view shows yours")
    limit = ctx.setting("limits", "critique_points")
    if not points or len(points) > limit:
        raise RTError(INVALID, f"give 1-{limit} points")
    clean = []
    for pt in points:
        v = str(pt.get("verdict", "")).strip().lower()
        if v not in ("keep", "change", "drop"):
            raise RTError(INVALID, f"verdict must be keep, change or drop (got {v!r})")
        clean.append({"verdict": v, "text": util.cap_chars(util.require_text(pt.get("text"), "point text"), 400, "point text")})
    if not any(pt["verdict"] in ("change", "drop") for pt in clean):
        if not (reason or "").strip():
            raise RTError(INVALID, "a critique with no change or drop points needs a reason", "say why the draft needs no changes")
        clean.append({"verdict": "keep", "text": "reason for no changes: " + util.cap_chars(reason.strip(), 400, "reason")})
    with ctx.tx():
        ctx.db.execute("INSERT OR REPLACE INTO critiques(id, plan_id, draft_id, critic, points, submitted_at) VALUES (?,?,?,?,?,?)",
                       (util.next_id(ctx.db, "critique", "K"), p["id"], d["id"], me, util.jdump(clean), util.now()))
        ctx.db.execute("UPDATE assignments SET status = 'done', done_at = ? WHERE id = ?", (util.now(), a["id"]))
        events.emit(ctx, "plan.critique", f"a critique of draft {d['label']} is in", ref=f"P{p['id']}")
        left = ctx.db.scalar("SELECT COUNT(*) FROM assignments WHERE kind = 'critique' AND status = 'open' AND target IN (SELECT id FROM drafts WHERE plan_id = ?)", (p["id"],), 0)
        tail = ""
        if not left:
            _set_stage(ctx, p["id"], "merging", f"P{p['id']}: all critiques in; chair {p['chair']} merges", audience=[p["chair"]])
            tail = f" · all critiques in; {p['chair']} merges next"
    return Result(f"critique of draft {d['label']} saved{tail}")


@op("plan.propose", tool="rt_plan", action="propose", desc="Chair: propose the merged plan",
    params=[Param("text", required=True, desc="the merged approach, <= 300 words"), Param("tasks", type="objects", required=True)])
def propose(ctx, text, tasks) -> Result:
    from . import tasks as tasks_mod

    p = _plan(ctx, ("merging",))
    if ctx.actor != p["chair"]:
        raise RTError(FORBIDDEN, f"{p['chair']} chairs P{p['id']}, not you", "review the proposal when it comes")
    text = util.cap_words(util.require_text(text, "text"), ctx.setting("limits", "draft_words"), "text")
    specs = tasks_mod.validate_specs(ctx, tasks)
    with ctx.tx():
        version = p["version"] + 1
        ctx.db.execute("UPDATE plans SET version = ?, proposal_text = ?, proposal_tasks = ? WHERE id = ?", (version, text, util.jdump(specs), p["id"]))
        others = [v for v in _voters(ctx) if v != p["chair"]]
        if not others or _mode(p) == "quick":
            _set_stage(ctx, p["id"], "awaiting_human", f"P{p['id']} v{version} proposed by {p['chair']} ({len(specs)} tasks); ready for the human to lock")
            started = _auto_lock(ctx, p["id"])
            if started:
                return Result(f"proposal v{version} saved · {started}")
            why = "quick mode" if _mode(p) == "quick" and others else "no other seats to approve"
            return Result(f"proposal v{version} saved ({len(specs)} tasks) · {why}: waiting for the human to lock")
        _set_stage(ctx, p["id"], "proposed", f"P{p['id']} v{version} proposed by {p['chair']} ({len(specs)} tasks): approve or object", audience=others)
    return Result(f"proposal v{version} saved ({len(specs)} tasks) · waiting for: {', '.join(others)}", {"version": version})


def _mode(p) -> str:
    try:
        return p["mode"] or "full"
    except (IndexError, KeyError):
        return "full"


def _auto_lock(ctx, plan_id: int) -> str:
    """When the human chose to start without approving, lock the plan the moment it is ready."""
    from . import tasks as tasks_mod

    p = ctx.db.one("SELECT * FROM plans WHERE id = ?", (plan_id,))
    if p is None or not p["auto_lock"] or p["stage"] != "awaiting_human" or not p["proposal_tasks"]:
        return ""
    specs = tasks_mod.validate_specs(ctx, util.jload(p["proposal_tasks"], []))
    with ctx.tx():
        ctx.db.execute("UPDATE plans SET stage = 'locked', locked_at = ?, stage_changed_at = ?, proposal_tasks = ? WHERE id = ?",
                       (util.now(), util.now(), util.jdump(specs), p["id"]))
        ctx.db.execute("UPDATE assignments SET status = 'cancelled', done_at = ? WHERE kind = 'critique' AND status = 'open'", (util.now(),))
        events.emit(ctx, "plan.locked", f"P{p['id']} started without approval, as the human chose: {len(specs)} tasks", ref=f"P{p['id']}",
                    audience=[r["handle"] for r in ctx.db.all("SELECT handle FROM seats WHERE status = 'active'")], actor="system")
        ids = tasks_mod.materialize(ctx, p["id"], specs)
    return f"plan locked automatically (the human chose not to approve it): {', '.join(ids)} are ready to claim"


def _respond(ctx, decision: str, reason: str | None) -> Result:
    from . import votes

    p = _plan(ctx, ("proposed",))
    me = ctx.actor
    if me == p["chair"]:
        raise RTError(INVALID, "you proposed it; your approval is implied")
    if me not in _voters(ctx):
        raise RTError(FORBIDDEN, "only seats with the plan or review role respond to plans")
    if decision == "object":
        reason = util.cap_chars(util.require_text(reason, "reason"), ctx.setting("limits", "text_chars"), "reason")
    with ctx.tx():
        ctx.db.execute("INSERT OR REPLACE INTO approvals(plan_id, version, seat, decision, reason, at) VALUES (?,?,?,?,?,?)",
                       (p["id"], p["version"], me, decision, reason, util.now()))
        events.emit(ctx, f"plan.{'approved' if decision == 'approve' else 'objected'}",
                    f"{me} {'approves' if decision == 'approve' else 'objects to'} P{p['id']} v{p['version']}" + (f": {util.one_line(reason, 80)}" if reason else ""),
                    ref=f"P{p['id']}", audience=[p["chair"]])
        needed = [v for v in _voters(ctx) if v != p["chair"]]
        got = {r["seat"]: r["decision"] for r in ctx.db.all("SELECT seat, decision FROM approvals WHERE plan_id = ? AND version = ?", (p["id"], p["version"]))}
        waiting = [v for v in needed if v not in got]
        if waiting:
            return Result(f"recorded · waiting for: {', '.join(waiting)}")
        objections = [s for s, d in got.items() if d == "object"]
        if not objections:
            _set_stage(ctx, p["id"], "awaiting_human", f"P{p['id']} v{p['version']} approved by all seats; the human can lock it")
            started = _auto_lock(ctx, p["id"])
            return Result("recorded · everyone approved; " + (started or "waiting for the human to lock the plan"))
        if p["revision_rounds"] == 0:
            ctx.db.execute("UPDATE plans SET revision_rounds = 1 WHERE id = ?", (p["id"],))
            _set_stage(ctx, p["id"], "merging", f"P{p['id']}: objections from {', '.join(objections)}; chair {p['chair']} revises once", audience=[p["chair"]])
            return Result(f"recorded · objections from {', '.join(objections)}: the chair revises once")
        _set_stage(ctx, p["id"], "voting", f"P{p['id']} still has objections after revision; vote opened")
        vid = votes.open(ctx, f"Adopt plan P{p['id']} v{p['version']}?", ["approve", "reject"], needed + [p["chair"]], kind="plan", ref=str(p["id"]))
    return Result(f"recorded · objections remain after the revision: vote {vid} opened (the human has the final say)")


@op("plan.approve", tool="rt_plan", action="approve", desc="Approve the proposed plan", params=[Param("reason", desc="optional")])
def approve(ctx, reason=None) -> Result:
    return _respond(ctx, "approve", reason)


@op("plan.object", tool="rt_plan", action="object", desc="Object to the proposed plan, with a reason", params=[Param("reason", required=True)])
def object_(ctx, reason) -> Result:
    return _respond(ctx, "object", reason)


def on_vote_decided(ctx, vote_row) -> None:
    p = ctx.db.one("SELECT * FROM plans WHERE id = ?", (int(vote_row["ref"]),))
    if p is None or p["stage"] != "voting":
        return
    with ctx.tx():
        _set_stage(ctx, p["id"], "awaiting_human", f"P{p['id']}: vote {vote_row['id']} result '{vote_row['result']}'; the human decides whether to lock")


# ---------------------------------------------------------------- human: lock / cancel

@op("plan.lock", who=WHO_HUMAN, desc="Approve the plan and create its tasks (shows every proof command)",
    params=[Param("force", type="bool", default=False, desc="lock the latest proposal even if seats have not all approved"),
            Param("draft", desc="lock a draft (label) directly instead of a proposal")])
def lock(ctx, force=False, draft=None) -> Result:
    from . import tasks as tasks_mod

    p = _plan(ctx, OPEN_STAGES)
    if draft:
        d = _draft_by_label(ctx, p["id"], draft) if p["stage"] != "drafting" else ctx.db.one(
            "SELECT * FROM drafts WHERE plan_id = ? AND (label = ? OR author = ?)", (p["id"], draft.upper(), draft.lower()))
        if d is None:
            raise RTError(NOT_FOUND, f"no draft {draft}")
        specs = util.jload(d["tasks"], [])
    else:
        if not p["proposal_tasks"]:
            raise RTError(STATE, f"P{p['id']} has no proposal yet (stage {p['stage']})", "wait for the chair, or lock a draft: rt plan lock --draft A")
        if p["stage"] != "awaiting_human" and not force:
            raise RTError(STATE, f"P{p['id']} is {p['stage']}; not every seat has approved", "wait, or lock anyway: rt plan lock --force")
        specs = util.jload(p["proposal_tasks"], [])
    specs = tasks_mod.validate_specs(ctx, specs)
    with ctx.tx():
        ctx.db.execute("UPDATE plans SET stage = 'locked', locked_at = ?, stage_changed_at = ?, proposal_tasks = ? WHERE id = ?",
                       (util.now(), util.now(), util.jdump(specs), p["id"]))
        ctx.db.execute("UPDATE assignments SET status = 'cancelled', done_at = ? WHERE kind = 'critique' AND status = 'open'", (util.now(),))
        events.emit(ctx, "plan.locked", f"P{p['id']} locked by the human: {len(specs)} tasks", ref=f"P{p['id']}",
                    audience=[r["handle"] for r in ctx.db.all("SELECT handle FROM seats WHERE status = 'active'")])
        ids = tasks_mod.materialize(ctx, p["id"], specs)
    lines = [f"P{p['id']} locked · {len(ids)} tasks: {', '.join(ids)}", "proof commands you approved (Roundtable will run these on your computer):"]
    for tid, s in zip(ids, specs):
        lines.append(f"  {tid}: {' && '.join(s['proof'])}")
    lines.append("seats can now claim ready tasks. Watch progress: rt status, rt watch, rt ui")
    return Result("\n".join(lines), {"tasks": ids})


@op("plan.cancel", who=WHO_HUMAN, desc="Cancel the active plan (and its unfinished tasks)", params=[Param("reason", required=True)])
def cancel(ctx, reason) -> Result:
    from . import leases

    p = _plan(ctx)
    with ctx.tx():
        ctx.db.execute("UPDATE plans SET stage = 'cancelled', stage_changed_at = ? WHERE id = ?", (util.now(), p["id"]))
        ctx.db.execute("UPDATE assignments SET status = 'cancelled', done_at = ? WHERE status = 'open' AND kind = 'critique'", (util.now(),))
        open_tasks = [r["id"] for r in ctx.db.all("SELECT id FROM tasks WHERE plan_id = ? AND status NOT IN ('done','cancelled')", (p["id"],))]
        for tid in open_tasks:
            ctx.db.execute("UPDATE tasks SET status = 'cancelled', updated_at = ? WHERE id = ?", (util.now(), tid))
            leases.release_task(ctx, tid)
            ctx.db.execute("UPDATE assignments SET status = 'cancelled', done_at = ? WHERE kind = 'review' AND target = ? AND status = 'open'", (util.now(), tid))
        events.emit(ctx, "plan.cancelled", f"P{p['id']} cancelled by the human: {util.one_line(reason, 80)}", ref=f"P{p['id']}")
    return Result(f"P{p['id']} cancelled" + (f"; tasks cancelled: {', '.join(open_tasks)}" if open_tasks else ""))


# ---------------------------------------------------------------- amendments (after lock)

def _amendment(ctx, mid):
    m = str(mid or "").strip().upper()
    row = ctx.db.one("SELECT * FROM amendments WHERE id = ?", (m,))
    if row is None:
        raise RTError(NOT_FOUND, f"no amendment {m}")
    return row


def _apply(ctx, m) -> str:
    from . import leases, tasks as tasks_mod

    pl = util.jload(m["payload"], {})
    kind, now = m["kind"], util.now()
    if kind == "add_task":
        spec = tasks_mod.validate_specs(ctx, [dict(pl, ref="new", depends_on=[])])[0]
        deps = [tasks_mod.get(ctx, d)["id"] for d in util.as_list(pl.get("depends_on"), "depends_on")]
        tid = util.next_id(ctx.db, "task", "T")
        seq = ctx.db.scalar("SELECT COALESCE(MAX(seq), 0) + 1 FROM tasks", default=1)
        ctx.db.execute("INSERT INTO tasks(id, plan_id, seq, title, summary, detail, owner, status, risk, files, proof, created_at, updated_at) "
                       "VALUES (?,?,?,?,?,?,?, 'open', ?,?,?,?,?)",
                       (tid, m["plan_id"], seq, spec["title"], spec["summary"], spec["detail"], spec["owner"], spec["risk"],
                        util.jdump(spec["files"]), util.jdump(spec["proof"]), now, now))
        for d in deps:
            ctx.db.execute("INSERT OR IGNORE INTO deps(task, depends_on) VALUES (?, ?)", (tid, d))
        tasks_mod.refresh_ready(ctx)
        return f"added {tid}"
    t = tasks_mod.get(ctx, m["task"])
    if t["status"] in ("done", "cancelled"):
        raise RTError(STATE, f"{t['id']} is {t['status']}; it cannot be amended")
    if kind == "edit_task":
        title = util.cap_chars(pl.get("title") or t["title"], ctx.setting("limits", "title_chars"), "title")
        summary = util.cap_words(pl.get("summary") if pl.get("summary") is not None else t["summary"], ctx.setting("limits", "summary_words"), "summary")
        ctx.db.execute("UPDATE tasks SET title = ?, summary = ?, updated_at = ? WHERE id = ?", (title, summary, now, t["id"]))
    elif kind == "change_files":
        files = [util.norm_path(ctx.root, f) for f in util.as_list(pl.get("files"), "files")]
        if not files:
            raise RTError(INVALID, "files cannot be empty")
        if t["status"] in ("claimed", "changes_requested"):
            leases.acquire(ctx, t["owner"], t["id"], files)
        ctx.db.execute("UPDATE tasks SET files = ?, updated_at = ? WHERE id = ?", (util.jdump(files), now, t["id"]))
    elif kind == "change_owner":
        new = util.check_handle(pl.get("owner")) if pl.get("owner") else None
        if t["status"] not in ("open", "ready"):
            raise RTError(STATE, f"{t['id']} is {t['status']}; the human can reassign it: rt task reassign")
        ctx.db.execute("UPDATE tasks SET owner = ?, updated_at = ? WHERE id = ?", (new, now, t["id"]))
    elif kind == "cancel_task":
        ctx.db.execute("UPDATE tasks SET status = 'cancelled', updated_at = ? WHERE id = ?", (now, t["id"]))
        leases.release_task(ctx, t["id"])
    elif kind == "change_proof":
        proof = [util.require_text(c, "proof command") for c in util.as_list(pl.get("proof"), "proof")]
        if not proof:
            raise RTError(INVALID, "a task needs at least one proof command")
        for c in proof:
            why = proofs.proof_problem(c)
            if why:
                raise RTError(INVALID, f"that proof command can't run here: {why}", "give a command that runs on this computer")
        ctx.db.execute("UPDATE tasks SET proof = ?, updated_at = ? WHERE id = ?", (util.jdump(proof), now, t["id"]))
    elif kind == "remove_dep":
        dep = tasks_mod.norm_id(pl.get("depends_on"))
        ctx.db.execute("DELETE FROM deps WHERE task = ? AND depends_on = ?", (t["id"], dep))
        tasks_mod.refresh_ready(ctx)
    return f"{kind} applied to {t['id']}"


def _finalize(ctx, m, status: str, by: str) -> str:
    msg = _apply(ctx, m) if status == "applied" else "rejected"
    ctx.db.execute("UPDATE amendments SET status = ?, decided_at = ?, needs = '[]' WHERE id = ?", (status, util.now(), m["id"]))
    events.emit(ctx, f"plan.amend_{status}", f"amendment {m['id']} ({m['kind']} {m['task'] or ''}) {status} by {by}: {msg}",
                ref=m["id"], task=m["task"], audience=[m["proposed_by"]] if m["proposed_by"] != HUMAN else None)
    return msg


@op("plan.amend", tool="rt_plan", action="amend", desc="Propose a change to the locked plan",
    params=[Param("kind", required=True, enum=AMEND_KINDS), Param("task", desc="task id (not for add_task)"),
            Param("change", type="object", required=True, desc='e.g. {"title":..}, {"files":[..]}, {"owner":..}, {"proof":[..]}, a new task spec, {"depends_on":"T2"}'),
            Param("reason", required=True)])
def amend(ctx, kind, change, reason, task=None) -> Result:
    from . import tasks as tasks_mod

    p = _plan(ctx, ("locked",))
    me = ctx.actor
    reason = util.cap_chars(util.require_text(reason, "reason"), 1000, "reason")
    t = None
    if kind != "add_task":
        if not task:
            raise RTError(INVALID, f"{kind} needs a task id")
        t = tasks_mod.get(ctx, task)
    owners = set()
    if t is not None and t["owner"]:
        owners.add(t["owner"])
    if kind == "change_owner" and change.get("owner"):
        owners.add(util.check_handle(change["owner"]))
    if kind == "edit_task":
        if me not in owners | {p["chair"]}:
            raise RTError(FORBIDDEN, "only the task owner or the chair edits titles and summaries", "propose it to them with rt_suggest")
        needs: list[str] = []
    else:
        needs = sorted(({p["chair"]} | owners) - {me})
        if kind == "change_proof":
            needs.append(HUMAN)
            for c in util.as_list(change.get("proof"), "proof"):
                why = proofs.proof_problem(str(c))
                if why:
                    raise RTError(INVALID, f"that proof command can't run here: {why}", "give a command that runs on this computer")
    with ctx.tx():
        mid = util.next_id(ctx.db, "amendment", "M")
        ctx.db.execute("INSERT INTO amendments(id, plan_id, proposed_by, kind, task, payload, reason, status, needs, created_at) VALUES (?,?,?,?,?,?,?, 'pending', ?, ?)",
                       (mid, p["id"], me, kind, t["id"] if t else None, util.jdump(change), reason, util.jdump(needs), util.now()))
        m = _amendment(ctx, mid)
        if not needs:
            msg = _finalize(ctx, m, "applied", me)
            return Result(f"{mid}: {msg}")
        events.emit(ctx, "plan.amend_proposed", f"{me} proposes {mid}: {kind} {t['id'] if t else ''} ({util.one_line(reason, 60)}) · needs {', '.join(needs)}",
                    ref=mid, task=t["id"] if t else None, audience=[n for n in needs if n != HUMAN] or None)
    return Result(f"{mid} proposed · needs approval from: {', '.join(needs)}")


@op("plan.amend_vote", tool="rt_plan", action="amend_vote", desc="Approve or reject an amendment that needs you",
    params=[Param("id", required=True), Param("decision", required=True, enum=("approve", "reject")), Param("reason", desc="required to reject")])
def amend_vote(ctx, id, decision, reason=None) -> Result:
    me = ctx.actor
    with ctx.tx():
        m = _amendment(ctx, id)
        if m["status"] != "pending":
            raise RTError(STATE, f"{m['id']} is already {m['status']}")
        needs = util.jload(m["needs"], [])
        if me not in needs:
            raise RTError(FORBIDDEN, f"{m['id']} does not need your approval (needs: {', '.join(needs)})")
        if decision == "reject":
            util.require_text(reason, "reason")
            return Result(f"{m['id']} {_finalize(ctx, m, 'rejected', me)}")
        needs.remove(me)
        ctx.db.execute("UPDATE amendments SET needs = ? WHERE id = ?", (util.jdump(needs), m["id"]))
        if not needs:
            return Result(f"{m['id']}: {_finalize(ctx, _amendment(ctx, m['id']), 'applied', me)}")
    return Result(f"approved · {m['id']} still needs: {', '.join(needs)}")


@op("plan.amend_decide", who=WHO_HUMAN, desc="Approve (applies now) or reject an amendment",
    params=[Param("id", required=True), Param("decision", required=True, enum=("approve", "reject"))])
def amend_decide(ctx, id, decision) -> Result:
    with ctx.tx():
        m = _amendment(ctx, id)
        if m["status"] != "pending":
            raise RTError(STATE, f"{m['id']} is already {m['status']}")
        msg = _finalize(ctx, m, "applied" if decision == "approve" else "rejected", "the human")
    return Result(f"{m['id']}: {msg}")

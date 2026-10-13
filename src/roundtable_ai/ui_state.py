"""Everything the dashboard shows, as plain data.

Built from the database with plain queries (no model tokens). The dashboard
polls `build()` every few seconds, so it must stay cheap: no git commands
here except where a section asks for details (`task_detail`, `diff`).
"""

from __future__ import annotations

import time
from typing import Any

from . import __version__, apps, util

STAGE_LABEL = {
    "drafting": "Models are writing their plans",
    "critique": "Models are critiquing each other's plans",
    "merging": "The chair is merging the plans",
    "proposed": "Models are approving the merged plan",
    "voting": "Models are voting on objections",
    "awaiting_human": "Ready for you to lock",
    "locked": "Locked: models are building",
    "done": "Done",
    "cancelled": "Cancelled",
}
STAGES = ("drafting", "critique", "merging", "proposed", "awaiting_human", "locked")

STATUS_LABEL = {
    "backlog": "Backlog", "open": "Waiting", "ready": "Ready", "claimed": "In progress", "changes_requested": "Changes requested",
    "proving": "Testing", "in_review": "In review", "merge_blocked": "Waiting to merge", "done": "Done", "cancelled": "Cancelled",
}

_probe_cache: dict[str, tuple[float, bool]] = {}


def _probe(name: str) -> bool:
    """has_terminal / has_vscode, cached for a minute (they scan PATH)."""
    from . import desktop

    hit = _probe_cache.get(name)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    value = desktop.has_terminal() if name == "terminal" else desktop.has_vscode()
    _probe_cache[name] = (time.time(), value)
    return value


def _ago(value: str | None) -> str:
    return util.human_ago(value) if value else ""


def _seats(ctx) -> list[dict]:
    from . import launch, usage
    from .seats import is_live, roles_of

    out = []
    live_tasks: dict[str, list[str]] = {}
    for t in ctx.db.all("SELECT id, owner FROM tasks WHERE status IN ('claimed','changes_requested','proving','in_review','merge_blocked') AND owner IS NOT NULL ORDER BY priority, seq"):
        live_tasks.setdefault(t["owner"], []).append(t["id"])
    for s in ctx.db.all("SELECT * FROM seats WHERE status != 'removed' ORDER BY created_at, handle"):
        app = apps.get(s["app"])
        try:
            snap = usage.seat_snapshot(ctx, s)
        except Exception:
            snap = None
        ex = usage.exchange_totals(ctx, s["handle"])
        out.append({
            "handle": s["handle"], "model": s["model"], "company": s["company"], "app": s["app"], "app_label": app.label,
            "roles": roles_of(s), "status": s["status"], "live": is_live(ctx, s), "seen": _ago(s["last_seen"]),
            "joined_ever": bool(s["last_seen"]), "doing": s["now_doing"] or "", "worktree": s["worktree"] or "",
            "tasks": live_tasks.get(s["handle"], []), "start": launch.start_info(ctx, s),
            "usage": {"snapshot": snap, "text": usage.describe(snap), "exchange": ex},
        })
    return out


def _plan(ctx) -> dict | None:
    p = ctx.db.one("SELECT * FROM plans ORDER BY id DESC LIMIT 1")
    if p is None:
        return None
    planners = util.jload(p["planners"], [])
    drafts = ctx.db.all("SELECT * FROM drafts WHERE plan_id = ? ORDER BY COALESCE(label, author)", (p["id"],))
    crits = ctx.db.all("SELECT c.*, d.label FROM critiques c JOIN drafts d ON d.id = c.draft_id WHERE c.plan_id = ? ORDER BY c.submitted_at", (p["id"],))
    assigned = ctx.db.all("SELECT seat, status FROM assignments WHERE kind = 'critique' AND target IN (SELECT id FROM drafts WHERE plan_id = ?)", (p["id"],))
    approvals = {a["seat"]: {"decision": a["decision"], "reason": a["reason"] or ""}
                 for a in ctx.db.all("SELECT * FROM approvals WHERE plan_id = ? AND version = ?", (p["id"], p["version"]))}
    seats_involved = list(dict.fromkeys(planners + [a["seat"] for a in assigned] + list(approvals)))
    people = []
    for h in seats_involved:
        mine = [a for a in assigned if a["seat"] == h]
        people.append({"seat": h, "planner": h in planners, "drafted": any(d["author"] == h for d in drafts),
                       "critiques_done": sum(1 for a in mine if a["status"] == "done"), "critiques": len(mine),
                       "approval": approvals.get(h), "chair": h == p["chair"]})
    specs = util.jload(p["proposal_tasks"], []) if p["proposal_tasks"] else []
    if not specs and len(drafts) == 1 and p["stage"] in ("awaiting_human",):
        specs = util.jload(drafts[0]["tasks"], [])
    commands = list(dict.fromkeys(c for s in specs for c in (s.get("proof") or [])))
    age = util.seconds_since(p["stage_changed_at"]) or 0
    amendments = [{"id": m["id"], "kind": m["kind"], "task": m["task"], "change": util.jload(m["payload"], {}), "reason": m["reason"] or "",
                   "by": m["proposed_by"], "needs": util.jload(m["needs"], []), "human": "human" in util.jload(m["needs"], [])}
                  for m in ctx.db.all("SELECT * FROM amendments WHERE plan_id = ? AND status = 'pending' ORDER BY created_at", (p["id"],))]
    return {
        "id": p["id"], "goal": p["goal"], "stage": p["stage"], "stage_label": STAGE_LABEL.get(p["stage"], p["stage"]),
        "chair": p["chair"], "planners": planners, "version": p["version"], "people": people,
        "since": _ago(p["stage_changed_at"]), "created": _ago(p["created_at"]),
        "overdue": p["stage"] == "drafting" and age > ctx.setting("planning", "draft_timeout_minutes") * 60,
        "drafts": [{"label": d["label"] or "", "author": d["author"], "text": d["text"], "tasks": util.jload(d["tasks"], []),
                    "at": _ago(d["submitted_at"])} for d in drafts],
        "critiques": [{"draft": c["label"] or "", "critic": c["critic"], "points": util.jload(c["points"], []), "at": _ago(c["submitted_at"])} for c in crits],
        "proposal": p["proposal_text"] or "", "tasks": specs, "commands": commands, "revisions": p["revision_rounds"],
        "amendments": amendments,
        "critique_pairs": [[r["seat"], r["author"]] for r in ctx.db.all(
            "SELECT a.seat, d.author FROM assignments a JOIN drafts d ON d.id = a.target WHERE a.kind = 'critique' AND a.status = 'open' AND d.plan_id = ?", (p["id"],))],
    }


def _tasks(ctx) -> list[dict]:
    from . import reviews

    proofs = {r["task"]: r for r in ctx.db.all(
        "SELECT p.* FROM proof_runs p JOIN (SELECT task, MAX(created_at) m FROM proof_runs GROUP BY task) x ON x.task = p.task AND x.m = p.created_at")}
    waits: dict[str, list[str]] = {}
    for d in ctx.db.all("SELECT task, depends_on FROM deps WHERE kind = 'blocks'"):
        waits.setdefault(d["task"], []).append(d["depends_on"])
    reviewing: dict[str, list[str]] = {}
    for r in ctx.db.all("SELECT seat, target FROM assignments WHERE kind = 'review' AND status = 'open' AND seat != 'human'"):
        reviewing.setdefault(r["target"], []).append(r["seat"])
    blocked_note = {e["task"]: e["text"] for e in ctx.db.all(
        "SELECT task, text FROM events WHERE type = 'task.merge_blocked' AND id IN (SELECT MAX(id) FROM events WHERE type = 'task.merge_blocked' GROUP BY task)")}
    out = []
    for t in ctx.db.all("SELECT * FROM tasks ORDER BY CASE status WHEN 'done' THEN 1 WHEN 'cancelled' THEN 2 ELSE 0 END, priority, seq, id LIMIT 600"):
        pr = proofs.get(t["id"])
        out.append({
            "id": t["id"], "title": t["title"], "status": t["status"], "status_label": STATUS_LABEL.get(t["status"], t["status"]),
            "owner": t["owner"] or "", "kind": t["kind"], "priority": t["priority"], "labels": util.jload(t["labels"], []),
            "parent": t["parent"] or "", "files": util.jload(t["files"], []), "proof": util.jload(t["proof"], []), "risk": t["risk"],
            "summary": t["summary"], "review": reviews.effective_level(ctx, t), "waits_for": waits.get(t["id"], []),
            "filed_by": t["filed_by"] or "", "updated": _ago(t["updated_at"]),
            "proof_status": pr["status"] if pr else "", "merge_note": blocked_note.get(t["id"], "") if t["status"] == "merge_blocked" else "",
            "plan": t["plan_id"], "reviewers": reviewing.get(t["id"], []),
        })
    return out


def _alerts(ctx) -> list[dict]:
    acks: dict[str, list[str]] = {}
    for a in ctx.db.all("SELECT alert_id, seat FROM alert_acks"):
        acks.setdefault(a["alert_id"], []).append(a["seat"])
    return [{"id": a["id"], "level": a["level"], "title": a["title"], "description": a["description"], "evidence": a["evidence"],
             "files": util.jload(a["files"], []), "tasks": util.jload(a["tasks"], []), "by": a["raised_by"], "status": a["status"],
             "must_ack": util.jload(a["must_ack"], []), "acked": acks.get(a["id"], []), "proposed": a["proposed_level"],
             "proposed_by": a["proposed_by"] or "", "at": _ago(a["created_at"])}
            for a in ctx.db.all("SELECT * FROM alerts WHERE status != 'resolved' ORDER BY level DESC, created_at")]


def _votes(ctx) -> list[dict]:
    out = []
    for v in ctx.db.all("SELECT * FROM votes WHERE status IN ('open','tied') ORDER BY created_at"):
        ballots = [{"seat": b["seat"], "choice": b["choice"], "reason": b["reason"] or ""}
                   for b in ctx.db.all("SELECT * FROM ballots WHERE vote_id = ? ORDER BY at", (v["id"],))]
        out.append({"id": v["id"], "topic": v["topic"], "options": util.jload(v["options"], []), "kind": v["kind"], "ref": v["ref"] or "",
                    "voters": util.jload(v["voters"], []), "ballots": ballots, "status": v["status"], "by": v["opened_by"]})
    return out


def _needs(ctx, plan, tasks, alerts, votes, seats) -> list[dict]:
    """What waits on the human, most urgent first, each with the buttons that settle it."""
    items: list[dict] = []
    if ctx.db.meta_get("frozen") == "1":
        items.append({"key": "frozen", "tone": "stop", "title": "All models are stopped",
                      "body": ctx.db.meta_get("frozen_reason") or "You stopped them.",
                      "actions": [{"label": "Let them work again", "op": "admin.unfreeze", "params": {}, "style": "primary"}]})
    for a in alerts:
        if a["level"] >= 4:
            items.append({"key": f"alert:{a['id']}", "tone": "stop" if a["level"] == 5 else "warn",
                          "title": f"Level {a['level']} alert from {a['by']}: {a['title']}", "body": a["description"],
                          "go": f"alerts/{a['id']}", "actions": [{"label": "Open alert", "go": f"alerts/{a['id']}"}]})
        if a["proposed"]:
            items.append({"key": f"alert-level:{a['id']}", "tone": "decide",
                          "title": f"{a['proposed_by']} suggests level {a['proposed']} for {a['id']} (now {a['level']})", "body": a["title"],
                          "actions": [{"label": f"Change to level {a['proposed']}", "op": "alert.set_level", "params": {"id": a["id"], "level": a["proposed"]}, "style": "primary"},
                                      {"label": "Open alert", "go": f"alerts/{a['id']}"}]})
    if plan and plan["stage"] == "awaiting_human":
        items.append({"key": f"plan:{plan['id']}:v{plan['version']}", "tone": "decide", "title": "The plan is ready for you",
                      "body": f"{len(plan['tasks'])} tasks. Check the test commands it will run, then lock it.",
                      "actions": [{"label": "Review and lock", "go": "plan", "style": "primary"}]})
    if plan and plan["overdue"]:
        missing = [p["seat"] for p in plan["people"] if p["planner"] and not p["drafted"]]
        items.append({"key": f"plan:{plan['id']}:overdue", "tone": "decide", "title": "Some plans are late",
                      "body": f"Still waiting for: {', '.join(missing) or 'drafts'}. You can go on with the drafts that are in.",
                      "actions": [{"label": "Go on without them", "op": "plan.continue", "params": {}, "style": "primary"}]})
    if plan:
        for m in plan["amendments"]:
            if m["human"]:
                items.append({"key": f"amend:{m['id']}", "tone": "decide", "title": f"{m['by']} wants to change the plan ({m['kind'].replace('_', ' ')}{' ' + m['task'] if m['task'] else ''})",
                              "body": m["reason"], "actions": [
                                  {"label": "Approve change", "op": "plan.amend_decide", "params": {"id": m["id"], "decision": "approve"}, "style": "primary"},
                                  {"label": "Reject", "op": "plan.amend_decide", "params": {"id": m["id"], "decision": "reject"}}]})
    for v in votes:
        if v["status"] == "tied":
            items.append({"key": f"vote:{v['id']}", "tone": "decide", "title": f"Tied vote: {v['topic']}",
                          "body": "The models are split. Read their reasons and choose.", "actions": [{"label": "Decide", "go": "alerts", "style": "primary"}]})
    for r in ctx.db.all("SELECT a.target, t.title FROM assignments a JOIN tasks t ON t.id = a.target WHERE a.seat = 'human' AND a.kind = 'review' AND a.status = 'open'"):
        items.append({"key": f"review:{r['target']}", "tone": "decide", "title": f"Review {r['target']}: {r['title']}",
                      "body": "No model from another company could review it, so it comes to you.",
                      "actions": [{"label": "Review", "go": f"reviews/{r['target']}", "style": "primary"}]})
    for q in ctx.db.all("SELECT * FROM level_requests WHERE status = 'pending' ORDER BY created_at"):
        items.append({"key": f"level:{q['id']}", "tone": "decide", "title": f"{q['seat']} asks for a {q['level']} review of {q['task']}",
                      "body": q["reason"], "actions": [
                          {"label": "Allow", "op": "review.level_decide", "params": {"id": q["id"], "decision": "approve"}, "style": "primary"},
                          {"label": "Keep current depth", "op": "review.level_decide", "params": {"id": q["id"], "decision": "deny"}}]})
    for t in tasks:
        if t["status"] == "merge_blocked":
            items.append({"key": f"merge:{t['id']}", "tone": "warn", "title": f"{t['id']} is approved but cannot merge yet",
                          "body": t["merge_note"] or "Your main folder has changes or is on another branch.",
                          "actions": [{"label": "Try the merge again", "op": "task.merge", "params": {"task": t["id"]}, "style": "primary"},
                                      {"label": "Details", "go": f"tasks/{t['id']}"}]})
    backlog = [t for t in tasks if t["status"] == "backlog"]
    if backlog:
        items.append({"key": "backlog", "tone": "info", "title": f"{len(backlog)} new item{'s' if len(backlog) != 1 else ''} in the backlog",
                      "body": "Models filed work they found. Accept it, or cancel what you do not want.",
                      "actions": [{"label": "Open backlog", "go": "tasks/backlog", "style": "primary"}]})
    if not seats:
        items.append({"key": "no-seats", "tone": "info", "title": "Add the models that will work together",
                      "body": "Two or more, ideally from different companies, so they check each other.",
                      "actions": [{"label": "Add a model", "go": "models/add", "style": "primary"}]})
    elif not plan or plan["stage"] in ("done", "cancelled"):
        items.append({"key": "no-plan", "tone": "info", "title": "Give the models a goal",
                      "body": "They each write a plan without seeing the others', critique each other, and agree on one for you to lock.",
                      "actions": [{"label": "Start a plan", "go": "plan", "style": "primary"}]})
    never = [s["handle"] for s in seats if s["status"] == "active" and not s["joined_ever"]]
    if never and seats:
        items.append({"key": "not-started", "tone": "info", "title": f"Not started yet: {', '.join(never)}",
                      "body": "Each model works in its own app. Start it once and it joins the table.",
                      "actions": [{"label": "Start models", "go": "models", "style": "primary"}]})
    return items


def _getting_started(seats, plan, tasks) -> list[dict]:
    companies = {s["company"] for s in seats}
    return [
        {"title": "Add two or more models", "done": len(seats) >= 2,
         "hint": "From different companies if you can: they review each other." + ("" if len(companies) > 1 or not seats else " All yours are from one company so far.")},
        {"title": "Start each model in its app", "done": bool(seats) and all(s["joined_ever"] for s in seats if s["status"] == "active")},
        {"title": "Give them a goal", "done": plan is not None},
        {"title": "Lock the plan they agree on", "done": bool(plan and plan["stage"] in ("locked", "done"))},
        {"title": "Watch the first task get tested, reviewed and merged", "done": any(t["status"] == "done" for t in tasks)},
    ]


def _config(ctx) -> list[dict]:
    from . import config

    out = []
    for section, keys in config.SCHEMA.items():
        for key, (default, typ, desc) in keys.items():
            kind = "choice" if isinstance(typ, tuple) else {str: "text", int: "number", bool: "switch", "list[str]": "list"}.get(typ, "text")
            out.append({"key": f"{section}.{key}", "section": section, "value": ctx.cfg.get(section, key), "default": default,
                        "type": kind, "choices": list(typ) if isinstance(typ, tuple) else None, "desc": desc})
    return out


def _events(ctx, limit: int = 80, before: int | None = None, query: str | None = None, task: str | None = None) -> list[dict]:
    sql, args = "SELECT * FROM events WHERE 1=1", []
    if before:
        sql += " AND id < ?"
        args.append(int(before))
    if task:
        sql += " AND task = ?"
        args.append(str(task).upper())
    if query:
        sql += " AND (instr(lower(text), ?) > 0 OR lower(actor) = ?)"
        args += [str(query).lower(), str(query).lower()]
    rows = ctx.db.all(sql + " ORDER BY id DESC LIMIT ?", (*args, int(limit)))
    return [{"id": e["id"], "at": util.local_hm(e["at"]), "day": util.parse_time(e["at"]).astimezone().strftime("%a %d %b"),
             "actor": e["actor"], "type": e["type"], "text": e["text"], "task": e["task"] or "", "level": e["level"]} for e in rows]


def build(ctx) -> dict[str, Any]:
    from . import appsetup, gitops, usage

    seats = _seats(ctx)
    plan = _plan(ctx)
    tasks = _tasks(ctx)
    alerts = _alerts(ctx)
    votes = _votes(ctx)
    needs = _needs(ctx, plan, tasks, alerts, votes, seats)
    memories = [{"id": m["id"], "text": m["text"], "author": m["author"], "tags": util.jload(m["tags"], []), "pinned": bool(m["pinned"]),
                 "at": _ago(m["created_at"])}
                 for m in ctx.db.all("SELECT * FROM memories WHERE status = 'active' ORDER BY pinned DESC, created_at DESC")]
    reviews_for_you = [{"task": r["target"], "title": r["title"], "level": r["level"] or "mid"} for r in ctx.db.all(
        "SELECT a.target, t.title, (SELECT level FROM reviews WHERE task = a.target AND reviewer = 'human' ORDER BY created_at DESC LIMIT 1) AS level "
        "FROM assignments a JOIN tasks t ON t.id = a.target WHERE a.seat = 'human' AND a.kind = 'review' AND a.status = 'open'")]
    level_requests = [dict(q) for q in ctx.db.all("SELECT id, task, seat, level, reason FROM level_requests WHERE status = 'pending'")]
    git = gitops.is_git(ctx)
    return {
        "mode": "project",
        "project": {
            "name": ctx.setting("project", "name") or ctx.root.name, "root": str(ctx.root), "home": str(ctx.home), "git": git,
            "main_branch": ctx.setting("project", "main_branch") or "", "worktrees": gitops.uses_worktrees(ctx),
            "review": ctx.setting("review", "level"), "frozen": ctx.db.meta_get("frozen") == "1",
            "frozen_reason": ctx.db.meta_get("frozen_reason") or "", "version": __version__,
            "terminal": _probe("terminal"), "vscode": _probe("vscode"), "connected": appsetup.connected(ctx),
        },
        "apps": [{"key": a.key, "label": a.label, "company": a.company, "start": a.start, "coding": a.coding, "connect": a.connect}
                 for a in apps.APPS.values()],
        "companies": list(apps.COMPANIES), "models": apps.MODEL_SUGGESTIONS,
        "seats": seats, "plan": plan, "tasks": tasks, "alerts": alerts, "votes": votes, "memories": memories,
        "reviews": reviews_for_you, "level_requests": level_requests, "needs": needs,
        "getting_started": _getting_started(seats, plan, tasks),
        "events": _events(ctx), "config": _config(ctx),
        "overhead_tokens": usage.tool_overhead_tokens(),
        "counts": {"needs": sum(1 for n in needs if n["tone"] in ("decide", "stop", "warn")), "alerts": len(alerts),
                   "reviews": len(reviews_for_you) + len(level_requests), "backlog": sum(1 for t in tasks if t["status"] == "backlog")},
    }


def task_detail(ctx, task_id: str) -> dict[str, Any]:
    from . import gitops, tasks

    t = tasks.get(ctx, task_id)
    data = next((x for x in _tasks(ctx) if x["id"] == t["id"]), {})
    data["detail"] = t["detail"]
    data["links"] = tasks.links_of(ctx, t["id"])
    data["children"] = [dict(r) for r in ctx.db.all("SELECT id, title, status FROM tasks WHERE parent = ? ORDER BY priority, seq", (t["id"],))]
    data["checkpoints"] = [{"id": c["id"], "seat": c["seat"], "line": c["l0"], "summary": c["l1"], "at": _ago(c["at"]),
                            "files": util.jload(c["files"], []), "added": c["added"], "removed": c["removed"]}
                           for c in ctx.db.all("SELECT * FROM checkpoints WHERE task = ? ORDER BY at DESC LIMIT 20", (t["id"],))]
    data["proofs"] = [{"id": p["id"], "status": p["status"], "exit": p["exit_code"], "failed": p["failed_cmd"] or "", "output": p["output_tail"] or "",
                       "at": _ago(p["created_at"]), "by": p["seat"]}
                      for p in ctx.db.all("SELECT * FROM proof_runs WHERE task = ? ORDER BY created_at DESC LIMIT 5", (t["id"],))]
    data["reviews"] = [{"id": r["id"], "reviewer": r["reviewer"], "level": r["level"], "round": r["round"], "verdict": r["verdict"],
                        "points": util.jload(r["points"], []), "tokens": r["est_tokens"]}
                       for r in ctx.db.all("SELECT * FROM reviews WHERE task = ? ORDER BY created_at", (t["id"],))]
    data["comments"] = [{"id": c["id"], "file": c["file"], "line": c["line"], "text": c["text"], "resolved": bool(c["resolved"]), "reply": c["reply"] or ""}
                        for c in ctx.db.all("SELECT * FROM line_comments WHERE task = ? ORDER BY id", (t["id"],))]
    data["events"] = _events(ctx, limit=30, task=t["id"])
    data["changed"] = []
    if gitops.is_git(ctx) and t["status"] not in ("backlog", "open", "ready"):
        try:
            data["changed"] = gitops.changed_files(ctx, t)
        except Exception:
            data["changed"] = []
    return data


def diff(ctx, task_id: str, max_lines: int = 4000) -> dict[str, Any]:
    from . import gitops, tasks

    t = tasks.get(ctx, task_id)
    if not gitops.is_git(ctx):
        return {"task": t["id"], "diff": "", "note": "This project has no git, so there is no diff to show."}
    try:
        text = gitops.diff_text(ctx, t, max_lines=max_lines)
    except Exception as exc:  # noqa: BLE001 - shown to the human as a note
        return {"task": t["id"], "diff": "", "note": f"Could not read the changes: {exc}"}
    return {"task": t["id"], "diff": text, "note": "" if text.strip() else "No changes on this task's branch."}


def setup_state(folder) -> dict[str, Any]:
    """For a folder without a Roundtable project: what `Set up` would do there."""
    from pathlib import Path

    from . import project
    from .paths import recent_projects

    folder = Path(folder).expanduser().resolve()
    info: dict[str, Any] = {"folder": str(folder), "exists": folder.is_dir(), "name": folder.name}
    if folder.is_dir():
        g = project.detect_git(folder)
        info["git"] = bool(g.get("git"))
        info["has_commits"] = bool(g.get("has_commits"))
        info["branch"] = g.get("branch") or ""
        info["worktree_of"] = g.get("worktree_of") or ""
        info["toplevel"] = g.get("toplevel") or ""
        info["inside"] = bool(g.get("git") and g.get("toplevel") and Path(g["toplevel"]) != folder and not g.get("worktree_of"))
    return {"mode": "setup", "version": __version__, "setup": info, "recent": recent_projects()}

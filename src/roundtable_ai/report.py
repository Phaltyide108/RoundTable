"""Overviews for the human: rt status, STATUS.md, JSONL exports."""

from __future__ import annotations

import json
from pathlib import Path

from . import util


def waiting_on_human(ctx) -> list[str]:
    items = []
    plan = ctx.db.one("SELECT * FROM plans WHERE stage NOT IN ('done','cancelled','locked') ORDER BY id DESC LIMIT 1")
    if plan and plan["stage"] == "awaiting_human":
        items.append(f"plan P{plan['id']} is ready to lock: rt plan lock")
    if plan and plan["stage"] == "drafting":
        age = util.seconds_since(plan["stage_changed_at"]) or 0
        if age > ctx.setting("planning", "draft_timeout_minutes") * 60:
            items.append(f"plan P{plan['id']}: drafts overdue; continue without them? rt plan continue")
    for v in ctx.db.all("SELECT id, topic FROM votes WHERE status = 'tied'"):
        items.append(f"vote {v['id']} is tied: {util.one_line(v['topic'], 50)} · rt vote decide {v['id']} <option>")
    for t in ctx.db.all("SELECT id FROM tasks WHERE status = 'merge_blocked'"):
        items.append(f"{t['id']} waits to merge: rt task merge {t['id']}")
    for a in ctx.db.all("SELECT target FROM assignments WHERE seat = 'human' AND status = 'open' AND kind = 'review'"):
        items.append(f"review {a['target']} (no seat could): rt review submit {a['target']} approve|changes")
    for q in ctx.db.all("SELECT id, task, level, seat FROM level_requests WHERE status = 'pending'"):
        items.append(f"{q['seat']} asks for {q['level']} review on {q['task']}: rt review level-decide {q['id']} approve|deny")
    for m in ctx.db.all("SELECT id, kind, task FROM amendments WHERE status = 'pending' AND instr(needs, '\"human\"') > 0"):
        items.append(f"amendment {m['id']} ({m['kind']} {m['task'] or ''}) needs you: rt plan amend-decide {m['id']} approve|reject")
    for a in ctx.db.all("SELECT id, level, title FROM alerts WHERE status != 'resolved' AND level >= 4"):
        items.append(f"alert {a['id']} L{a['level']}: {util.one_line(a['title'], 50)} · rt alert show {a['id']}")
    for a in ctx.db.all("SELECT id, title, proposed_level FROM alerts WHERE status != 'resolved' AND proposed_level IS NOT NULL"):
        items.append(f"alert {a['id']}: level change to {a['proposed_level']} proposed · rt alert set-level {a['id']} <level>")
    return items


def status_text(ctx) -> str:
    from .seats import is_live

    name = ctx.setting("project", "name") or ctx.root.name
    lines = [f"{name} · review depth {ctx.setting('review', 'level')}" + (" · STOPPED: " + (ctx.db.meta_get("frozen_reason") or "") if ctx.db.meta_get("frozen") == "1" else "")]
    plan = ctx.db.one("SELECT * FROM plans ORDER BY id DESC LIMIT 1")
    if plan:
        lines.append(f"plan P{plan['id']} [{plan['stage']}]: {util.one_line(plan['goal'], 70)}")
    else:
        lines.append('no plan yet: rt goal "what you want built"')
    seats = ctx.db.all("SELECT * FROM seats WHERE status != 'removed' ORDER BY created_at")
    if seats:
        lines.append("seats:")
        for s in seats:
            state = "paused" if s["status"] == "paused" else ("live" if is_live(ctx, s) else f"idle, seen {util.human_ago(s['last_seen'])}")
            doing = f" · {s['now_doing']}" if s["now_doing"] else ""
            lines.append(f"  {s['handle']:<10} {s['model']} ({s['app']}) · {state}{doing}")
    else:
        lines.append("no seats: rt seat add <name> --model <model id> --app claude-code|codex-cli|claude-app|codex-app")
    by = {}
    for t in ctx.db.all("SELECT id, status FROM tasks ORDER BY seq, id"):
        by.setdefault(t["status"], []).append(t["id"])
    if by:
        order = ("claimed", "proving", "in_review", "changes_requested", "merge_blocked", "ready", "open", "done", "cancelled")
        lines.append("tasks: " + " · ".join(f"{s} {len(by[s])} ({', '.join(by[s][:6])}{' …' if len(by[s]) > 6 else ''})" for s in order if s in by))
    alerts = ctx.db.all("SELECT id, level, title FROM alerts WHERE status != 'resolved' ORDER BY level DESC")
    if alerts:
        lines.append("alerts: " + "; ".join(f"{a['id']} L{a['level']} {util.one_line(a['title'], 40)}" for a in alerts[:5]))
    waiting = waiting_on_human(ctx)
    lines.append("waiting on you: " + ("none" if not waiting else ""))
    lines += [f"  {w}" for w in waiting]
    return "\n".join(lines)


def write_status_md(ctx) -> Path:
    path = ctx.home / "STATUS.md"
    body = f"# Roundtable status\n\nUpdated {util.local_hm(util.now())} (local time).\n\n```text\n{status_text(ctx)}\n```\n"
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(path)
    return path


def export_jsonl(ctx) -> Path:
    out = ctx.home / "export"
    out.mkdir(exist_ok=True)
    for table in ("events", "tasks", "alerts", "suggestions", "reviews", "plans", "votes"):
        rows = ctx.db.all(f"SELECT * FROM {table}")
        tmp = out / f"{table}.jsonl.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps({k: r[k] for k in r.keys()}, ensure_ascii=False) + "\n")
        tmp.replace(out / f"{table}.jsonl")
    return out

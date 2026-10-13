"""The human's controls: stop/resume everything, settings, status, history."""

from __future__ import annotations

from . import config, events, report, util
from .errors import INVALID, RTError
from .registry import HUMAN, Param, Result, op


@op("admin.freeze", who=HUMAN, desc="Stop all seats until you unfreeze", params=[Param("reason", default="")])
def freeze(ctx, reason="") -> Result:
    with ctx.tx():
        ctx.db.meta_set("frozen", "1")
        ctx.db.meta_set("frozen_reason", util.one_line(reason or "paused by the human", 120))
        events.emit(ctx, "human.freeze", "the human stopped all work" + (f": {util.one_line(reason, 80)}" if reason else ""), level=5)
    return Result("all seats stopped: every call they make now returns STOP. Resume with: rt unfreeze")


@op("admin.unfreeze", who=HUMAN, desc="Let seats work again")
def unfreeze(ctx) -> Result:
    with ctx.tx():
        ctx.db.meta_set("frozen", "0")
        ctx.db.meta_set("frozen_reason", "")
        events.emit(ctx, "human.unfreeze", "the human resumed work: carry on (rt_sync first)")
    return Result("seats can work again")


@op("admin.config_show", who=HUMAN, desc="Show all settings")
def config_show(ctx) -> Result:
    lines = []
    for section, keys in config.SCHEMA.items():
        for key, (default, _t, desc) in keys.items():
            value = ctx.cfg.get(section, key)
            mark = "" if value == default else "  (changed)"
            lines.append(f"{section}.{key} = {config.toml_value(value)}{mark}   # {desc}")
    return Result("\n".join(lines), {"config": ctx.cfg.data})


@op("admin.config_set", who=HUMAN, desc="Change a setting", params=[Param("key", required=True), Param("value", required=True)])
def config_set(ctx, key, value) -> Result:
    section, name = config.split_key(key)
    new = config.set_value(ctx.cfg.path, key, value)
    old = ctx.cfg.get(section, name)
    ctx.cfg.data[section][name] = new
    with ctx.tx():  # broadcast: every digest shows human.* events, but nobody is forced to sync first
        events.emit(ctx, "human.config", f"the human set {key} = {config.toml_value(new)} (was {config.toml_value(old)})")
    return Result(f"{key} = {config.toml_value(new)}")


@op("admin.status", who=HUMAN, desc="Overview for the human")
def status(ctx) -> Result:
    try:
        report.write_status_md(ctx)
    except OSError:
        pass
    return Result(report.status_text(ctx))


@op("admin.export", who=HUMAN, desc="Write JSONL snapshots to .roundtable/export")
def export(ctx) -> Result:
    out = report.export_jsonl(ctx)
    return Result(f"exported to {out}")


@op("admin.log", who=HUMAN, desc="History of events",
    params=[Param("since", desc="event id or HH:MM (today, local time)"), Param("limit", type="int", default=50),
            Param("task", desc="only this task")])
def log(ctx, since=None, limit=50, task=None) -> Result:
    where, args = [], []
    if since:
        s = str(since).strip()
        if s.isdigit():
            where.append("id > ?")
            args.append(int(s))
        elif len(s) == 5 and s[2] == ":":
            from datetime import datetime, timezone

            try:
                hh, mm = int(s[:2]), int(s[3:])
                local = datetime.now().astimezone().replace(hour=hh, minute=mm, second=0, microsecond=0)
            except ValueError:
                raise RTError(INVALID, f"bad time {s!r}", "use HH:MM, e.g. 14:39") from None
            where.append("at >= ?")
            args.append(local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
        else:
            raise RTError(INVALID, f"since must be an event id or HH:MM (got {s!r})")
    if task:
        where.append("task = ?")
        args.append(str(task).strip().upper())
    sql = "SELECT * FROM events" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC LIMIT ?"
    rows = list(reversed(ctx.db.all(sql, (*args, max(1, min(int(limit), 1000))))))
    if not rows:
        return Result("no events")
    return Result("\n".join(f"#{e['id']} {util.local_hm(e['at'])} {e['actor']:<8} {e['text']}" for e in rows),
                  {"events": [dict(e) for e in rows]})


CHATTER = ("task.checkpoint", "task.claimed", "task.proving", "task.ready", "review.assigned", "lease.released", "seat.joined")


@op("admin.compact", who=HUMAN, desc="Shrink old history: keep each finished task's outcome, drop step-by-step detail",
    params=[Param("days", type="int", desc="only work finished more than this many days ago (default: history.keep_days)")])
def compact(ctx, days=None) -> Result:
    import os

    keep = int(days if days not in (None, "") else ctx.setting("history", "keep_days"))
    if keep < 0:
        raise RTError(INVALID, "days cannot be negative")
    cutoff = util.ago_iso(keep * 86400)
    db_file = ctx.db.path
    before = os.path.getsize(db_file) if db_file.exists() else 0
    with ctx.tx():
        old = [r["id"] for r in ctx.db.all("SELECT id FROM tasks WHERE status IN ('done','cancelled') AND updated_at < ?", (cutoff,))]
        removed = {"events": 0, "checkpoints": 0, "proof outputs": 0}
        for tid in old:
            cur = ctx.db.execute(f"DELETE FROM events WHERE task = ? AND type IN ({','.join('?' * len(CHATTER))})", (tid, *CHATTER))
            removed["events"] += cur.rowcount or 0
            last = ctx.db.one("SELECT id FROM checkpoints WHERE task = ? ORDER BY at DESC LIMIT 1", (tid,))
            if last:
                cur = ctx.db.execute("DELETE FROM checkpoints WHERE task = ? AND id != ?", (tid, last["id"]))
                removed["checkpoints"] += cur.rowcount or 0
            cur = ctx.db.execute("UPDATE proof_runs SET output_tail = NULL WHERE task = ? AND output_tail IS NOT NULL AND status = 'passed'", (tid,))
            removed["proof outputs"] += cur.rowcount or 0
        cur = ctx.db.execute(f"DELETE FROM events WHERE task IS NULL AND at < ? AND type IN ({','.join('?' * len(CHATTER))})", (cutoff, *CHATTER))
        removed["events"] += cur.rowcount or 0
        events.emit(ctx, "human.compact", f"the human compacted history of {len(old)} finished task(s) older than {keep} days")
    try:
        ctx.db.conn.execute("VACUUM")
    except Exception:  # another process holds the database: space is reclaimed next time
        pass
    after = os.path.getsize(db_file) if db_file.exists() else 0
    parts = ", ".join(f"{n} {k}" for k, n in removed.items())
    return Result(f"compacted {len(old)} finished task(s): removed {parts}; database {before // 1024} KB -> {after // 1024} KB",
                  {"tasks": old, "removed": removed, "kb_before": before // 1024, "kb_after": after // 1024})

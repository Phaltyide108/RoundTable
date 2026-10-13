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
    with ctx.tx():
        aud = None
        if key == "review.level":
            aud = [r["handle"] for r in ctx.db.all("SELECT handle FROM seats WHERE status = 'active'")]
        events.emit(ctx, "human.config", f"the human set {key} = {config.toml_value(new)} (was {config.toml_value(old)})", audience=aud)
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

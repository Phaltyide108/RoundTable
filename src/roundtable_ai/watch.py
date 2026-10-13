"""`rt watch`: the part that keeps time, because models only act when started.

Every few seconds it: expires stale leases, cleans up dead proof runs,
notifies the human (once per item) about anything waiting on them, wakes
command-line seats for critical alerts (rate limited), retries blocked
merges, and refreshes STATUS.md. One failing step never stops the loop.
"""

from __future__ import annotations

import time
import traceback

from . import notify, util
from .context import open_ctx


def _notice_once(ctx, key: str, title: str, body: str) -> bool:
    if ctx.db.one("SELECT 1 FROM notices WHERE key = ?", (key,)):
        return False
    with ctx.tx():
        ctx.db.execute("INSERT OR IGNORE INTO notices(key, at) VALUES (?, ?)", (key, util.now()))
    notify.send(title, body, home=ctx.home)
    return True


def collect(ctx) -> list[tuple[str, str, str]]:
    """(key, title, body) for everything the human should hear about."""
    items = []
    stuck = ctx.setting("watch", "stuck_minutes") * 60
    for a in ctx.db.all("SELECT * FROM alerts WHERE status != 'resolved' AND level >= 4"):
        items.append((f"alert:{a['id']}:{a['level']}", f"Roundtable: L{a['level']} alert {a['id']}", f"{a['title']} (by {a['raised_by']}) · rt alert show {a['id']}"))
    p = ctx.db.one("SELECT * FROM plans WHERE stage NOT IN ('done','cancelled','locked') ORDER BY id DESC LIMIT 1")
    if p is not None:
        if p["stage"] == "awaiting_human":
            items.append((f"plan:{p['id']}:v{p['version']}:awaiting", "Roundtable: plan ready", f"P{p['id']} is ready for you to lock: rt plan lock"))
        if p["stage"] == "drafting" and (util.seconds_since(p["stage_changed_at"]) or 0) > ctx.setting("planning", "draft_timeout_minutes") * 60:
            items.append((f"plan:{p['id']}:draft-timeout", "Roundtable: drafts overdue", f"P{p['id']}: some planners have not drafted. Wait, or: rt plan continue"))
    for v in ctx.db.all("SELECT * FROM votes WHERE status = 'tied'"):
        items.append((f"vote:{v['id']}:tied", "Roundtable: tied vote", f"{v['id']}: {util.one_line(v['topic'], 80)} · rt vote decide {v['id']} <choice>"))
    for t in ctx.db.all("SELECT * FROM tasks WHERE status = 'merge_blocked'"):
        items.append((f"task:{t['id']}:merge_blocked:{t['commit_sha']}", f"Roundtable: {t['id']} waits to merge", "rt task merge (see rt status for why)"))
    for a in ctx.db.all("SELECT * FROM assignments WHERE seat = 'human' AND status = 'open'"):
        items.append((f"review:{a['target']}:{a['round']}", f"Roundtable: review {a['target']}", f"no seat could review it: rt review get {a['target']}"))
    for q in ctx.db.all("SELECT * FROM level_requests WHERE status = 'pending'"):
        items.append((f"levelreq:{q['id']}", "Roundtable: deeper review?", f"{q['seat']} asks for {q['level']} review on {q['task']}: rt review level-decide {q['id']} approve|deny"))
    for m in ctx.db.all("SELECT * FROM amendments WHERE status = 'pending' AND needs LIKE '%\"human\"%'"):
        items.append((f"amend:{m['id']}", "Roundtable: plan change needs you", f"{m['id']} {m['kind']} {m['task'] or ''}: rt plan amend-decide {m['id']} approve|reject"))
    for t in ctx.db.all("SELECT * FROM tasks WHERE status IN ('claimed','changes_requested')"):
        last = ctx.db.one("SELECT id, at FROM events WHERE task = ? ORDER BY id DESC LIMIT 1", (t["id"],))
        if last and (util.seconds_since(last["at"]) or 0) > stuck:
            items.append((f"stuck:{t['id']}:{last['id']}", f"Roundtable: {t['id']} looks stuck",
                          f"{t['owner']} has not updated it for {ctx.setting('watch', 'stuck_minutes')}+ min"))
    for a in ctx.db.all("SELECT * FROM assignments WHERE status = 'open' AND seat != 'human'"):
        if (util.seconds_since(a["created_at"]) or 0) > stuck:
            items.append((f"assign:{a['id']}", f"Roundtable: {a['kind']} waiting", f"{a['seat']} has not done its {a['kind']} of {a['target']}; open its app and say 'check Roundtable'"))
    return items


def wake(ctx) -> list[str]:
    """Start background runs of command-line seats that must react to critical alerts."""
    from . import launch, seats

    started = []
    level = ctx.setting("watch", "wake_level")
    window = ctx.setting("watch", "wake_min_interval_minutes") * 60
    for a in ctx.db.all("SELECT * FROM alerts WHERE status = 'open' AND level >= ?", (level,)):
        acked = {r["seat"] for r in ctx.db.all("SELECT seat FROM alert_acks WHERE alert_id = ?", (a["id"],))}
        for h in util.jload(a["must_ack"], []):
            if h in acked:
                continue
            row = ctx.db.one("SELECT * FROM seats WHERE handle = ? AND status = 'active'", (h,))
            if row is None or row["app"] not in ("claude-code", "codex-cli") or seats.is_live(ctx, row):
                continue
            last = ctx.db.one("SELECT at FROM wakeups WHERE seat = ? ORDER BY id DESC LIMIT 1", (h,))
            if last and (util.seconds_since(last["at"]) or 0) < window:
                continue
            prompt = f"You are Roundtable seat {h}. Call rt_sync now, then read and acknowledge alert {a['id']} (rt_alert show, rt_alert ack) and handle it."
            try:
                pid = launch.start_headless(ctx, row, prompt, ctx.home / "logs" / f"wake-{h}.log")
            except Exception as exc:
                notify.send(f"Roundtable: could not wake {h}", str(exc), home=ctx.home)
                pid = None
            with ctx.tx():
                ctx.db.execute("INSERT INTO wakeups(seat, reason, ref, pid, at) VALUES (?,?,?,?,?)", (h, f"alert L{a['level']}", a["id"], pid, util.now()))
            if pid:
                started.append(h)
    return started


def tick(ctx, state: dict) -> list[str]:
    from . import dispatch, proofs, report, tasks

    done = []
    steps = [
        ("housekeeping", lambda: dispatch.housekeeping(ctx, None)),
        ("proofs", lambda: proofs.check_stale(ctx)),
        ("notify", lambda: [done.append(k) for k, t, b in collect(ctx) if _notice_once(ctx, k, t, b)]),
        ("wake", lambda: done.extend(f"woke {h}" for h in wake(ctx))),
        ("status", lambda: report.write_status_md(ctx)),
    ]
    now = time.monotonic()
    if now - state.get("merge_at", 0) > 60:
        state["merge_at"] = now
        steps.append(("merge", lambda: [tasks.complete(ctx, t["id"]) for t in ctx.db.all("SELECT id FROM tasks WHERE status = 'merge_blocked'")]))
    for name, fn in steps:
        try:
            fn()
        except Exception:
            try:
                with open(ctx.home / "logs" / "watch.log", "a", encoding="utf-8") as fh:
                    fh.write(f"{util.now()} step {name} failed:\n{traceback.format_exc()}\n")
            except OSError:
                pass
    return done


def watch(home: str | None = None, *, once: bool = False, interval: int = 15) -> int:
    ctx = open_ctx(home, actor="system", client="watch")
    state: dict = {}
    print(f"watching {ctx.root} (Ctrl+C to stop) · notifications for alerts, decisions and stuck work")
    from . import config as config_mod
    from .paths import config_path

    try:
        while True:
            try:
                ctx.cfg = config_mod.load(config_path(ctx.home))  # pick up `rt config set` changes
            except Exception:
                pass  # keep the last good settings
            for item in tick(ctx, state):
                print(f"{util.local_hm(util.now())} {item}")
            if once:
                return 0
            time.sleep(max(2, interval))
    except KeyboardInterrupt:
        print("stopped watching")
        return 0
    finally:
        ctx.close()

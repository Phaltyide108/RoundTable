"""The single entry point for every operation (CLI, MCP server, dashboard).

call() does, in order:
1. find the operation and the project
2. work out who is acting (human, or which seat) and check they may
3. housekeeping: expire leases of inactive seats, renew the caller's leases,
   mark the caller as seen
4. refuse with STOP while work is frozen or a level-5 alert is unacknowledged
5. validate parameters and run the handler
6. start a seat's reply with its one-line inbox

Unexpected exceptions are logged to .roundtable/logs/errors.log and turned
into a clear INTERNAL error, so a bug never crashes a model's session.
"""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any

from . import inbox, registry, seats, util
from .context import HUMAN, SYSTEM, Ctx, open_ctx
from .errors import FORBIDDEN, INTERNAL, NOT_FOUND, STATE, STOP, RTError
from .registry import OPS, Result


def housekeeping(ctx: Ctx, handle: str | None) -> None:
    """Cheap, idempotent upkeep run before operations."""
    now = util.now()
    ttl = ctx.setting("leases", "ttl_minutes") * 60
    with ctx.tx():
        # Leases only expire while their task is actively being worked on.
        # Tasks waiting on proof/review/merge keep their files parked.
        stale = ctx.db.all(
            "SELECT l.id, l.seat, l.pattern, l.task FROM leases l LEFT JOIN tasks t ON t.id = l.task "
            "WHERE l.state = 'active' AND l.expires_at < ? AND (t.status IS NULL OR t.status IN ('claimed','changes_requested'))",
            (now,),
        )
        if stale:
            ids = [r["id"] for r in stale]
            ctx.db.execute(
                f"UPDATE leases SET state = 'expired', ended_at = ? WHERE id IN ({','.join('?' * len(ids))})", (now, *ids)
            )
            from . import events

            by_seat: dict[str, list[str]] = {}
            for r in stale:
                by_seat.setdefault(r["seat"], []).append(r["pattern"])
            for seat, pats in by_seat.items():
                events.emit(
                    ctx, "lease.expired",
                    f"{seat}'s leases expired after inactivity: {', '.join(pats[:5])}{' …' if len(pats) > 5 else ''}",
                    actor=SYSTEM, files=pats, audience=[seat],
                )
        if handle:
            ctx.db.execute(
                "UPDATE leases SET renewed_at = ?, expires_at = ? WHERE seat = ? AND state = 'active'",
                (now, util.add_seconds(now, ttl), handle),
            )
            seats.touch(ctx, handle)


def _meter(ctx: Ctx, handle: str, name: str, params: Any, text: str, ok: bool) -> None:
    """Record what this call cost in characters (models pay ~1 token per 4)."""
    if ctx.client != "mcp":
        return
    try:
        import json

        from .usage import record_exchange

        record_exchange(ctx, handle, name, len(json.dumps(params or {}, ensure_ascii=False, default=str)), len(text or ""), ok)
    except Exception:
        pass


def _log_internal(ctx: Ctx | None, name: str) -> str:
    tb = traceback.format_exc()
    if ctx is not None:
        try:
            logdir = ctx.home / "logs"
            logdir.mkdir(exist_ok=True)
            with open(logdir / "errors.log", "a", encoding="utf-8") as fh:
                fh.write(f"--- {util.now()} {name} actor={ctx.actor}\n{tb}\n")
            return str(logdir / "errors.log")
        except OSError:
            pass
    return "(log unavailable)"


def call(
    name: str,
    params: dict[str, Any] | None = None,
    *,
    home: str | Path | None = None,
    seat: str | None = None,
    key: str | None = None,
    pinned: bool = False,
    as_human: bool | None = None,
    client: str = "cli",
    ctx: Ctx | None = None,
) -> Result:
    """Run one operation.

    as_human: True for CLI/dashboard callers acting as the human. When None,
    the caller is the human unless a seat or key is given.
    """
    registry.load_all()
    o = OPS.get(name)
    if o is None:
        raise RTError(NOT_FOUND, f"unknown operation {name!r}")
    own_ctx = ctx is None
    if ctx is None:
        ctx = open_ctx(home, client=client)
    else:
        ctx.client = client or ctx.client
    if as_human is None:
        as_human = not (seat or key)
    handle: str | None = None
    try:
        if as_human:
            if o.who == registry.SEAT:
                raise RTError(
                    FORBIDDEN, f"{name} is done by a seat (a model), not by the human",
                    "to act as a seat from the command line: rt --seat <name> ...",
                )
            ctx.actor = HUMAN
        else:
            if o.who == registry.HUMAN:
                raise RTError(FORBIDDEN, f"only the human can do {name}", "ask the human to run it with the rt command or the dashboard")
            if name == "seat.join":
                ctx.actor = SYSTEM
            else:
                handle = seats.resolve(ctx, seat, key, pinned=pinned)
                row = seats.get(ctx, handle)
                if row["status"] == "paused":
                    raise RTError(STATE, f"seat {handle} is paused by the human", f"wait, or ask the human to run `rt seat resume {handle}`")
                ctx.actor = handle

        if o.housekeeping:
            housekeeping(ctx, handle)

        if handle and not o.frozen_ok:
            if ctx.db.meta_get("frozen", "0") == "1":
                reason = ctx.db.meta_get("frozen_reason", "") or "no reason given"
                raise RTError(STOP, f"STOP: the human paused all work ({reason})", "do nothing else; call rt_sync later to check")
            l5 = inbox.unacked_alerts(ctx, handle, 5)
            if l5:
                a = l5[0]
                raise RTError(
                    STOP, f"STOP: level-5 alert {a['id']}: {a['title']}",
                    f'read it (rt_alert show id="{a["id"]}") and acknowledge it (rt_alert ack id="{a["id"]}") before anything else',
                )

        clean = registry.coerce_params(o, params or {})
        result = o.func(ctx, **clean)
        if not isinstance(result, Result):  # defensive: handlers must return Result
            result = Result(str(result))
        if ctx.notes:
            result.text = result.text + "\n" + "\n".join(ctx.notes)
            ctx.notes.clear()
        if name == "seat.join" and result.data.get("handle"):
            handle = result.data["handle"]
        if handle:
            try:
                result.text = inbox.line(ctx, handle) + "\n" + result.text
            except Exception:  # never let the inbox line break a reply
                pass
            _meter(ctx, handle, name, params, result.text, True)
        return result
    except RTError as exc:
        if handle:
            try:
                exc.inbox = inbox.line(ctx, handle)  # type: ignore[attr-defined]
            except Exception:
                pass
            _meter(ctx, handle, name, params, exc.render(), False)
        raise
    except Exception as exc:  # a bug: log it, explain it, keep the session alive
        where = _log_internal(ctx, name)
        raise RTError(
            INTERNAL,
            f"unexpected error in {name}: {type(exc).__name__}: {exc}",
            f"run `rt status` to see the current state. Details saved in {where}; please report it.",
        ) from exc
    finally:
        if own_ctx:
            ctx.close()

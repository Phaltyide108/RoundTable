"""The `rt` command (also `roundtable`).

Every command maps to a registered operation and goes through
dispatch.call, so the CLI, the dashboard and the models share one set of
rules and messages. Exit codes: 0 ok, 1 refused (RTError), 2 usage, 3 bug.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from . import __version__
from .errors import INTERNAL, RTError

GETTING_STARTED = """Roundtable {version}: several AI models plan, build and review one project together.

Getting started (in your project's main folder, a git repo with at least one commit):
  rt init                                                   set up this project
  rt seat add opus --model claude-opus-5-5 --app claude-code
  rt seat add sol --model gpt-5.6-sol --app codex-cli       add as many seats as you like
  rt setup claude-code   /   rt setup codex   /   rt setup claude-app
  rt launch opus         (in one terminal)   rt launch sol   (in another)
  rt goal "what you want built"                             seats draft plans blind
  rt plan lock                                              after they agree; creates tasks
  rt status · rt watch · rt ui                              follow along

More: rt <command> --help, rt doctor if anything looks wrong.
"""


def _force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def _parse_kv(items: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in items:
        if "=" not in item:
            raise RTError("invalid", f"expected key=value, got {item!r}")
        k, v = item.split("=", 1)
        try:
            out[k.strip()] = json.loads(v)
        except json.JSONDecodeError:
            out[k.strip()] = v
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rt", description="Roundtable: AI models planning, building and reviewing one project together.")
    p.add_argument("--version", action="version", version=f"roundtable {__version__}")
    p.add_argument("--home", help="project folder or its .roundtable folder (default: search upward from here)")
    p.add_argument("--seat", help="act as this seat (for apps without MCP)")
    p.add_argument("--key", help="act as the seat that joined with this key")
    p.add_argument("--json", action="store_true", help="print JSON")
    sub = p.add_subparsers(dest="cmd", metavar="command")

    s = sub.add_parser("init", help="set up Roundtable in this project")
    s.add_argument("path", nargs="?", default=".")
    s.add_argument("--name")

    sub.add_parser("status", help="overview: plan, seats, tasks, what waits on you")
    s = sub.add_parser("log", help="history of events")
    s.add_argument("--since", help="event id or HH:MM")
    s.add_argument("--limit", type=int, default=50)
    s.add_argument("--task")

    seat = sub.add_parser("seat", help="manage seats (models)").add_subparsers(dest="sub", metavar="action")
    s = seat.add_parser("add", help="register a model as a seat")
    s.add_argument("handle")
    s.add_argument("--model", required=True, help="model id the app understands, e.g. claude-opus-5-5")
    s.add_argument("--app", required=True, choices=["claude-code", "claude-app", "codex-cli", "codex-app", "other"])
    s.add_argument("--company", help="anthropic, openai, google ... (guessed when omitted)")
    s.add_argument("--roles", help="comma list of plan,build,review (default all)")
    s.add_argument("--no-worktree", action="store_true", help="no separate working copy")
    seat.add_parser("list", help="list seats")
    for name, hlp in (("pause", "pause a seat"), ("resume", "resume a seat"), ("remove", "remove a seat"),
                      ("release", "free a seat whose chat was closed"), ("worktree", "create or repair its working copy")):
        seat.add_parser(name, help=hlp).add_argument("handle")

    s = sub.add_parser("goal", help="start a plan")
    s.add_argument("goal")
    s.add_argument("--planners", help="comma list of seats")
    s.add_argument("--review", choices=["low", "mid", "high"])

    plan = sub.add_parser("plan", help="the plan").add_subparsers(dest="sub", metavar="action")
    plan.add_parser("view", help="show the plan").add_argument("--draft")
    plan.add_parser("continue", help="move on without missing drafts/critiques")
    s = plan.add_parser("lock", help="approve the plan; creates tasks")
    s.add_argument("--force", action="store_true")
    s.add_argument("--draft", help="lock a draft directly")
    plan.add_parser("cancel", help="cancel the active plan").add_argument("reason")
    s = plan.add_parser("amend-decide", help="approve or reject an amendment")
    s.add_argument("id")
    s.add_argument("decision", choices=["approve", "reject"])

    task = sub.add_parser("task", help="tasks").add_subparsers(dest="sub", metavar="action")
    s = task.add_parser("show", help="show a task")
    s.add_argument("task")
    s.add_argument("--zoom", choices=["L0", "L1", "L2"], default="L2")
    s = task.add_parser("cancel", help="cancel a task")
    s.add_argument("task")
    s.add_argument("reason")
    s = task.add_parser("reassign", help="give a task to another seat")
    s.add_argument("task")
    s.add_argument("owner", nargs="?")
    task.add_parser("merge", help="retry merges").add_argument("task", nargs="?")
    s = task.add_parser("review-level", help="set one task's review depth")
    s.add_argument("task")
    s.add_argument("level", choices=["low", "mid", "high", "default"])

    review = sub.add_parser("review", help="reviews assigned to you (the human)").add_subparsers(dest="sub", metavar="action")
    review.add_parser("queue", help="reviews waiting for you")
    review.add_parser("get", help="read a task for review").add_argument("task")
    s = review.add_parser("submit", help="approve or request changes")
    s.add_argument("task")
    s.add_argument("verdict", choices=["approve", "changes"])
    s.add_argument("--point", action="append", default=[], help="repeatable")
    s = review.add_parser("level-decide", help="approve/deny a deeper-review request")
    s.add_argument("id")
    s.add_argument("decision", choices=["approve", "deny"])

    vote = sub.add_parser("vote", help="votes").add_subparsers(dest="sub", metavar="action")
    vote.add_parser("show", help="open votes, or one").add_argument("id", nargs="?")
    s = vote.add_parser("decide", help="decide a vote")
    s.add_argument("id")
    s.add_argument("choice")

    alert = sub.add_parser("alert", help="alerts").add_subparsers(dest="sub", metavar="action")
    alert.add_parser("list", help="open alerts").add_argument("--all", action="store_true")
    alert.add_parser("show", help="one alert").add_argument("id")
    s = alert.add_parser("raise", help="raise an alert yourself")
    s.add_argument("level", type=int, choices=[1, 2, 3, 4, 5])
    s.add_argument("title")
    s.add_argument("--description")
    s.add_argument("--evidence")
    s.add_argument("--files")
    s.add_argument("--tasks")
    s = alert.add_parser("resolve", help="close an alert")
    s.add_argument("id")
    s.add_argument("resolution")
    s = alert.add_parser("set-level", help="change an alert's level")
    s.add_argument("id")
    s.add_argument("level", type=int, choices=[1, 2, 3, 4, 5])

    sub.add_parser("freeze", help="stop all seats").add_argument("reason", nargs="?", default="")
    sub.add_parser("unfreeze", help="let seats work again")

    cfg = sub.add_parser("config", help="settings").add_subparsers(dest="sub", metavar="action")
    cfg.add_parser("show", help="all settings")
    s = cfg.add_parser("set", help="change one setting")
    s.add_argument("key")
    s.add_argument("value")

    sub.add_parser("export", help="write JSONL snapshots")

    s = sub.add_parser("setup", help="connect an app to this project")
    s.add_argument("app", choices=["claude-code", "claude-app", "codex"])
    s.add_argument("--dry-run", action="store_true", help="show what would change")
    s.add_argument("--remove", action="store_true", help="remove Roundtable's entry")

    s = sub.add_parser("launch", help="start a seat's app")
    s.add_argument("handle")
    s.add_argument("--print", action="store_true", dest="print_only", help="print the command instead of running it")

    sub.add_parser("doctor", help="check everything and suggest fixes")
    s = sub.add_parser("watch", help="notify you and wake seats when needed")
    s.add_argument("--once", action="store_true")
    s.add_argument("--interval", type=int, default=15)
    s = sub.add_parser("ui", help="local dashboard in your browser")
    s.add_argument("--port", type=int)
    s.add_argument("--no-open", action="store_true")
    sub.add_parser("mcp", help="run the MCP server (apps start this themselves)")
    s = sub.add_parser("call", help="run any operation: rt call task.show task=T3")
    s.add_argument("op")
    s.add_argument("params", nargs="*")
    sub.add_parser("version", help="print the version")
    return p


def _route(args) -> tuple[str, dict[str, Any]] | None:
    """Map parsed args to (operation, params). None = handled elsewhere."""
    c, s = args.cmd, getattr(args, "sub", None)
    if c == "status":
        return "admin.status", {}
    if c == "log":
        return "admin.log", {"since": args.since, "limit": args.limit, "task": args.task}
    if c == "seat":
        if s == "add":
            roles = [r.strip() for r in args.roles.split(",")] if args.roles else None
            return "seat.add", {"handle": args.handle, "model": args.model, "app": args.app, "company": args.company,
                                "roles": roles, "worktree": False if args.no_worktree else None}
        if s == "list":
            return "seat.list", {}
        if s in ("pause", "resume", "remove", "release", "worktree"):
            return f"seat.{s}", {"handle": args.handle}
    if c == "goal":
        planners = [x.strip() for x in args.planners.split(",")] if args.planners else None
        return "plan.goal", {"goal": args.goal, "planners": planners, "review": args.review}
    if c == "plan":
        if s == "view":
            return "plan.view", {"draft": args.draft}
        if s == "continue":
            return "plan.continue", {}
        if s == "lock":
            return "plan.lock", {"force": args.force, "draft": args.draft}
        if s == "cancel":
            return "plan.cancel", {"reason": args.reason}
        if s == "amend-decide":
            return "plan.amend_decide", {"id": args.id, "decision": args.decision}
    if c == "task":
        if s == "show":
            return "task.show", {"task": args.task, "zoom": args.zoom}
        if s == "cancel":
            return "task.cancel", {"task": args.task, "reason": args.reason}
        if s == "reassign":
            return "task.reassign", {"task": args.task, "owner": args.owner}
        if s == "merge":
            return "task.merge", {"task": args.task}
        if s == "review-level":
            return "task.set_review", {"task": args.task, "level": args.level}
    if c == "review":
        if s == "queue":
            return "review.queue", {}
        if s == "get":
            return "review.get", {"task": args.task}
        if s == "submit":
            return "review.submit", {"task": args.task, "verdict": args.verdict, "points": args.point or None}
        if s == "level-decide":
            return "review.level_decide", {"id": args.id, "decision": args.decision}
    if c == "vote":
        if s == "show":
            return "vote.show", {"id": args.id}
        if s == "decide":
            return "vote.decide", {"id": args.id, "choice": args.choice}
    if c == "alert":
        if s == "list":
            return "alert.list", {"all": args.all}
        if s == "show":
            return "alert.show", {"id": args.id}
        if s == "raise":
            return "alert.raise", {"level": args.level, "title": args.title, "description": args.description,
                                   "evidence": args.evidence, "files": args.files, "tasks": args.tasks}
        if s == "resolve":
            return "alert.resolve", {"id": args.id, "resolution": args.resolution}
        if s == "set-level":
            return "alert.set_level", {"id": args.id, "level": args.level}
    if c == "freeze":
        return "admin.freeze", {"reason": args.reason}
    if c == "unfreeze":
        return "admin.unfreeze", {}
    if c == "config":
        if s == "show":
            return "admin.config_show", {}
        if s == "set":
            return "admin.config_set", {"key": args.key, "value": args.value}
    if c == "export":
        return "admin.export", {}
    if c == "call":
        return args.op, _parse_kv(args.params)
    return None


def _seat_for_cwd(home: str | None) -> str | None:
    """If the current folder is inside a seat's working copy, return that seat.

    Commands run by a model from its own working copy therefore act as that
    seat, never as the human. (A guard against mix-ups, not a security wall:
    anything with shell access to your computer can do what you can.)
    """
    from pathlib import Path

    try:
        from .context import open_ctx

        ctx = open_ctx(home)
    except RTError:
        return None
    try:
        cwd = Path.cwd().resolve()
        for r in ctx.db.all("SELECT handle, worktree FROM seats WHERE worktree IS NOT NULL AND status != 'removed'"):
            wt = Path(r["worktree"]).resolve()
            if cwd == wt or wt in cwd.parents:
                return r["handle"]
        return None
    finally:
        ctx.close()


def _print(result_text: str, data: dict | None, as_json: bool) -> None:
    if as_json:
        print(json.dumps({"ok": True, "text": result_text, "data": data or {}}, ensure_ascii=False, indent=2, default=str))
    else:
        print(result_text)


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["_guard"]:
        from .guard import main as guard_main

        return guard_main(argv[1:])
    if argv[:1] == ["_proofrun"]:
        from .proofrun import main as pr_main

        return pr_main(argv[1:])
    parser = build_parser()
    if not argv:
        print(GETTING_STARTED.format(version=__version__))
        return 0
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0) if exc.code in (0, None) else 2
    if args.cmd is None:
        print(GETTING_STARTED.format(version=__version__))
        return 0
    if args.cmd in ("seat", "plan", "task", "review", "vote", "alert", "config") and not getattr(args, "sub", None):
        parser.parse_args([args.cmd, "--help"])
        return 2
    try:
        return _run(args)
    except RTError as exc:
        if args.json:
            print(json.dumps(exc.to_dict(), ensure_ascii=False, indent=2, default=str))
        else:
            inbox = getattr(exc, "inbox", None)
            if inbox:
                print(inbox, file=sys.stderr)
            print(exc.render(), file=sys.stderr)
        return 3 if exc.code == INTERNAL else 1
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)
        return 130


def _run(args) -> int:
    from . import dispatch

    if args.cmd == "version":
        print(f"roundtable {__version__}")
        return 0
    if args.cmd == "init":
        from .project import init_project

        home, report = init_project(args.path, args.name)
        _print("\n".join(report), {"home": str(home)}, args.json)
        return 0
    if args.cmd == "mcp":
        from .mcp_server import serve

        return serve(args.home)
    if args.cmd == "setup":
        from .appsetup import setup

        _print(setup(args.app, home=args.home, dry_run=args.dry_run, remove=args.remove), None, args.json)
        return 0
    if args.cmd == "launch":
        from .launch import launch

        return launch(args.handle, home=args.home, print_only=args.print_only)
    if args.cmd == "doctor":
        from .doctor import run_doctor

        text, ok = run_doctor(args.home)
        _print(text, {"ok": ok}, args.json)
        return 0 if ok else 1
    if args.cmd == "watch":
        from .watch import watch

        return watch(args.home, once=args.once, interval=args.interval)
    if args.cmd == "ui":
        from .dashboard import run_dashboard

        return run_dashboard(args.home, port=args.port, open_browser=not args.no_open)
    route = _route(args)
    if route is None:
        raise RTError("invalid", f"unknown command {args.cmd}", "rt --help")
    op, params = route
    params = {k: v for k, v in params.items() if v is not None}
    seat = args.seat or os.environ.get("RT_SEAT") or None
    key = args.key or os.environ.get("RT_SEAT_KEY") or None
    if not seat and not key:
        seat = _seat_for_cwd(args.home)  # a model's shell inside its working copy acts as that seat
    as_seat = bool(seat or key)
    res = dispatch.call(op, params, home=args.home, seat=seat, key=key, pinned=bool(seat) and not key,
                        as_human=not as_seat, client="cli")
    _print(res.text, res.data, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())

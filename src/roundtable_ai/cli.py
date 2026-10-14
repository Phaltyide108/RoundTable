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

from . import apps as apps_mod
from . import __version__
from .errors import INTERNAL, RTError
from .tasks import KINDS

GETTING_STARTED = """Roundtable {version}: several AI models plan, build and review one project together.

The easy way: open the dashboard and click through it.
  rt ui            opens it in your browser (it can also set up this folder)

The same from the terminal, in your project's main folder:
  rt init                                                    set up this folder
  rt seat add opus --model claude-opus-5-5 --app claude-code add models (two or more)
  rt seat add sol --model gpt-6.1-sol --app codex-cli
  rt launch opus      (one terminal per model)               start each one
  rt goal "what you want built"                              they plan together
  rt plan lock                                               you approve; they build
  rt status                                                  what needs you now

All commands: rt --help    Something wrong: rt doctor    Guide: the Guide page in rt ui
"""

HELP_GROUPS = """commands by purpose:
  start here        ui, init, status, doctor
  models            seat (add, set, list, pause, resume, release, remove), launch, run, setup
  plan and work     goal, plan, task (list, show, file, accept, edit, link, ...), review, memory
  problems          alert, vote, freeze, unfreeze
  follow along      log, usage, watch, export, compact, config, bench
  for apps          mcp, call
"""


def _next_step_text() -> str | None:
    """Inside a project: one short status block and the next thing to do."""
    from .context import open_ctx

    try:
        ctx = open_ctx(None)
    except RTError:
        return None
    try:
        from . import report

        waiting = report.waiting_on_human(ctx)
        seats = ctx.db.scalar("SELECT COUNT(*) FROM seats WHERE status != 'removed'", default=0)
        plan = ctx.db.one("SELECT stage FROM plans WHERE stage NOT IN ('done','cancelled') ORDER BY id DESC LIMIT 1")
        if not seats:
            nxt = "add models: rt ui (Models page), or rt seat add <name> --model <id> --app <app>"
        elif plan is None:
            nxt = 'give them a goal: rt ui (Plan page), or rt goal "what to build"'
        elif waiting:
            nxt = waiting[0]
        else:
            nxt = "nothing waits on you; follow along with rt ui or rt status"
        name = ctx.setting("project", "name") or ctx.root.name
        return f"Roundtable {__version__} · project {name}\nnext: {nxt}\n\ndashboard: rt ui    everything: rt status    help: rt --help"
    finally:
        ctx.close()



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


def _csv(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [x.strip() for x in value.split(",") if x.strip()]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rt", description="Roundtable: AI models planning, building and reviewing one project together. "
                                "Easiest: rt ui opens the dashboard, where every command below is a button.",
                                epilog=HELP_GROUPS, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"roundtable {__version__}")
    p.add_argument("--home", help="project folder or its .roundtable folder (default: search upward from here)")
    p.add_argument("--seat", dest="as_seat", help="act as this seat (for apps without MCP)")
    p.add_argument("--key", dest="seat_key", help="act as the seat that joined with this key")
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
    s.add_argument("--app", required=True, choices=list(apps_mod.APPS),
                   help="; ".join(f"{k}: {a.label}" for k, a in apps_mod.APPS.items()))
    s.add_argument("--company", help="anthropic, openai, google ... (guessed when omitted)")
    s.add_argument("--roles", help="comma list of plan,build,review (default all)")
    s.add_argument("--no-worktree", action="store_true", help="no separate working copy")
    seat.add_parser("list", help="list seats")
    s = seat.add_parser("set", help="change a seat's model or thinking effort")
    s.add_argument("handle")
    s.add_argument("--model")
    s.add_argument("--effort", help="claude-code: low|medium|high|xhigh|max; codex-cli: minimal|low|medium|high|xhigh; default clears it")
    for name, hlp in (("pause", "pause a seat"), ("resume", "resume a seat"), ("remove", "remove a seat"),
                      ("release", "free a seat whose chat was closed"), ("worktree", "create or repair its working copy")):
        seat.add_parser(name, help=hlp).add_argument("handle")

    s = sub.add_parser("goal", help="start a plan")
    s.add_argument("goal")
    s.add_argument("--planners", help="comma list of seats")
    s.add_argument("--review", choices=["low", "mid", "high"])
    s.add_argument("--quick", action="store_true", help="skip the planning rounds: one AI splits the goal into tasks")
    s.add_argument("--auto", action="store_true", help="start building without waiting for your approval")

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
    s = task.add_parser("list", help="list tasks, most urgent first")
    s.add_argument("--status", help="backlog, open, ready, working, review, done, all")
    s.add_argument("--kind", choices=list(KINDS))
    s.add_argument("--label")
    s.add_argument("--priority", type=int, choices=range(5), help="this priority or more urgent (0 urgent .. 4 someday)")
    s.add_argument("--owner")
    s.add_argument("--limit", type=int, default=30)
    s = task.add_parser("file", help="add work to the backlog (ready at once if you give files and a test command)")
    s.add_argument("title")
    s.add_argument("--kind", choices=list(KINDS), default="task")
    s.add_argument("--priority", type=int, choices=range(5), default=2)
    s.add_argument("--summary")
    s.add_argument("--files", help="comma list")
    s.add_argument("--proof", action="append", help="test command (repeatable)")
    s.add_argument("--parent", help="epic task id")
    s.add_argument("--labels", help="comma list")
    s = task.add_parser("accept", help="turn a backlog item into work")
    s.add_argument("task")
    s.add_argument("--files", help="comma list (default: as filed)")
    s.add_argument("--proof", action="append", help="test command (repeatable; default: as filed)")
    s.add_argument("--owner")
    s.add_argument("--priority", type=int, choices=range(5))
    s = task.add_parser("edit", help="change title, kind, priority, labels, summary, files or test command")
    s.add_argument("task")
    s.add_argument("--title")
    s.add_argument("--kind", choices=list(KINDS))
    s.add_argument("--priority", type=int, choices=range(5))
    s.add_argument("--labels", help="comma list (replaces)")
    s.add_argument("--summary")
    s.add_argument("--files", help="comma list")
    s.add_argument("--proof", action="append", help="test command (repeatable)")
    s = task.add_parser("link", help="TASK waits_for|related|discovered_from|parent OTHER")
    s.add_argument("task")
    s.add_argument("relation", choices=["waits_for", "related", "discovered_from", "parent"])
    s.add_argument("other")
    s.add_argument("--remove", action="store_true")

    mem = sub.add_parser("memory", help="project memory every model sees when it joins").add_subparsers(dest="sub", metavar="action")
    s = mem.add_parser("add", help="remember something (yours are pinned)")
    s.add_argument("text")
    s.add_argument("--tags", help="comma list")
    s = mem.add_parser("list", help="show project memory")
    s.add_argument("query", nargs="?")
    s.add_argument("--all", action="store_true")
    s = mem.add_parser("forget", help="forget a note")
    s.add_argument("id")
    s.add_argument("--reason")
    mem.add_parser("pin", help="pin a note").add_argument("id")
    mem.add_parser("unpin", help="unpin a note").add_argument("id")
    s = sub.add_parser("compact", help="shrink history of work finished long ago")
    s.add_argument("--days", type=int)

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
    sub.add_parser("usage", help="context, tokens and 5h/7d limits per seat, plus Roundtable's own token cost")

    s = sub.add_parser("setup", help="connect an app to this project")
    s.add_argument("app", choices=["claude-code", "claude-app", "codex", "copilot"])
    s.add_argument("--dry-run", action="store_true", help="show what would change")
    s.add_argument("--remove", action="store_true", help="remove Roundtable's entry")

    s = sub.add_parser("launch", help="start a seat's app")
    s.add_argument("handle")
    s.add_argument("--print", action="store_true", dest="print_only", help="print the command instead of running it")

    s = sub.add_parser("run", help="run a seat in the background: Roundtable starts its app whenever it has work")
    s.add_argument("handle")
    s.add_argument("--once", action="store_true", help="do the waiting work once, then stop")
    s.add_argument("--stop", action="store_true", help="stop the seat's background runner")
    s.add_argument("--detach", action="store_true", help="start it as its own process and return")

    bench = sub.add_parser("bench", help="does a team do better than one AI? same task, hidden tests").add_subparsers(dest="sub", metavar="action")
    bench.add_parser("list", help="benchmark tasks")
    s = bench.add_parser("run", help="run each contender on a task, then score them with hidden tests")
    s.add_argument("--task", default="sheet")
    s.add_argument("--solo", action="append", help="an AI alone: claude, codex, claude:high, codex:gpt-6.1-sol:xhigh (repeatable)")
    s.add_argument("--team", action="append", help="a team, comma separated: claude,codex (repeatable)")
    s.add_argument("--mode", choices=["quick", "full"], default="quick", help="how the team plans (default quick)")
    s.add_argument("--review", choices=["low", "mid", "high"], default="mid", help="how carefully the team checks itself")
    s.add_argument("--minutes", type=float, default=40, help="time limit per contender")
    s.add_argument("--out", help="folder for the work and the report (default ./roundtable-bench/<time>)")
    s = bench.add_parser("score", help="score a folder against a task's hidden tests")
    s.add_argument("folder")
    s.add_argument("--task", default="sheet")

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
        if s == "set":
            return "seat.set", {"handle": args.handle, "model": args.model, "effort": args.effort}
        if s in ("pause", "resume", "remove", "release", "worktree"):
            return f"seat.{s}", {"handle": args.handle}
    if c == "goal":
        planners = [x.strip() for x in args.planners.split(",")] if args.planners else None
        return "plan.goal", {"goal": args.goal, "planners": planners, "review": args.review,
                             "mode": "quick" if args.quick else "full", "auto": bool(args.auto)}
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
        if s == "list":
            return "task.list", {"status": args.status, "kind": args.kind, "label": args.label, "priority": args.priority,
                                 "owner": args.owner, "limit": args.limit}
        if s == "file":
            return "task.file", {"title": args.title, "kind": args.kind, "priority": args.priority, "summary": args.summary,
                                 "files": _csv(args.files), "proof": args.proof, "parent": args.parent, "labels": _csv(args.labels)}
        if s == "accept":
            return "task.accept", {"task": args.task, "files": _csv(args.files), "proof": args.proof, "owner": args.owner,
                                   "priority": args.priority}
        if s == "edit":
            return "task.edit", {"task": args.task, "title": args.title, "kind": args.kind, "priority": args.priority,
                                 "labels": _csv(args.labels) if args.labels is not None else None, "summary": args.summary,
                                 "files": _csv(args.files), "proof": args.proof}
        if s == "link":
            return "task.link", {"task": args.task, "relation": args.relation, "other": args.other, "remove": args.remove}
    if c == "memory":
        if s == "add":
            return "memory.add", {"text": args.text, "tags": _csv(args.tags)}
        if s == "list":
            return "memory.list", {"query": args.query, "all": args.all}
        if s == "forget":
            return "memory.forget", {"id": args.id, "reason": args.reason}
        if s in ("pin", "unpin"):
            return "memory.pin", {"id": args.id, "pinned": s == "pin"}
    if c == "compact":
        return "admin.compact", {"days": args.days}
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
    if c == "usage":
        return "admin.usage", {}
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
    if argv[:1] == ["_statusline"]:
        from .usage import statusline_main

        return statusline_main(argv[1:])
    if argv[:1] == ["_proofrun"]:
        from .proofrun import main as pr_main

        return pr_main(argv[1:])
    parser = build_parser()
    if not argv:
        print(_next_step_text() or GETTING_STARTED.format(version=__version__))
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
    if args.cmd == "bench":
        from . import bench

        if not args.sub:
            print("rt bench list | rt bench run [--solo claude --solo codex --team claude,codex] | rt bench score FOLDER")
            return 2
        return bench.main(args)
    if args.cmd == "run":
        from . import runner
        from .context import open_ctx

        if args.stop or args.detach:
            ctx = open_ctx(args.home)
            home = ctx.home
            ctx.close()
            if args.stop:
                runner.request_stop(home, args.handle)
                print(f"{args.handle}: background runner stopped")
                return 0
            pid = runner.start_detached(home, args.handle)
            print(f"{args.handle} now runs in the background (process {pid}); stop it with: rt run {args.handle} --stop")
            return 0
        return runner.run_seat(args.home, args.handle, once=args.once)
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
    seat = args.as_seat or os.environ.get("RT_SEAT") or None
    key = args.seat_key or os.environ.get("RT_SEAT_KEY") or None
    if not seat and not key:
        seat = _seat_for_cwd(args.home)  # a model's shell inside its working copy acts as that seat
    as_seat = bool(seat or key)
    res = dispatch.call(op, params, home=args.home, seat=seat, key=key, pinned=bool(seat) and not key,
                        as_human=not as_seat, client="cli")
    _print(res.text, res.data, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())

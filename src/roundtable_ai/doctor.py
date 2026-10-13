"""`rt doctor`: check everything and say exactly how to fix what is wrong."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .errors import RTError

SYNC_HINTS = ("dropbox", "onedrive", "icloud", "mobile documents", "google drive", "googledrive", "box sync", "pcloud")


class Report:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.failed = False

    def ok(self, msg: str) -> None:
        self.lines.append(f"ok    {msg}")

    def warn(self, msg: str, fix: str | None = None) -> None:
        self.lines.append(f"warn  {msg}" + (f"\n      fix: {fix}" if fix else ""))

    def fail(self, msg: str, fix: str | None = None) -> None:
        self.failed = True
        self.lines.append(f"FAIL  {msg}" + (f"\n      fix: {fix}" if fix else ""))


def _check_entry(r: Report, label: str, entry: dict | None, home: Path) -> None:
    if not entry:
        r.warn(f"{label}: no Roundtable entry", "run the matching `rt setup ...` if you use this app")
        return
    cmd = entry.get("command", "")
    if not cmd or not Path(cmd).exists():
        r.fail(f"{label}: points at a Python that no longer exists ({cmd})", "run the matching `rt setup ...` again")
        return
    rt_home = (entry.get("env") or {}).get("RT_HOME", "")
    if rt_home and Path(rt_home).resolve() != home.resolve():
        r.warn(f"{label}: entry belongs to another project ({rt_home})", "fine if intended; each project has its own entry")
        return
    r.ok(f"{label}: entry found")


def run_doctor(home: str | None = None) -> tuple[str, bool]:
    r = Report()
    v = sys.version_info
    (r.ok if v >= (3, 10) else r.fail)(f"Python {v.major}.{v.minor}.{v.micro} ({sys.executable})")
    r.ok(f"Roundtable {__version__}")
    from .context import open_ctx

    try:
        ctx = open_ctx(home)
    except RTError as exc:
        r.fail(exc.message, exc.hint)
        return "\n".join(r.lines), not r.failed
    try:
        r.ok(f"project: {ctx.root} (database schema {ctx.db.meta_get('schema_version')})")
        low = str(ctx.root).lower()
        if any(h in low for h in SYNC_HINTS):
            r.warn("the project is inside a cloud-synced folder; the database can be corrupted by syncing",
                   "move the project to a normal local folder")
        from . import gitops

        git = shutil.which("git")
        if not git:
            r.fail("git is not installed", "install git")
        else:
            out = subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.strip()
            r.ok(out)
        if gitops.is_git(ctx):
            try:
                main = gitops.main_branch(ctx)
                if gitops.branch_exists(ctx.root, main):
                    r.ok(f"main branch: {main}")
                else:
                    r.fail(f"main branch {main} does not exist", "rt config set project.main_branch <branch>")
                cur = gitops.current_branch(ctx.root)
                if cur != main:
                    r.warn(f"the main folder is on {cur or 'a detached commit'}, so finished work cannot merge", f"git switch {main}")
            except RTError as exc:
                r.fail(exc.message, exc.hint)
            hooks = gitops.run(ctx.root, "config", "--get", "core.hooksPath").stdout.strip()
            if hooks:
                r.warn(f"git uses a custom hooks folder ({hooks}); the commit guard must be added by hand",
                       f'add to its pre-commit: "{Path(sys.executable).as_posix()}" -m roundtable_ai.guard; [ $? -eq 10 ] && exit 1')
        else:
            r.warn("no git: shared-folder mode (no working copies, diffs or merges)", "git init, commit, and start a new Roundtable project")
        seats = ctx.db.all("SELECT * FROM seats WHERE status != 'removed' ORDER BY created_at")
        if not seats:
            r.warn("no seats yet", "rt seat add <name> --model <id> --app <app>")
        for s in seats:
            label = f"seat {s['handle']} ({s['app']})"
            if s["status"] == "paused":
                r.warn(f"{label} is paused", f"rt seat resume {s['handle']}")
            if s["worktree"]:
                wt = Path(s["worktree"])
                if not wt.exists():
                    r.fail(f"{label}: working copy missing ({wt})", f"rt seat worktree {s['handle']}")
                else:
                    b = gitops.current_branch(wt)
                    if not (b or "").startswith("rt/"):
                        r.warn(f"{label}: working copy is on {b}, not an rt/ branch", "the seat should claim a task, or: git switch rt/" + s["handle"] + "/idle")
                    else:
                        r.ok(f"{label}: working copy {wt} on {b}")
            elif gitops.uses_worktrees(ctx) and "build" in (s["roles"] or ""):
                r.fail(f"{label}: no working copy", f"rt seat worktree {s['handle']}")
            need = {"claude-code": "claude", "codex-cli": "codex"}.get(s["app"])
            if need and not shutil.which(need):
                from .launch import INSTALL_HINT

                r.warn(f"{label}: `{need}` not found on PATH", INSTALL_HINT[need])
        if gitops.is_git(ctx):
            hook = None
            try:
                hook = gitops._hooks_dir(ctx) / "pre-commit"
            except RTError:
                pass
            if any(s["worktree"] for s in seats):
                if hook and hook.exists() and gitops.GUARD_MARKER in hook.read_text(encoding="utf-8", errors="replace"):
                    r.ok("commit guard installed")
                else:
                    r.warn("commit guard not installed", "rt seat worktree <any seat> reinstalls it")
        from . import appsetup

        mcp_json = ctx.root / ".mcp.json"
        if mcp_json.exists():
            try:
                data = json.loads(mcp_json.read_text(encoding="utf-8"))
                _check_entry(r, "Claude Code (.mcp.json)", (data.get("mcpServers") or {}).get("roundtable"), ctx.home)
            except (json.JSONDecodeError, OSError):
                r.fail(".mcp.json is not valid JSON", "fix or delete it, then: rt setup claude-code")
        cd = appsetup.claude_desktop_config()
        if cd.exists():
            try:
                data = json.loads(cd.read_text(encoding="utf-8"))
                _check_entry(r, "Claude app", (data.get("mcpServers") or {}).get(appsetup.server_name(ctx)), ctx.home)
            except (json.JSONDecodeError, OSError):
                r.warn(f"{cd} is not valid JSON", "fix it in the Claude app's settings")
        cx = appsetup.codex_config()
        if cx.exists():
            try:
                data = appsetup.tomllib.loads(cx.read_text(encoding="utf-8"))
                _check_entry(r, "Codex (CLI / VS Code / ChatGPT app)", (data.get("mcp_servers") or {}).get(appsetup.server_name(ctx)), ctx.home)
            except (appsetup.tomllib.TOMLDecodeError, OSError) as exc:
                r.warn(f"{cx} could not be read ({exc})")
        from . import proofs

        stale = proofs.check_stale(ctx)
        if stale:
            r.warn(f"cleaned up proof runs whose runner had stopped: {', '.join(stale)}")
        if ctx.db.meta_get("frozen") == "1":
            r.warn("all seats are stopped (frozen)", "rt unfreeze")
        blocked = [t["id"] for t in ctx.db.all("SELECT id FROM tasks WHERE status = 'merge_blocked'")]
        if blocked:
            r.warn(f"tasks waiting to merge: {', '.join(blocked)}", "rt task merge")
    finally:
        ctx.close()
    r.lines.append("all checks passed" if not r.failed else "some checks failed: see the fixes above")
    return "\n".join(r.lines), not r.failed

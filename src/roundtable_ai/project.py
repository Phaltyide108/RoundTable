"""Creating a project (`rt init`).

Creates only .roundtable/ (fully git-ignored) and changes nothing else in
the repository, so the main working copy stays clean and merges never get
blocked by Roundtable's own files.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import config as config_mod
from . import events, util
from .context import Ctx
from .db import Store
from .errors import CONFLICT, INVALID, RTError
from .paths import CONFIG_NAME, DB_NAME, HOME_DIR

GITIGNORE = "# Roundtable's shared state is local to this computer. Nothing here is committed.\n*\n"


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL
    )


def detect_git(root: Path) -> dict:
    """Is this the main folder of a git repo, and which branch is checked out?"""
    try:
        top = _git(root, "rev-parse", "--show-toplevel")
    except (OSError, subprocess.SubprocessError):
        return {"git": False, "reason": "git is not installed or not on PATH"}
    if top.returncode != 0:
        return {"git": False, "reason": "not a git repository"}
    toplevel = Path(top.stdout.strip()).resolve()
    common = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common.returncode == 0:
        common_dir = Path(common.stdout.strip()).resolve()
        if common_dir.name == ".git" and common_dir.parent != toplevel:
            return {"git": True, "worktree_of": str(common_dir.parent), "toplevel": str(toplevel)}
    branch = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    head = _git(root, "rev-parse", "--verify", "--quiet", "HEAD")
    return {
        "git": True,
        "toplevel": str(toplevel),
        "branch": branch.stdout.strip() if branch.returncode == 0 else "",
        "has_commits": head.returncode == 0,
    }


def init_project(root: str | Path, name: str | None = None) -> tuple[Path, list[str]]:
    """Create .roundtable in `root`. Returns (home, report lines)."""
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise RTError(INVALID, f"{root} is not a folder")
    home = root / HOME_DIR
    if (home / DB_NAME).exists():
        raise RTError(CONFLICT, f"{root} already has a Roundtable project", "use `rt status`; to start over, move .roundtable aside first")
    report: list[str] = []
    g = detect_git(root)
    if g.get("worktree_of"):
        raise RTError(
            INVALID,
            f"{root} is a git working copy of {g['worktree_of']}",
            f"run `rt init` in the main folder instead: {g['worktree_of']}",
        )
    if g.get("git") and Path(g["toplevel"]) != root:
        raise RTError(
            INVALID,
            f"{root} is inside the git repository at {g['toplevel']}",
            f"run `rt init` at the repository's top folder: {g['toplevel']}",
        )
    main_branch = ""
    if g.get("git"):
        main_branch = g.get("branch") or ""
        if not g.get("has_commits"):
            report.append("warning: the repository has no commits yet. Make a first commit before adding coding seats (working copies need one).")
        if not main_branch:
            report.append("warning: HEAD is detached; set the branch to merge into with `rt config set project.main_branch main`.")
    else:
        report.append(f"note: no git ({g.get('reason')}). Roundtable runs in shared-folder mode: leases are enforced, but there are no per-seat working copies or diffs. Run `git init` and commit first if you want them.")
    home.mkdir(exist_ok=True)
    (home / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    for sub in ("logs", "seats", "proofs", "export"):
        (home / sub).mkdir(exist_ok=True)
    cfg_path = home / CONFIG_NAME
    if not cfg_path.exists():
        cfg_path.write_text(config_mod.render_default(name or root.name, main_branch), encoding="utf-8")
    else:
        config_mod.load(cfg_path)  # validate an existing one
        report.append("kept the existing config.toml")
    store = Store.create(home / DB_NAME)
    try:
        cfg = config_mod.load(cfg_path)
        ctx = Ctx(home=home, root=root, db=store, cfg=cfg, actor="human", client="cli")
        with store.tx():
            store.meta_set("project_id", util.new_key() + util.new_key())
            store.meta_set("created_at", util.now())
            store.meta_set("frozen", "0")
            store.meta_set("git", "1" if g.get("git") else "0")
            events.emit(ctx, "project.created", f"Roundtable project created in {root.name}")
    finally:
        store.close()
    report.insert(0, f"Roundtable project created: {home}")
    if main_branch:
        report.insert(1, f"finished work will be merged into branch: {main_branch}")
    report.append("next: rt ui opens the dashboard to add models and start them (or: rt seat add opus --model claude-opus-5-5 --app claude-code)")
    return home, report

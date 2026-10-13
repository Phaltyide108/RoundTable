"""Finding the project's shared Roundtable folder (.roundtable).

Order:
1. RT_HOME (set in every app config Roundtable writes) - either the
   .roundtable folder itself or the project folder containing it.
2. Walk up from the current folder looking for .roundtable/roundtable.db.
3. If the current folder is a git worktree (a seat's working copy), use the
   main worktree's .roundtable. Worktrees never get their own database.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .errors import NOT_INITIALIZED, RTError

HOME_DIR = ".roundtable"
DB_NAME = "roundtable.db"
CONFIG_NAME = "config.toml"


def _git_main_root(start: Path) -> Path | None:
    """Root folder of the main worktree for any folder inside a git repo/worktree."""
    for args in (["rev-parse", "--path-format=absolute", "--git-common-dir"], ["rev-parse", "--git-common-dir"]):
        try:
            out = subprocess.run(
                ["git", "-C", str(start), *args],
                capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if out.returncode == 0 and out.stdout.strip():
            common = Path(out.stdout.strip())
            if not common.is_absolute():
                common = (start / common).resolve()
            # common dir is <main>/.git for normal repos
            if common.name == ".git":
                return common.parent
            return None
    return None


def resolve_home_arg(value: str | os.PathLike) -> Path:
    p = Path(value).expanduser()
    if p.name != HOME_DIR and (p / HOME_DIR).is_dir():
        p = p / HOME_DIR
    return p.resolve()


def find_home(start: Path | None = None, *, use_env: bool = True) -> Path:
    if use_env and os.environ.get("RT_HOME"):
        home = resolve_home_arg(os.environ["RT_HOME"])
        if not (home / DB_NAME).exists():
            raise RTError(
                NOT_INITIALIZED,
                f"RT_HOME points at {home}, but there is no Roundtable project there",
                "run `rt init` in the project folder, or fix RT_HOME in the app's MCP settings (`rt doctor` shows them)",
            )
        return home
    cur = (start or Path.cwd()).resolve()
    for d in (cur, *cur.parents):
        cand = d / HOME_DIR
        if (cand / DB_NAME).exists():
            return cand
    main = _git_main_root(cur)
    if main is not None and (main / HOME_DIR / DB_NAME).exists():
        return main / HOME_DIR
    raise RTError(
        NOT_INITIALIZED,
        f"{cur} is not inside a Roundtable project",
        "run `rt init` in your project's main folder, or pass --home / set RT_HOME",
    )


def project_root(home: Path) -> Path:
    return home.parent


def db_path(home: Path) -> Path:
    return home / DB_NAME


def config_path(home: Path) -> Path:
    return home / CONFIG_NAME


def user_config_dir() -> Path:
    """Per-user settings folder (only the dashboard's list of recent projects lives here)."""
    import sys

    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "Roundtable"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Roundtable"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "roundtable"


def recent_projects() -> list[dict]:
    """Projects opened in the dashboard, newest first, that still exist."""
    import json

    path = user_config_dir() / "recent.json"
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for item in items if isinstance(items, list) else []:
        root = Path(str(item.get("root", "")))
        if (root / HOME_DIR / DB_NAME).exists():
            out.append({"root": str(root), "name": item.get("name") or root.name})
    return out[:12]


def remember_project(root: Path, name: str) -> None:
    import json

    path = user_config_dir() / "recent.json"
    items = [i for i in recent_projects() if i["root"] != str(root)]
    items.insert(0, {"root": str(root), "name": name})
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items[:12], indent=1), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass

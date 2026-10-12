"""Shared test fixtures.

repo   - a fresh git repository with one commit, cwd set to it
nogit  - a plain folder (no git), cwd set to it
rt     - a Harness on an initialized Roundtable project in `repo`
rt_nogit - the same in `nogit`

Harness.human(op, **params)        run an op as the human
Harness.seat(handle, op, **params) run an op as a pinned seat (no key needed)
Harness.add_seat(handle, ...)      register a seat (no working copy unless worktree=True)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from roundtable_ai import dispatch, project  # noqa: E402
from roundtable_ai.context import open_ctx  # noqa: E402
from roundtable_ai.errors import RTError  # noqa: E402


def git(root: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {out.stderr}")
    return out.stdout


def make_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test")
    git(root, "config", "commit.gpgsign", "false")
    (root / "README.md").write_text("# test project\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("def hello():\n    return 'hi'\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "initial")
    return root


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("RT_HOME", "RT_SEAT", "RT_SEAT_KEY"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def repo(tmp_path, monkeypatch) -> Path:
    root = make_repo(tmp_path / "proj")
    monkeypatch.chdir(root)
    return root


@pytest.fixture
def nogit(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "plain"
    root.mkdir()
    (root / "notes.txt").write_text("hello\n", encoding="utf-8")
    monkeypatch.chdir(root)
    return root


class Harness:
    def __init__(self, home: Path):
        self.home = Path(home)
        self.root = self.home.parent

    def human(self, op: str, /, **params):
        return dispatch.call(op, params, home=self.home, as_human=True, client="test")

    def seat(self, who: str, op: str, /, **params):
        return dispatch.call(op, params, home=self.home, seat=who, pinned=True, as_human=False, client="test")

    def keyed(self, key: str, op: str, /, **params):
        return dispatch.call(op, params, home=self.home, key=key, as_human=False, client="test")

    def join(self, handle: str) -> str:
        res = dispatch.call("seat.join", {"handle": handle}, home=self.home, as_human=False, client="test")
        return res.data["key"]

    def add_seat(self, handle: str, model: str = "claude-opus-5-5", app: str = "claude-code", worktree: bool = False, **kw):
        return self.human("seat.add", handle=handle, model=model, app=app, worktree=worktree, **kw)

    def ctx(self):
        return open_ctx(self.home, client="test")

    def q(self, sql: str, params=()):
        ctx = self.ctx()
        try:
            return [dict(r) for r in ctx.db.all(sql, params)]
        finally:
            ctx.close()

    def error(self, fn, /, *args, **kwargs) -> RTError:
        with pytest.raises(RTError) as exc:
            fn(*args, **kwargs)
        return exc.value


@pytest.fixture
def rt(repo) -> Harness:
    home, _ = project.init_project(repo)
    return Harness(home)


@pytest.fixture
def rt_nogit(nogit) -> Harness:
    home, _ = project.init_project(nogit)
    return Harness(home)

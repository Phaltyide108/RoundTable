"""Everything Roundtable does with git.

Model:
- The main folder stays on the main branch; it is where finished work is merged.
- Each coding seat has one working copy (git worktree) next to the project,
  idle on branch rt/<seat>/idle.
- Each task gets its own branch rt/<seat>/<task>, created from the main branch
  when claimed. Finished tasks are merged by their proven commit, so one
  task's review never drags in another task's code.
- We never touch the human's uncommitted work: merges wait until the main
  folder has no tracked changes.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from . import util
from .errors import CONFLICT, GIT, INVALID, STATE, RTError

GUARD_MARKER = "roundtable-guard"


# ---------------------------------------------------------------- plumbing

def run(cwd: Path | str, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        raise RTError(GIT, "git is not installed or not on PATH", "install git, then run `rt doctor`") from None
    except subprocess.TimeoutExpired:
        raise RTError(GIT, f"git {' '.join(args[:2])} took longer than {timeout}s", "check the repository with `git status`, then retry") from None


def ok(cwd: Path | str, *args: str, what: str | None = None, timeout: int = 120) -> str:
    out = run(cwd, *args, timeout=timeout)
    if out.returncode != 0:
        msg = (out.stderr or out.stdout).strip().splitlines()
        detail = msg[-1] if msg else f"exit code {out.returncode}"
        if "tell me who you are" in (out.stderr or "").lower() or "empty ident" in (out.stderr or "").lower():
            raise RTError(GIT, "git does not know your name and email yet",
                          'run: git config --global user.name "Your Name" && git config --global user.email you@example.com')
        raise RTError(GIT, f"{what or 'git ' + ' '.join(args[:2])} failed: {detail}")
    return out.stdout


def is_git(ctx) -> bool:
    return ctx.db.meta_get("git", "0") == "1"


def uses_worktrees(ctx) -> bool:
    return is_git(ctx) and bool(ctx.setting("git", "worktrees"))


def main_branch(ctx) -> str:
    name = ctx.setting("project", "main_branch")
    if name:
        return name
    out = run(ctx.root, "symbolic-ref", "--quiet", "--short", "HEAD")
    if out.returncode == 0 and out.stdout.strip():
        return out.stdout.strip()
    raise RTError(GIT, "cannot tell which branch finished work should be merged into",
                  "set it: rt config set project.main_branch main")


def head(path: Path | str) -> str:
    return ok(path, "rev-parse", "HEAD", what="reading the current commit").strip()


def current_branch(path: Path | str) -> str | None:
    out = run(path, "symbolic-ref", "--quiet", "--short", "HEAD")
    return out.stdout.strip() if out.returncode == 0 else None


def branch_exists(cwd: Path | str, name: str) -> bool:
    return run(cwd, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}").returncode == 0


def has_commits(cwd: Path | str) -> bool:
    return run(cwd, "rev-parse", "--verify", "--quiet", "HEAD").returncode == 0


def _porcelain(path: Path | str, untracked: str) -> list[str]:
    out = ok(path, "status", "--porcelain=v1", "-z", f"--untracked-files={untracked}", what="checking for uncommitted changes")
    files, parts, i = [], out.split("\0"), 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if len(entry) < 4:
            continue
        status, name = entry[:2], entry[3:]
        files.append(name)
        if status[0] in "RC":  # renames/copies carry the old name next
            i += 1
    return files


def dirty_files(path: Path | str) -> list[str]:
    """Tracked changes and untracked files (git-ignored files excluded)."""
    return _porcelain(path, "all")


def tracked_dirty(path: Path | str) -> list[str]:
    return _porcelain(path, "no")


ARTIFACT_PARTS = ("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules", ".DS_Store", ".tox", ".venv")


def is_artifact(path: str) -> bool:
    """Build/test leftovers that should never block closing a task."""
    parts = path.split("/")
    return any(p in ARTIFACT_PARTS for p in parts) or path.endswith((".pyc", ".pyo"))


def untracked_files(path: Path | str) -> list[str]:
    out = ok(path, "ls-files", "--others", "--exclude-standard", "-z", what="listing new files")
    return [f for f in out.split("\0") if f]


def task_branch(owner: str, task_id: str) -> str:
    return f"rt/{owner}/{task_id}"


def idle_branch(handle: str) -> str:
    """Where a seat's working copy rests between tasks (rt/<seat>/idle).

    Not rt/<seat>: git cannot have both rt/opus and rt/opus/T1."""
    return f"rt/{handle}/idle"


# ---------------------------------------------------------------- worktrees

def _worktrees(root: Path) -> dict[str, str | None]:
    """{absolute path: branch or None} for every registered worktree."""
    out = ok(root, "worktree", "list", "--porcelain", what="listing working copies")
    result, cur = {}, None
    for line in out.splitlines():
        if line.startswith("worktree "):
            cur = str(Path(line[9:]).resolve())
            result[cur] = None
        elif line.startswith("branch ") and cur:
            result[cur] = line[7:].replace("refs/heads/", "", 1)
    return result


def worktree_path(ctx, handle: str) -> Path:
    base = ctx.setting("git", "worktree_dir")
    if base:
        b = Path(base).expanduser()
        if not b.is_absolute():
            b = ctx.root / b
        return (b / handle).resolve()
    return (ctx.root.parent / f"{ctx.root.name}.{handle}").resolve()


def ensure_worktree(ctx, handle: str) -> tuple[Path, str]:
    """Create (or repair) a seat's working copy. Idempotent."""
    if not is_git(ctx):
        raise RTError(GIT, "this project has no git, so seats share the project folder",
                      "to use working copies: git init, commit, then start a new Roundtable project")
    if not ctx.setting("git", "worktrees"):
        raise RTError(INVALID, "working copies are turned off (git.worktrees = false)", "rt config set git.worktrees true")
    root = ctx.root
    if not has_commits(root):
        raise RTError(GIT, "the repository has no commits yet", "make a first commit (git add -A && git commit -m init), then: rt seat worktree " + handle)
    path = worktree_path(ctx, handle)
    branch = idle_branch(handle)
    trees = _worktrees(root)
    if str(path) in trees and not path.exists():
        run(root, "worktree", "prune")
        trees = _worktrees(root)
    if str(path) not in trees:
        if path.exists() and any(path.iterdir()):
            raise RTError(CONFLICT, f"{path} already exists and is not a working copy of this project",
                          "move that folder away, or set another location: rt config set git.worktree_dir <folder>")
        path.parent.mkdir(parents=True, exist_ok=True)
        if branch_exists(root, branch):
            ok(root, "worktree", "add", str(path), branch, what="creating the working copy")
        else:
            ok(root, "worktree", "add", "-b", branch, str(path), main_branch(ctx), what="creating the working copy")
    with ctx.tx():
        ctx.db.execute("UPDATE seats SET worktree = ?, branch = ? WHERE handle = ?", (str(path), branch, handle))
    try:
        install_guard(ctx)
    except RTError as exc:
        ctx.notes.append(f"warning: pre-commit guard not installed: {exc.message}")
    return path, branch


def switch_to_task(ctx, seat_row, task_row, *, create: bool) -> str:
    """Put the seat's working copy on the task branch. Returns the base commit."""
    wt = seat_row["worktree"]
    if not wt or not Path(wt).exists():
        raise RTError(GIT, f"seat {seat_row['handle']} has no working copy",
                      f"the human runs: rt seat worktree {seat_row['handle']}")
    branch = task_branch(seat_row["handle"], task_row["id"])
    if current_branch(wt) == branch:
        return task_row["base_commit"] or head(ctx.root)
    dirty = tracked_dirty(wt)  # untracked leftovers are fine; git refuses itself if one would be overwritten
    if dirty:
        listed = ", ".join(dirty[:6]) + (" …" if len(dirty) > 6 else "")
        raise RTError(CONFLICT, f"your working copy has uncommitted changes ({listed})",
                      "commit them on the current task branch (or discard them), then claim again")
    if branch_exists(ctx.root, branch):
        ok(wt, "switch", branch, what=f"switching to {branch}")
        return task_row["base_commit"] or ok(ctx.root, "merge-base", main_branch(ctx), branch).strip()
    if not create:
        raise RTError(GIT, f"branch {branch} is missing", "the human can cancel and recreate the task")
    base = head_of_branch(ctx.root, main_branch(ctx))
    ok(wt, "switch", "-c", branch, base, what=f"creating branch {branch}")
    return base


def head_of_branch(cwd: Path | str, branch: str) -> str:
    return ok(cwd, "rev-parse", f"refs/heads/{branch}", what=f"reading branch {branch}").strip()


def task_tip(ctx, task_row) -> str | None:
    if task_row["commit_sha"]:
        return task_row["commit_sha"]
    if task_row["owner"]:
        b = task_branch(task_row["owner"], task_row["id"])
        if branch_exists(ctx.root, b):
            return head_of_branch(ctx.root, b)
    return None


# ---------------------------------------------------------------- diffs

def _range(ctx, task_row) -> str | None:
    if not is_git(ctx):
        return None
    tip = task_tip(ctx, task_row)
    if not tip:
        return None
    base = task_row["base_commit"]
    if base:
        return f"{base}..{tip}"
    return f"{main_branch(ctx)}...{tip}"


def changed_files(ctx, task_row) -> list[dict]:
    """[{path, added, removed}] for a task's own changes (empty if unknown)."""
    rng = _range(ctx, task_row)
    if not rng:
        return []
    out = ok(ctx.root, "diff", "--numstat", "-z", "--no-renames", rng, what="reading changed files")
    files = []
    for entry in out.split("\0"):
        if not entry.strip():
            continue
        parts = entry.split("\t", 2)
        if len(parts) != 3:
            continue
        a, r, p = parts
        files.append({"path": p, "added": int(a) if a.isdigit() else 0, "removed": int(r) if r.isdigit() else 0})
    return files


def diff_text(ctx, task_row, max_lines: int | None = None) -> str:
    rng = _range(ctx, task_row)
    if not rng:
        return "(no code diff available: this project has no git, or the task has no commits yet)"
    out = ok(ctx.root, "diff", "--no-color", "-U3", "--no-renames", rng, what="reading the diff", timeout=180)
    lines = out.splitlines()
    if max_lines is not None and len(lines) > max_lines:
        extra = len(lines) - max_lines
        lines = lines[:max_lines] + [f"… diff cut here: {extra} more lines (ask the human for a full review if needed)"]
    return "\n".join(lines) if lines else "(no changes)"


_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@ ?(.*)$")


def hunk_map(ctx, task_row) -> list[dict]:
    """Which functions changed in which files, without reading the code."""
    rng = _range(ctx, task_row)
    if not rng:
        return []
    stats = {f["path"]: f for f in changed_files(ctx, task_row)}
    out = ok(ctx.root, "diff", "--no-color", "-U0", "--no-renames", rng, what="reading the diff", timeout=180)
    result: dict[str, dict] = {}
    cur = None
    for line in out.splitlines():
        if line.startswith("+++ "):
            name = line[4:]
            cur = None if name == "/dev/null" else (name[2:] if name.startswith("b/") else name)
            if cur:
                st = stats.get(cur, {"added": 0, "removed": 0})
                result.setdefault(cur, {"path": cur, "functions": [], "hunks": 0, "added": st["added"], "removed": st["removed"]})
        elif line.startswith("--- ") and cur is None:
            pass
        elif line.startswith("@@") and cur:
            m = _HUNK.match(line)
            entry = result[cur]
            entry["hunks"] += 1
            if m and m.group(3):
                fn = util.one_line(m.group(3), 80)
                if fn not in entry["functions"]:
                    entry["functions"].append(fn)
    for path, st in stats.items():  # deleted files / binary files
        result.setdefault(path, {"path": path, "functions": [], "hunks": 0, "added": st["added"], "removed": st["removed"]})
    return list(result.values())


# ---------------------------------------------------------------- merging

def merge_task(ctx, task_row) -> tuple[bool, str]:
    """Merge a task's proven commit into the main branch, in the main folder."""
    if not uses_worktrees(ctx):
        return True, "no merge needed (shared folder)"
    sha = task_row["commit_sha"]
    if not sha:
        return False, "the task has no proven commit"
    root, main = ctx.root, main_branch(ctx)
    cur = current_branch(root)
    if cur != main:
        return False, f"the main folder is on {cur or 'a detached commit'}, not {main}; switch it back (git switch {main}) and run: rt task merge"
    dirty = tracked_dirty(root)
    if dirty:
        listed = ", ".join(dirty[:5]) + (" …" if len(dirty) > 5 else "")
        return False, f"the main folder has uncommitted changes ({listed}); commit or stash them, then run: rt task merge"
    if run(root, "merge-base", "--is-ancestor", sha, "HEAD").returncode == 0:
        return True, f"already in {main}"
    title = util.one_line(task_row["title"], 60)
    out = run(root, "merge", "--no-ff", "-m", f"Roundtable {task_row['id']}: {title}", sha, timeout=300)
    if out.returncode == 0:
        return True, head(root)
    conflicts = run(root, "diff", "--name-only", "--diff-filter=U").stdout.split()
    run(root, "merge", "--abort")
    err = (out.stderr or out.stdout).lower()
    if "tell me who you are" in err or "empty ident" in err:
        return False, 'git needs your name and email: git config --global user.name "Your Name" && git config --global user.email you@example.com; then run: rt task merge'
    if conflicts:
        return False, "merge conflict in: " + ", ".join(conflicts[:8])
    detail = (out.stderr or out.stdout).strip().splitlines()
    return False, "merge failed: " + (detail[-1] if detail else "unknown git error")


# ---------------------------------------------------------------- files

def known_files(ctx) -> list[str]:
    cached = getattr(ctx, "_known_files", None)
    if cached is not None:
        return cached
    files: list[str] = []
    if is_git(ctx):
        out = run(ctx.root, "ls-files", "-z")
        if out.returncode == 0:
            files = [f for f in out.stdout.split("\0") if f]
    else:
        for dirpath, dirnames, filenames in os.walk(ctx.root):
            dirnames[:] = [d for d in dirnames if d not in (".git", ".roundtable", "node_modules", "__pycache__", ".venv")]
            rel = Path(dirpath).relative_to(ctx.root)
            for fn in filenames:
                files.append((rel / fn).as_posix() if str(rel) != "." else fn)
                if len(files) > 50_000:
                    break
    try:
        ctx._known_files = files  # type: ignore[attr-defined]
    except AttributeError:
        pass
    return files


# ---------------------------------------------------------------- guard hook

def _hooks_dir(ctx) -> Path:
    common = ok(ctx.root, "rev-parse", "--git-common-dir", what="finding git hooks").strip()
    p = Path(common)
    if not p.is_absolute():
        p = (ctx.root / p).resolve()
    return p / "hooks"


def hook_script() -> str:
    py = Path(sys.executable).as_posix()
    return f"""#!/bin/sh
# {GUARD_MARKER}: installed by Roundtable. Stops a seat from committing files
# another seat owns. Human commits on non-rt/ branches are never blocked.
# Safe to delete; `rt seat worktree <name>` reinstalls it.
PY="{py}"
if [ -f "$PY" ]; then
  "$PY" -m roundtable_ai.guard
  code=$?
  if [ "$code" -eq 10 ]; then exit 1; fi
  if [ "$code" -ne 0 ]; then echo "roundtable: guard skipped (exit $code)" >&2; fi
else
  echo "roundtable: guard skipped (Roundtable is no longer installed at $PY)" >&2
fi
HOOK_DIR="$(dirname "$0")"
if [ -f "$HOOK_DIR/pre-commit.rt-chained" ]; then
  sh "$HOOK_DIR/pre-commit.rt-chained" "$@" || exit $?
fi
exit 0
"""


def install_guard(ctx) -> str:
    hooks_path = run(ctx.root, "config", "--get", "core.hooksPath").stdout.strip()
    if hooks_path:
        raise RTError(
            GIT,
            f"git uses a custom hooks folder ({hooks_path}, e.g. husky), so Roundtable did not change it",
            f'add this line to that folder\'s pre-commit hook: "{Path(sys.executable).as_posix()}" -m roundtable_ai.guard; [ $? -eq 10 ] && exit 1',
        )
    d = _hooks_dir(ctx)
    d.mkdir(parents=True, exist_ok=True)
    hook = d / "pre-commit"
    if hook.exists():
        current = hook.read_text(encoding="utf-8", errors="replace")
        if GUARD_MARKER not in current:
            chained = d / "pre-commit.rt-chained"
            if not chained.exists():
                hook.rename(chained)
            else:
                raise RTError(GIT, "an existing pre-commit hook could not be chained safely",
                              f"merge {hook} and {chained} by hand, then run: rt seat worktree <name>")
    hook.write_text(hook_script(), encoding="utf-8", newline="\n")
    try:
        hook.chmod(0o755)
    except OSError:
        pass
    return str(hook)


def staged_files(path: Path | str) -> list[str]:
    out = ok(path, "diff", "--cached", "--name-only", "-z", "--no-renames", what="listing staged files")
    return [f for f in out.split("\0") if f]


def commit_leased(ctx, seat_row, task_row, message: str) -> tuple[str | None, list[str], list[str]]:
    """Commit the seat's changes that its leases cover, on its task branch.

    Runs in Roundtable's own process, so it works for apps whose sandbox keeps
    `.git` read-only (Codex's workspace-write mode does). Files outside the
    seat's leases are left uncommitted and returned as `skipped`.
    Returns (new commit or None, committed files, skipped files).
    """
    from . import leases

    wt = seat_row["worktree"]
    branch = task_branch(seat_row["handle"], task_row["id"])
    if not wt or current_branch(wt) != branch:
        raise RTError(STATE, f"your working copy is not on {branch}", f'rt_task claim task="{task_row["id"]}" switches back to it')
    mine = [r["pattern"] for r in leases.active(ctx, seat_row["handle"])]
    candidates = list(dict.fromkeys(tracked_dirty(wt) + [f for f in untracked_files(wt) if not is_artifact(f)]))
    files = [f for f in candidates if util.files_covered(mine, f)]
    skipped = [f for f in candidates if f not in files]
    if not files:
        return None, [], skipped
    ident = []
    if run(wt, "config", "user.email").returncode != 0:  # no identity configured: commit as Roundtable rather than fail
        ident = ["-c", "user.name=Roundtable", "-c", "user.email=roundtable@localhost"]
    model = (seat_row["model"] or "").replace("<", "").replace(">", "")
    author = f"{seat_row['handle']} ({model}) <{seat_row['handle']}@roundtable.invalid>"
    ok(wt, "add", "-A", "--", *files, what="staging your files")
    ok(wt, *ident, "commit", "-q", "-m", message, f"--author={author}", "--", *files, what="committing")
    return head(wt), files, skipped


def seat_from_branch(branch: str | None) -> str | None:
    if not branch or not branch.startswith("rt/"):
        return None
    rest = branch[3:]
    handle = rest.split("/", 1)[0]
    return handle or None


def guard_check(ctx, worktree_path: Path | str, staged: list[str]) -> list[str]:
    """Reasons a seat may not commit these files (empty = allowed)."""
    seat = seat_from_branch(current_branch(worktree_path))
    if seat is None:
        return []
    from . import alerts, leases

    problems = []
    holds = alerts.holds(ctx)
    for f in staged:
        hold = next((h for h in holds if util.glob_match(h["pattern"], f)), None)
        if hold:
            problems.append(f"{f}: held by alert {hold['alert_id']} ({hold['kind']})")
            continue
        rows = leases.covering(ctx, f)
        others = [r for r in rows if r["seat"] != seat]
        if others:
            problems.append(f"{f}: leased to {others[0]['seat']} for {others[0]['task']}")
        elif not rows:
            problems.append(f"{f}: not in your leases (rt_lease extend first)")
    return problems

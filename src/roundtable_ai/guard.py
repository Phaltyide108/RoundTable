"""The pre-commit check: `python -m roundtable_ai.guard` (run by the git hook).

Exit 10 (commit stopped) only when a seat tries to commit files it does not
lease, files another seat leases, or files held by an alert. Anything
unexpected prints a warning and lets the commit through: Roundtable must
never break git for the human.
"""

from __future__ import annotations

import sys
from pathlib import Path

VIOLATION = 10  # the hook stops the commit only on this code; anything else lets it through


def main(argv: list[str] | None = None) -> int:
    try:
        from . import dispatch, gitops, paths
        from .context import open_ctx
        from .errors import RTError

        cwd = Path.cwd()
        branch = gitops.current_branch(cwd)
        if gitops.seat_from_branch(branch) is None:
            return 0  # the human's own branches are never blocked
        try:
            home = paths.find_home(cwd)
        except RTError:
            return 0  # not a Roundtable project (any more)
        ctx = open_ctx(home, actor="system", client="hook")
        try:
            dispatch.housekeeping(ctx, None)
            problems = gitops.guard_check(ctx, cwd, gitops.staged_files(cwd))
        finally:
            ctx.close()
        if problems:
            print("roundtable: commit stopped. These files are not yours to commit right now:", file=sys.stderr)
            for p in problems:
                print(f"  - {p}", file=sys.stderr)
            print("unstage them (git restore --staged <file>), or lease them first (rt_lease extend).", file=sys.stderr)
            return VIOLATION
        return 0
    except Exception as exc:  # never break git
        print(f"roundtable: guard skipped ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())

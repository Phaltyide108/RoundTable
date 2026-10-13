"""Detached proof runner: python -m roundtable_ai.proofrun <home> <run_id>."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("usage: python -m roundtable_ai.proofrun <home> <run_id>", file=sys.stderr)
        return 2
    from .proofs import run

    status = run(args[0], args[1])
    return 0 if status in ("passed", "failed", "timeout", "error", "stale") else 1


if __name__ == "__main__":
    sys.exit(main())

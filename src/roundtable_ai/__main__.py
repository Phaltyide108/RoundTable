"""Allow `python -m roundtable_ai ...` (used in app configs, so no PATH lookup is needed)."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())

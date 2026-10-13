#!/bin/sh
# Install Roundtable for the current user (macOS / Linux). No sudo needed.
# Usage: sh install.sh            or   REPO_URL=https://github.com/you/roundtable sh install.sh
set -eu
REPO_URL="${REPO_URL:-https://github.com/OWNER/roundtable}"
SPEC="git+${REPO_URL}"

say() { printf '%s\n' "$*"; }
fail() { printf 'roundtable install: %s\n' "$*" >&2; exit 1; }

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
[ -n "$PY" ] || fail "Python 3.10+ is required. Install it from https://www.python.org/downloads/ and run this again."
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || fail "Python 3.10+ is required (found $("$PY" --version 2>&1))."
command -v git >/dev/null 2>&1 || fail "git is required. Install it from https://git-scm.com/downloads and run this again."

if command -v uv >/dev/null 2>&1; then
  say "installing with uv: $SPEC"
  uv tool install --force "$SPEC"
elif command -v pipx >/dev/null 2>&1; then
  say "installing with pipx: $SPEC"
  pipx install --force "$SPEC"
else
  say "neither uv nor pipx found; installing pipx for your user first"
  "$PY" -m pip install --user pipx || fail "could not install pipx. Install uv (https://docs.astral.sh/uv/) or pipx, then run this again."
  "$PY" -m pipx ensurepath || true
  "$PY" -m pipx install --force "$SPEC"
fi

say ""
say "Roundtable installed. If 'rt' is not found, open a new terminal (your PATH was updated)."
say "Next, in your project folder:  rt init   then   rt seat add <name> --model <model> --app claude-code|codex-cli|claude-app|codex-app"

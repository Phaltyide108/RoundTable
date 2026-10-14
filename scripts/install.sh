#!/bin/sh
# Install Roundtable for the current user (Linux / macOS). No sudo needed.
#
#   sh scripts/install.sh                 from a downloaded copy: installs that copy
#   curl -fsSL <raw url of this file> | sh   installs from GitHub (set REPO_URL for a fork)
#
# Uses uv or pipx if you have one; otherwise installs uv (a single program, into
# ~/.local/bin) and uses it. Never uses sudo and never touches system Python.
set -eu

say() { printf '%s\n' "$*"; }
fail() { printf 'roundtable install: %s\n' "$*" >&2; exit 1; }

HERE=""
case "$0" in
  */install.sh) HERE=$(CDPATH= cd -- "$(dirname -- "$0")/.." 2>/dev/null && pwd || true) ;;
esac
if [ -z "${REPO_URL:-}" ] && [ -n "$HERE" ] && [ -f "$HERE/pyproject.toml" ] && grep -q 'name = "roundtable-ai"' "$HERE/pyproject.toml"; then
  SPEC="$HERE"
  say "installing Roundtable from this folder: $SPEC"
else
  SPEC="git+${REPO_URL:-https://github.com/Phaltyide108/RoundTable}"
  say "installing Roundtable from $SPEC"
fi

command -v git >/dev/null 2>&1 || fail "git is required. Ubuntu/Debian: sudo apt install git   macOS: xcode-select --install"

if command -v uv >/dev/null 2>&1; then
  UV=uv
elif [ -x "$HOME/.local/bin/uv" ]; then
  UV="$HOME/.local/bin/uv"
else
  UV=""
fi

if [ -n "$UV" ]; then
  "$UV" tool install --force --python ">=3.10" "$SPEC"
elif command -v pipx >/dev/null 2>&1; then
  pipx install --force "$SPEC"
else
  say "neither uv nor pipx found: installing uv for your user (https://docs.astral.sh/uv/)"
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://astral.sh/uv/install.sh | sh
  else
    fail "need curl or wget to install uv. Ubuntu/Debian: sudo apt install curl  (or: sudo apt install pipx)"
  fi
  UV="$HOME/.local/bin/uv"
  [ -x "$UV" ] || UV="$HOME/.cargo/bin/uv"
  [ -x "$UV" ] || fail "uv was installed but not found; open a new terminal and run this script again"
  # uv downloads a suitable Python by itself if yours is older than 3.10
  "$UV" tool install --force --python ">=3.10" "$SPEC"
fi

say ""
if command -v rt >/dev/null 2>&1 && rt --version 2>/dev/null | grep -q roundtable; then
  say "Roundtable is installed: $(rt --version)"
else
  # make sure ~/.local/bin is on PATH in new terminals (Ubuntu only adds it at login)
  if [ -n "$UV" ]; then "$UV" tool update-shell >/dev/null 2>&1 || true; else pipx ensurepath >/dev/null 2>&1 || true; fi
  say "Roundtable is installed. Open a NEW terminal so 'rt' is found (or run: export PATH=\"\$HOME/.local/bin:\$PATH\")."
  say "If 'rt' is another program on your system, use the same commands with 'roundtable' instead."
fi
# add Roundtable to the app menu (a .desktop entry on Linux, ~/Applications/Roundtable.app on macOS)
RT_BIN=$(command -v rt 2>/dev/null || true)
[ -n "$RT_BIN" ] || RT_BIN="$HOME/.local/bin/rt"
if [ -x "$RT_BIN" ] && "$RT_BIN" app --install >/dev/null 2>&1; then
  say "Roundtable is in your app menu: open it like any other app (search for \"Roundtable\")."
fi
say "Next: open Roundtable from your app menu, or run:  rt app   (it can set up your project folder)"

"""One error type with a stable code, a plain message and a next step.

Every failure a user or a model can hit is raised as RTError so the CLI and
the MCP server can show "what happened" and "what to do next" consistently.
"""

from __future__ import annotations

from typing import Any

# Stable error codes. Models and scripts may branch on these, so never rename.
NOT_FOUND = "not_found"        # an id or seat that does not exist
INVALID = "invalid"            # bad input (wrong type, empty, malformed)
TOO_LONG = "too_long"          # a summary/title/etc. over its size cap
CONFLICT = "conflict"          # someone else holds it (task, file lease, seat)
FORBIDDEN = "forbidden"        # this actor may not do this (e.g. human-only)
STATE = "state"                # not allowed in the current state
STOP = "stop"                  # all work paused, or an unacknowledged level-5 alert
BUSY = "busy"                  # database locked for too long
NEED_JOIN = "need_join"        # caller has no seat yet
NOT_INITIALIZED = "not_initialized"
CONFIG = "config"              # config.toml problem
VERSION = "version"            # database made by a newer Roundtable
GIT = "git"                    # a git operation failed
PROOF = "proof"                # proof failed / could not run
INTERNAL = "internal"          # a bug: should never happen


class RTError(Exception):
    """An expected, explainable failure.

    message: what happened, in plain words.
    hint:    the exact next step (a command or tool call), if there is one.
    data:    machine-readable details for --json / structured output.
    """

    def __init__(self, code: str, message: str, hint: str | None = None, data: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.data = data or {}

    def render(self) -> str:
        text = f"error [{self.code}]: {self.message}"
        if self.hint:
            text += f"\nnext: {self.hint}"
        return text

    def to_dict(self) -> dict[str, Any]:
        return {"ok": False, "code": self.code, "message": self.message, "hint": self.hint, "data": self.data}

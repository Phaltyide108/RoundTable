"""Roundtable's MCP server over stdio, with no third-party dependencies.

Why our own: the official Python SDK changed its API between 1.x and 2.x;
the wire protocol for tools is small and stable, so speaking it directly
removes a whole class of install-time breakage.

Protocol notes
- JSON-RPC 2.0, one JSON message per line, UTF-8.
- Handshake era: `initialize` (versions below). Newer clients first probe
  `server/discover` (2026-07-28 protocol); we answer -32601 "Method not
  found", which makes them fall back to `initialize` (the official clients
  fall back on every error except -32022).
- stdout carries protocol messages only. Everything else goes to stderr and
  .roundtable/logs/mcp.log.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, BinaryIO

from . import __version__, registry
from .errors import RTError

SUPPORTED_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
LATEST_VERSION = "2025-11-25"

INSTRUCTIONS = (
    "Roundtable connects you with other AI models working on the same project. "
    "Call rt_sync first in every session (the first time in a chat: rt_sync join=\"<your seat name>\", "
    "then pass the returned key on every call). Follow the rules it returns."
)

TOOL_INFO = {
    "rt_sync": "Start here every session: what changed since you last looked and what needs you. First call in a chat: join=\"<your seat name>\".",
    "rt_plan": "Plan together: blind drafts, critique, propose, approve or object, amendments to the locked plan.",
    "rt_task": "Your work: ready tasks, claim (leases its files), checkpoint, close (Roundtable runs the proof), show, now. "
               "file: put a bug or missing work you found into the human's backlog.",
    "rt_lease": "Lease more files for your task, or give them back.",
    "rt_review": "Review others' tasks at the depth the human set; answer review comments on yours.",
    "rt_suggest": "Advise the owner of a task or file instead of editing it; answer suggestions sent to you.",
    "rt_alert": "Problems, level 1-5 (4 and 5 need evidence): raise, ack, resolve, show, list.",
    "rt_vote": "Settle stuck decisions by vote; every ballot needs a reason.",
    "rt_memory": "Project memory that outlives chats: add a convention, decision or gotcha; list; forget what no longer holds.",
}
TOOL_ORDER = tuple(TOOL_INFO)
DEFAULT_ACTION = {"rt_sync": "sync"}

JSON_TYPES = {"str": {"type": "string"}, "int": {"type": "integer"}, "bool": {"type": "boolean"},
              "list": {"type": "array", "items": {"type": "string"}},
              "objects": {"type": "array", "items": {"type": "object"}}, "object": {"type": "object"}}


def _empty(v: Any) -> bool:
    return v is None or v == "" or v == [] or v == {}


def build_tools() -> tuple[list[dict], dict[tuple[str, str], registry.Op]]:
    registry.load_all()
    by_tool = registry.tools()
    tools, index = [], {}
    for name in TOOL_ORDER:
        ops = by_tool.get(name, [])
        if not ops:
            continue
        props: dict[str, dict] = {}
        sigs = []
        for o in ops:
            index[(name, o.action)] = o
            parts = []
            for p in o.params:
                if p.required:
                    parts.append(p.name)
                schema = dict(JSON_TYPES[p.type])
                if p.enum:
                    schema["enum"] = list(p.enum)
                if p.desc:
                    schema["description"] = p.desc
                if p.name in props and props[p.name].get("type") != schema.get("type"):
                    merged = {k: v for k, v in props[p.name].items() if k != "type"}
                    merged["description"] = (merged.get("description", "") + " / " + p.desc).strip(" /")
                    props[p.name] = merged
                elif p.name in props and "enum" in props[p.name] and p.enum:
                    props[p.name]["enum"] = sorted(set(props[p.name]["enum"]) | set(p.enum))
                elif p.name in props and "enum" in props[p.name] and not p.enum:
                    props[p.name].pop("enum")
                else:
                    props.setdefault(p.name, schema)
            if any(not p.required for p in o.params):
                parts.append("…")
            sigs.append(f"{o.action}({', '.join(parts)})")
        if name == "rt_sync":
            props["join"] = {"type": "string", "description": "your seat name; first call in a new chat only"}
        props["key"] = {"type": "string", "description": "your seat key from join (omit if this session is already bound)"}
        props["format"] = {"type": "string", "enum": ["text", "json"], "description": "reply format (default text)"}
        action_schema = {"type": "string", "enum": [o.action for o in ops]}
        if name in DEFAULT_ACTION:
            action_schema["description"] = f"default: {DEFAULT_ACTION[name]}"
        schema = {"type": "object", "properties": {"action": action_schema, **props}, "additionalProperties": False}
        if name not in DEFAULT_ACTION:
            schema["required"] = ["action"]
        tools.append({"name": name, "description": TOOL_INFO[name] + "\nactions: " + " · ".join(sigs), "inputSchema": schema})
    return tools, index


class Server:
    def __init__(self, home: str | os.PathLike | None = None):
        self.home = str(home) if home else (os.environ.get("RT_HOME") or None)
        self.pinned = (os.environ.get("RT_SEAT") or "").strip().lower() or None
        self.card_sent = False
        self.tools, self.index = build_tools()
        self.log_path: Path | None = None
        try:
            from .paths import find_home, resolve_home_arg

            h = resolve_home_arg(self.home) if self.home else find_home()
            if h.is_dir():
                self.log_path = h / "logs" / "mcp.log"
        except Exception:
            self.log_path = None  # no project yet: log to stderr only

    # -------------------------------------------------------------- logging
    def log(self, msg: str) -> None:
        line = f"[roundtable mcp] {msg}"
        try:
            sys.stderr.write(line + "\n")
            sys.stderr.flush()
        except Exception:
            pass
        if self.log_path:
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.log_path, "a", encoding="utf-8") as fh:
                    from .util import now

                    fh.write(f"{now()} {msg}\n")
            except OSError:
                pass

    # -------------------------------------------------------------- protocol
    @staticmethod
    def _error(mid: Any, code: int, message: str, data: Any = None) -> dict:
        err: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        return {"jsonrpc": "2.0", "id": mid, "error": err}

    @staticmethod
    def _ok(mid: Any, result: Any) -> dict:
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def handle(self, msg: Any) -> dict | None:
        if not isinstance(msg, dict):
            return self._error(None, -32600, "Invalid Request")
        method = msg.get("method")
        mid = msg.get("id")
        is_request = "id" in msg
        if method is None:
            return None  # a response to something we never asked; ignore
        if not is_request:
            return None  # notifications (initialized, cancelled, ...) need no answer
        try:
            if method == "initialize":
                params = msg.get("params") or {}
                asked = params.get("protocolVersion")
                version = asked if asked in SUPPORTED_VERSIONS else LATEST_VERSION
                client = (params.get("clientInfo") or {}).get("name", "?")
                self.log(f"initialize from {client}, protocol {asked} -> {version}")
                return self._ok(mid, {
                    "protocolVersion": version,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "roundtable", "version": __version__},
                    "instructions": INSTRUCTIONS,
                })
            if method == "ping":
                return self._ok(mid, {})
            if method == "tools/list":
                return self._ok(mid, {"tools": self.tools})
            if method == "tools/call":
                params = msg.get("params") or {}
                name = params.get("name")
                if not any(t["name"] == name for t in self.tools):
                    return self._error(mid, -32602, f"Unknown tool: {name}")
                return self._ok(mid, self.call_tool(name, params.get("arguments") or {}))
            if method in ("resources/list", "resources/templates/list", "prompts/list"):
                key = {"resources/list": "resources", "resources/templates/list": "resourceTemplates", "prompts/list": "prompts"}[method]
                return self._ok(mid, {key: []})
            if method == "logging/setLevel":
                return self._ok(mid, {})
            return self._error(mid, -32601, f"Method not found: {method}")
        except Exception as exc:  # never die on one bad request
            self.log("internal error: " + traceback.format_exc())
            return self._error(mid, -32603, f"Internal error: {type(exc).__name__}: {exc}")

    # -------------------------------------------------------------- tools
    def _text(self, text: str, is_error: bool = False) -> dict:
        return {"content": [{"type": "text", "text": text}], "isError": is_error}

    def call_tool(self, name: str, args: dict) -> dict:
        from . import dispatch

        if not isinstance(args, dict):
            return self._text("error [invalid]: arguments must be an object", True)
        args = dict(args)
        fmt = args.pop("format", None) or "text"
        key = args.pop("key", None)
        join = args.pop("join", None) if name == "rt_sync" else None
        action = args.pop("action", None) or DEFAULT_ACTION.get(name)
        actions = [a for (t, a) in self.index if t == name]
        if not action:
            return self._text(f"error [invalid]: {name} needs an action\nnext: one of {', '.join(actions)}", True)
        op = self.index.get((name, action))
        if op is None:
            return self._text(f"error [invalid]: {name} has no action {action!r}\nnext: one of {', '.join(actions)}", True)
        own = {p.name for p in op.params}
        params: dict[str, Any] = {}
        for k, v in args.items():
            if k in own:
                if not _empty(v):
                    params[k] = v
            elif not _empty(v):
                users = [a for (t, a), o in self.index.items() if t == name and any(p.name == k for p in o.params)]
                hint = f"it belongs to: {', '.join(users)}" if users else f"{action} takes: {', '.join(sorted(own)) or 'nothing'}"
                return self._text(f"error [invalid]: parameter '{k}' is not used by {name} {action}\nnext: {hint}", True)
        seat = self.pinned
        pinned = bool(self.pinned)
        prefix = ""
        try:
            if join and not pinned:
                jr = dispatch.call("seat.join", {"handle": join}, home=self.home, as_human=False, client="mcp")
                key = jr.data["key"]
                prefix = jr.text + "\n\n"
            elif join and pinned:
                prefix = f"(this session is already bound to seat {self.pinned}; join ignored)\n"
            res = dispatch.call(op.name, params, home=self.home, seat=seat, key=key, pinned=pinned, as_human=False, client="mcp")
            if pinned and not self.card_sent:
                try:
                    from . import seats
                    from .context import open_ctx

                    c = open_ctx(self.home, client="mcp")
                    try:
                        prefix = seats.pinned_card(c, self.pinned) + "\n\n" + prefix
                    finally:
                        c.close()
                    self.card_sent = True
                except RTError:
                    pass
            if fmt == "json":
                body = dict(res.data)
                if join and not pinned:
                    body.setdefault("key", key)
                return self._text(json.dumps({"ok": True, "text": prefix + res.text, "data": body}, ensure_ascii=False, default=str))
            return self._text(prefix + res.text)
        except RTError as exc:
            inbox = getattr(exc, "inbox", None)
            text = (inbox + "\n" if inbox else "") + exc.render()
            if prefix:
                text = prefix + text
            if fmt == "json":
                return self._text(json.dumps(exc.to_dict(), ensure_ascii=False, default=str), True)
            return self._text(text, True)
        except Exception as exc:
            self.log("tool error: " + traceback.format_exc())
            return self._text(f"error [internal]: {type(exc).__name__}: {exc}\nnext: the human can check .roundtable/logs/mcp.log", True)

    # -------------------------------------------------------------- loop
    def serve(self, stdin: BinaryIO | None = None, stdout: BinaryIO | None = None) -> int:
        inp = stdin or sys.stdin.buffer
        out = stdout or sys.stdout.buffer
        real_stdout = sys.stdout
        sys.stdout = sys.stderr  # nothing but protocol may reach stdout
        self.log(f"started (roundtable {__version__}, python {sys.version.split()[0]}, home={self.home or 'auto'}, seat={self.pinned or 'join'})")

        def write(obj: Any) -> None:
            out.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8") + b"\n")
            out.flush()

        try:
            for raw in inp:
                line = raw.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    write(self._error(None, -32700, "Parse error"))
                    continue
                if isinstance(msg, list):
                    if not msg:
                        write(self._error(None, -32600, "Invalid Request"))
                        continue
                    replies = [r for r in (self.handle(m) for m in msg) if r is not None]
                    if replies:
                        write(replies)
                    continue
                reply = self.handle(msg)
                if reply is not None:
                    write(reply)
        except (BrokenPipeError, KeyboardInterrupt):
            pass
        finally:
            sys.stdout = real_stdout
            self.log("stopped")
        return 0


def serve(home: str | os.PathLike | None = None) -> int:
    return Server(home).serve()

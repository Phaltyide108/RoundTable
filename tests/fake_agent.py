"""A stand-in for `claude -p`, `codex exec` and `opencode run` used by the end-to-end tests.

It is started exactly the way Roundtable's background runner starts the real
apps (same flags), starts the Roundtable MCP server from the settings it was
given, and plays a sensible model: it reads the table (read-only) to decide,
and acts only through the MCP tools, like a real model. It prints the same
event stream the real apps print, so the runner's parsing is exercised too.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


def parse(argv: list[str]) -> dict:
    out: dict = {"overrides": {}, "app": "claude"}
    if argv and argv[0] == "exec":
        out["app"] = "codex"
        argv = argv[1:]
    elif argv and argv[0] == "run":
        out["app"] = "opencode"
        argv = argv[1:]
    i = 0
    rest = []
    while i < len(argv):
        a = argv[i]
        if a in ("-p",):
            out["prompt"] = argv[i + 1]
            i += 2
            continue
        if a in ("--mcp-config",):
            out["mcp_config"] = argv[i + 1]
            i += 2
            continue
        if a in ("--resume",):
            out["resume"] = argv[i + 1]
            i += 2
            continue
        if a == "-c":
            key, _, value = argv[i + 1].partition("=")
            out["overrides"][key] = tomllib.loads("v = " + value)["v"]
            i += 2
            continue
        if a in ("-C", "--dir"):
            out["cwd"] = argv[i + 1]
            i += 2
            continue
        if a in ("--session",):
            out["resume"] = argv[i + 1]
            i += 2
            continue
        if a in ("--model", "-m", "--effort", "--output-format", "--append-system-prompt", "--permission-mode",
                 "--allowedTools", "-s", "--variant", "--format", "--disallowedTools"):
            out[a.lstrip("-")] = argv[i + 1]
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        rest.append(a)
        i += 1
    if out["app"] == "codex":
        if rest and rest[0] == "resume":
            out["resume"] = rest[1]
            rest = rest[2:]
        out["prompt"] = rest[-1] if rest else ""
    if out["app"] == "opencode":
        out["prompt"] = rest[-1] if rest else ""
    return out


def server_from(args: dict) -> tuple[list[str], dict]:
    if args["app"] == "opencode":
        srv = json.loads(os.environ["OPENCODE_CONFIG_CONTENT"])["mcp"]["roundtable"]
        return list(srv["command"]), srv.get("environment", {})
    if args["app"] == "claude":
        cfg = json.loads(Path(args["mcp_config"]).read_text())
        srv = next(iter(cfg["mcpServers"].values()))
        return [srv["command"], *srv.get("args", [])], srv.get("env", {})
    ov = args["overrides"]
    name = next(k.split(".")[1] for k in ov if k.startswith("mcp_servers."))
    base = f"mcp_servers.{name}."
    return [ov[base + "command"], *ov.get(base + "args", [])], ov.get(base + "env", {})


class Mcp:
    def __init__(self, cmd: list[str], env: dict, cwd: str):
        full = dict(os.environ)
        full.update(env)
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=full, cwd=cwd)
        self.n = 0
        self.call_raw("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "fake-agent", "version": "1"}})
        self.notify("notifications/initialized")

    def notify(self, method: str) -> None:
        self.p.stdin.write((json.dumps({"jsonrpc": "2.0", "method": method}) + "\n").encode())
        self.p.stdin.flush()

    def call_raw(self, method: str, params: dict) -> dict:
        self.n += 1
        self.p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params}) + "\n").encode())
        self.p.stdin.flush()
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("MCP server closed")
            msg = json.loads(line)
            if msg.get("id") == self.n:
                return msg

    def tool(self, name: str, **arguments) -> str:
        msg = self.call_raw("tools/call", {"name": name, "arguments": arguments})
        res = msg.get("result") or {}
        return "".join(c.get("text", "") for c in res.get("content", []))

    def close(self) -> None:
        try:
            self.p.stdin.close()
            self.p.wait(timeout=10)
        except Exception:
            self.p.kill()


class Out:
    def __init__(self, app: str):
        self.app = app
        self.session = ""

    def emit(self, obj: dict) -> None:
        if self.app == "opencode":
            obj = dict(obj, timestamp=1791900000000, sessionID=self.session)
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()

    def start(self, session: str) -> None:
        self.session = session
        if self.app == "opencode":
            self.emit({"type": "step_start", "part": {"type": "step-start"}})
        elif self.app == "claude":
            self.emit({"type": "system", "subtype": "init", "session_id": session, "model": "fake"})
        else:
            self.emit({"type": "thread.started", "thread_id": session})

    def think(self, text: str) -> None:
        if self.app == "opencode":
            self.emit({"type": "reasoning", "part": {"type": "reasoning", "text": text}})
        elif self.app == "claude":
            self.emit({"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": text}]}})
        else:
            self.emit({"type": "item.completed", "item": {"id": "r", "type": "reasoning", "text": text}})

    def tool(self, name: str, args: dict) -> None:
        if self.app == "opencode":
            self.emit({"type": "tool_use", "part": {"type": "tool", "tool": f"roundtable_{name}", "state": {"status": "completed", "input": args}}})
        elif self.app == "claude":
            self.emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": f"mcp__roundtable__{name}", "input": args}]}})
        else:
            self.emit({"type": "item.started", "item": {"id": "m", "type": "mcp_tool_call", "server": "roundtable", "tool": name, "arguments": args}})

    def edit(self, path: str) -> None:
        if self.app == "opencode":
            self.emit({"type": "tool_use", "part": {"type": "tool", "tool": "write", "state": {"status": "completed", "input": {"filePath": path}}}})
        elif self.app == "claude":
            self.emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Write", "input": {"file_path": path}}]}})
        else:
            self.emit({"type": "item.completed", "item": {"id": "f", "type": "file_change", "changes": [{"path": path, "kind": "add"}]}})

    def done(self, session: str, text: str) -> None:
        if self.app == "opencode":
            self.emit({"type": "text", "part": {"type": "text", "text": text}})
            self.emit({"type": "step_finish", "part": {"type": "step-finish", "tokens": {"input": 1000, "output": 200, "reasoning": 0, "cache": {"read": 0, "write": 0}}}})
        elif self.app == "claude":
            self.emit({"type": "result", "subtype": "success", "is_error": False, "result": text, "session_id": session,
                       "num_turns": 3, "usage": {"input_tokens": 1000, "output_tokens": 200}})
        else:
            self.emit({"type": "item.completed", "item": {"id": "a", "type": "agent_message", "text": text}})
            self.emit({"type": "turn.completed", "usage": {"input_tokens": 1000, "cached_input_tokens": 0, "output_tokens": 200}})


def solo(args) -> int:
    """No Roundtable: the benchmark's 'alone' contender. Copies a prepared answer if the test gives one."""
    out = Out(args["app"])
    out.start("solo-1")
    out.think("Reading TASK.md and writing sheet.py.")
    src = os.environ.get("FAKE_SOLO_ANSWER")
    if src:
        Path(args.get("cwd") or os.getcwd(), "sheet.py").write_text(Path(src).read_text())
        out.edit("sheet.py")
    out.done("solo-1", "wrote sheet.py" if src else "gave up")
    return 0


def council(args) -> int:
    """Ask the table: answer, rank or combine, depending on the prompt (no Roundtable tools)."""
    import re

    out = Out(args["app"])
    model = args.get("model") or args.get("m") or "?"
    prompt = args.get("prompt") or ""
    with open(os.environ["FAKE_COUNCIL_LOG"], "a") if os.environ.get("FAKE_COUNCIL_LOG") else open(os.devnull, "w") as fh:
        fh.write(json.dumps({"model": model, "app": args["app"], "permission": args.get("permission-mode") or args.get("s"),
                             "kind": "rank" if "FINAL RANKING:" in prompt else "final" if "You write the final answer" in prompt
                             else "rescue" if "second opinion" in prompt else "answer"}) + "\n")
    if os.environ.get("FAKE_COUNCIL_FAIL") == model:
        sys.stderr.write("fake failure: not signed in\n")
        return 1
    out.start("council-1")
    out.think("Reading the project to answer.")
    if "FINAL RANKING:" in prompt:
        answers = re.findall(r"Answer ([A-H]):\n<<<\n(.*?)\n>>>", prompt, re.S)
        order = sorted(answers, key=lambda a: ("BEST" not in a[1], a[0]))
        text = "\n".join(f"Answer {label}: fine." for label, _t in answers) + "\nFINAL RANKING:\n" + "\n".join(
            f"{i}. Answer {label}" for i, (label, _t) in enumerate(order, 1))
    elif "You write the final answer" in prompt:
        text = f"Final answer by {model}: 42, as the best answer said."
    elif "second opinion" in prompt:
        text = f"Diagnosis from {model}: the test expects 'Hi' but the code returns 'hi'."
    else:
        text = f"{model} says 42." + (" BEST" if model == os.environ.get("FAKE_BEST_MODEL") else "")
    out.done("council-1", text)
    return 0


def main() -> int:
    args = parse(sys.argv[1:])
    no_mcp = not args.get("mcp_config") and not any(k.startswith("mcp_servers.") for k in args["overrides"]) \
        and not (args["app"] == "opencode" and "roundtable" in os.environ.get("OPENCODE_CONFIG_CONTENT", ""))
    if no_mcp and ("answering the same question" in (args.get("prompt") or "") or "FINAL RANKING:" in (args.get("prompt") or "")
                   or "You write the final answer" in (args.get("prompt") or "") or "second opinion" in (args.get("prompt") or "")):
        return council(args)
    if no_mcp:
        return solo(args)
    cmd, env = server_from(args)
    home = Path(env["RT_HOME"])
    me = env["RT_SEAT"]
    cwd = args.get("cwd") or os.getcwd()
    log = home / "fake-calls.log"
    with open(log, "a") as fh:
        fh.write(json.dumps({"seat": me, "app": args["app"], "resume": args.get("resume"), "model": args.get("model") or args.get("m"),
                             "effort": args.get("effort") or args["overrides"].get("model_reasoning_effort"),
                             "permission": args.get("permission-mode") or args.get("s") or args["overrides"].get("sandbox_mode")}) + "\n")
    if os.environ.get("FAKE_AGENT_FAIL") == me:
        sys.stderr.write("fake failure: not signed in\n")
        return 1
    if os.environ.get("FAKE_LIMIT") == me:      # what Claude Code printed when its plan ran out (October 2026)
        out = Out(args["app"])
        out.start("sess-limited")
        msg = "You've hit your session limit · resets 9:20pm (Asia/Kolkata)"
        if args["app"] == "claude":
            out.emit({"type": "assistant", "message": {"content": [{"type": "text", "text": msg}]}})
            out.emit({"type": "result", "subtype": "success", "is_error": True, "result": msg, "session_id": "sess-limited"})
        else:
            out.emit({"type": "error", "message": msg})
        return 1
    out = Out(args["app"])
    session = args.get("resume") or f"sess-{me}-1"
    out.start(session)
    mcp = Mcp(cmd, env, cwd)
    db = sqlite3.connect(f"file:{home / 'roundtable.db'}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    did = []
    try:
        out.tool("rt_sync", {})
        mcp.tool("rt_sync")
        for _ in range(12):
            step = next_step(db, me, cwd)
            if step is None:
                break
            thought, tool, params, edit = step
            out.think(thought)
            if os.environ.get("FAKE_AGENT_DELAY"):
                import time

                time.sleep(float(os.environ["FAKE_AGENT_DELAY"]))
            if edit:
                path = Path(cwd) / edit[0]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(edit[1])
                out.edit(str(path))
            out.tool(tool, params)
            reply = mcp.tool(tool, **params)
            did.append(f"{tool} {params.get('action', '')}: {reply.splitlines()[0] if reply else ''}")
    finally:
        mcp.close()
        db.close()
    out.done(session, "; ".join(did) or "nothing to do")
    return 0


def spec(owner: str, n: int) -> dict:
    return {"ref": str(n), "title": f"Greeting from {owner}", "summary": f"{owner} writes greet_{owner}.py",
            "files": [f"greet_{owner}.py"], "proof": [f"python -c \"import greet_{owner} as g; assert g.hello() == '{owner}'\""],
            "owner": owner}


def next_step(db, me: str, cwd: str):
    q = lambda sql, *a: db.execute(sql, a).fetchall()  # noqa: E731
    one = lambda sql, *a: db.execute(sql, a).fetchone()  # noqa: E731
    seats = [r["handle"] for r in q("SELECT handle FROM seats WHERE status = 'active' ORDER BY created_at")]
    p = one("SELECT * FROM plans WHERE stage NOT IN ('done','cancelled') ORDER BY id DESC LIMIT 1")
    if p is not None:
        planners = json.loads(p["planners"])
        if p["stage"] == "drafting" and me in planners and not one("SELECT 1 FROM drafts WHERE plan_id = ? AND author = ?", p["id"], me):
            return ("I'll write my own plan first.", "rt_plan",
                    {"action": "draft", "text": f"{me}: one greeting module per seat.", "tasks": [spec(s, i + 1) for i, s in enumerate(seats)]}, None)
        if p["stage"] == "critique":
            a = one("SELECT d.label FROM assignments a JOIN drafts d ON d.id = a.target WHERE a.kind = 'critique' AND a.seat = ? AND a.status = 'open'", me)
            if a:
                return (f"Plan {a['label']} looks fine but needs a test.", "rt_plan",
                        {"action": "critique", "draft": a["label"], "points": [{"verdict": "change", "text": "add a test for each module"}]}, None)
        if p["stage"] == "merging" and p["chair"] == me:
            return ("Combining the plans.", "rt_plan",
                    {"action": "propose", "text": "One greeting module per seat, each tested.", "tasks": [spec(s, i + 1) for i, s in enumerate(seats)]}, None)
        if p["stage"] == "proposed" and p["chair"] != me and not one(
                "SELECT 1 FROM approvals WHERE plan_id = ? AND version = ? AND seat = ?", p["id"], p["version"], me):
            return ("The combined plan covers everything.", "rt_plan", {"action": "approve"}, None)
    r = one("SELECT target FROM assignments WHERE kind = 'review' AND seat = ? AND status = 'open'", me)
    if r:
        if not one("SELECT 1 FROM events WHERE type = 'review.read' AND actor = ? AND task = ?", me, r["target"]):
            pass
        return (f"Checking {r['target']}.", "rt_review", {"action": "submit", "task": r["target"], "verdict": "approve", "points": ["works and is tested"]}, None)
    t = one("SELECT id, files FROM tasks WHERE owner = ? AND status IN ('claimed','changes_requested')", me)
    if t:
        return (f"Writing the code for {t['id']}.", "rt_task",
                {"action": "close", "task": t["id"], "summary": "greeting module", "commit": True},
                (f"greet_{me}.py", f"def hello():\n    return {me!r}\n"))
    t = one("SELECT id FROM tasks WHERE status = 'ready' AND (owner = ? OR owner IS NULL) ORDER BY seq", me)
    if t and not one("SELECT 1 FROM tasks WHERE owner = ? AND status IN ('proving','in_review')", me):
        return (f"Claiming {t['id']}.", "rt_task", {"action": "claim", "task": t["id"]}, None)
    return None


if __name__ == "__main__":
    sys.exit(main())

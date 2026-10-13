"""The MCP server: raw protocol behavior, and the official client end to end."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def rpc(lines: list, env: dict | None = None, cwd: Path | None = None, timeout: int = 30) -> list:
    """Run the server, feed it messages (dicts or raw strings), return parsed replies."""
    payload = "\n".join(m if isinstance(m, str) else json.dumps(m) for m in lines) + "\n"
    e = dict(os.environ)
    e.update(env or {})
    out = subprocess.run([sys.executable, "-m", "roundtable_ai", "mcp"], input=payload.encode(), capture_output=True,
                         env=e, cwd=str(cwd) if cwd else None, timeout=timeout)
    replies = [json.loads(line) for line in out.stdout.decode().splitlines() if line.strip()]
    return replies


INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}}


@pytest.fixture
def project(rt):
    rt.add_seat("opus")
    rt.add_seat("sol", model="gpt-5.6-sol", app="codex-cli")
    return rt


def test_handshake_versions_and_discover(project):
    env = {"RT_HOME": str(project.home)}
    newer = dict(INIT, id=2, params=dict(INIT["params"], protocolVersion="2099-01-01"))
    r = rpc([{"jsonrpc": "2.0", "id": 0, "method": "server/discover", "params": {}}, INIT, newer,
             {"jsonrpc": "2.0", "method": "notifications/initialized"}, {"jsonrpc": "2.0", "id": 3, "method": "ping"}], env)
    assert r[0]["error"]["code"] == -32601  # discover -> fall back to initialize
    assert r[1]["result"]["protocolVersion"] == "2025-06-18"
    assert r[1]["result"]["serverInfo"]["name"] == "roundtable"
    assert r[2]["result"]["protocolVersion"] == "2025-11-25"  # unknown version -> our latest
    assert r[3] == {"jsonrpc": "2.0", "id": 3, "result": {}}
    assert len(r) == 4  # the notification got no reply


def test_bad_json_batch_and_unknown(project):
    env = {"RT_HOME": str(project.home)}
    r = rpc(["{not json", [INIT, {"jsonrpc": "2.0", "id": 9, "method": "nope"}], "[]",
             {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "rt_nope", "arguments": {}}}], env)
    assert r[0]["error"]["code"] == -32700
    assert isinstance(r[1], list) and r[1][1]["error"]["code"] == -32601
    assert r[2]["error"]["code"] == -32600
    assert r[3]["error"]["code"] == -32602


def test_tools_list_schema(project):
    r = rpc([INIT, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}], {"RT_HOME": str(project.home)})
    tools = r[1]["result"]["tools"]
    assert [t["name"] for t in tools] == ["rt_sync", "rt_plan", "rt_task", "rt_lease", "rt_review", "rt_suggest", "rt_alert", "rt_vote", "rt_memory"]
    for t in tools:
        s = t["inputSchema"]
        assert s["type"] == "object" and "action" in s["properties"]
        for name, prop in s["properties"].items():
            assert "type" in prop, (t["name"], name)  # strict clients need a type on every property
        assert len(t["description"]) < 400


def call(name, args, id=10):
    return {"jsonrpc": "2.0", "id": id, "method": "tools/call", "params": {"name": name, "arguments": args}}


def test_join_key_flow_and_errors(project):
    env = {"RT_HOME": str(project.home)}
    r = rpc([INIT, call("rt_sync", {"join": "opus"}, 2)], env)
    text = r[1]["result"]["content"][0]["text"]
    assert "ROUNDTABLE: you are seat 'opus'" in text and r[1]["result"]["isError"] is False
    key = text.split('key="', 1)[1].split('"', 1)[0]
    r = rpc([INIT, call("rt_task", {"action": "ready", "key": key}, 2), call("rt_task", {"action": "claim", "key": key}, 3),
             call("rt_task", {"action": "ready", "key": key, "summary": "x"}, 4), call("rt_task", {"action": "ready", "key": key, "summary": ""}, 5),
             call("rt_task", {"action": "ready"}, 6), call("rt_task", {"key": key}, 7)], env)
    assert r[1]["result"]["isError"] is False and r[1]["result"]["content"][0]["text"].startswith("[rt:")
    assert r[2]["result"]["isError"] and "missing required parameter 'task'" in r[2]["result"]["content"][0]["text"]
    assert r[3]["result"]["isError"] and "belongs to" in r[3]["result"]["content"][0]["text"]
    assert r[4]["result"]["isError"] is False  # empty extras are ignored
    assert r[5]["result"]["isError"] and "join" in r[5]["result"]["content"][0]["text"]
    assert r[6]["result"]["isError"] and "needs an action" in r[6]["result"]["content"][0]["text"]


def test_pinned_seat_and_json_format(project):
    env = {"RT_HOME": str(project.home), "RT_SEAT": "sol"}
    r = rpc([INIT, call("rt_sync", {}, 2), call("rt_sync", {"format": "json"}, 3)], env)
    first = r[1]["result"]["content"][0]["text"]
    assert "ROUNDTABLE: you are seat 'sol'" in first and "no key needed" in first
    data = json.loads(r[2]["result"]["content"][0]["text"])
    assert data["ok"] is True and "since_event" in data["data"]


def test_server_starts_without_project(tmp_path):
    r = rpc([INIT, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, call("rt_sync", {"join": "opus"}, 3)], cwd=tmp_path)
    assert len(r[1]["result"]["tools"]) == 9
    out = r[2]["result"]
    assert out["isError"] and "not inside a Roundtable project" in out["content"][0]["text"]


def test_stdout_stays_clean(project):
    out = subprocess.run([sys.executable, "-m", "roundtable_ai", "mcp"], input=(json.dumps(INIT) + "\n").encode(),
                         capture_output=True, env=dict(os.environ, RT_HOME=str(project.home)), timeout=30)
    for line in out.stdout.decode().splitlines():
        json.loads(line)  # nothing but JSON on stdout
    assert b"started" in out.stderr


def test_official_client(project):
    pytest.importorskip("mcp")
    script = Path(__file__).with_name("mcp_client_check.py")
    out = subprocess.run([sys.executable, str(script), sys.executable, str(project.home), "opus"], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-3000:]
    assert out.stdout.startswith("OK mcp-client")

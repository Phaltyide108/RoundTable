"""App setup, CLI, launcher, doctor, watcher and dashboard."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from roundtable_ai import appsetup, errors


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("USERPROFILE", str(h))
    monkeypatch.setenv("APPDATA", str(h / "AppData"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(h / ".config"))
    monkeypatch.setenv("CODEX_HOME", str(h / ".codex"))
    return h


def run_rt(*args, cwd=None, env=None):
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run([sys.executable, "-m", "roundtable_ai", *args], capture_output=True, text=True, cwd=cwd, env=e, timeout=120)


# ---------------------------------------------------------------- setup

def test_setup_claude_code_merges_and_backs_up(rt, repo, fake_home):
    (repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"github": {"command": "gh-mcp"}}}))
    out = appsetup.setup("claude-code", home=str(rt.home))
    assert "added 'roundtable'" in out
    data = json.loads((repo / ".mcp.json").read_text())
    assert data["mcpServers"]["github"] == {"command": "gh-mcp"}
    rtentry = data["mcpServers"]["roundtable"]
    assert rtentry["command"] == sys.executable and rtentry["env"]["RT_HOME"] == str(rt.home)
    assert list(repo.glob(".mcp.json.rt-backup-*"))
    assert "already up to date" in appsetup.setup("claude-code", home=str(rt.home))
    assert "removed" in appsetup.setup("claude-code", home=str(rt.home), remove=True)
    assert "roundtable" not in json.loads((repo / ".mcp.json").read_text())["mcpServers"]


def test_setup_refuses_corrupt_json(rt, repo, fake_home):
    (repo / ".mcp.json").write_text("{ broken")
    with pytest.raises(errors.RTError) as e:
        appsetup.setup("claude-code", home=str(rt.home))
    assert "not valid JSON" in e.value.message
    assert (repo / ".mcp.json").read_text() == "{ broken"


def test_setup_claude_app_dry_run(rt, fake_home):
    out = appsetup.setup("claude-app", home=str(rt.home), dry_run=True)
    assert "would add" in out
    assert not appsetup.claude_desktop_config().exists()
    appsetup.setup("claude-app", home=str(rt.home))
    data = json.loads(appsetup.claude_desktop_config().read_text())
    assert "roundtable-proj" in data["mcpServers"]


def test_setup_codex_preserves_everything(rt, fake_home):
    cfg = appsetup.codex_config()
    cfg.parent.mkdir(parents=True)
    original = '# my settings\nmodel = "gpt-5.6"\n\n[mcp_servers.other]\ncommand = "node"\nargs = ["x.js"]\n\n[profiles.fast]\nmodel = "o4"\n'
    cfg.write_text(original)
    appsetup.setup("codex", home=str(rt.home))
    text = cfg.read_text()
    assert text.startswith(original.rstrip("\n"))
    parsed = appsetup.tomllib.loads(text)
    entry = parsed["mcp_servers"]["roundtable-proj"]
    assert entry["command"] == sys.executable and entry["env"]["RT_HOME"] == str(rt.home) and entry["tool_timeout_sec"] == 120
    assert parsed["profiles"]["fast"]["model"] == "o4"
    appsetup.setup("codex", home=str(rt.home))  # idempotent
    assert cfg.read_text().count("[mcp_servers.roundtable-proj]") == 1
    appsetup.setup("codex", home=str(rt.home), remove=True)
    assert cfg.read_text().strip() == original.strip()


def test_setup_codex_refuses_bad_toml(rt, fake_home):
    cfg = appsetup.codex_config()
    cfg.parent.mkdir(parents=True)
    cfg.write_text("model = \n")
    with pytest.raises(errors.RTError):
        appsetup.setup("codex", home=str(rt.home))
    assert cfg.read_text() == "model = \n"


# ---------------------------------------------------------------- CLI

def test_cli_getting_started_and_exit_codes(repo):
    out = run_rt(cwd=repo)
    assert out.returncode == 0 and "rt init" in out.stdout
    out = run_rt("status", cwd=repo)
    assert out.returncode == 1 and "rt init" in out.stderr
    out = run_rt("init", cwd=repo)
    assert out.returncode == 0 and "project created" in out.stdout
    out = run_rt("seat", "add", "opus", "--model", "claude-opus-5-5", "--app", "claude-code", cwd=repo)
    assert out.returncode == 0 and "working copy" in out.stdout
    out = run_rt("--json", "seat", "list", cwd=repo)
    assert json.loads(out.stdout)["data"]["seats"][0]["handle"] == "opus"
    out = run_rt("config", "set", "review.level", "extreme", cwd=repo)
    assert out.returncode == 1 and "low, mid, high" in out.stderr
    out = run_rt("call", "task.show", "task=T9", cwd=repo)
    assert out.returncode == 1 and "no task T9" in out.stderr
    out = run_rt("bogus", cwd=repo)
    assert out.returncode == 2
    out = run_rt("freeze", "lunch", cwd=repo)
    assert out.returncode == 0
    out = run_rt("--seat", "opus", "call", "task.ready", cwd=repo)
    assert out.returncode == 1 and "STOP" in out.stderr
    assert run_rt("unfreeze", cwd=repo).returncode == 0
    out = run_rt("log", "--limit", "3", cwd=repo)
    assert "#" in out.stdout


# ---------------------------------------------------------------- launch

def fake_bin(dir_: Path, name: str) -> None:
    dir_.mkdir(exist_ok=True)
    p = dir_ / name
    p.write_text("#!/bin/sh\necho fake\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)


@pytest.mark.skipif(os.name == "nt", reason="shell script stand-ins")
def test_launch_print(rt, tmp_path, monkeypatch):
    bins = tmp_path / "bin"
    fake_bin(bins, "claude")
    fake_bin(bins, "codex")
    monkeypatch.setenv("PATH", f"{bins}{os.pathsep}{os.environ['PATH']}")
    rt.add_seat("opus", worktree=True)
    rt.add_seat("sol", model="gpt-5.6-sol", app="codex-cli", worktree=True)
    rt.add_seat("fable", model="claude-fable-5", app="claude-app")
    out = run_rt("launch", "opus", "--print", cwd=rt.root, env={"PATH": os.environ["PATH"]})
    line = out.stdout.splitlines()[-1]
    assert "claude" in line and "--mcp-config" in line and "--model claude-opus-5-5" in line
    assert line.index("You are Roundtable seat opus") < line.index("--mcp-config")  # prompt before the variadic option
    seat_cfg = json.loads((rt.home / "seats" / "opus" / "mcp.json").read_text())
    assert seat_cfg["mcpServers"]["roundtable"]["env"]["RT_SEAT"] == "opus"
    out = run_rt("launch", "sol", "--print", cwd=rt.root, env={"PATH": os.environ["PATH"]})
    line = out.stdout.splitlines()[-1]
    assert "codex" in line and "-m gpt-5.6-sol" in line and "mcp_servers.roundtable-proj.env=" in line
    out = run_rt("launch", "fable", cwd=rt.root)
    assert "join Roundtable as fable" in out.stdout


def test_launch_missing_app(rt, monkeypatch):
    rt.add_seat("opus", worktree=True)
    monkeypatch.setenv("PATH", "/nonexistent")
    from roundtable_ai.launch import launch

    with pytest.raises(errors.RTError) as e:
        launch("opus", home=str(rt.home), print_only=True)
    assert "not installed" in e.value.message


# ---------------------------------------------------------------- doctor / watch

def test_doctor(rt, fake_home):
    rt.add_seat("opus", worktree=True)
    from roundtable_ai.doctor import run_doctor

    text, ok = run_doctor(str(rt.home))
    assert ok, text
    assert "working copy" in text and "commit guard installed" in text
    wt = Path(rt.q("SELECT worktree FROM seats")[0]["worktree"])
    subprocess.run(["git", "-C", str(rt.root), "worktree", "remove", "--force", str(wt)], check=True)
    text, ok = run_doctor(str(rt.home))
    assert not ok and "rt seat worktree opus" in text


def test_watch_notifies_once_and_wakes(rt, monkeypatch):
    rt.add_seat("opus", worktree=True)
    rt.add_seat("sol", model="gpt-5.6-sol", app="codex-cli", worktree=True)
    sent, woke = [], []
    from roundtable_ai import launch, notify, watch

    monkeypatch.setattr(notify, "send", lambda t, b, home=None: sent.append(t) or True)
    monkeypatch.setattr(launch, "start_headless", lambda ctx, row, prompt, log: woke.append(row["handle"]) or 4242)
    rt.seat("opus", "alert.raise", level=5, title="secret leaked", evidence="config.py:3")
    watch.watch(str(rt.home), once=True)
    watch.watch(str(rt.home), once=True)
    assert sum("L5" in s for s in sent) == 1
    assert woke == ["sol"]  # once, rate limited


# ---------------------------------------------------------------- dashboard

def test_dashboard_security(rt):
    from roundtable_ai import dashboard

    ref: dict = {}
    ready = threading.Event()
    t = threading.Thread(target=dashboard.serve, args=(rt.home, 18765), kwargs={"open_browser": False, "ready": ready, "server_ref": ref}, daemon=True)
    t.start()
    assert ready.wait(10)
    port, token = ref["port"], ref["token"]
    base = f"http://127.0.0.1:{port}"
    page = urllib.request.urlopen(base + "/").read().decode()
    assert token in page and "Sabha" in page
    state = json.loads(urllib.request.urlopen(base + "/api/state").read())
    assert state["project"]["review"] == "low"

    def post(body, headers=None):
        req = urllib.request.Request(base + "/api/action", data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", **(headers or {})})
        try:
            return json.loads(urllib.request.urlopen(req).read())
        except urllib.error.HTTPError as e:
            return json.loads(e.read())

    assert post({"op": "admin.freeze", "params": {}})["ok"] is False
    assert post({"token": token, "op": "seat.remove", "params": {"handle": "x"}})["ok"] is False
    assert post({"token": token, "op": "admin.freeze", "params": {}}, {"Origin": "http://evil.example"})["ok"] is False
    assert "not available" in post({"token": token, "op": "task.claim", "params": {"task": "T1"}})["message"]  # seat-only
    assert post({"token": token, "op": "admin.freeze", "params": {"reason": "test"}})["ok"] is True
    assert json.loads(urllib.request.urlopen(base + "/api/state").read())["project"]["frozen"] is True
    req = urllib.request.Request(base + "/api/state", headers={"Host": "evil.example"})
    with pytest.raises(urllib.error.HTTPError):
        urllib.request.urlopen(req)
    ref["httpd"].shutdown()

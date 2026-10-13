"""The dashboard can do everything the terminal can: set up, add and start models, plan, review."""

from __future__ import annotations

import json
import os
import stat
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from roundtable_ai import dashboard, desktop


class Client:
    def __init__(self, home, folder=None, port=18900):
        self.ref: dict = {}
        ready = threading.Event()
        t = threading.Thread(target=dashboard.serve, args=(home, port), daemon=True,
                             kwargs={"open_browser": False, "ready": ready, "server_ref": self.ref, "folder": folder})
        t.start()
        assert ready.wait(10)
        self.base = f"http://127.0.0.1:{self.ref['port']}"
        self.token = self.ref["token"]

    def get(self, path):
        return json.loads(urllib.request.urlopen(self.base + path, timeout=20).read())

    def raw(self, path):
        return urllib.request.urlopen(self.base + path, timeout=20)

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps({"token": self.token, **body}).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            return json.loads(urllib.request.urlopen(req, timeout=60).read())
        except urllib.error.HTTPError as exc:
            return json.loads(exc.read())

    def act(self, op, **params):
        return self.post("/api/action", {"op": op, "params": params})

    def close(self):
        self.ref["httpd"].shutdown()


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    return tmp_path


def test_setup_then_full_project_from_the_dashboard(repo, fake_home, monkeypatch):
    c = Client(None, folder=repo, port=18910)
    try:
        st = c.get("/api/state")
        assert st["mode"] == "setup" and st["setup"]["git"] and st["setup"]["has_commits"]
        page = c.raw("/").read().decode()
        assert c.token in page and "app.js" in page
        resp = c.raw("/app.js")
        assert "javascript" in resp.headers["Content-Type"] and "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]
        assert c.post("/api/do", {"kind": "init", "folder": str(repo)})["ok"]
        st = c.get("/api/state")
        assert st["mode"] == "project" and st["project"]["git"]
        assert any(n["key"] == "no-seats" for n in st["needs"])
        assert c.get("/api/state")["getting_started"][0]["done"] is False
        r = c.act("seat.add", handle="opus", model="claude-opus-5-5", app="claude-code", roles=["plan", "build", "review"])
        assert r["ok"], r
        assert c.act("seat.add", handle="sol", model="gpt-6.1-sol", app="codex-vscode")["ok"]
        st = c.get("/api/state")
        seats = {x["handle"]: x for x in st["seats"]}
        assert seats["opus"]["start"]["kind"] == "terminal" and seats["sol"]["start"]["kind"] == "vscode"
        assert seats["opus"]["worktree"] and any(n["key"] == "not-started" for n in st["needs"])
        assert c.act("plan.goal", goal="Add a greeting", review="mid")["ok"]
        st = c.get("/api/state")
        assert st["plan"]["stage"] == "drafting" and st["project"]["review"] == "mid"
        assert {p["seat"] for p in st["plan"]["people"]} == {"opus", "sol"}
        assert c.act("task.file", title="Write docs", kind="docs")["ok"]
        st = c.get("/api/state")
        tid = next(t["id"] for t in st["tasks"] if t["title"] == "Write docs")
        assert st["counts"]["backlog"] == 1 and any(n["key"] == "backlog" for n in st["needs"])
        detail = c.get(f"/api/task?id={tid}")
        assert detail["status"] == "backlog" and detail["filed_by"] == "human"
        assert c.get(f"/api/diff?task={tid}")["task"] == tid
        assert c.act("memory.add", text="Run tests with uv")["ok"]
        assert c.get("/api/state")["memories"][0]["pinned"] is True
        log = c.get("/api/log?q=greeting")
        assert log["events"] and all("greeting" in e["text"].lower() or e["actor"] == "greeting" for e in log["events"])
        doc = c.get("/api/doctor")
        assert any(i["status"] == "ok" for i in doc["items"])
        assert c.act("admin.config_set", key="proof.timeout_seconds", value="600")["ok"]
        assert c.act("task.claim", task="T1")["message"].startswith("action")
        from roundtable_ai.paths import recent_projects

        assert recent_projects()[0]["root"] == str(repo.resolve())
    finally:
        c.close()


def test_start_opens_a_terminal_or_says_what_to_run(rt, fake_home, monkeypatch, tmp_path):
    if os.name == "nt":
        pytest.skip("terminal detection differs on Windows; covered by terminal_command tests")
    rt.add_seat("opus", worktree=True)
    record = tmp_path / "args.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "gnome-terminal"
    fake.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$@\" > {record}\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin")
    monkeypatch.delenv("TERMINAL", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    c = Client(rt.home, port=18930)
    try:
        r = c.post("/api/do", {"kind": "start", "handle": "opus"})
        assert r["ok"] and r["join"] == "join Roundtable as opus"
        for _ in range(50):
            if record.exists() and record.read_text():
                break
            import time
            time.sleep(0.1)
        args = record.read_text().splitlines()
        assert args[0].startswith("--working-directory=") and "--" in args
        assert "roundtable_ai" in args[-1] and "launch opus" in args[-1]
        monkeypatch.setenv("PATH", str(tmp_path / "empty"))
        desktop.terminal_command  # noqa: B018
        r = c.post("/api/do", {"kind": "start", "handle": "opus"})
        assert r["ok"] is False and r["command"] == "rt launch opus"
    finally:
        c.close()


def test_terminal_and_editor_commands_per_platform(tmp_path):
    which = {"gnome-terminal": "/usr/bin/gnome-terminal", "konsole": "/usr/bin/konsole", "bash": "/bin/bash"}.get
    cmd = desktop.terminal_command(["rt", "launch", "opus"], "/p q", "Roundtable opus", platform="linux", which=which)
    assert cmd[:3] == ["/usr/bin/gnome-terminal", "--working-directory=/p q", "--"]
    assert "cd '/p q' && rt launch opus" in cmd[-1]
    mac = desktop.terminal_command(["rt", "launch", "opus"], "/p", "t", platform="darwin", which=which)
    assert mac[0] == "osascript" and any("do script" in x for x in mac)
    win = desktop.terminal_command(["C:\\py\\python.exe", "-m", "roundtable_ai", "launch", "opus"], "C:\\p", "Roundtable opus", platform="win32", which=which)
    assert win[:2] == ["cmd.exe", "/k"] and "launch opus" in win[2]
    assert desktop.terminal_command(["x"], "/", "t", platform="linux", which=lambda n: None) is None
    assert desktop.vscode_command("/p", platform="linux", which={"code": "/usr/bin/code"}.get) == ["/usr/bin/code", "--new-window", "/p"]


def test_switching_projects_and_refusing_bad_folders(rt, fake_home, tmp_path):
    other = tmp_path / "plain"
    other.mkdir()
    c = Client(rt.home, port=18950)
    try:
        assert c.post("/api/do", {"kind": "open", "folder": str(tmp_path / "missing")})["ok"] is False
        assert c.post("/api/do", {"kind": "open", "folder": str(other)})["ok"]
        st = c.get("/api/state")
        assert st["mode"] == "setup" and st["setup"]["git"] is False and st["recent"][0]["root"] == str(rt.root)
        assert c.post("/api/do", {"kind": "open", "folder": str(rt.root)})["ok"]
        assert c.get("/api/state")["mode"] == "project"
        assert c.post("/api/do", {"kind": "folder", "path": "/etc"})["ok"] is False
    finally:
        c.close()


def test_a_terminal_that_fails_is_reported(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("POSIX shell script")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    bad = bin_dir / "xterm"
    bad.write_text("#!/bin/sh\nexit 2\n")
    bad.chmod(0o755)
    # only the fake terminal on PATH: a real one (gnome-terminal...) would be picked first and open a window
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.delenv("TERMINAL", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    from roundtable_ai.errors import RTError

    with pytest.raises(RTError) as exc:
        desktop.open_terminal(["rt", "launch", "opus"], tmp_path, "Roundtable opus")
    assert "exit 2" in exc.value.message and "rt launch opus" in exc.value.hint


def test_dashboard_speaks_plainly_and_links_to_real_pages(rt, fake_home):
    """Every link in 'what needs you' opens one of the dashboard's sections, labels avoid jargon,
    and the page loads nothing from outside this computer."""
    import re

    from roundtable_ai import ui_state

    rt.add_seat("opus")
    rt.human("task.file", title="Write docs", kind="docs")
    ctx = rt.ctx()
    try:
        st = ui_state.build(ctx)
    finally:
        ctx.close()
    pages = {"home", "inbox", "team", "plan", "work", "usage", "notes", "history", "settings", "help", "more", "switch"}
    gos = [a["go"] for n in st["needs"] for a in n["actions"] if a.get("go")]
    assert gos and all(g.split("/")[0] in pages for g in gos), gos
    words = " ".join([*ui_state.STATUS_LABEL.values(), *ui_state.STAGE_LABEL.values(), *(n["title"] for n in st["needs"])]).lower()
    for jargon in ("backlog", "lock", "seat", "proof", "review depth"):
        assert jargon not in words, jargon
    ui = dashboard.UI_DIR
    js = (ui / "app.js").read_text(encoding="utf-8")
    for page in pages:
        assert f"PAGES.{page} =" in js, page
    for name in ("index.html", "app.css", "app.js"):
        text = (ui / name).read_text(encoding="utf-8")
        assert not re.search(r"""(src|href)=["']https?:|url\(\s*["']?https?:|@import""", text), name

"""Fixes found by running the real Claude Code and Codex in the background, and the desktop app.

- Codex refused every Roundtable tool in `codex exec` ("approval policy is never");
- a quick-mode planner saw the goal cut at 80 characters and dropped the other seat's part;
- proof commands that cannot run here (`python` missing, no pytest) were only found after the work;
- a seat waiting on an amendment it asked for was woken again and again;
- activity showed Roundtable's inbox line instead of the error, and Codex's shell wrapper.
"""

from __future__ import annotations

import json
import shutil
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

from roundtable_ai import activity, appsetup, icon, launch, proofs, runner, window
from roundtable_ai.errors import RTError

TASK = {"ref": "1", "title": "A", "files": ["src/app.py"], "proof": ["true"], "owner": None}


# ---------------------------------------------------------------- proof commands that cannot run here

def test_proof_problem_names_the_missing_program(monkeypatch):
    monkeypatch.delenv("RT_PROOF_CHECK", raising=False)
    assert "not installed" in proofs.proof_problem("surely-not-a-real-program-rt --flag")
    assert proofs.proof_problem(f'"{sys.executable}" -c "print(1)"') is None
    assert proofs.proof_problem("cd src && surely-not-a-real-program-rt") is None   # only the first program is checked
    assert proofs.proof_problem("FOO=1 BAR=2 surely-not-a-real-program-rt").startswith("`surely-not")
    assert proofs.proof_problem("./scripts/test.sh") is None                         # may be created by the task itself


def test_proof_problem_suggests_python3(monkeypatch):
    monkeypatch.delenv("RT_PROOF_CHECK", raising=False)
    real = shutil.which
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: None if name == "python" else (real(name, *a, **k) or f"/usr/bin/{name}"))
    assert proofs.proof_problem("python -m unittest") == "`python` is not installed on this computer; use `python3`"


def test_plan_with_unrunnable_proof_is_refused(rt, monkeypatch):
    monkeypatch.delenv("RT_PROOF_CHECK", raising=False)
    rt.add_seat("opus")
    rt.human("plan.goal", goal="g", mode="quick")
    e = rt.error(rt.seat, "opus", "plan.propose", text="t", tasks=[dict(TASK, proof=["surely-not-a-real-program-rt"])])
    assert "can't run here" in e.message and "not installed" in e.message
    rt.seat("opus", "plan.propose", text="t", tasks=[dict(TASK, proof=[f'"{sys.executable}" -c "pass"'])])


# ---------------------------------------------------------------- quick mode sees the whole goal

def test_quick_planner_gets_the_whole_goal(rt):
    rt.add_seat("opus")
    rt.add_seat("sol", model="gpt-6.1-sol", app="codex-cli")
    goal = "opus: add slugify(text) to textkit.py with tests in test_slug.py. " + "x" * 120 + " sol: add word_count(text) to counting.py"
    rt.human("plan.goal", goal=goal, mode="quick", planners="opus")
    view = rt.seat("opus", "plan.view").text
    assert "Cover the WHOLE goal" in view and "opus, sol" in view and "sol: add word_count" in view
    assert "depends_on for every task whose code it imports" in view          # no proofs that wait on each other
    ctx = rt.ctx()
    try:
        work = runner.pending(ctx, "opus")
    finally:
        ctx.close()
    assert any("sol: add word_count(text) to counting.py" in text for _k, text in work)
    assert "rt_plan view first" in rt.seat("opus", "sync").text


# ---------------------------------------------------------------- a blocked seat is not woken again

def test_seat_waiting_on_its_own_amendment_is_not_woken(rt):
    rt.add_seat("opus", worktree=True)
    rt.add_seat("sol", model="gpt-6.1-sol", app="codex-cli")
    rt.human("plan.goal", goal="g", mode="quick", planners="opus")
    rt.seat("opus", "plan.propose", text="t", tasks=[dict(TASK, owner="opus")])
    rt.human("plan.lock")
    rt.seat("opus", "sync")
    rt.seat("opus", "task.claim", task="T1")
    ctx = rt.ctx()
    try:
        assert any(k.startswith("task:T1") for k, _t in runner.pending(ctx, "opus"))
    finally:
        ctx.close()
    rt.seat("opus", "plan.amend", kind="change_proof", task="T1", change={"proof": ["true"]}, reason="the proof needs python3")
    ctx = rt.ctx()
    try:
        assert not any(k.startswith("task:T1") for k, _t in runner.pending(ctx, "opus"))
    finally:
        ctx.close()


# ---------------------------------------------------------------- Codex may call Roundtable's tools without a prompt

def test_codex_gets_roundtable_tools_preapproved(rt):
    ctx = rt.ctx()
    try:
        flags = " ".join(launch._codex_overrides(ctx, "sol"))
    finally:
        ctx.close()
    assert 'default_tools_approval_mode="approve"' in flags
    assert 'default_tools_approval_mode = "approve"' in appsetup._toml_block("roundtable-x", rt.home)


# ---------------------------------------------------------------- what the dashboard shows

def test_error_line_skips_inbox_and_joins_exit_code():
    assert activity._error_line("[rt: 1 new]\nerror [state]: you have 1 unread update") == "error [state]: you have 1 unread update"
    assert activity._error_line("Exit code 2\nls: cannot access 'tests'") == "Exit code 2: ls: cannot access 'tests'"


def test_codex_items_unwrap_shell_and_show_tool_errors():
    assert activity._codex_command("/bin/bash -lc 'git status; ls'") == "git status; ls"
    ev = {"type": "item.completed", "item": {"type": "mcp_tool_call", "tool": "rt_sync", "error": {"message": "user cancelled MCP tool call"}}}
    assert activity.from_codex_exec(ev) == [{"kind": "error", "text": "user cancelled MCP tool call"}]
    ok = {"type": "item.completed", "item": {"type": "mcp_tool_call", "tool": "rt_sync", "result": {"content": [{"type": "text", "text": "fine"}]}}}
    assert activity.from_codex_exec(ok) == []


# ---------------------------------------------------------------- the desktop app

def test_icon_formats():
    png = icon.png(32)
    assert png.startswith(b"\x89PNG\r\n\x1a\n") and b"IHDR" in png
    assert icon.ico(png)[:6] == b"\0\0\1\0\1\0"
    data = icon.icns(png)
    assert data[:4] == b"icns" and int.from_bytes(data[4:8], "big") == len(data)


@pytest.mark.skipif(sys.platform == "win32", reason="pretending to be Linux on Windows would break pathlib for the whole process")
def test_menu_entry_on_linux(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    lines = window.install()
    desktop = tmp_path / "share" / "applications" / "ai.roundtable.Roundtable.desktop"
    text = desktop.read_text()
    assert "Exec=" in text and "roundtable_ai app --foreground" in text and "StartupWMClass=ai.roundtable.Roundtable" in text
    assert (tmp_path / "share" / "icons" / "hicolor" / "256x256" / "apps" / "ai.roundtable.Roundtable.png").exists()
    assert window.installed() and "app menu" in lines[0]
    window.install(remove=True)
    assert not desktop.exists() and not window.installed()


def test_app_bundle_on_macos(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(window.Path, "home", classmethod(lambda cls: tmp_path))
    window.install()
    app = tmp_path / "Applications" / "Sabha.app" / "Contents"
    assert "CFBundleExecutable" in (app / "Info.plist").read_text()
    assert "roundtable_ai app --foreground" in (app / "MacOS" / "Sabha").read_text()
    assert (app / "Resources" / "roundtable.icns").read_bytes()[:4] == b"icns"
    window.install(remove=True)
    assert not app.exists()


def test_open_window_falls_back_to_the_browser(monkeypatch):
    opened = []
    monkeypatch.setattr(window.webbrowser, "open", lambda url: opened.append(url))
    proc, how = window.open_window("http://127.0.0.1:1/", prefer="browser")
    assert proc is None and how == "browser" and opened == ["http://127.0.0.1:1/"]


def test_server_records_when_a_page_last_asked(rt):
    from roundtable_ai import dashboard

    ref: dict = {}
    ready = threading.Event()
    t = threading.Thread(target=dashboard.serve, args=(rt.home, 0), kwargs={"open_browser": False, "ready": ready, "server_ref": ref, "quiet": True},
                         daemon=True)
    t.start()
    assert ready.wait(10)
    try:
        assert "last" not in ref
        with urllib.request.urlopen(f"http://127.0.0.1:{ref['port']}/api/state", timeout=10) as r:
            assert json.loads(r.read())
        assert ref["last"] > 0
    finally:
        ref["httpd"].shutdown()


def test_default_home_is_the_most_recent_project(rt, tmp_path, monkeypatch):
    from roundtable_ai.paths import remember_project

    remember_project(rt.root, "proj")
    monkeypatch.chdir(tmp_path)
    assert Path(window.default_home()) == rt.home
    monkeypatch.chdir(rt.root)
    assert window.default_home() is None


def test_login_path_is_added(monkeypatch, tmp_path):
    if sys.platform == "win32":
        pytest.skip("no login shell on Windows")
    shell = tmp_path / "fakeshell"
    shell.write_text('#!/bin/sh\nprintf "__RT_PATH__/opt/fake/bin:/usr/bin__RT_PATH__"\n')
    shell.chmod(0o755)
    monkeypatch.setenv("SHELL", str(shell))
    monkeypatch.setenv("PATH", "/usr/bin")
    window.adopt_login_path()
    assert window.os.environ["PATH"].split(window.os.pathsep)[:2] == ["/opt/fake/bin", "/usr/bin"]


def test_rt_app_install_from_cli(tmp_path, monkeypatch, capsys):
    from roundtable_ai import cli

    monkeypatch.setattr(window, "install", lambda remove=False: ["removed" if remove else "added"])
    assert cli.main(["app", "--install"]) == 0
    assert "added" in capsys.readouterr().out
    assert cli.main(["app", "--uninstall"]) == 0
    assert "removed" in capsys.readouterr().out


def test_rt_error_is_importable():
    assert RTError


def test_setup_screen_in_the_home_folder_offers_choosing_a_project(tmp_path, monkeypatch):
    from roundtable_ai import ui_state

    monkeypatch.setattr(window.Path, "home", classmethod(lambda cls: tmp_path))
    assert ui_state.setup_state(tmp_path)["setup"]["is_home"] is True
    (tmp_path / "proj").mkdir()
    assert ui_state.setup_state(tmp_path / "proj")["setup"]["is_home"] is False


def test_folder_chooser_command_per_platform():
    from roundtable_ai import desktop

    assert desktop.folder_picker_command("Pick", "/home/a", platform="darwin")[0] == "osascript"
    assert desktop.folder_picker_command("Pick", "C:\\Users\\a", platform="win32")[0] == "powershell"
    has = lambda names: (lambda n: f"/usr/bin/{n}" if n in names else None)  # noqa: E731
    assert desktop.folder_picker_command("Pick", "/home/a", platform="linux", which=has({"zenity"}))[:3] == ["zenity", "--file-selection", "--directory"]
    assert desktop.folder_picker_command("Pick", "/home/a", platform="linux", which=has({"kdialog"}))[0] == "kdialog"

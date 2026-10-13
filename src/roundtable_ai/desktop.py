"""Open things on the person's computer for the dashboard: a terminal window
running a command, a folder in VS Code.

Every function returns what it did in plain words, or raises RTError with the
command to run by hand, so the dashboard can always offer a copyable fallback.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

from .errors import NOT_FOUND, RTError

Which = Callable[[str], "str | None"]


def _keep_open(cmd: str) -> str:
    """POSIX shell line that runs cmd and leaves the window open afterwards."""
    return f"{cmd}; status=$?; echo; echo \"Roundtable: this window's model has stopped (exit $status). You can close it.\"; exec \"${{SHELL:-bash}}\" -l"


def terminal_command(argv: list[str], cwd: str, title: str, *, platform: str | None = None,
                     which: Which = shutil.which) -> list[str] | None:
    """The command that opens a new terminal window running argv in cwd, or None if no terminal is known."""
    platform = platform or sys.platform
    if platform.startswith("win"):  # run in a new console window (see _spawn); /k keeps it open
        return ["cmd.exe", "/k", f"title {title} && {subprocess.list2cmdline(argv)}"]
    shell_line = _keep_open(f"cd {shlex.quote(cwd)} && " + " ".join(shlex.quote(a) for a in argv))
    if platform == "darwin":
        script = shell_line.replace("\\", "\\\\").replace('"', '\\"')
        return ["osascript", "-e", 'tell application "Terminal"', "-e", "activate",
                "-e", f'do script "{script}"', "-e", "end tell"]
    bash = which("bash") or "/bin/sh"
    run = [bash, "-lc", shell_line]
    preferred = os.environ.get("TERMINAL", "").strip()
    candidates = ([preferred] if preferred else []) + ["gnome-terminal", "ptyxis", "konsole", "xfce4-terminal", "mate-terminal",
                                                        "kitty", "alacritty", "wezterm", "foot", "x-terminal-emulator", "xterm"]
    for name in candidates:
        exe = which(name)
        if not exe:
            continue
        base = os.path.basename(name)
        if base == "gnome-terminal":  # --title is deprecated in recent versions, so it is left out
            return [exe, f"--working-directory={cwd}", "--", *run]
        if base == "ptyxis":
            return [exe, "--new-window", f"--working-directory={cwd}", "--", *run]
        if base == "konsole":
            return [exe, "--workdir", cwd, "-p", f"tabtitle={title}", "-e", *run]
        if base in ("xfce4-terminal", "mate-terminal"):
            return [exe, f"--title={title}", f"--working-directory={cwd}", "-x", *run]
        if base == "kitty":
            return [exe, "--title", title, "--directory", cwd, *run]
        if base == "alacritty":
            return [exe, "--title", title, "--working-directory", cwd, "-e", *run]
        if base == "wezterm":
            return [exe, "start", "--cwd", cwd, "--", *run]
        if base == "foot":
            return [exe, f"--title={title}", f"--working-directory={cwd}", *run]
        return [exe, "-T", title, "-e", *run]  # x-terminal-emulator, xterm and most others
    return None


def _spawn(cmd: list[str], cwd: str, *, console: bool = False) -> subprocess.Popen:
    kwargs: dict = {"cwd": cwd, "stdin": subprocess.DEVNULL}
    if not console:
        kwargs.update(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.name == "nt":
        # CREATE_NEW_CONSOLE for a terminal window; otherwise DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        kwargs["creationflags"] = 0x00000010 if console else 0x00000008 | 0x00000200
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)


def open_terminal(argv: list[str], cwd: str | Path, title: str) -> str:
    cwd = str(cwd)
    cmd = terminal_command(argv, cwd, title)
    if cmd is None:
        raise RTError(NOT_FOUND, "no terminal program found to open a window",
                      "run this in a terminal yourself: " + manual_line(argv, cwd))
    try:
        proc = _spawn(cmd, cwd, console=os.name == "nt")
    except OSError as exc:
        raise RTError(NOT_FOUND, f"could not open a terminal ({exc})", "run this in a terminal yourself: " + manual_line(argv, cwd)) from None
    try:  # a terminal that rejects its arguments exits at once with an error; say so instead of failing silently
        code = proc.wait(timeout=1.5)
    except subprocess.TimeoutExpired:
        code = None
    if code not in (None, 0):
        raise RTError(NOT_FOUND, f"{os.path.basename(cmd[0])} could not open a window (exit {code})",
                      "run this in a terminal yourself: " + manual_line(argv, cwd))
    return f"opened a terminal window for {title.replace('Roundtable ', '')}"


def manual_line(argv: list[str], cwd: str | Path) -> str:
    if os.name == "nt":
        return f'cd /d "{cwd}" && {subprocess.list2cmdline(argv)}'
    return f"cd {shlex.quote(str(cwd))} && " + " ".join(shlex.quote(a) for a in argv)


def vscode_command(folder: str, *, platform: str | None = None, which: Which = shutil.which) -> list[str] | None:
    platform = platform or sys.platform
    for name in ("code", "code-insiders", "codium"):
        exe = which(name)
        if exe:
            return [exe, "--new-window", folder]
    if platform == "darwin" and Path("/Applications/Visual Studio Code.app").exists():
        return ["open", "-a", "Visual Studio Code", folder]
    return None


def open_vscode(folder: str | Path) -> str:
    folder = str(folder)
    cmd = vscode_command(folder)
    if cmd is None:
        raise RTError(NOT_FOUND, "VS Code's `code` command was not found",
                      f"open VS Code, choose File > Open Folder, and pick {folder} (or in VS Code run 'Shell Command: Install code command in PATH')")
    try:
        _spawn(cmd, folder)
    except OSError as exc:
        raise RTError(NOT_FOUND, f"could not start VS Code ({exc})", f"open {folder} in VS Code yourself") from None
    return f"opened {folder} in VS Code"


def has_terminal() -> bool:
    return terminal_command(["true"], ".", "x") is not None


def has_vscode() -> bool:
    return vscode_command(".") is not None


EDITORS = {"cursor": ("cursor", "/Applications/Cursor.app", "Cursor")}


def open_editor(app: str, folder: str | Path) -> str:
    """Open a folder in an editor app that has its own command (Cursor)."""
    folder = str(folder)
    cmd_name, mac_app, label = EDITORS.get(app, (app, "", app))
    exe = shutil.which(cmd_name)
    if exe:
        cmd = [exe, folder]
    elif sys.platform == "darwin" and mac_app and Path(mac_app).exists():
        cmd = ["open", "-a", label, folder]
    else:
        raise RTError(NOT_FOUND, f"{label}'s `{cmd_name}` command was not found", f"open {label} and choose File > Open Folder: {folder}")
    try:
        _spawn(cmd, folder)
    except OSError as exc:
        raise RTError(NOT_FOUND, f"could not start {label} ({exc})", f"open {folder} in {label} yourself") from None
    return f"opened {folder} in {label}"


def open_folder(folder: str | Path) -> str:
    """Show a folder in the file manager."""
    folder = str(folder)
    if os.name == "nt":
        cmd = ["explorer", folder]
    elif sys.platform == "darwin":
        cmd = ["open", folder]
    else:
        exe = shutil.which("xdg-open")
        if not exe:
            raise RTError(NOT_FOUND, "no file manager command (xdg-open) found", f"open {folder} yourself")
        cmd = [exe, folder]
    try:
        _spawn(cmd, folder)
    except OSError as exc:
        raise RTError(NOT_FOUND, f"could not open the folder ({exc})", f"open {folder} yourself") from None
    return f"opened {folder}"

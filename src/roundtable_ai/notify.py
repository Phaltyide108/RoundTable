"""Desktop notifications for the human (best effort; never raises)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import util


def _log(home: Path | None, title: str, body: str) -> None:
    if home is None:
        return
    try:
        d = Path(home) / "logs"
        d.mkdir(exist_ok=True)
        with open(d / "notifications.log", "a", encoding="utf-8") as fh:
            fh.write(f"{util.now()} {title}: {body}\n")
    except OSError:
        pass


def send(title: str, body: str, home: Path | None = None) -> bool:
    """Show a desktop notification. Returns True if a notifier ran."""
    title, body = util.one_line(title, 80), util.one_line(body, 240)
    _log(home, title, body)
    if os.environ.get("RT_NO_NOTIFY") == "1":
        return False
    try:
        if sys.platform == "darwin" and shutil.which("osascript"):
            script = f"display notification {_applescript(body)} with title {_applescript(title)}"
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
            return True
        if sys.platform.startswith("linux") and shutil.which("notify-send"):
            subprocess.run(["notify-send", "--app-name=Roundtable", title, body], capture_output=True, timeout=10)
            return True
        if os.name == "nt" and shutil.which("powershell"):
            ps = (
                "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
                "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
                f"$x = $t.GetElementsByTagName('text'); $x.Item(0).AppendChild($t.CreateTextNode({_ps(title)})) > $null;"
                f"$x.Item(1).AppendChild($t.CreateTextNode({_ps(body)})) > $null;"
                "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Roundtable').Show([Windows.UI.Notifications.ToastNotification]::new($t))"
            )
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, timeout=15)
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    print(f"[roundtable] {title}: {body}", file=sys.stderr)
    return False


def _applescript(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _ps(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"

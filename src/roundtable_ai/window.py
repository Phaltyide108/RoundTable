"""Roundtable as an application: its own window and an entry in your app menu, not a browser tab.

`rt app` (and `rt ui`) runs the dashboard server inside this process and shows it in a
window of its own, the first of these that works:

1. Linux: a native GTK window with WebKit, the desktop's own web view (python3-gi and
   WebKitGTK ship with GNOME and most desktops), run by the system Python;
2. Chrome, Edge, Brave, Chromium or Vivaldi in app mode: a plain window with no tabs or
   address bar, using its own profile so it never mixes with your browsing (Edge is part
   of every Windows 10/11);
3. your default browser, as a last resort.

Closing the window ends the dashboard. Background runs keep going: they are their own
processes. `rt app --install` adds Roundtable to the app menu: a .desktop entry on Linux,
~/Applications/Sabha.app on macOS, a Start menu shortcut on Windows.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

APP_ID = "ai.roundtable.Roundtable"
TITLE = "Sabha"
IDLE_SECONDS = 12            # after its window closes, the server waits this long for other windows still polling


# ---------------------------------------------------------------- the environment a menu launch lacks

def adopt_login_path() -> None:
    """Apps started from a desktop menu do not get the PATH your terminal has (~/.local/bin, nvm, ...),
    so `claude` or `codex` would not be found. Ask the login shell once and add what is missing."""
    if os.name == "nt":
        return
    shell = os.environ.get("SHELL") or "/bin/sh"
    try:
        out = subprocess.run([shell, "-ilc", 'printf "__RT_PATH__%s__RT_PATH__" "$PATH"'], capture_output=True, text=True,
                             timeout=8, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return
    m = re.search(r"__RT_PATH__(.*?)__RT_PATH__", out.stdout or "", re.S)
    if not m:
        return
    have = os.environ.get("PATH", "").split(os.pathsep)
    extra = [p for p in m.group(1).split(os.pathsep) if p and p not in have]
    if extra:
        os.environ["PATH"] = os.pathsep.join(extra + have)


# ---------------------------------------------------------------- which window

def config_dir() -> Path:
    from .paths import user_config_dir

    return user_config_dir()


def _gtk_python() -> str | None:
    """A Python that has GTK and WebKit bindings (Linux), or None."""
    if sys.platform != "linux" or os.environ.get("RT_WINDOW") in ("browser", "chromium"):
        return None
    seen = set()
    for cand in ("/usr/bin/python3", shutil.which("python3", path="/usr/local/bin:/usr/bin:/bin")):
        if not cand or cand in seen or not Path(cand).exists():
            continue
        seen.add(cand)
        probe = ("import gi\n"
                 "for g, w, n in (('4.0','6.0','WebKit'), ('3.0','4.1','WebKit2'), ('3.0','4.0','WebKit2')):\n"
                 "    try:\n        gi.require_version('Gtk', g); gi.require_version(n, w); break\n"
                 "    except ValueError: pass\n"
                 "else:\n    raise SystemExit(3)\n")
        try:
            if subprocess.run([cand, "-I", "-c", probe], capture_output=True, timeout=15).returncode == 0:
                return cand
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def chromium_paths() -> list[str]:
    names = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "microsoft-edge-stable",
             "brave-browser", "brave", "vivaldi", "vivaldi-stable"]
    out = [p for p in (shutil.which(n) for n in names) if p]
    if sys.platform == "darwin":
        for base in ("/Applications", str(Path.home() / "Applications")):
            for app, exe in (("Google Chrome", "Google Chrome"), ("Microsoft Edge", "Microsoft Edge"), ("Brave Browser", "Brave Browser"),
                             ("Chromium", "Chromium"), ("Vivaldi", "Vivaldi")):
                p = Path(base) / f"{app}.app" / "Contents" / "MacOS" / exe
                if p.exists():
                    out.append(str(p))
    if os.name == "nt":
        roots = [os.environ.get(k) for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
        for root in filter(None, roots):
            for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe",
                        r"BraveSoftware\Brave-Browser\Application\brave.exe", r"Chromium\Application\chrome.exe"):
                p = Path(root) / rel
                if p.exists():
                    out.append(str(p))
    return list(dict.fromkeys(out))


def _assets() -> Path:
    """Icon files the window and the menu entry use (written once, from the bundled drawing)."""
    from . import icon

    d = config_dir() / "app"
    try:
        d.mkdir(parents=True, exist_ok=True)
        svg = d / f"{APP_ID}.svg"
        src = Path(__file__).parent / "ui" / "icon.svg"
        if not svg.exists() or svg.read_bytes() != src.read_bytes():
            svg.write_bytes(src.read_bytes())
            (d / f"{APP_ID}.png").write_bytes(icon.png(256))
        elif not (d / f"{APP_ID}.png").exists():
            (d / f"{APP_ID}.png").write_bytes(icon.png(256))
    except OSError:
        pass
    return d


def _popen(cmd: list[str], **kw) -> subprocess.Popen:
    kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.PIPE}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000  # no console window
    kwargs.update(kw)
    return subprocess.Popen(cmd, **kwargs)


def open_window(url: str, prefer: str | None = None) -> tuple[subprocess.Popen | None, str]:
    """Open `url` in a window of its own. Returns (process to wait for or None, what was used)."""
    prefer = prefer or os.environ.get("RT_WINDOW") or ""
    assets = _assets()
    if prefer not in ("browser", "chromium"):
        py = _gtk_python()
        if py:
            script = Path(__file__).parent / "webview_gtk.py"
            proc = _popen([py, "-I", str(script), url, TITLE, str(assets), str(config_dir() / "window.json"),
                           str(config_dir() / "webview")])
            if _survives(proc, 1.5):
                return proc, "window"
    if prefer != "browser":
        for exe in chromium_paths():
            profile = config_dir() / "app-profile"
            cmd = [exe, f"--app={url}", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
                   f"--class={APP_ID}", "--window-size=1440,920", "--disable-features=Translate"]
            proc = _popen(cmd)
            if _survives(proc, 2.0):
                return proc, "app-mode window (" + Path(exe).stem + ")"
    try:
        webbrowser.open(url)
    except Exception:
        pass
    return None, "browser"


def _survives(proc: subprocess.Popen, seconds: float) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        time.sleep(0.1)
    return True


# ---------------------------------------------------------------- run

def default_home() -> str | None:
    """When started from the app menu (not inside a project), open the most recent project."""
    from .paths import HOME_DIR, recent_projects

    cwd = Path.cwd()
    for d in (cwd, *cwd.parents):
        if (d / HOME_DIR).is_dir():
            return None
    recent = recent_projects()
    return str(Path(recent[0]["root"]) / HOME_DIR) if recent else None


def run(home: str | None = None, *, port: int | None = None, prefer: str | None = None) -> int:
    """Start the dashboard server and show it in its own window until the window closes."""
    from . import dashboard

    adopt_login_path()
    if home is None and not sys.stdin.isatty():
        home = default_home()
    ref: dict[str, Any] = {}
    ready = threading.Event()
    box: dict[str, Any] = {}

    def serve():
        try:
            dashboard.run_dashboard(home, port=port, open_browser=False, ready=ready, server_ref=ref, quiet=True)
        except BaseException as exc:  # noqa: BLE001 - shown below
            box["error"] = exc
            ready.set()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    ready.wait(30)
    if "error" in box:
        raise box["error"]
    if "httpd" not in ref:
        print("Sabha could not start its dashboard", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{ref['port']}/"
    proc, how = open_window(url, prefer)
    print(f"Sabha is open ({how}): {url}", flush=True)
    try:
        if proc is not None:
            proc.wait()
            _wait_idle(ref, IDLE_SECONDS)
        else:
            # a browser tab: keep serving while the page keeps asking; stop a while after it is closed
            _wait_idle(ref, 90, first=300)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            ref["httpd"].shutdown()
        except Exception:
            pass
    return 0


def _wait_idle(ref: dict, quiet: float, first: float | None = None) -> None:
    """Return once no page has asked the server anything for `quiet` seconds."""
    start = time.time()
    while True:
        last = float(ref.get("last") or 0)
        limit = quiet if last > start or first is None else first
        if time.time() - max(last, start) > limit:
            return
        time.sleep(1)


def start_detached(home: str | None, *, port: int | None = None, prefer: str | None = None) -> int:
    """`rt app` from a terminal: start the app as its own process and give the terminal back."""
    cmd = [sys.executable, "-m", "roundtable_ai"] + (["--home", home] if home else []) + ["app", "--foreground"]
    if port:
        cmd += ["--port", str(port)]
    if prefer == "browser":
        cmd += ["--browser"]
    log = config_dir() / "app.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL, "cwd": os.getcwd()}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000
    else:
        kwargs["start_new_session"] = True
    with open(log, "ab") as fh:
        p = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, **kwargs)
    return p.pid


# ---------------------------------------------------------------- the app-menu entry

def _python_for_menu() -> str:
    exe = Path(sys.executable)
    if os.name == "nt":
        w = exe.with_name("pythonw.exe")
        if w.exists():
            return str(w)
    return str(exe)


def _desktop_file() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "applications" / f"{APP_ID}.desktop"


def install(remove: bool = False) -> list[str]:
    """Add Sabha to the app menu (or take it out again). Only touches its own files (and the older Roundtable entries)."""
    from . import icon

    lines: list[str] = []
    if sys.platform == "darwin":
        app = Path.home() / "Applications" / "Sabha.app"
        old = Path.home() / "Applications" / "Roundtable.app"          # the name before Sabha
        for gone in (app, old) if remove else (old,):
            if gone.exists():
                shutil.rmtree(gone)
                lines.append(f"removed {gone}")
        if remove:
            return lines or ["Sabha was not in ~/Applications"]
        (app / "Contents" / "MacOS").mkdir(parents=True, exist_ok=True)
        (app / "Contents" / "Resources").mkdir(parents=True, exist_ok=True)
        (app / "Contents" / "Info.plist").write_text(_PLIST, encoding="utf-8")
        exe = app / "Contents" / "MacOS" / "Sabha"
        exe.write_text(f'#!/bin/sh\nexec "{_python_for_menu()}" -m roundtable_ai app --foreground "$@"\n', encoding="utf-8")
        exe.chmod(0o755)
        (app / "Contents" / "Resources" / "roundtable.icns").write_bytes(icon.icns())
        lines.append(f"added {app}: open it from Launchpad or Spotlight (\"Sabha\")")
        return lines
    if os.name == "nt":
        start = Path(os.environ.get("APPDATA") or Path.home()) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        lnk = start / "Sabha.lnk"
        for gone in (lnk, start / "Roundtable.lnk") if remove else (start / "Roundtable.lnk",):
            if gone.exists():
                gone.unlink()
                lines.append(f"removed {gone}")
        if remove:
            return lines or ["Sabha was not in the Start menu"]
        ico = config_dir() / "app" / "roundtable.ico"
        ico.parent.mkdir(parents=True, exist_ok=True)
        ico.write_bytes(icon.ico())
        ps = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:RT_LNK); $s.TargetPath = $env:RT_PY; "
              "$s.Arguments = '-m roundtable_ai app --foreground'; $s.IconLocation = $env:RT_ICO; "
              "$s.WorkingDirectory = $env:USERPROFILE; $s.Description = 'Sabha'; $s.Save()")
        env = dict(os.environ, RT_LNK=str(lnk), RT_PY=_python_for_menu(), RT_ICO=str(ico))
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, text=True, env=env)
        if r.returncode != 0:
            from .errors import STATE, RTError

            raise RTError(STATE, "could not create the Start menu shortcut: " + (r.stderr or r.stdout).strip()[:300],
                          "start Sabha with: rt app")
        return lines + [f"added Sabha to the Start menu ({lnk})"]
    desktop = _desktop_file()
    icons = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "icons" / "hicolor"
    svg = icons / "scalable" / "apps" / f"{APP_ID}.svg"
    png = icons / "256x256" / "apps" / f"{APP_ID}.png"
    if remove:
        for p in (desktop, svg, png):
            if p.exists():
                p.unlink()
                lines.append(f"removed {p}")
        return lines or ["Sabha was not in the app menu"]
    svg.parent.mkdir(parents=True, exist_ok=True)
    png.parent.mkdir(parents=True, exist_ok=True)
    svg.write_bytes((Path(__file__).parent / "ui" / "icon.svg").read_bytes())
    png.write_bytes(icon.png(256))
    desktop.parent.mkdir(parents=True, exist_ok=True)
    py = _python_for_menu()
    exec_line = " ".join(f'"{p}"' if " " in p else p for p in (py, "-m", "roundtable_ai", "app", "--foreground"))
    desktop.write_text("\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Name=Sabha",
        "GenericName=AI team workspace",
        "Comment=Several AI models plan, build and review your project together",
        f"Exec={exec_line}",
        f"Icon={APP_ID}",
        "Terminal=false",
        "Categories=Development;",
        "Keywords=AI;Claude;Codex;agents;council;Roundtable;",
        f"StartupWMClass={APP_ID}",
        "StartupNotify=true",
        "",
    ]), encoding="utf-8")
    desktop.chmod(0o755)
    for tool in (["update-desktop-database", str(desktop.parent)], ["gtk-update-icon-cache", "-q", "-t", str(icons)]):
        if shutil.which(tool[0]):
            try:
                subprocess.run(tool, capture_output=True, timeout=20)
            except (OSError, subprocess.SubprocessError):
                pass
    lines.append(f"added Sabha to the app menu ({desktop}); find it by typing \"Sabha\"")
    return lines


_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Sabha</string>
  <key>CFBundleDisplayName</key><string>Sabha</string>
  <key>CFBundleIdentifier</key><string>ai.roundtable.Roundtable</string>
  <key>CFBundleExecutable</key><string>Sabha</string>
  <key>CFBundleIconFile</key><string>roundtable</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSUIElement</key><false/>
</dict>
</plist>
"""


def installed() -> bool:
    if sys.platform == "darwin":
        return (Path.home() / "Applications" / "Sabha.app").exists()
    if os.name == "nt":
        return (Path(os.environ.get("APPDATA") or Path.home()) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Sabha.lnk").exists()
    return _desktop_file().exists()


def describe() -> dict[str, Any]:
    """What `rt app` would use on this computer (for rt doctor and the tests)."""
    return {"gtk_python": _gtk_python(), "chromium": chromium_paths(), "menu_entry": installed()}


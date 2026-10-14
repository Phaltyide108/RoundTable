"""`rt ui`: the dashboard. Everything a person does with Roundtable can be done here.

Standard library only. The page itself lives in ui/ (index.html, app.css, app.js).

Safety: listens on 127.0.0.1 only; checks the Host header (blocks DNS
rebinding); every change needs a per-run token embedded in the page and a
same-origin request. Models never talk to the dashboard: it acts as the human.
"""

from __future__ import annotations

import json
import secrets
import socketserver
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .errors import CONFLICT, FORBIDDEN, INVALID, NOT_FOUND, RTError

UI_DIR = Path(__file__).parent / "ui"
STATIC = {"/app.css": ("app.css", "text/css; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/icon.svg": ("icon.svg", "image/svg+xml"), "/fonts/atkinson-next.woff2": ("fonts/atkinson-next.woff2", "font/woff2")}
DEFAULT_PORT = 8765


class Session:
    """Which project the dashboard is showing; it can switch without restarting."""

    def __init__(self, home: Path | None, folder: Path):
        self.home = home
        self.folder = folder
        self.lock = threading.Lock()

    def open_ctx(self):
        from .context import open_ctx

        if self.home is None:
            raise RTError(NOT_FOUND, "no project is open", "set one up or open one first")
        return open_ctx(self.home, client="dashboard")

    def switch(self, home: Path) -> None:
        from .paths import project_root, remember_project

        with self.lock:
            self.home = home
            self.folder = project_root(home)
        try:
            ctx = self.open_ctx()
            try:
                remember_project(ctx.root, ctx.setting("project", "name") or ctx.root.name)
            finally:
                ctx.close()
        except RTError:
            pass


def state(home) -> dict[str, Any]:
    """Kept for callers of the old API: the full dashboard state for one project."""
    from . import ui_state
    from .context import open_ctx

    ctx = open_ctx(home, client="dashboard")
    try:
        return ui_state.build(ctx)
    finally:
        ctx.close()


def _allowed(op_name: str) -> bool:
    from . import registry

    registry.load_all()
    o = registry.OPS.get(op_name)
    return o is not None and o.who in (registry.HUMAN, registry.ANY) and op_name not in ("seat.join",)


def do_special(session: Session, kind: str, body: dict) -> dict[str, Any]:
    """Things that are not plain operations: set up, open, start a model, connect an app."""
    from . import appsetup, apps, desktop, launch, project, seats
    from .paths import DB_NAME, HOME_DIR

    if kind in ("open", "init"):
        folder = Path(str(body.get("folder") or "")).expanduser()
        if not str(folder).strip() or not folder.is_dir():
            raise RTError(INVALID, f"{folder} is not a folder on this computer", "type the full path of your project folder")
        folder = folder.resolve()
        if kind == "init":
            home, lines = project.init_project(folder, name=(body.get("name") or None))
            session.switch(home)
            return {"text": "\n".join(lines)}
        if (folder / HOME_DIR / DB_NAME).exists():
            session.switch(folder / HOME_DIR)
            return {"text": f"opened {folder}"}
        with session.lock:
            session.home, session.folder = None, folder
        return {"text": f"{folder} has no Roundtable project yet"}

    if kind == "close":
        with session.lock:
            session.home = None
        return {"text": "closed"}

    ctx = session.open_ctx()
    try:
        if kind == "connect":
            app = str(body.get("app") or "")
            if app not in ("claude-code", "claude-app", "codex", "copilot"):
                raise RTError(INVALID, f"unknown app {app!r}")
            text = appsetup.setup(app, home=str(ctx.home), dry_run=bool(body.get("preview")), remove=bool(body.get("remove")))
            return {"text": text}
        if kind == "start":
            row = seats.get(ctx, str(body.get("handle") or "").lower())
            if row["status"] != "active":
                raise RTError(CONFLICT, f"{row['handle']} is {row['status']}", "resume it first")
            app = apps.get(row["app"])
            info = launch.start_info(ctx, row)
            if app.folder and row["worktree"]:
                appsetup.seat_folder_config(ctx, row["handle"])
            if app.start == "terminal":
                if seats.is_live(ctx, row):
                    raise RTError(CONFLICT, f"{row['handle']} is already live in another chat",
                                  "use that window; if you closed it, choose Free the seat and start again")
                argv = launch.terminal_argv(ctx, row["handle"])
                try:
                    text = desktop.open_terminal(argv, ctx.root, f"Roundtable {row['handle']}")
                except RTError as exc:
                    exc.data = {"command": f"rt launch {row['handle']}", "folder": str(ctx.root)}  # type: ignore[attr-defined]
                    raise
                return {"text": text, "join": info["join"]}
            if app.start == "vscode":
                return {"text": desktop.open_vscode(info["folder"]), "join": info["join"], "steps": info["steps"]}
            if app.start == "editor":
                return {"text": desktop.open_editor(row["app"], info["folder"]), "join": info["join"], "steps": info["steps"]}
            return {"text": "follow these steps", "join": info["join"], "steps": info["steps"]}
        if kind == "folder":  # open a seat's working copy (or the project) in the file manager
            target = str(body.get("path") or ctx.root)
            allowed = {str(ctx.root)} | {r["worktree"] for r in ctx.db.all("SELECT worktree FROM seats WHERE worktree IS NOT NULL")}
            if target not in allowed:
                raise RTError(FORBIDDEN, "only the project folder and the models' working copies can be opened from here")
            return {"text": desktop.open_folder(target)}
        raise RTError(INVALID, f"unknown request {kind!r}")
    finally:
        ctx.close()


def make_handler(session: Session, token: str, port_ref: dict):
    from . import dispatch, ui_state

    class Handler(BaseHTTPRequestHandler):
        server_version = "Roundtable"

        def log_message(self, fmt: str, *args) -> None:  # quiet
            pass

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").lower()
            return host in (f"127.0.0.1:{port_ref['port']}", f"localhost:{port_ref['port']}")

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
                             "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: Any) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"), "application/json; charset=utf-8")

        def _error(self, exc: RTError) -> None:
            out = exc.to_dict()
            out.update(getattr(exc, "data", None) or {})
            self._json(200, out)

        def do_GET(self) -> None:
            if not self._host_ok():
                return self._json(403, {"ok": False, "message": "bad host"})
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path in ("/", "/index.html"):
                page = (UI_DIR / "index.html").read_text(encoding="utf-8").replace("__TOKEN__", token)
                return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            if url.path in STATIC:
                name, ctype = STATIC[url.path]
                return self._send(200, (UI_DIR / name).read_bytes(), ctype)
            try:
                if url.path == "/api/state":
                    if session.home is None:
                        return self._json(200, ui_state.setup_state(session.folder))
                    ctx = session.open_ctx()
                    try:
                        return self._json(200, ui_state.build(ctx))
                    finally:
                        ctx.close()
                if url.path in ("/api/task", "/api/diff", "/api/log"):
                    ctx = session.open_ctx()
                    try:
                        if url.path == "/api/task":
                            return self._json(200, ui_state.task_detail(ctx, q.get("id", "")))
                        if url.path == "/api/diff":
                            return self._json(200, ui_state.diff(ctx, q.get("task", "")))
                        before = int(q["before"]) if q.get("before", "").isdigit() else None
                        return self._json(200, {"events": ui_state._events(ctx, limit=100, before=before, query=q.get("q") or None,
                                                                           task=q.get("task") or None)})
                    finally:
                        ctx.close()
                if url.path == "/api/doctor":
                    from . import doctor

                    r = doctor.check(str(session.home) if session.home else None)
                    return self._json(200, {"items": r.items, "failed": r.failed})
            except RTError as exc:
                return self._error(exc)
            return self._json(404, {"ok": False, "message": "not found"})

        def do_POST(self) -> None:
            if not self._host_ok():
                return self._json(403, {"ok": False, "message": "bad host"})
            origin = self.headers.get("Origin")
            if origin and origin.lower() not in (f"http://127.0.0.1:{port_ref['port']}", f"http://localhost:{port_ref['port']}"):
                return self._json(403, {"ok": False, "message": "cross-site request refused"})
            if self.path not in ("/api/action", "/api/do"):
                return self._json(404, {"ok": False, "message": "not found"})
            try:
                length = min(int(self.headers.get("Content-Length") or 0), 400_000)
                body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            except (ValueError, UnicodeDecodeError):
                return self._json(400, {"ok": False, "message": "bad request"})
            if not isinstance(body, dict) or not secrets.compare_digest(str(body.get("token", "")), token):
                return self._json(403, {"ok": False, "message": "missing or wrong token; reload the page"})
            try:
                if self.path == "/api/do":
                    out = do_special(session, str(body.get("kind") or ""), body)
                    return self._json(200, {"ok": True, **out})
                op = str(body.get("op") or "")
                params = body.get("params") or {}
                if not _allowed(op) or not isinstance(params, dict):
                    return self._json(400, {"ok": False, "message": f"action {op!r} is not available here"})
                if session.home is None:
                    raise RTError(NOT_FOUND, "no project is open", "set one up or open one first")
                res = dispatch.call(op, params, home=session.home, as_human=True, client="dashboard")
                return self._json(200, {"ok": True, "text": res.text, "data": res.data})
            except RTError as exc:
                return self._error(exc)

    return Handler


class _LocalServer(ThreadingHTTPServer):
    """HTTPServer.server_bind looks up the host's full name, which can stall for
    many seconds on some Macs. We only ever bind 127.0.0.1, so skip it."""

    daemon_threads = True

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]


def serve(home, port: int, *, open_browser: bool = True, ready: threading.Event | None = None, server_ref: dict | None = None,
          folder: Path | None = None) -> int:
    from .paths import project_root

    session = Session(Path(home) if home else None, Path(folder) if folder else (project_root(Path(home)) if home else Path.cwd()))
    if session.home is not None:
        session.switch(session.home)
    token = secrets.token_urlsafe(24)
    port_ref = {"port": port}
    httpd = None
    for p in range(port, port + 20):
        try:
            port_ref["port"] = p
            httpd = _LocalServer(("127.0.0.1", p), make_handler(session, token, port_ref))
            break
        except OSError:
            continue
    if httpd is None:
        raise RTError("conflict", f"ports {port}-{port + 19} are all busy", "pass another: rt ui --port 9000")
    if server_ref is not None:
        server_ref.update({"httpd": httpd, "port": port_ref["port"], "token": token, "session": session})
    url = f"http://127.0.0.1:{port_ref['port']}/"
    print(f"Roundtable dashboard: {url}  (only this computer can open it; Ctrl+C to stop)")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    if ready:
        ready.set()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


def run_dashboard(home: str | None = None, *, port: int | None = None, open_browser: bool = True) -> int:
    """Open the dashboard on this project, or on the set-up screen if there is none here yet."""
    from .context import open_ctx
    from .paths import resolve_home_arg

    try:
        ctx = open_ctx(home)
    except RTError:
        folder = Path(home).expanduser() if home else Path.cwd()
        if folder.name == ".roundtable":
            folder = folder.parent
        try:
            h = resolve_home_arg(folder) if home else None
        except RTError:
            h = None
        if h is not None and (h / "roundtable.db").exists():
            return serve(h, port or DEFAULT_PORT, open_browser=open_browser)
        return serve(None, port or DEFAULT_PORT, open_browser=open_browser, folder=folder)
    try:
        h = ctx.home
        p = port or ctx.setting("dashboard", "port")
    finally:
        ctx.close()
    return serve(h, p, open_browser=open_browser)

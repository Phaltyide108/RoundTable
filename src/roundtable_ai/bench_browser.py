"""Scoring a benchmark task that runs in a browser (the koi pond).

The contender's folder is served on 127.0.0.1 and opened in headless Chrome (or Edge,
Brave, Chromium), driven through the Chrome DevTools Protocol with a tiny WebSocket
client written here (standard library only). The task's hidden checks.js runs inside
the page; Python adds the checks only a browser can make (script errors while loading,
a real picture on screen, following a window resize) and saves a screenshot next to the
contender's folder so a person can look at it too.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


class BrowserError(Exception):
    pass


def find_browser() -> str | None:
    from . import window

    paths = window.chromium_paths()
    return paths[0] if paths else None


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:  # noqa: D401 - silence
        pass


class CDP:
    """Just enough of the DevTools Protocol: call a method, collect events."""

    def __init__(self, ws_url: str, timeout: float = 30):
        host, path = ws_url[len("ws://"):].split("/", 1)
        h, p = host.split(":")
        self.sock = socket.create_connection((h, int(p)), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET /{path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise BrowserError("the browser closed the connection")
            buf += chunk
        self.buf = buf.split(b"\r\n\r\n", 1)[1]
        self.next_id = 0
        self.events: list[dict] = []

    def _send(self, obj: dict) -> None:
        data = json.dumps(obj).encode()
        head = bytearray([0x81])
        n = len(data)
        if n < 126:
            head.append(0x80 | n)
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        head += mask
        self.sock.sendall(bytes(head) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _need(self, k: int) -> None:
        while len(self.buf) < k:
            chunk = self.sock.recv(1 << 20)
            if not chunk:
                raise BrowserError("the browser closed the connection")
            self.buf += chunk

    def _frame(self) -> bytes:
        out = b""
        while True:
            self._need(2)
            b1, b2 = self.buf[0], self.buf[1]
            n, off = b2 & 0x7F, 2
            if n == 126:
                self._need(4)
                n, off = struct.unpack(">H", self.buf[2:4])[0], 4
            elif n == 127:
                self._need(10)
                n, off = struct.unpack(">Q", self.buf[2:10])[0], 10
            self._need(off + n)
            out += self.buf[off:off + n]
            self.buf = self.buf[off + n:]
            if b1 & 0x80:
                return out

    def call(self, method: str, params: dict | None = None, timeout: float = 60) -> dict:
        self.next_id += 1
        mid = self.next_id
        self._send({"id": mid, "method": method, "params": params or {}})
        self.sock.settimeout(timeout)
        while True:
            msg = json.loads(self._frame())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise BrowserError(f"{method}: {msg['error'].get('message')}")
                return msg.get("result", {})
            if "method" in msg:
                self.events.append(msg)

    def evaluate(self, expr: str, timeout: float = 60) -> Any:
        r = self.call("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True}, timeout=timeout)
        if r.get("exceptionDetails"):
            ex = r["exceptionDetails"]
            raise BrowserError((ex.get("exception") or {}).get("description") or ex.get("text") or "script error")
        return (r.get("result") or {}).get("value")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def score_browser(task_dir: Path, folder: Path, checks: list[str], *, shot: Path | None = None, timeout: int = 300) -> dict[str, Any]:
    """Serve `folder`, open its index.html in a headless browser, run the hidden checks."""
    total = len(checks)
    exe = find_browser()
    if not exe:
        return {"passed": 0, "total": total, "failed": ["(no Chrome, Edge, Brave or Chromium to run the page in)"]}
    if not (Path(folder) / "index.html").exists():
        return {"passed": 0, "total": total, "failed": ["(index.html is missing)"]}
    results: dict[str, list] = {}
    with tempfile.TemporaryDirectory(prefix="rt-bench-browser-") as tmp:
        work = Path(tmp) / "site"
        shutil.copytree(folder, work, ignore=shutil.ignore_patterns(".git", ".roundtable", "__pycache__", "node_modules"))
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(_Quiet, directory=str(work)))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        port = _free_port()
        proc = subprocess.Popen([exe, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={Path(tmp) / 'profile'}",
                                 "--no-first-run", "--no-default-browser-check", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
                                 "--ignore-gpu-blocklist", "--window-size=1280,800", "--hide-scrollbars", "about:blank"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cdp = None
        try:
            ws = None
            for _ in range(100):
                try:
                    tabs = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2).read())
                    ws = next((t["webSocketDebuggerUrl"] for t in tabs if t.get("type") == "page"), None)
                    if ws:
                        break
                except Exception:
                    pass
                time.sleep(0.2)
            if not ws:
                raise BrowserError("the browser did not start")
            cdp = CDP(ws)
            cdp.call("Runtime.enable")
            cdp.call("Page.enable")
            cdp.call("Page.navigate", {"url": f"http://127.0.0.1:{httpd.server_address[1]}/index.html"})
            ready = False
            deadline = time.time() + 40
            while time.time() < deadline:
                try:
                    if cdp.evaluate("!!(window.pond && window.pond.fish && window.pond.fish.length)", timeout=10):
                        ready = True
                        break
                except BrowserError:
                    pass
                time.sleep(0.5)
            time.sleep(2.0)       # let it draw a few frames
            errors = [e for e in cdp.events if e.get("method") == "Runtime.exceptionThrown"]
            text = "; ".join(((e["params"].get("exceptionDetails") or {}).get("exception") or {}).get("description", "error").splitlines()[0] for e in errors[:3])
            results["no_script_errors"] = [not errors, text or "no uncaught errors while loading"]
            png = base64.b64decode(cdp.call("Page.captureScreenshot", {"format": "png"}, timeout=60)["data"])
            if shot:
                try:
                    Path(shot).write_bytes(png)
                except OSError:
                    pass
            results["renders_a_scene"] = [len(png) > 40_000, f"screenshot of {len(png) // 1024} KB (a blank page is a few KB)"]
            if ready:
                js = (task_dir / "hidden" / "checks.js").read_text(encoding="utf-8")
                try:
                    got = cdp.evaluate(f"({js})()", timeout=timeout) or {}
                    results.update({k: list(v) for k, v in got.items()})
                except BrowserError as exc:
                    results["test_interface"] = [False, f"the checks stopped: {str(exc).splitlines()[0][:200]}"]
                before = cdp.evaluate("(() => { const c = document.querySelector('canvas'); return c ? c.width : 0; })()") or 0
                cdp.call("Emulation.setDeviceMetricsOverride", {"width": 900, "height": 600, "deviceScaleFactor": 1, "mobile": False})
                time.sleep(1.0)
                after = cdp.evaluate("(() => { const c = document.querySelector('canvas'); return c ? [c.width, c.clientWidth, innerWidth] : [0, 0, 0]; })()") or [0, 0, 0]
                results["follows_window_resize"] = [after[0] != before and abs(after[1] - after[2]) <= 2, f"canvas {before} -> {after[0]} px wide for a {after[2]} px window"]
            else:
                results["test_interface"] = [False, "window.pond with fish never appeared"]
        except (BrowserError, OSError, ValueError) as exc:
            results.setdefault("test_interface", [False, f"could not run the page: {exc}"])
        finally:
            if cdp:
                cdp.close()
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            httpd.shutdown()
    passed = [c for c in checks if results.get(c, [False])[0]]
    failed = [f"{c} ({results[c][1]})" if c in results else f"{c} (not reached)" for c in checks if c not in passed]
    return {"passed": len(passed), "total": total, "failed": failed, "details": {c: results.get(c) for c in checks}}

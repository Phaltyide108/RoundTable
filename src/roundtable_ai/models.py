"""Which models each app offers, for the model pickers in the app.

- Claude Code: its current models (any other name Claude Code accepts can still be typed);
- Codex: the list Codex itself keeps in ~/.codex/models_cache.json;
- opencode: every model `opencode models --verbose` lists, with price, context size and the
  thinking levels each one offers. Free models (price 0) are marked, so they are easy to find.

Lists are kept for an hour in Roundtable's user folder; nothing here ever fails: a missing app
gives an empty list and the picker still takes any name.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

CACHE_SECONDS = 3600
CLAUDE = [
    ("claude-opus-5-5", "Claude Opus 5.5", "Most capable"),
    ("claude-fable-5-1", "Claude Fable 5.1", "Creative and long-form"),
    ("claude-sonnet-5-5", "Claude Sonnet 5.5", "Fast and strong"),
    ("claude-haiku-5-5", "Claude Haiku 5.5", "Fastest, lightest"),
]
CLAUDE_EFFORTS = ["low", "medium", "high", "xhigh", "max"]
CODEX_EFFORTS = ["minimal", "low", "medium", "high", "xhigh"]


def _cache_file(app: str) -> Path:
    from .paths import user_config_dir

    return user_config_dir() / "models" / f"{app}.json"


def for_app(app: str, *, refresh: bool = False) -> dict[str, Any]:
    """{"app", "models": [{"id", "name", "note", "free", "efforts", "context"}], "source"}"""
    app = str(app or "")
    if app in ("claude-code", "claude-vscode", "claude-app"):
        return {"app": app, "source": "Claude Code's current models", "models": [
            {"id": i, "name": n, "note": note, "free": False, "efforts": CLAUDE_EFFORTS, "context": None} for i, n, note in CLAUDE]}
    if app in ("codex-cli", "codex-vscode", "codex-app"):
        return {"app": app, "source": "Codex's own model list", "models": codex_models()}
    if app == "opencode":
        return {"app": app, "source": "opencode models", "models": opencode_models(refresh=refresh)}
    return {"app": app, "source": "", "models": []}


def codex_models() -> list[dict[str, Any]]:
    base = os.environ.get("CODEX_HOME")
    path = (Path(base) if base else Path.home() / ".codex") / "models_cache.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    out = []
    for m in (data.get("models") or []) if isinstance(data, dict) else []:
        if not isinstance(m, dict) or m.get("visibility") not in (None, "list") or not m.get("slug"):
            continue
        levels = [x.get("effort") for x in m.get("supported_reasoning_levels") or [] if isinstance(x, dict) and x.get("effort")]
        out.append({"id": m["slug"], "name": m.get("display_name") or m["slug"], "note": m.get("description") or "",
                    "free": False, "efforts": levels or CODEX_EFFORTS, "context": m.get("context_window")})
    if not out:
        out = [{"id": "gpt-6.1-sol", "name": "GPT-6.1 Sol", "note": "", "free": False, "efforts": CODEX_EFFORTS, "context": None}]
    return out


def parse_opencode(text: str) -> list[dict[str, Any]]:
    """`opencode models --verbose`: each model is a 'provider/id' line followed by a JSON object."""
    out: list[dict[str, Any]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        head = lines[i].strip()
        i += 1
        if not head or head.startswith("{") or "/" not in head or " " in head:
            continue
        body: list[str] = []
        depth = 0
        while i < len(lines):
            line = lines[i]
            if not body and not line.strip().startswith("{"):
                break
            body.append(line)
            depth += line.count("{") - line.count("}")
            i += 1
            if depth <= 0:
                break
        info: dict[str, Any] = {}
        if body:
            try:
                info = json.loads("\n".join(body))
            except ValueError:
                info = {}
        cost = info.get("cost") if isinstance(info.get("cost"), dict) else {}
        free = bool(cost) and not float(cost.get("input") or 0) and not float(cost.get("output") or 0)
        variants = list((info.get("variants") or {}).keys()) if isinstance(info.get("variants"), dict) else []
        limit = info.get("limit") if isinstance(info.get("limit"), dict) else {}
        out.append({"id": head, "name": info.get("name") or head.split("/", 1)[1], "note": "free" if free else "",
                    "free": free or head.endswith("-free"), "efforts": variants, "context": limit.get("context")})
    return out


def opencode_models(*, refresh: bool = False) -> list[dict[str, Any]]:
    path = _cache_file("opencode")
    if not refresh:
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - float(cached.get("at") or 0) < CACHE_SECONDS and cached.get("models"):
                return cached["models"]
        except (OSError, ValueError):
            pass
    exe = shutil.which("opencode")
    if not exe:
        return []
    try:
        res = subprocess.run([exe, "models", "--verbose"], capture_output=True, text=True, timeout=90, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return []
    models = parse_opencode(res.stdout or "")
    models.sort(key=lambda m: (not m["free"], m["id"]))
    if models:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"at": time.time(), "models": models}), encoding="utf-8")
        except OSError:
            pass
    return models

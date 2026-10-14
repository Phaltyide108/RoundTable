"""Connect apps to a project by writing their MCP settings, safely.

Rules: read and parse first; merge (never replace other entries); save a
timestamped backup before changing a file; write atomically; refuse to touch
a file we cannot parse (and say how to fix it). --dry-run shows the change.

Every entry starts `<this python> -m roundtable_ai mcp` by absolute path, so
apps never depend on your shell's PATH.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

from . import util
from .errors import CONFIG, INVALID, RTError

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


PAST = {"add": "added", "update": "updated", "remove": "removed"}


def server_command() -> tuple[str, list[str]]:
    return sys.executable, ["-m", "roundtable_ai", "mcp"]


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    return (s or "project")[:40]


def server_name(ctx) -> str:
    return "roundtable-" + slug(ctx.setting("project", "name") or ctx.root.name)


def entry(home: Path, seat: str | None = None, *, stdio_type: bool = False) -> dict:
    cmd, args = server_command()
    env = {"RT_HOME": str(home)}
    if seat:
        env["RT_SEAT"] = seat
    e: dict = {"command": cmd, "args": args, "env": env}
    if stdio_type:
        e = {"type": "stdio", **e}
    return e


# ---------------------------------------------------------------- file helpers

def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = util.now().replace(":", "").replace("-", "")[:15]
    b = path.with_name(f"{path.name}.rt-backup-{stamp}")
    shutil.copy2(path, b)
    return b


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".rt-tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def _load_json(path: Path) -> dict:
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RTError(CONFIG, f"{path} is not valid JSON (line {exc.lineno}: {exc.msg}); Roundtable did not change it",
                      "fix that file (or move it aside), then run the setup again") from None
    except UnicodeDecodeError:
        raise RTError(CONFIG, f"{path} is not UTF-8 text; Roundtable did not change it") from None
    if not isinstance(data, dict):
        raise RTError(CONFIG, f"{path} does not contain a JSON object; Roundtable did not change it")
    return data


def merge_json(path: Path, name: str, value: dict | None, *, dry_run: bool) -> str:
    """Set (or remove, value=None) mcpServers[name] in a JSON config file."""
    data = _load_json(path)
    servers = data.get("mcpServers")
    if servers is None:
        servers = {}
    if not isinstance(servers, dict):
        raise RTError(CONFIG, f"'mcpServers' in {path} is not an object; Roundtable did not change it")
    before = servers.get(name)
    if value is None:
        if before is None:
            return f"{path}: no '{name}' entry to remove"
        servers.pop(name)
    else:
        if before == value:
            return f"{path}: '{name}' is already up to date"
        servers[name] = value
    data["mcpServers"] = servers
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    action = "remove" if value is None else ("update" if before is not None else "add")
    if dry_run:
        return f"would {action} '{name}' in {path}:\n" + json.dumps({name: value} if value else {name: before}, indent=2)
    b = _backup(path)
    _atomic_write(path, text)
    return f"{PAST[action]} '{name}' in {path}" + (f" (backup: {b.name})" if b else "")


# ---------------------------------------------------------------- per app

def claude_desktop_config() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "Claude" / "claude_desktop_config.json"
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "Claude" / "claude_desktop_config.json"


def codex_config() -> Path:
    base = os.environ.get("CODEX_HOME")
    return (Path(base) if base else Path.home() / ".codex") / "config.toml"


def seat_mcp_file(ctx, handle: str) -> Path:
    """Per-seat MCP config used by `rt launch` (pins RT_SEAT)."""
    path = ctx.home / "seats" / handle / "mcp.json"
    data = {"mcpServers": {"roundtable": entry(ctx.home, handle, stdio_type=True)}}
    text = json.dumps(data, indent=2) + "\n"
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        _atomic_write(path, text)
    return path


def _folder_entry(rel: str, home: Path, handle: str) -> tuple[str, dict]:
    """(top-level key, entry) for a per-seat settings file, by app format."""
    cmd, args = server_command()
    env = {"RT_HOME": str(home), "RT_SEAT": handle}
    if rel == "opencode.json":
        return "mcp", {"type": "local", "command": [cmd, *args], "environment": env, "enabled": True}
    if rel == ".cursor/mcp.json":
        return "mcpServers", {"type": "stdio", "command": cmd, "args": args, "env": env}
    if rel in (".gemini/settings.json", ".qwen/settings.json"):
        return "mcpServers", {"command": cmd, "args": args, "env": env, "timeout": 120000, "trust": False}
    return "mcpServers", entry(home, handle, stdio_type=True)


def seat_folder_config(ctx, handle: str) -> str:
    """Write this seat's settings file into its working copy, so the app opened
    there connects to Roundtable already bound to the seat (no join step).

    Kept out of git with the repository's info/exclude, so it never shows as a
    change. If the project already tracks that file, nothing is written
    (changing it would dirty the working copy) and the reply says what to do.
    """
    from . import apps, gitops, seats

    row = seats.get(ctx, handle)
    rel = apps.get(row["app"]).folder
    if not rel:
        return f"{apps.label(row['app'])} needs no per-seat settings file"
    if not row["worktree"] or not Path(row["worktree"]).exists():
        raise RTError(INVALID, f"{handle} has no working copy", f"rt seat worktree {handle}")
    wt = Path(row["worktree"])
    if gitops.run(wt, "ls-files", "--error-unmatch", rel).returncode == 0:
        return (f"{rel} is tracked by git in this project, so Roundtable left it alone. Add an MCP server named roundtable by hand: "
                f'command "{sys.executable}", arguments -m roundtable_ai mcp, environment RT_HOME={ctx.home} RT_SEAT={handle}')
    key, value = _folder_entry(rel, ctx.home, handle)
    path = wt / rel
    if key == "mcpServers":
        msg = merge_json(path, "roundtable", value, dry_run=False)
    else:
        data = _load_json(path)
        section = data.get(key) if isinstance(data.get(key), dict) else {}
        if section.get("roundtable") == value:
            msg = f"{path}: 'roundtable' is already up to date"
        else:
            section["roundtable"] = value
            data.setdefault("$schema", "https://opencode.ai/config.json")
            data[key] = section
            _backup(path)
            _atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            msg = f"wrote 'roundtable' into {path}"
    common = gitops.run(wt, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    if common:
        exclude = Path(common) / "info" / "exclude"
        text = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        line = "/" + rel
        if line not in text.splitlines():
            exclude.parent.mkdir(parents=True, exist_ok=True)
            with open(exclude, "a", encoding="utf-8") as fh:
                fh.write(("" if not text or text.endswith("\n") else "\n") + f"# Roundtable: per-seat settings in working copies\n{line}\n")
    return msg


def seat_folder_mcp(ctx, handle: str) -> str:  # kept for older callers
    return seat_folder_config(ctx, handle)


def copilot_config() -> Path:
    base = os.environ.get("COPILOT_HOME")
    return (Path(base) if base else Path.home() / ".copilot") / "mcp-config.json"


def connected(ctx) -> dict[str, bool]:
    """Which apps already have this project's Roundtable entry (quick check, no repairs)."""
    out = {"claude-code": False, "claude-app": False, "codex": False, "copilot": False}
    try:
        data = _load_json(ctx.root / ".mcp.json")
        out["claude-code"] = "roundtable" in (data.get("mcpServers") or {})
    except RTError:
        pass
    try:
        data = _load_json(claude_desktop_config())
        out["claude-app"] = server_name(ctx) in (data.get("mcpServers") or {})
    except RTError:
        pass
    try:
        data = _load_json(copilot_config())
        out["copilot"] = server_name(ctx) in (data.get("mcpServers") or {})
    except RTError:
        pass
    try:
        path = codex_config()
        if path.exists():
            out["codex"] = server_name(ctx) in (tomllib.loads(path.read_text(encoding="utf-8")).get("mcp_servers") or {})
    except (OSError, tomllib.TOMLDecodeError):
        pass
    return out


_HEADER = re.compile(r"^\s*\[\s*(.+?)\s*\]\s*(#.*)?$")


def _toml_key_path(header: str) -> list[str]:
    parts, cur, quote = [], "", None
    for ch in header:
        if quote:
            if ch == quote:
                quote = None
            else:
                cur += ch
        elif ch in "\"'":
            quote = ch
        elif ch == ".":
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    parts.append(cur.strip())
    return parts


def _strip_toml_table(text: str, name: str) -> tuple[str, bool]:
    """Remove [mcp_servers.<name>] and its subtables, keeping everything else."""
    lines = text.splitlines()
    out, skipping, removed = [], False, False
    for line in lines:
        m = _HEADER.match(line)
        if m and not line.strip().startswith("[["):
            path = _toml_key_path(m.group(1))
            if len(path) >= 2 and path[0] == "mcp_servers" and path[1] == name:
                skipping, removed = True, True
                continue
            skipping = False
        elif m:
            skipping = False
        if not skipping:
            out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out) + ("\n" if out else ""), removed


def _toml_block(name: str, home: Path, seat: str | None = None) -> str:
    from .config import toml_value

    cmd, args = server_command()
    env = {"RT_HOME": str(home)}
    if seat:
        env["RT_SEAT"] = seat
    lines = [
        f"# Added by Roundtable (rt setup codex). Remove with: rt setup codex --remove",
        f"[mcp_servers.{name}]",
        f"command = {toml_value(cmd)}",
        f"args = {toml_value(args)}",
        "startup_timeout_sec = 30",
        "tool_timeout_sec = 120",
        "# Roundtable's tools only touch the shared table: no approval prompt for each call",
        'default_tools_approval_mode = "approve"',
        "",
        f"[mcp_servers.{name}.env]",
    ]
    lines += [f"{k} = {toml_value(v)}" for k, v in env.items()]
    return "\n".join(lines) + "\n"


def merge_codex(path: Path, name: str, home: Path | None, *, dry_run: bool) -> str:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise RTError(CONFIG, f"{path} has a TOML error ({exc}); Roundtable did not change it", "fix that file, then run the setup again") from None
    stripped, had = _strip_toml_table(text, name)
    stripped = stripped.replace(f"# Added by Roundtable (rt setup codex). Remove with: rt setup codex --remove\n", "")
    if home is None:
        if not had:
            return f"{path}: no '{name}' entry to remove"
        new = stripped
    else:
        new = (stripped.rstrip("\n") + "\n\n" if stripped.strip() else "") + _toml_block(name, home)
    try:
        parsed = tomllib.loads(new)
    except tomllib.TOMLDecodeError as exc:  # pragma: no cover - defensive
        raise RTError(CONFIG, f"internal: generated an invalid {path.name} ({exc}); nothing was changed") from None
    if home is not None:
        got = parsed.get("mcp_servers", {}).get(name, {})
        if got.get("command") != server_command()[0]:
            raise RTError(CONFIG, f"could not write a clean entry into {path}; nothing was changed", "add it by hand (see docs/setup-apps.md)")
    if new == text:
        return f"{path}: '{name}' is already up to date"
    action = "remove" if home is None else ("update" if had else "add")
    if dry_run:
        return f"would {action} [mcp_servers.{name}] in {path}:\n" + (_toml_block(name, home) if home else "(entry removed)")
    b = _backup(path)
    _atomic_write(path, new)
    return f"{PAST[action]} [mcp_servers.{name}] in {path}" + (f" (backup: {b.name})" if b else "")


def setup(app: str, *, home: str | None = None, dry_run: bool = False, remove: bool = False) -> str:
    from .context import open_ctx

    ctx = open_ctx(home)
    try:
        lines = []
        if app == "claude-code":
            path = ctx.root / ".mcp.json"
            lines.append(merge_json(path, "roundtable", None if remove else entry(ctx.home, stdio_type=True), dry_run=dry_run))
            if not remove:
                lines.append("Claude Code asks you to approve project MCP servers the first time; choose to allow 'roundtable'.")
                lines.append("Seats started with `rt launch <seat>` use their own config and need no approval step.")
                lines.append("note: .mcp.json is in your project folder; commit it if your team uses Roundtable, or add it to .gitignore.")
        elif app == "claude-app":
            path = claude_desktop_config()
            lines.append(merge_json(path, server_name(ctx), None if remove else entry(ctx.home), dry_run=dry_run))
            if not remove:
                lines.append("Restart the Claude app, then in a new chat say: join Roundtable as <seat name>.")
        elif app == "codex":
            path = codex_config()
            lines.append(merge_codex(path, server_name(ctx), None if remove else ctx.home, dry_run=dry_run))
            if not remove:
                lines.append("This one entry serves Codex CLI, the Codex VS Code extension and the ChatGPT desktop app's Codex mode.")
                lines.append("Restart them, open the seat's working copy folder, and say: join Roundtable as <seat name>.")
        elif app == "copilot":
            cmd, args = server_command()
            value = {"type": "local", "command": cmd, "args": args, "env": {"RT_HOME": str(ctx.home)}, "tools": ["*"]}
            lines.append(merge_json(copilot_config(), server_name(ctx), None if remove else value, dry_run=dry_run))
            if not remove:
                lines.append("Restart Copilot CLI in the seat's working copy folder and say: join Roundtable as <seat name>.")
        else:
            raise RTError(INVALID, f"unknown app {app!r}", "use claude-code, claude-app, codex or copilot")
        return "\n".join(lines)
    finally:
        ctx.close()

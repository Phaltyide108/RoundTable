"""Project settings in .roundtable/config.toml.

- Unknown keys and wrong types are refused with the line to fix, so a typo
  never silently changes behavior.
- `set_value` edits one line in place and keeps the user's comments.
- Only the human changes settings (CLI / dashboard); seats cannot.
"""

from __future__ import annotations

import copy
import difflib
import re
import sys
from pathlib import Path
from typing import Any

from .errors import CONFIG, INVALID, RTError

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on 3.10 only
    import tomli as tomllib

REVIEW_LEVELS = ("low", "mid", "high")

# section -> key -> (default, type, description). Types: str, int, bool, list[str], choice tuple.
SCHEMA: dict[str, dict[str, tuple[Any, Any, str]]] = {
    "project": {
        "name": ("", str, "Project name shown in digests and the dashboard"),
        "main_branch": ("", str, "Integration branch finished work is merged into (detected at init)"),
    },
    "review": {
        "level": ("low", REVIEW_LEVELS, "How much of each other's work seats read: low | mid | high"),
        "always_high": ([], "list[str]", "Path patterns always reviewed at high, e.g. [\"auth/**\"]"),
        "max_diff_lines": (400, int, "At mid, bigger changes get a summary review and ask you"),
        "spot_check_every": (5, int, "At mid, 1 task in N gets a full-code spot check"),
        "max_rounds": (3, int, "Review rounds before the task is escalated to you"),
    },
    "leases": {
        "ttl_minutes": (30, int, "Leases of an inactive seat expire after this many minutes"),
    },
    "seats": {
        "live_minutes": (10, int, "A seat active within this many minutes counts as live in its chat"),
    },
    "proof": {
        "timeout_seconds": (900, int, "A proof command is stopped after this many seconds"),
        "wait_seconds": (20, int, "How long close waits for the proof before answering 'running'"),
        "output_lines": (40, int, "Lines of proof output kept"),
    },
    "planning": {
        "max_planners": (3, int, "Most seats that write blind plan drafts"),
        "draft_timeout_minutes": (30, int, "After this, you are asked whether to continue without missing drafts"),
        "critiques_per_seat": (2, int, "Drafts each seat critiques"),
    },
    "limits": {
        "summary_words": (80, int, "Max words in a task or checkpoint summary"),
        "draft_words": (300, int, "Max words in a plan draft"),
        "critique_points": (10, int, "Max points in one critique"),
        "digest_lines": (20, int, "Max lines in a digest before folding"),
        "title_chars": (80, int, "Max characters in a title"),
        "text_chars": (4000, int, "Max characters in a description, suggestion or comment"),
    },
    "git": {
        "worktrees": (True, bool, "Give each coding seat its own working copy and branch"),
        "worktree_dir": ("", str, "Where working copies go (default: next to the project folder)"),
        "auto_merge": (True, bool, "Merge finished tasks into the main branch automatically"),
    },
    "watch": {
        "notify": (True, bool, "Desktop notifications for level 4+ alerts and stuck work"),
        "wake_level": (5, int, "Alert level that starts background runs of command-line seats"),
        "wake_min_interval_minutes": (10, int, "At most one background run per seat in this window"),
        "stuck_minutes": (30, int, "Work waiting longer than this is flagged to you"),
    },
    "usage": {
        "statusline": (True, bool, "Seats started with rt launch in Claude Code show usage + inbox in their status line"),
        "warn_percent": (90, int, "Notify you when a seat passes this share of its 5-hour or 7-day limit"),
    },
    "runner": {
        "permissions": ("edits", ("edits", "all"), "Background runs: edits = its own files, Roundtable, git and the project's test commands; all = any command"),
        "max_minutes": (45, int, "A background run is stopped after this many minutes"),
    },
    "dashboard": {
        "port": (8765, int, "Local dashboard port (127.0.0.1 only)"),
    },
    "history": {
        "keep_days": (30, int, "rt compact keeps full detail for work finished within this many days"),
    },
}


def defaults() -> dict[str, dict[str, Any]]:
    return {sec: {k: copy.deepcopy(v[0]) for k, v in keys.items()} for sec, keys in SCHEMA.items()}


def _type_name(t: Any) -> str:
    if isinstance(t, tuple):
        return " | ".join(t)
    return {str: "text", int: "a whole number", bool: "true or false", "list[str]": "a list of text"}.get(t, str(t))


def _check_value(section: str, key: str, value: Any) -> Any:
    _, t, _ = SCHEMA[section][key]
    where = f"[{section}] {key}"
    if isinstance(t, tuple):
        if value not in t:
            raise RTError(CONFIG, f"{where} = {value!r} is not allowed", f"use one of: {', '.join(t)}")
        return value
    if t is bool:
        if not isinstance(value, bool):
            raise RTError(CONFIG, f"{where} must be true or false (got {value!r})")
        return value
    if t is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise RTError(CONFIG, f"{where} must be a whole number (got {value!r})")
        if value < 0:
            raise RTError(CONFIG, f"{where} cannot be negative")
        return value
    if t is str:
        if not isinstance(value, str):
            raise RTError(CONFIG, f"{where} must be text in quotes (got {value!r})")
        return value
    if t == "list[str]":
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise RTError(CONFIG, f"{where} must be a list of text, like [\"auth/**\"]")
        return value
    raise RTError(CONFIG, f"{where}: unknown type")  # pragma: no cover


class Config:
    """Validated settings. Access as cfg.get('review', 'level') or cfg['review']['level']."""

    def __init__(self, data: dict[str, dict[str, Any]], path: Path | None = None):
        self.data = data
        self.path = path

    def get(self, section: str, key: str) -> Any:
        return self.data[section][key]

    def __getitem__(self, section: str) -> dict[str, Any]:
        return self.data[section]


def load(path: Path) -> Config:
    data = defaults()
    if not path.exists():
        return Config(data, path)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise RTError(CONFIG, f"{path} has a syntax error: {exc}", "fix that line, or delete the file and run `rt init` to recreate defaults") from None
    except UnicodeDecodeError:
        raise RTError(CONFIG, f"{path} is not valid UTF-8 text") from None
    for section, values in raw.items():
        if section not in SCHEMA:
            close = difflib.get_close_matches(section, SCHEMA.keys(), n=1)
            raise RTError(CONFIG, f"unknown section [{section}] in {path.name}", f"did you mean [{close[0]}]?" if close else "remove it")
        if not isinstance(values, dict):
            raise RTError(CONFIG, f"[{section}] in {path.name} must be a table")
        for key, value in values.items():
            if key not in SCHEMA[section]:
                close = difflib.get_close_matches(key, SCHEMA[section].keys(), n=1)
                raise RTError(CONFIG, f"unknown setting [{section}] {key} in {path.name}", f"did you mean {close[0]}?" if close else "remove it")
            data[section][key] = _check_value(section, key, value)
    return Config(data, path)


# ---------------------------------------------------------------- writing

def toml_value(value: Any) -> str:
    """Serialize the simple values we use. JSON string escapes are valid TOML."""
    import json

    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    raise TypeError(f"unsupported TOML value {value!r}")


def render_default(project_name: str, main_branch: str) -> str:
    data = defaults()
    data["project"]["name"] = project_name
    data["project"]["main_branch"] = main_branch
    lines = [
        "# Roundtable settings for this project.",
        "# Change with `rt config set section.key value` (keeps comments) or edit by hand.",
        "# Only you (the human) change settings; seats cannot.",
        "",
    ]
    for section, keys in SCHEMA.items():
        lines.append(f"[{section}]")
        for key, (_, _, desc) in keys.items():
            lines.append(f"# {desc}")
            lines.append(f"{key} = {toml_value(data[section][key])}")
        lines.append("")
    return "\n".join(lines)


def parse_cli_value(section: str, key: str, text: str) -> Any:
    """Turn a command-line string into the right type for a setting."""
    _, t, _ = SCHEMA[section][key]
    s = text.strip()
    if t is bool:
        if s.lower() in ("true", "yes", "on", "1"):
            return True
        if s.lower() in ("false", "no", "off", "0"):
            return False
        raise RTError(INVALID, f"{section}.{key} needs true or false (got {text!r})")
    if t is int:
        try:
            return int(s)
        except ValueError:
            raise RTError(INVALID, f"{section}.{key} needs a whole number (got {text!r})") from None
    if t == "list[str]":
        if s.startswith("["):
            try:
                v = tomllib.loads(f"v = {s}")["v"]
            except tomllib.TOMLDecodeError:
                raise RTError(INVALID, f"{section}.{key} needs a list like [\"auth/**\", \"payments/**\"]") from None
            return v
        return [p.strip() for p in s.split(",") if p.strip()]
    return s


def split_key(dotted: str) -> tuple[str, str]:
    if "." not in dotted:
        raise RTError(INVALID, f"setting {dotted!r} needs a section, like review.level")
    section, key = dotted.split(".", 1)
    if section not in SCHEMA or key not in SCHEMA[section]:
        all_keys = [f"{s}.{k}" for s, ks in SCHEMA.items() for k in ks]
        close = difflib.get_close_matches(dotted, all_keys, n=1)
        raise RTError(INVALID, f"unknown setting {dotted!r}", f"did you mean {close[0]}?" if close else "run `rt config show` to list settings")
    return section, key


def set_value(path: Path, dotted: str, raw_value: Any) -> Any:
    """Change one setting, preserving every other line and comment."""
    section, key = split_key(dotted)
    value = parse_cli_value(section, key, raw_value) if isinstance(raw_value, str) else raw_value
    value = _check_value(section, key, value)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = text.splitlines()
    header_re = re.compile(r"^\s*\[([^\]]+)\]\s*(#.*)?$")
    key_re = re.compile(rf"^\s*{re.escape(key)}\s*=")
    current = None
    section_end = None
    replaced = False
    for i, line in enumerate(lines):
        m = header_re.match(line)
        if m:
            if current == section and section_end is None:
                section_end = i
            current = m.group(1).strip()
            continue
        if current == section and key_re.match(line):
            lines[i] = f"{key} = {toml_value(value)}"
            replaced = True
            break
    if not replaced:
        if current == section and section_end is None:
            section_end = len(lines)
        if section_end is None:
            lines += ["", f"[{section}]", f"{key} = {toml_value(value)}"]
        else:
            # insert before trailing blank lines of the section
            j = section_end
            while j > 0 and lines[j - 1].strip() == "":
                j -= 1
            lines.insert(j, f"{key} = {toml_value(value)}")
    new_text = "\n".join(lines) + "\n"
    tmp = path.with_suffix(".toml.tmp")
    tmp.write_text(new_text, encoding="utf-8")
    load_check = tomllib.loads(new_text)  # never write a file we cannot read back
    del load_check
    tmp.replace(path)
    return value

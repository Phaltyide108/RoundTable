"""Small shared helpers: time, ids, text size caps, paths and glob matching.

Everything here is pure (no database access) except next_id, which takes a
Store-like object with an `execute` method and must be called inside a
write transaction.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sys
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .errors import INVALID, TOO_LONG, RTError

# ---------------------------------------------------------------- time
# Stored timestamps are always UTC ISO-8601 with microseconds and a Z suffix,
# so they sort correctly as text. Shown to people in local time.

_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"


def now() -> str:
    return datetime.now(timezone.utc).strftime(_FMT)


def parse_time(value: str) -> datetime:
    return datetime.strptime(value, _FMT).replace(tzinfo=timezone.utc)


def seconds_since(value: str | None) -> float | None:
    if not value:
        return None
    return (datetime.now(timezone.utc) - parse_time(value)).total_seconds()


def add_seconds(value: str, seconds: float) -> str:
    from datetime import timedelta

    return (parse_time(value) + timedelta(seconds=seconds)).strftime(_FMT)


def ago_iso(seconds: float) -> str:
    """The UTC timestamp `seconds` ago, in the stored format (sorts correctly as text)."""
    return add_seconds(now(), -seconds)


def local_hm(value: str | None) -> str:
    """'14:39' in the computer's local time zone."""
    if not value:
        return "--:--"
    return parse_time(value).astimezone().strftime("%H:%M")


def human_ago(value: str | None) -> str:
    secs = seconds_since(value)
    if secs is None:
        return "never"
    secs = max(0, int(secs))
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60} min ago"
    if secs < 86400:
        return f"{secs // 3600} h ago"
    return f"{secs // 86400} d ago"


# ---------------------------------------------------------------- json

def jdump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=False)


def jload(value: str | None, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    return json.loads(value)


# ---------------------------------------------------------------- ids

def next_id(db: Any, kind: str, prefix: str) -> str:
    """Allocate the next human-friendly id for a kind: T1, T2 ... / A1 ...

    Must run inside a write transaction (db.tx()) so two seats never get the
    same id.
    """
    row = db.execute("SELECT next FROM counters WHERE kind = ?", (kind,)).fetchone()
    if row is None:
        n = 1
        db.execute("INSERT INTO counters(kind, next) VALUES (?, ?)", (kind, 2))
    else:
        n = int(row[0])
        db.execute("UPDATE counters SET next = ? WHERE kind = ?", (n + 1, kind))
    return f"{prefix}{n}"


def new_key() -> str:
    """Short seat session key, easy for a model to repeat (e.g. 'k7m2qp')."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"  # no look-alikes (0/o, 1/l/i)
    return "".join(secrets.choice(alphabet) for _ in range(6))


# ---------------------------------------------------------------- validation

HANDLE_RE = re.compile(r"^[a-z][a-z0-9_-]{1,23}$")


def check_handle(handle: Any) -> str:
    if not isinstance(handle, str) or not HANDLE_RE.match(handle.strip().lower()):
        raise RTError(
            INVALID,
            f"invalid seat name {handle!r}",
            "use 2-24 characters: lowercase letters, digits, - or _, starting with a letter (e.g. opus, sol61)",
        )
    return handle.strip().lower()


def require_text(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise RTError(INVALID, f"{field} must be text")
    value = value.strip()
    if not value and not allow_empty:
        raise RTError(INVALID, f"{field} is required and cannot be empty")
    return value


def count_words(text: str) -> int:
    return len(text.split())


def cap_words(text: str, limit: int, field: str) -> str:
    n = count_words(text)
    if n > limit:
        raise RTError(TOO_LONG, f"{field} is {n} words; the limit is {limit}", f"shorten {field} to {limit} words or fewer")
    return text


def cap_chars(text: str, limit: int, field: str) -> str:
    if len(text) > limit:
        raise RTError(TOO_LONG, f"{field} is {len(text)} characters; the limit is {limit}", f"shorten {field} to {limit} characters or fewer")
    return text


def one_line(text: str, limit: int = 120) -> str:
    """Collapse whitespace and trim, for digest lines."""
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def as_list(value: Any, field: str) -> list:
    """Accept a list, a JSON list in a string, or a comma-separated string."""
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        s = value.strip()
        if s.startswith("["):
            try:
                parsed = json.loads(s)
            except json.JSONDecodeError as exc:
                raise RTError(INVALID, f"{field}: invalid JSON list ({exc.msg})") from None
            if not isinstance(parsed, list):
                raise RTError(INVALID, f"{field} must be a list")
            return parsed
        return [part.strip() for part in s.split(",") if part.strip()]
    raise RTError(INVALID, f"{field} must be a list")


# ---------------------------------------------------------------- paths

CASE_INSENSITIVE_FS = sys.platform in ("win32", "darwin")


def norm_path(root: Path | str, path: str) -> str:
    """Normalize a user/model-supplied file path or glob to a repo-relative
    POSIX string. Rejects paths that escape the project.

    'src\\a.py', './src/a.py', '/abs/project/src/a.py' -> 'src/a.py'
    """
    if not isinstance(path, str) or not path.strip():
        raise RTError(INVALID, "file path is empty")
    raw = path.strip().replace("\\", "/")
    root_posix = str(Path(root).resolve()).replace("\\", "/").rstrip("/")
    if raw.startswith(root_posix + "/"):
        raw = raw[len(root_posix) + 1 :]
    # Any rooted path is outside the project. Not os.path.isabs: since Python 3.13 it says
    # False on Windows for "/etc/passwd" (rooted, but no drive letter).
    elif raw.startswith("/") or re.match(r"^[A-Za-z]:/" if os.name != "nt" else r"^[A-Za-z]:", raw):
        raise RTError(INVALID, f"path {path!r} is outside the project", "use a path relative to the project folder, e.g. src/app.py")
    parts: list[str] = []
    for part in PurePosixPath(raw).parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                raise RTError(INVALID, f"path {path!r} is outside the project", "use a path relative to the project folder")
            parts.pop()
            continue
        parts.append(part)
    if not parts:
        raise RTError(INVALID, f"path {path!r} points at the project folder itself", "name files or a pattern like src/**")
    norm = "/".join(parts)
    if norm == ".roundtable" or norm.startswith(".roundtable/") or norm == ".git" or norm.startswith(".git/"):
        raise RTError(INVALID, f"path {path!r} is internal to git or Roundtable and cannot be leased")
    return norm


def _fold(s: str) -> str:
    return s.lower() if CASE_INSENSITIVE_FS else s


@lru_cache(maxsize=1024)
def _glob_regex(pattern: str) -> re.Pattern:
    """Translate a glob to a regex.

    *   any run of characters except '/'
    **  any run of characters including '/' (also matches zero directories)
    ?   one character except '/'
    [abc] character class
    A pattern ending in '/' or naming a directory prefix is matched by glob_match.
    """
    i, out = 0, ["^"]
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                # '**/' matches zero or more directories
                if i + 2 < n and pattern[i + 2] == "/":
                    out.append("(?:.*/)?")
                    i += 3
                    continue
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = pattern.find("]", i + 1)
            if j == -1:
                out.append(re.escape(c))
            else:
                cls = pattern[i + 1 : j].replace("\\", "\\\\")
                if cls.startswith("!"):
                    cls = "^" + cls[1:]
                out.append(f"[{cls}]")
                i = j
        else:
            out.append(re.escape(c))
        i += 1
    out.append("$")
    return re.compile("".join(out), re.IGNORECASE if CASE_INSENSITIVE_FS else 0)


def is_glob(pattern: str) -> bool:
    return any(ch in pattern for ch in "*?[")


def glob_match(pattern: str, path: str) -> bool:
    """True if repo-relative `path` is covered by `pattern`.

    A plain directory name covers everything under it: 'src' covers 'src/a.py'.
    """
    pattern = pattern.rstrip("/")
    if not is_glob(pattern):
        p, q = _fold(pattern), _fold(path)
        return q == p or q.startswith(p + "/")
    return bool(_glob_regex(pattern).match(path))


def _static_prefix(pattern: str) -> str:
    """Leading directory part with no wildcard: 'src/api/**/*.py' -> 'src/api'."""
    parts = []
    for part in pattern.split("/"):
        if is_glob(part):
            break
        parts.append(part)
    return "/".join(parts)


def patterns_overlap(a: str, b: str, known_files: Iterable[str] = ()) -> bool:
    """Conservative check: could two lease patterns cover a common file?

    Exact for plain paths. For globs: true if either matches the other's
    literal form, if any known project file matches both, or if one static
    prefix contains the other and both are recursive. When in doubt we say
    "overlap" — a false conflict is safer than two seats editing one file.
    """
    a, b = a.rstrip("/"), b.rstrip("/")
    if _fold(a) == _fold(b):
        return True
    if glob_match(a, b) or glob_match(b, a):
        return True
    if not is_glob(a) and not is_glob(b):
        return False
    for f in known_files:
        if glob_match(a, f) and glob_match(b, f):
            return True
    pa, pb = _fold(_static_prefix(a)), _fold(_static_prefix(b))
    rec_a, rec_b = "**" in a, "**" in b
    if rec_a and (pb == pa or pb.startswith(pa + "/") or pa == ""):
        return True
    if rec_b and (pa == pb or pa.startswith(pb + "/") or pb == ""):
        return True
    return False


def files_covered(patterns: Iterable[str], path: str) -> bool:
    return any(glob_match(p, path) for p in patterns)

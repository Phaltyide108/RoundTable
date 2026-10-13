"""SQLite store shared by every seat's MCP server process, the CLI, the
watcher and the dashboard.

- WAL mode + busy timeout: many processes can read while one writes.
- `with store.tx():` runs BEGIN IMMEDIATE, so checks-then-writes (claims,
  id allocation) are atomic across processes. Nested tx() calls join the
  outer transaction.
- The database is never created implicitly: only `rt init` creates it. This
  prevents a "split brain" where a seat in another folder silently starts a
  second, empty project.
"""

from __future__ import annotations

import shutil
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .errors import BUSY, NOT_INITIALIZED, VERSION, RTError
from .schema import SCHEMA_V1, SCHEMA_VERSION

BUSY_TIMEOUT_MS = 10_000

# Forward-only migrations: {from_version: sql_script}. Version 1 is the base.
MIGRATIONS: dict[int, str] = {}

# Extra CREATE TABLE IF NOT EXISTS statements registered by modules
# (applied on every open; must be idempotent).
_EXTRA_SCHEMA: list[str] = []


def register_schema(sql: str) -> None:
    """Modules may add tables/indexes they own. Must be idempotent SQL."""
    if sql not in _EXTRA_SCHEMA:
        _EXTRA_SCHEMA.append(sql)


def _busy(exc: sqlite3.OperationalError) -> bool:
    msg = str(exc).lower()
    return "locked" in msg or "busy" in msg


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._depth = 0
        self.conn = self._connect()

    # -------------------------------------------------------------- open
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @classmethod
    def create(cls, path: Path) -> "Store":
        """Create a new database (rt init only)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        store = cls(path)
        store.conn.execute("PRAGMA journal_mode = WAL")
        store.conn.execute("PRAGMA synchronous = NORMAL")
        with store.tx():
            for stmt in _split_sql(SCHEMA_V1):
                store.conn.execute(stmt)
            for extra in _EXTRA_SCHEMA:
                for stmt in _split_sql(extra):
                    store.conn.execute(stmt)
            store.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        return store

    @classmethod
    def open(cls, path: Path) -> "Store":
        """Open an existing database, migrating it forward if needed."""
        path = Path(path)
        if not path.exists():
            raise RTError(
                NOT_INITIALIZED,
                f"no Roundtable database at {path}",
                "run `rt init` in the main project folder (not in a seat's working copy)",
            )
        store = cls(path)
        store._check_version_and_migrate()
        return store

    def _check_version_and_migrate(self) -> None:
        try:
            row = self.conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        except sqlite3.DatabaseError as exc:
            raise RTError(
                NOT_INITIALIZED,
                f"{self.path} is not a readable Roundtable database ({exc})",
                "if you moved or synced it, restore it; otherwise move it aside and run `rt init` again",
            ) from None
        version = int(row[0]) if row else 0
        if version > SCHEMA_VERSION:
            from . import __version__

            raise RTError(
                VERSION,
                f"this project was set up by a newer Roundtable (database schema {version}; this install {__version__} knows up to {SCHEMA_VERSION})",
                "upgrade Roundtable: `pipx upgrade roundtable-ai` (or `uv tool upgrade roundtable-ai`)",
            )
        if version < SCHEMA_VERSION:
            backup = self.path.with_suffix(f".db.backup-v{version}")
            if not backup.exists():
                shutil.copy2(self.path, backup)
            with self.tx():
                for v in range(version, SCHEMA_VERSION):
                    script = MIGRATIONS.get(v)
                    if script:
                        for stmt in _split_sql(script):
                            self.conn.execute(stmt)
                self.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        # Tables added within the current schema version (CREATE ... IF NOT EXISTS) are
        # applied once per change, detected by a hash, so ordinary opens take no write lock.
        import hashlib

        digest = hashlib.sha256((SCHEMA_V1 + "".join(_EXTRA_SCHEMA)).encode()).hexdigest()[:16]
        if self.meta_get("schema_hash") != digest:
            with self.tx():
                for stmt in _split_sql(SCHEMA_V1):
                    if stmt.lstrip().upper().startswith("CREATE"):
                        self.conn.execute(stmt)
                for extra in _EXTRA_SCHEMA:
                    for stmt in _split_sql(extra):
                        self.conn.execute(stmt)
                self.meta_set("schema_hash", digest)

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:  # pragma: no cover
            pass

    # -------------------------------------------------------------- queries
    def execute(self, sql: str, params: tuple | list | dict = ()) -> sqlite3.Cursor:
        try:
            return self.conn.execute(sql, params)
        except sqlite3.OperationalError as exc:
            if _busy(exc):
                raise RTError(BUSY, "Roundtable is busy: another seat is writing right now", "try the same call again in a few seconds") from None
            raise

    def one(self, sql: str, params: tuple | list | dict = ()) -> sqlite3.Row | None:
        return self.execute(sql, params).fetchone()

    def all(self, sql: str, params: tuple | list | dict = ()) -> list[sqlite3.Row]:
        return self.execute(sql, params).fetchall()

    def scalar(self, sql: str, params: tuple | list | dict = (), default: Any = None) -> Any:
        row = self.one(sql, params)
        return default if row is None else row[0]

    def meta_get(self, key: str, default: str | None = None) -> str | None:
        row = self.one("SELECT value FROM meta WHERE key = ?", (key,))
        return default if row is None else row[0]

    def meta_set(self, key: str, value: str) -> None:
        self.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))

    # -------------------------------------------------------------- transactions
    @contextmanager
    def tx(self) -> Iterator["Store"]:
        """Write transaction (BEGIN IMMEDIATE). Re-entrant: inner calls join."""
        if self._depth > 0:
            self._depth += 1
            try:
                yield self
            finally:
                self._depth -= 1
            return
        deadline = time.monotonic() + BUSY_TIMEOUT_MS / 1000
        while True:
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                break
            except sqlite3.OperationalError as exc:
                if _busy(exc) and time.monotonic() < deadline:
                    time.sleep(0.05)
                    continue
                if _busy(exc):
                    raise RTError(BUSY, "Roundtable is busy: another seat is writing right now", "try the same call again in a few seconds") from None
                raise
        self._depth = 1
        try:
            yield self
        except BaseException:
            self._depth = 0
            try:
                self.conn.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass
            raise
        else:
            self._depth = 0
            try:
                self.conn.execute("COMMIT")
            except sqlite3.OperationalError as exc:
                try:
                    self.conn.execute("ROLLBACK")
                except sqlite3.OperationalError:
                    pass
                if _busy(exc):
                    raise RTError(BUSY, "Roundtable is busy: another seat is writing right now", "try the same call again in a few seconds") from None
                raise

    @property
    def in_tx(self) -> bool:
        return self._depth > 0


def _split_sql(script: str) -> list[str]:
    """Split a script of simple statements on ';' at line ends (no triggers)."""
    stmts, buf = [], []
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") or not stripped:
            continue
        # drop trailing inline comments after the SQL on the same line
        if "--" in line:
            line = line.split("--", 1)[0]
        buf.append(line)
        if line.rstrip().endswith(";"):
            stmts.append("\n".join(buf).strip().rstrip(";"))
            buf = []
    if buf and "\n".join(buf).strip():
        stmts.append("\n".join(buf).strip().rstrip(";"))
    return stmts

"""SQLite: una conexión por operación, WAL, claves foráneas y transacciones BEGIN IMMEDIATE.

Las escrituras se serializan con un candado de proceso además del bloqueo de SQLite, de modo que una
operación compuesta (venta: líneas + inventario + pagos + contabilidad) es atómica y no compite
con otra a mitad de camino.
"""
from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .migrations import MIGRATIONS


def _configure(conn: sqlite3.Connection) -> sqlite3.Connection:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.write_lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = FULL")
        finally:
            conn.close()

    def connect(self) -> sqlite3.Connection:
        return _configure(sqlite3.connect(self.path, isolation_level=None, check_same_thread=False))

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self.write_lock:
            conn = self.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    yield conn
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
                conn.execute("COMMIT")
            finally:
                conn.close()

    def migrate(self) -> list[int]:
        applied: list[int] = []
        with self.tx() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, name TEXT NOT NULL,"
                         " applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')))")
            done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
            for version, name, script in MIGRATIONS:
                if version in done:
                    continue
                for statement in split_sql(script):
                    conn.execute(statement)
                conn.execute("INSERT INTO schema_migrations(version, name) VALUES (?, ?)", (version, name))
                applied.append(version)
        return applied

    def schema_version(self) -> int:
        with self.read() as conn:
            row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
            return int(row[0] or 0)


def split_sql(script: str) -> list[str]:
    """Divide un script en sentencias completas (respeta triggers BEGIN…END)."""
    statements, buffer = [], ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            if buffer.strip():
                statements.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        statements.append(buffer.strip())
    return statements


def rows(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(r) for r in cursor.fetchall()]


def one(cursor: sqlite3.Cursor) -> dict[str, Any] | None:
    r = cursor.fetchone()
    return dict(r) if r else None

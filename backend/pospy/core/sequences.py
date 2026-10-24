"""Numeración consecutiva sin huecos dentro de la transacción que usa el número."""
from __future__ import annotations

import sqlite3


def next_number(conn: sqlite3.Connection, name: str) -> str:
    row = conn.execute("SELECT prefix, next_value, padding FROM sequences WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise KeyError(name)
    conn.execute("UPDATE sequences SET next_value = next_value + 1 WHERE name = ?", (name,))
    return f"{row['prefix']}{row['next_value']:0{row['padding']}d}"

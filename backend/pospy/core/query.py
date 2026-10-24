"""Listas paginadas con orden por columnas de lista blanca (los valores siempre van parametrizados)."""
from __future__ import annotations

import sqlite3
from typing import Any


def like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def paginate(conn: sqlite3.Connection, base_sql: str, params: list[Any], *, sort: str | None, direction: str | None,
             sortable: dict[str, str], default_sort: str, page: int = 1, page_size: int = 50,
             tiebreak: str = "id") -> dict:
    page = max(1, int(page or 1))
    page_size = min(200, max(1, int(page_size or 50)))
    column = sortable.get(sort or "", sortable[default_sort])
    order = "DESC" if (direction or "").lower() == "desc" else "ASC"
    total = conn.execute(f"SELECT COUNT(*) FROM ({base_sql})", params).fetchone()[0]
    items = [dict(r) for r in conn.execute(f"{base_sql} ORDER BY {column} {order}, {tiebreak} {order} LIMIT ? OFFSET ?",
                                           [*params, page_size, (page - 1) * page_size])]
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "pages": max(1, -(-total // page_size))}


def slug(text: str, max_len: int = 30) -> str:
    """'Remisión de venta' -> 'remision_de_venta' (código interno estable, sin tildes)."""
    import re
    import unicodedata
    plain = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", plain).strip("_")[:max_len]

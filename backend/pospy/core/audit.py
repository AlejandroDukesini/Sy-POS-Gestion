"""Bitácora de auditoría. Nunca registra contraseñas, tokens ni secretos."""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from .actor import Actor
from .clock import iso

_SENSITIVE = re.compile(r"(pass|token|secret|clave|key|authorization|cookie|code_verifier|refresh)", re.I)


def scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("[omitido]" if _SENSITIVE.search(str(k)) else scrub(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value]
    return value


def record(conn: sqlite3.Connection, actor: Actor | None, action: str, entity: str | None = None,
           entity_id: Any = None, details: dict | None = None) -> None:
    conn.execute(
        "INSERT INTO audit_log(created_at, user_id, username, action, entity, entity_id, details) VALUES (?,?,?,?,?,?,?)",
        (iso(), actor.id if actor else None, actor.username if actor else "anónimo", action, entity,
         None if entity_id is None else str(entity_id),
         json.dumps(scrub(details), ensure_ascii=False, default=str) if details else None),
    )

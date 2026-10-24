"""Migraciones versionadas. Cada módulo vNNN_*.py define VERSION, NAME y SQL; se aplican una sola vez y en orden."""
from __future__ import annotations

from . import v001_schema, v002_seed

MIGRATIONS: list[tuple[int, str, str]] = sorted(
    (m.VERSION, m.NAME, m.SQL) for m in (v001_schema, v002_seed)
)

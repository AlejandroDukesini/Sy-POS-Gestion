"""Migraciones versionadas. Cada módulo vNNN_*.py define VERSION, NAME y SQL; se aplican una sola vez y en orden."""
from __future__ import annotations

from . import v001_schema, v002_seed, v003_access, v004_supplier_records, v005_financial_reports, v006_inventory_observations

MIGRATIONS: list[tuple[int, str, str]] = sorted(
    (m.VERSION, m.NAME, m.SQL) for m in (v001_schema, v002_seed, v003_access, v004_supplier_records, v005_financial_reports,
                                     v006_inventory_observations)
)

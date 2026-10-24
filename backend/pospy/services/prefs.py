"""Preferencias personales de interfaz, por usuario (separadas de la configuración de la empresa)."""
from __future__ import annotations

import json

from ..core.actor import Actor
from ..core.clock import iso
from ..core.errors import ValidationError

SCHEMA = {
    "theme": ("light", ("light", "dark", "system")),
    "font_size": (16, (16, 18, 20, 22)),
    "density": ("comoda", ("comoda", "compacta")),
    "motion": ("system", ("system", "reduced")),
    "high_contrast": (False, (False, True)),
    "underline_links": (False, (False, True)),
    "sidebar": ("expanded", ("expanded", "collapsed")),
    "preferred_printer": ("", None),
}
VERSION = 1


def normalize(raw: dict | None) -> dict:
    data = raw or {}
    out = {}
    for key, (default, allowed) in SCHEMA.items():
        value = data.get(key, default)
        if allowed is None:
            value = str(value or "")[:200]
        elif value not in allowed:
            value = default
        out[key] = value
    out["version"] = VERSION
    return out


class PrefsService:
    def __init__(self, db):
        self.db = db

    def get(self, actor: Actor) -> dict:
        with self.db.read() as conn:
            row = conn.execute("SELECT data, updated_at FROM user_prefs WHERE user_id = ?", (actor.id,)).fetchone()
        prefs = normalize(json.loads(row["data"]) if row else None)
        prefs["updated_at"] = row["updated_at"] if row else None
        return prefs

    def save(self, actor: Actor, data: dict) -> dict:
        unknown = set(data) - set(SCHEMA) - {"version", "updated_at"}
        if unknown:
            raise ValidationError("Preferencias desconocidas: " + ", ".join(sorted(unknown)))
        for key, value in data.items():
            if key in SCHEMA and SCHEMA[key][1] is not None and value not in SCHEMA[key][1]:
                raise ValidationError("Valor no válido.", {key: "Opción no válida."})
        prefs = normalize({**self.get(actor), **data})
        prefs.pop("updated_at", None)
        with self.db.tx() as conn:
            conn.execute("INSERT INTO user_prefs(user_id, data, updated_at) VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE"
                         " SET data = excluded.data, updated_at = excluded.updated_at",
                         (actor.id, json.dumps(prefs), iso()))
        return self.get(actor)

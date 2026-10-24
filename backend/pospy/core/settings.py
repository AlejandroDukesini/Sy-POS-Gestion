"""Configuración global de la empresa, por secciones, con esquema, valores por defecto y validación.

Las preferencias personales (tema, tamaño de letra…) NO viven aquí: ver services/prefs.py.
Los secretos tampoco: ver core/secrets_store.py.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .actor import Actor
from .audit import record
from .clock import iso
from .errors import ValidationError


@dataclass(frozen=True)
class Field:
    kind: str                      # str | bool | int | choice | color
    default: Any
    label: str
    choices: tuple = ()
    minimum: int | None = None
    maximum: int | None = None
    max_len: int = 200
    check: Callable[[Any], str | None] | None = None


def _tz(value: str) -> str | None:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        return "Zona horaria desconocida (ej.: America/Bogota)."
    return None


def _email(value: str) -> str | None:
    return None if not value or re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value) else "Correo no válido."


SCHEMA: dict[str, dict[str, Field]] = {
    "empresa": {
        "name": Field("str", "Mi empresa", "Nombre comercial", max_len=120),
        "legal_name": Field("str", "", "Razón social", max_len=160),
        "tax_id": Field("str", "", "NIT o identificación", max_len=40),
        "address": Field("str", "", "Dirección", max_len=200),
        "city": Field("str", "", "Ciudad", max_len=80),
        "phone": Field("str", "", "Teléfono", max_len=60),
        "email": Field("str", "", "Correo", max_len=120, check=_email),
        "website": Field("str", "", "Sitio web", max_len=120),
        "primary_color": Field("color", "#1d4ed8", "Color corporativo"),
        "document_footer": Field("str", "", "Texto al pie de documentos", max_len=500),
        "timezone": Field("str", "America/Bogota", "Zona horaria", max_len=60, check=_tz),
        "currency_symbol": Field("str", "$", "Símbolo de moneda", max_len=4),
    },
    "ventas": {
        "prices_include_tax": Field("bool", True, "Los precios incluyen IVA"),
        "max_manual_discount_pct": Field("int", 10, "Descuento manual máximo (%)", minimum=0, maximum=100),
        "void_same_day_only": Field("bool", False, "Solo anular ventas del mismo día"),
    },
    "inventario": {
        "allow_negative_stock": Field("bool", False, "Permitir existencias negativas"),
        "default_min_stock": Field("int", 0, "Existencia mínima por defecto", minimum=0, maximum=1_000_000),
        "low_stock_alerts": Field("bool", True, "Mostrar alertas de existencias bajas"),
    },
    "impresion": {
        "receipt_printer": Field("str", "DIGITALPOS", "Impresora de comprobantes", max_len=200),
        "receipt_mode": Field("choice", "escpos", "Modo de impresión de comprobantes", choices=("escpos", "navegador")),
        "receipt_width_chars": Field("choice", 48, "Ancho de papel", choices=(32, 42, 48)),
        "receipt_copies": Field("int", 1, "Copias del comprobante", minimum=1, maximum=5),
        "receipt_cut": Field("bool", True, "Cortar papel al terminar"),
        "receipt_open_drawer": Field("bool", False, "Abrir cajón monedero en ventas en efectivo"),
        "auto_print_receipt": Field("bool", False, "Imprimir comprobante al confirmar la venta"),
        "receipt_header": Field("str", "", "Encabezado adicional del comprobante", max_len=300),
        "receipt_footer": Field("str", "Gracias por su compra", "Pie del comprobante", max_len=300),
    },
    "seguridad": {
        "session_idle_minutes": Field("int", 30, "Cierre por inactividad (minutos)", minimum=5, maximum=480),
        "session_max_hours": Field("int", 12, "Duración máxima de sesión (horas)", minimum=1, maximum=24),
        "lockout_attempts": Field("int", 5, "Intentos fallidos antes del bloqueo", minimum=3, maximum=20),
        "lockout_minutes": Field("int", 15, "Minutos de bloqueo", minimum=1, maximum=240),
    },
    "respaldos": {
        "auto_daily": Field("bool", True, "Copia automática diaria"),
        "keep": Field("int", 30, "Copias que se conservan", minimum=3, maximum=365),
    },
    "oauth": {
        "microsoft_client_id": Field("str", "", "Microsoft: Id. de aplicación (cliente)", max_len=80),
        "microsoft_tenant": Field("str", "common", "Microsoft: inquilino (common, consumers, organizations o Id.)", max_len=80),
        "google_client_id": Field("str", "", "Google: Id. de cliente OAuth (escritorio)", max_len=200),
    },
}

SECTION_LABELS = {
    "empresa": "Empresa", "ventas": "Ventas", "inventario": "Parámetros de inventario",
    "impresion": "Impresión de comprobantes", "seguridad": "Sesiones y seguridad",
    "respaldos": "Copias de seguridad", "oauth": "Credenciales de integraciones",
}
# Secciones que cualquier usuario autenticado puede leer (necesarias para operar la interfaz).
PUBLIC_READ = {"empresa", "ventas", "inventario", "impresion"}


def _coerce(name: str, f: Field, value: Any) -> Any:
    if f.kind == "bool":
        if isinstance(value, bool):
            return value
        raise ValidationError("Valor no válido.", {name: f"{f.label}: debe ser sí o no."})
    if f.kind == "int" or (f.kind == "choice" and isinstance(f.default, int)):
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise ValidationError("Valor no válido.", {name: f"{f.label}: debe ser un número entero."}) from None
        if f.kind == "choice" and number not in f.choices:
            raise ValidationError("Valor no válido.", {name: f"{f.label}: opción no válida."})
        if f.minimum is not None and number < f.minimum or f.maximum is not None and number > f.maximum:
            raise ValidationError("Valor fuera de rango.", {name: f"{f.label}: entre {f.minimum} y {f.maximum}."})
        return number
    text = "" if value is None else str(value).strip()
    if f.kind == "choice" and text not in f.choices:
        raise ValidationError("Valor no válido.", {name: f"{f.label}: opción no válida."})
    if f.kind == "color" and not re.fullmatch(r"#[0-9a-fA-F]{6}", text):
        raise ValidationError("Valor no válido.", {name: f"{f.label}: use un color hexadecimal (#1d4ed8)."})
    if len(text) > f.max_len:
        raise ValidationError("Texto demasiado largo.", {name: f"{f.label}: máximo {f.max_len} caracteres."})
    if f.check and (problem := f.check(text)):
        raise ValidationError("Valor no válido.", {name: problem})
    return text


class Settings:
    def __init__(self, db):
        self.db = db

    def get(self, section: str, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
        schema = SCHEMA[section]
        if conn is None:
            with self.db.read() as c:
                row = c.execute("SELECT value FROM settings WHERE key = ?", (section,)).fetchone()
        else:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (section,)).fetchone()
        stored = json.loads(row[0]) if row else {}
        return {k: stored.get(k, f.default) for k, f in schema.items()}

    def update(self, section: str, values: dict[str, Any], actor: Actor) -> dict[str, Any]:
        actor.require("gestion.configuracion")
        if section not in SCHEMA:
            raise ValidationError(f"Sección de configuración desconocida: {section}")
        schema = SCHEMA[section]
        unknown = set(values) - set(schema)
        if unknown:
            raise ValidationError("Campos desconocidos: " + ", ".join(sorted(unknown)))
        with self.db.tx() as conn:
            current = self.get(section, conn)
            changes = {}
            for name, value in values.items():
                coerced = _coerce(name, schema[name], value)
                if coerced != current[name]:
                    changes[name] = {"antes": current[name], "despues": coerced}
                current[name] = coerced
            conn.execute("INSERT INTO settings(key, value, updated_at, updated_by) VALUES (?,?,?,?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at,"
                         " updated_by = excluded.updated_by",
                         (section, json.dumps(current, ensure_ascii=False), iso(), actor.id))
            if changes:
                record(conn, actor, "configuracion.actualizar", "settings", section, changes)
        return current

    @staticmethod
    def describe() -> dict:
        return {section: {"label": SECTION_LABELS[section],
                          "fields": {k: {"kind": f.kind, "label": f.label, "default": f.default,
                                         "choices": list(f.choices), "min": f.minimum, "max": f.maximum,
                                         "max_len": f.max_len}
                                     for k, f in fields.items()}}
                for section, fields in SCHEMA.items()}

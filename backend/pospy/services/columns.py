"""Columnas del inventario: campos principales fijos + columnas adicionales configurables.

- Los campos principales (código, descripción, precios, costo, IVA, existencias…) viven en products y no
  se pueden eliminar ni mover: de ellos dependen ventas, compras, movimientos y contabilidad.
- Las columnas adicionales (inventory_columns) las administra quien tiene «inventario.columnas»:
  agregar, editar, ordenar, archivar (oculta, conserva los datos), restaurar y eliminar (borra sus
  valores, con confirmación). «Observaciones» es una columna del sistema: existe siempre y no se
  puede eliminar ni archivar.
- Cada valor se valida y normaliza según el tipo de su columna antes de guardarse. Un cambio de tipo
  u opciones solo se aplica si TODOS los valores existentes se pueden convertir (si no, se informa
  qué productos lo impiden). Con dry_run se calcula el impacto sin guardar nada.
"""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from datetime import date, datetime
from decimal import Decimal

from ..core.actor import Actor
from ..core.audit import record
from ..core.clock import iso
from ..core.errors import ConflictError, NotFoundError, ValidationError
from ..core.money import parse_decimal

TYPES = {
    "texto": "Texto", "texto_largo": "Texto largo", "entero": "Número entero", "decimal": "Número decimal",
    "fecha": "Fecha", "si_no": "Sí / No", "lista": "Lista de opciones",
}
MAX_LEN = {"texto": 200, "texto_largo": 5000}
# Campos principales: se muestran en «Administrar columnas» como fijos.
CORE = (
    ("code", "Código", "texto", True), ("description", "Descripción", "texto", True),
    ("category", "Categoría", "texto", False), ("unit", "Unidad", "lista", True),
    ("price", "Precio sin descuento", "decimal", True), ("discount_price", "Precio con descuento", "decimal", False),
    ("cost", "Costo", "decimal", False), ("tax_rate", "IVA %", "decimal", True),
    ("stock", "Cantidad disponible", "decimal", True), ("min_stock", "Existencia mínima", "decimal", True),
)
RESERVED = {n for _, n, _, _ in CORE} | {"Disponible", "Precio", "Cantidad", "Existencia", "Estado", "Activo"}
MAX_COLUMNS = 60
MAX_OPTIONS = 50
YES = {"si", "s", "1", "true", "verdadero", "x", "yes"}
NO = {"no", "n", "0", "false", "falso"}


def _norm(text) -> str:
    return unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower().strip()


def coerce(column: dict, raw) -> str | None:
    """Valor normalizado (texto) para guardar, o None si está vacío. ValueError si no es válido."""
    if raw is None:
        return None
    kind = column["data_type"]
    if isinstance(raw, str):
        raw = raw.strip()
        if raw == "":
            return None
    if kind in ("texto", "texto_largo"):
        if isinstance(raw, datetime):
            raw = raw.date().isoformat() if raw.time() == datetime.min.time() else raw.isoformat(sep=" ")
        elif isinstance(raw, date):
            raw = raw.isoformat()
        elif isinstance(raw, float) and raw.is_integer():
            raw = int(raw)
        text = str(raw)
        if len(text) > MAX_LEN[kind]:
            raise ValueError(f"admite hasta {MAX_LEN[kind]} caracteres")
        return text
    if kind in ("entero", "decimal"):
        if isinstance(raw, bool):
            raise ValueError("no es un número")
        number = parse_decimal(raw)
        if number is None:
            raise ValueError(f"«{raw}» no es un número")
        if abs(number) >= Decimal("1e15"):
            raise ValueError("número demasiado grande")
        if kind == "entero":
            if number != number.to_integral_value():
                raise ValueError(f"«{raw}» no es un número entero")
            return str(int(number))
        return format(number.normalize(), "f")
    if kind == "fecha":
        if isinstance(raw, datetime):
            return raw.date().isoformat()
        if isinstance(raw, date):
            return raw.isoformat()
        text = str(raw)[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", str(raw)) else str(raw)
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
            try:
                return datetime.strptime(text, fmt).date().isoformat()
            except ValueError:
                continue
        raise ValueError(f"«{raw}» no es una fecha (use AAAA-MM-DD o DD/MM/AAAA)")
    if kind == "si_no":
        if isinstance(raw, bool):
            return "1" if raw else "0"
        if isinstance(raw, (int, float)) and raw in (0, 1):
            return "1" if raw else "0"
        value = _norm(raw)
        if value in YES:
            return "1"
        if value in NO:
            return "0"
        raise ValueError(f"«{raw}» no es Sí o No")
    if kind == "lista":
        if isinstance(raw, float) and raw.is_integer():
            raw = int(raw)
        wanted = _norm(raw)
        for option in column["options"]:
            if _norm(option) == wanted:
                return option
        raise ValueError(f"«{raw}» no está entre las opciones ({', '.join(column['options'][:8])})")
    raise ValueError("tipo desconocido")


def typed(column: dict, value: str | None):
    """Valor para exportar a Excel con su tipo natural."""
    if value is None:
        return None
    kind = column["data_type"]
    if kind == "entero":
        return int(value)
    if kind == "decimal":
        return Decimal(value)
    if kind == "si_no":
        return "Sí" if value == "1" else "No"
    return value


class ColumnService:
    def __init__(self, db, scopes=None):
        self.db = db
        self.scopes = scopes   # inventario de la petición: cada inventario tiene sus propias columnas

    def _inv(self, conn: sqlite3.Connection, actor: Actor) -> int:
        return self.scopes.resolve(conn, actor, None)

    # ------------------------------------------------------------------ consulta
    def list(self, actor: Actor, include_archived: bool = False) -> dict:
        actor.require("inventario.ver")
        if include_archived:
            actor.require("inventario.columnas")
        with self.db.read() as conn:
            columns = self.columns_conn(conn, self._inv(conn, actor), include_archived)
            if include_archived:
                counts = dict(conn.execute("SELECT column_id, COUNT(*) FROM inventory_custom_values GROUP BY column_id").fetchall())
                for c in columns:
                    c["values_count"] = counts.get(c["id"], 0)
        return {"core": [{"key": k, "name": n, "data_type": t, "required": r} for k, n, t, r in CORE],
                "columns": columns, "types": TYPES}

    @staticmethod
    def columns_conn(conn: sqlite3.Connection, inventory_id: int, include_archived: bool = False) -> list[dict]:
        sql = ("SELECT * FROM inventory_columns WHERE inventory_id = ?" + ("" if include_archived else " AND active = 1")
               + " ORDER BY active DESC, position, id")
        out = []
        for r in conn.execute(sql, (inventory_id,)):
            c = dict(r)
            c["options"] = json.loads(c["options"] or "[]")
            out.append(c)
        return out

    def _get(self, conn: sqlite3.Connection, column_id: int, inventory_id: int | None = None) -> dict:
        row = conn.execute("SELECT * FROM inventory_columns WHERE id = ?", (column_id,)).fetchone()
        if not row or (inventory_id is not None and row["inventory_id"] != inventory_id):
            raise NotFoundError("Columna no encontrada.")
        c = dict(row)
        c["options"] = json.loads(c["options"] or "[]")
        return c

    # ------------------------------------------------------------------ definición
    def validate_definition(self, conn: sqlite3.Connection, data: dict, current: dict | None = None,
                            taken: set[str] = frozenset(), inventory_id: int | None = None) -> dict:
        """Nombre, tipo, descripción, opciones, obligatoriedad y valor predeterminado ya validados."""
        errors: dict[str, str] = {}
        merged = {**(current or {}), **{k: v for k, v in data.items() if v is not None or k == "default_value"}}
        name = " ".join(str(merged.get("name") or "").split())
        if not name:
            errors["name"] = "Escriba el nombre de la columna."
        elif len(name) > 60:
            errors["name"] = "El nombre admite hasta 60 caracteres."
        elif _norm(name) in {_norm(r) for r in RESERVED}:
            errors["name"] = f"«{name}» es un campo principal del inventario: elija otro nombre."
        elif _norm(name) in taken:
            errors["name"] = f"El nombre «{name}» está repetido."
        else:
            inv = current["inventory_id"] if current else inventory_id
            dup = conn.execute("SELECT name, active FROM inventory_columns WHERE name = ? COLLATE NOCASE AND inventory_id = ?"
                               " AND id IS NOT ?", (name, inv, current["id"] if current else None)).fetchone()
            if dup:
                errors["name"] = (f"Ya existe la columna «{dup['name']}»." if dup["active"] else
                                  f"Ya existe la columna archivada «{dup['name']}»: restáurela en lugar de crear otra.")
        kind = merged.get("data_type") or "texto"
        if kind not in TYPES:
            errors["data_type"] = "Elija un tipo de dato."
        description = str(merged.get("description") or "").strip()
        if len(description) > 300:
            errors["description"] = "La descripción admite hasta 300 caracteres."
        options: list[str] = []
        if kind == "lista":
            seen = set()
            for option in merged.get("options") or []:
                text = " ".join(str(option or "").split())
                if not text:
                    continue
                if len(text) > 60:
                    errors["options"] = "Cada opción admite hasta 60 caracteres."
                if _norm(text) in seen:
                    errors["options"] = f"La opción «{text}» está repetida."
                seen.add(_norm(text))
                options.append(text)
            if not options:
                errors["options"] = "Escriba al menos una opción."
            elif len(options) > MAX_OPTIONS:
                errors["options"] = f"Máximo {MAX_OPTIONS} opciones."
        required = bool(merged.get("required"))
        default = None
        raw_default = merged.get("default_value")
        if raw_default not in (None, "") and kind in TYPES and "options" not in errors:
            try:
                default = coerce({"data_type": kind, "options": options}, raw_default)
            except ValueError as exc:
                errors["default_value"] = f"Valor predeterminado: {exc}."
        if required and default is None and "default_value" not in errors:
            errors["default_value"] = "Una columna obligatoria necesita un valor predeterminado (se usa en los productos que no lo tengan)."
        if errors:
            raise ValidationError("Revise los datos de la columna.", errors)
        return {"name": name, "data_type": kind, "description": description, "required": int(required),
                "default_value": default, "options": options}

    def create(self, actor: Actor, data: dict) -> dict:
        actor.require("inventario.columnas")
        with self.db.tx() as conn:
            column_id, filled = self.create_conn(conn, actor, data, self._inv(conn, actor))
            column = self._get(conn, column_id)
        column["filled"] = filled
        return column

    def create_conn(self, conn: sqlite3.Connection, actor: Actor, data: dict, inventory_id: int,
                    system: bool = False) -> tuple[int, int]:
        if conn.execute("SELECT COUNT(*) FROM inventory_columns WHERE active = 1 AND inventory_id = ?",
                        (inventory_id,)).fetchone()[0] >= MAX_COLUMNS:
            raise ValidationError(f"El inventario admite hasta {MAX_COLUMNS} columnas adicionales activas.")
        values = self.validate_definition(conn, data, inventory_id=inventory_id)
        position = conn.execute("SELECT COALESCE(MAX(position), 0) + 10 FROM inventory_columns WHERE inventory_id = ?",
                                (inventory_id,)).fetchone()[0]
        now = iso()
        column_id = conn.execute(
            "INSERT INTO inventory_columns(inventory_id, name, data_type, description, required, default_value, options,"
            " position, is_system, created_at, updated_at, created_by, updated_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (inventory_id, values["name"], values["data_type"], values["description"], values["required"], values["default_value"],
             json.dumps(values["options"], ensure_ascii=False), position, int(system), now, now, actor.id, actor.id)).lastrowid
        filled = self._fill_default(conn, actor, column_id, values) if values["required"] else 0
        record(conn, actor, "inventario.columna_crear", "inventory_column", column_id,
               {"nombre": values["name"], "tipo": values["data_type"], "obligatoria": bool(values["required"]),
                "productos_completados": filled})
        return column_id, filled

    def update(self, actor: Actor, column_id: int, data: dict, dry_run: bool = False) -> dict:
        """Edita la definición. Si afecta valores existentes, los convierte o rechaza el cambio."""
        actor.require("inventario.columnas")
        with self.db.tx() as conn:
            current = self._get(conn, column_id, self._inv(conn, actor))
            if "version" in data and data["version"] is not None and int(data["version"]) != current["version"]:
                raise ConflictError("Otra persona modificó esta columna. Recargue y vuelva a intentarlo.")
            if current["is_system"] and any(k in data and data[k] is not None and data[k] != current[k]
                                            for k in ("data_type", "required", "default_value", "options")):
                raise ValidationError("En una columna del sistema solo se cambian el nombre, la descripción y la posición.")
            values = self.validate_definition(conn, {k: v for k, v in data.items() if k != "version"}, current)
            impact = self._impact(conn, current, values)
            if dry_run or impact["invalid"]:      # hasta aquí no se ha escrito nada
                if not dry_run:
                    examples = "; ".join(f"{i['code']}: «{i['value']}» ({i['error']})" for i in impact["invalid"][:5])
                    raise ValidationError(
                        f"No se puede aplicar el cambio: {impact['invalid_count']} producto(s) tienen valores que no se pueden"
                        f" convertir. Corríjalos primero. Ejemplos: {examples}", {"data_type": "Conversión no segura."})
                impact.pop("_converted")
                return {"column": current, "proposed": values, "impact": impact, "dry_run": True}
            for product_id, value in impact.pop("_converted"):
                conn.execute("UPDATE inventory_custom_values SET value = ?, updated_at = ?, updated_by = ?"
                             " WHERE product_id = ? AND column_id = ?", (value, iso(), actor.id, product_id, column_id))
            conn.execute("UPDATE inventory_columns SET name = ?, data_type = ?, description = ?, required = ?, default_value = ?,"
                         " options = ?, updated_at = ?, updated_by = ?, version = version + 1 WHERE id = ?",
                         (values["name"], values["data_type"], values["description"], values["required"],
                          values["default_value"], json.dumps(values["options"], ensure_ascii=False), iso(), actor.id, column_id))
            filled = self._fill_default(conn, actor, column_id, values) if values["required"] and current["active"] else 0
            changes = {k: {"antes": current[k], "despues": values[k]} for k in values if current[k] != values[k]}
            if changes:
                record(conn, actor, "inventario.columna_actualizar", "inventory_column", column_id,
                       {**changes, "valores_convertidos": impact["converted"], "productos_completados": filled})
            column = self._get(conn, column_id)
        impact.pop("_converted", None)
        impact["filled"] = filled
        return {"column": column, "impact": impact, "dry_run": False}

    def _impact(self, conn: sqlite3.Connection, current: dict, values: dict) -> dict:
        rows = conn.execute("SELECT v.product_id, v.value, p.code FROM inventory_custom_values v JOIN products p"
                            " ON p.id = v.product_id WHERE v.column_id = ? ORDER BY p.code", (current["id"],)).fetchall()
        missing = 0
        if values["required"] and current["active"]:
            missing = conn.execute("SELECT COUNT(*) FROM products p WHERE p.inventory_id = ? AND NOT EXISTS (SELECT 1 FROM"
                                   " inventory_custom_values v WHERE v.product_id = p.id AND v.column_id = ?)",
                                   (current["inventory_id"], current["id"])).fetchone()[0]
        converted, invalid = [], []
        type_change = values["data_type"] != current["data_type"] or values["options"] != current["options"]
        if type_change:
            for r in rows:
                source = r["value"]
                if current["data_type"] == "si_no" and values["data_type"] in ("texto", "texto_largo", "lista"):
                    source = "Sí" if source == "1" else "No"
                try:
                    new = coerce(values, source)
                except ValueError as exc:
                    invalid.append({"code": r["code"], "value": r["value"], "error": str(exc)})
                    continue
                if new != r["value"] and new is not None:
                    converted.append((r["product_id"], new))
        return {"values": len(rows), "type_change": type_change, "converted": len(converted), "_converted": converted,
                "invalid_count": len(invalid), "invalid": invalid[:20], "will_fill": missing}

    def _fill_default(self, conn: sqlite3.Connection, actor: Actor, column_id: int, values: dict) -> int:
        return conn.execute("INSERT INTO inventory_custom_values(product_id, column_id, value, updated_at, updated_by)"
                            " SELECT p.id, ?, ?, ?, ? FROM products p WHERE p.inventory_id = (SELECT inventory_id FROM"
                            " inventory_columns WHERE id = ?) AND NOT EXISTS (SELECT 1 FROM inventory_custom_values v"
                            " WHERE v.product_id = p.id AND v.column_id = ?)",
                            (column_id, values["default_value"], iso(), actor.id, column_id, column_id)).rowcount

    def set_active(self, actor: Actor, column_id: int, active: bool) -> dict:
        actor.require("inventario.columnas")
        with self.db.tx() as conn:
            column = self._get(conn, column_id, self._inv(conn, actor))
            if column["is_system"]:
                raise ValidationError("Las columnas del sistema no se archivan.")
            if column["active"] == int(active):
                return column
            if active and conn.execute("SELECT COUNT(*) FROM inventory_columns WHERE active = 1 AND inventory_id = ?",
                                       (column["inventory_id"],)).fetchone()[0] >= MAX_COLUMNS:
                raise ValidationError(f"El inventario admite hasta {MAX_COLUMNS} columnas adicionales activas.")
            position = column["position"]
            if active:
                position = conn.execute("SELECT COALESCE(MAX(position), 0) + 10 FROM inventory_columns WHERE active = 1"
                                        " AND inventory_id = ?", (column["inventory_id"],)).fetchone()[0]
            conn.execute("UPDATE inventory_columns SET active = ?, position = ?, updated_at = ?, updated_by = ?,"
                         " version = version + 1 WHERE id = ?", (int(active), position, iso(), actor.id, column_id))
            if active and column["required"]:
                self._fill_default(conn, actor, column_id, column)
            record(conn, actor, "inventario.columna_" + ("restaurar" if active else "archivar"), "inventory_column",
                   column_id, {"nombre": column["name"]})
            return self._get(conn, column_id)

    def delete(self, actor: Actor, column_id: int, dry_run: bool = False) -> dict:
        actor.require("inventario.columnas")
        with self.db.tx() as conn:
            column = self._get(conn, column_id, self._inv(conn, actor))
            if column["is_system"]:
                raise ValidationError("«{}» es una columna del sistema: no se puede eliminar.".format(column["name"]))
            count = conn.execute("SELECT COUNT(*) FROM inventory_custom_values WHERE column_id = ?", (column_id,)).fetchone()[0]
            if dry_run:
                return {"column": column, "values": count, "dry_run": True}
            conn.execute("DELETE FROM inventory_custom_values WHERE column_id = ?", (column_id,))
            conn.execute("DELETE FROM inventory_columns WHERE id = ?", (column_id,))
            record(conn, actor, "inventario.columna_eliminar", "inventory_column", column_id,
                   {"nombre": column["name"], "tipo": column["data_type"], "valores_eliminados": count})
        return {"deleted": column_id, "values": count, "dry_run": False}

    def reorder(self, actor: Actor, ids: list[int]) -> dict:
        actor.require("inventario.columnas")
        with self.db.tx() as conn:
            active = [r[0] for r in conn.execute("SELECT id FROM inventory_columns WHERE active = 1 AND inventory_id = ?",
                                                 (self._inv(conn, actor),))]
            if sorted(ids) != sorted(active) or len(set(ids)) != len(ids):
                raise ConflictError("La lista de columnas cambió. Recargue y vuelva a ordenar.")
            for position, column_id in enumerate(ids, start=1):
                conn.execute("UPDATE inventory_columns SET position = ?, updated_at = ? WHERE id = ?",
                             (position * 10, iso(), column_id))
            record(conn, actor, "inventario.columnas_ordenar", "inventory_column", None, {"orden": ids})
        return self.list(actor, include_archived=True)

    # ------------------------------------------------------------------ valores por producto
    @staticmethod
    def values_for(conn: sqlite3.Connection, product_ids: list[int]) -> dict[int, dict[str, str]]:
        result: dict[int, dict[str, str]] = {pid: {} for pid in product_ids}
        for start in range(0, len(product_ids), 500):
            chunk = product_ids[start:start + 500]
            marks = ",".join("?" * len(chunk))
            for r in conn.execute(f"SELECT v.product_id, v.column_id, v.value FROM inventory_custom_values v JOIN inventory_columns c"
                                  f" ON c.id = v.column_id WHERE c.active = 1 AND v.product_id IN ({marks})", chunk):
                result[r[0]][str(r[1])] = r[2]
        return result

    def set_values_conn(self, conn: sqlite3.Connection, actor: Actor, product_id: int, custom: dict | None,
                        creating: bool, keep_existing_on_empty: bool = False) -> dict:
        """Guarda los valores adicionales de un producto. Devuelve los cambios {nombre: {antes, despues}}.

        creating: las columnas activas sin valor toman su predeterminado; las obligatorias lo exigen.
        keep_existing_on_empty: un valor vacío NO borra el existente (importaciones incompletas).
        """
        custom = custom or {}
        inventory_id = conn.execute("SELECT inventory_id FROM products WHERE id = ?", (product_id,)).fetchone()[0]
        columns = {str(c["id"]): c for c in self.columns_conn(conn, inventory_id, include_archived=True)}
        errors: dict[str, str] = {}
        normalized: dict[str, str | None] = {}
        for key, raw in custom.items():
            column = columns.get(str(key))
            if column is None or not column["active"]:
                errors[f"custom.{key}"] = "Columna no disponible."
                continue
            try:
                normalized[str(key)] = coerce(column, raw)
            except ValueError as exc:
                errors[f"custom.{key}"] = f"{column['name']}: {exc}."
        current = dict(conn.execute("SELECT column_id, value FROM inventory_custom_values WHERE product_id = ?",
                                    (product_id,)).fetchall())
        for key, column in columns.items():
            if not column["active"]:
                continue
            if creating and normalized.get(key) is None and column["default_value"] is not None:
                normalized[key] = column["default_value"]
            if column["required"] and key in normalized and normalized[key] is None and not keep_existing_on_empty:
                errors[f"custom.{key}"] = f"{column['name']} es obligatoria."
        if errors:
            raise ValidationError("Revise las columnas adicionales del producto.", errors)
        changes = {}
        now = iso()
        for key, value in normalized.items():
            column_id = int(key)
            before = current.get(column_id)
            if value is None and keep_existing_on_empty:
                continue
            if value == before:
                continue
            if value is None:
                conn.execute("DELETE FROM inventory_custom_values WHERE product_id = ? AND column_id = ?", (product_id, column_id))
            else:
                conn.execute("INSERT INTO inventory_custom_values(product_id, column_id, value, updated_at, updated_by)"
                             " VALUES (?,?,?,?,?) ON CONFLICT(product_id, column_id) DO UPDATE SET value = excluded.value,"
                             " updated_at = excluded.updated_at, updated_by = excluded.updated_by",
                             (product_id, column_id, value, now, actor.id))
            changes[columns[key]["name"]] = {"antes": before, "despues": value}
        return changes

"""Categorías, clientes, proveedores y métodos de pago."""
from __future__ import annotations

import re
import sqlite3

from ..core.actor import Actor
from ..core.audit import record
from ..core.clock import iso
from ..core.errors import ConflictError, NotFoundError, ValidationError
from ..core.query import like, paginate, slug

PARTY_TABLES = {"clientes": ("customers", "credit_days", "cliente"), "proveedores": ("suppliers", "payment_days", "proveedor")}


def _text(data: dict, key: str, label: str, required: bool = False, max_len: int = 200) -> str:
    value = (data.get(key) or "").strip()
    if required and not value:
        raise ValidationError("Faltan datos.", {key: f"{label} es obligatorio."})
    if len(value) > max_len:
        raise ValidationError("Texto demasiado largo.", {key: f"{label}: máximo {max_len} caracteres."})
    return value


class CatalogService:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------ categorías
    def categories(self, actor: Actor, include_inactive: bool = False) -> list[dict]:
        actor.require("inventario.ver")
        sql = "SELECT c.*, (SELECT COUNT(*) FROM products p WHERE p.category_id = c.id) AS products FROM categories c"
        with self.db.read() as conn:
            return [dict(r) for r in conn.execute(sql + ("" if include_inactive else " WHERE active = 1") + " ORDER BY name")]

    def save_category(self, actor: Actor, data: dict, category_id: int | None = None) -> dict:
        actor.require("inventario.editar")
        name = _text(data, "name", "El nombre", required=True, max_len=80)
        active = int(bool(data.get("active", True)))
        with self.db.tx() as conn:
            dup = conn.execute("SELECT id FROM categories WHERE name = ? AND id IS NOT ?", (name, category_id)).fetchone()
            if dup:
                raise ConflictError("Ya existe una categoría con ese nombre.", {"name": "Nombre repetido."})
            now = iso()
            if category_id is None:
                category_id = conn.execute("INSERT INTO categories(name, active, created_at, updated_at) VALUES (?,?,?,?)",
                                           (name, active, now, now)).lastrowid
                record(conn, actor, "categoria.crear", "category", category_id, {"nombre": name})
            else:
                if not conn.execute("UPDATE categories SET name = ?, active = ?, updated_at = ? WHERE id = ?",
                                    (name, active, now, category_id)).rowcount:
                    raise NotFoundError("Categoría no encontrada.")
                record(conn, actor, "categoria.actualizar", "category", category_id, {"nombre": name, "activa": active})
            return dict(conn.execute("SELECT * FROM categories WHERE id = ?", (category_id,)).fetchone())

    # ------------------------------------------------------------------ clientes y proveedores
    def parties(self, actor: Actor, kind: str, q: str = "", include_inactive: bool = False, page: int = 1,
                page_size: int = 50, sort: str | None = None, direction: str | None = None) -> dict:
        table, _, _ = self._party(kind)
        self._require_party_read(actor, kind)
        where, params = [], []
        if not include_inactive:
            where.append("active = 1")
        if q:
            where.append("(name LIKE ? ESCAPE '\\' OR identification LIKE ? ESCAPE '\\' OR phone LIKE ? ESCAPE '\\')")
            params += [like(q)] * 3
        sql = f"SELECT * FROM {table}" + (" WHERE " + " AND ".join(where) if where else "")
        with self.db.read() as conn:
            return paginate(conn, sql, params, sort=sort, direction=direction, default_sort="name",
                            sortable={"name": "name COLLATE NOCASE", "identification": "identification", "created_at": "created_at"},
                            page=page, page_size=page_size)

    def get_party(self, actor: Actor, kind: str, party_id: int) -> dict:
        table, _, _ = self._party(kind)
        self._require_party_read(actor, kind)
        with self.db.read() as conn:
            row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (party_id,)).fetchone()
        if not row:
            raise NotFoundError("Registro no encontrado.")
        return dict(row)

    def save_party(self, actor: Actor, kind: str, data: dict, party_id: int | None = None) -> dict:
        self._party(kind)
        # Quien vende o cotiza puede registrar un cliente nuevo; editar terceros exige permiso de gestión.
        can_register = kind == "clientes" and party_id is None and (actor.can("ventas.vender") or actor.can("documentos.crear"))
        if not can_register:
            actor.require("terceros.gestionar")
        with self.db.tx() as conn:
            return self.save_party_conn(conn, actor, kind, data, party_id)

    def save_party_conn(self, conn: sqlite3.Connection, actor: Actor, kind: str, data: dict, party_id: int | None = None) -> dict:
        table, days_col, label = self._party(kind)
        values = {
            "identification": _text(data, "identification", "La identificación", max_len=40) or None,
            "name": _text(data, "name", "El nombre", required=True, max_len=160),
            "phone": _text(data, "phone", "El teléfono", max_len=60),
            "email": _text(data, "email", "El correo", max_len=120),
            "address": _text(data, "address", "La dirección", max_len=200),
        }
        if values["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", values["email"]):
            raise ValidationError("Correo no válido.", {"email": "Escriba un correo como nombre@dominio.com."})
        try:
            days = int(data.get(days_col, 30) if data.get(days_col) not in (None, "") else 30)
        except (TypeError, ValueError):
            raise ValidationError("Valor no válido.", {days_col: "Días de plazo: número entero."}) from None
        if not 0 <= days <= 365:
            raise ValidationError("Valor no válido.", {days_col: "Días de plazo entre 0 y 365."})
        values[days_col] = days
        values["active"] = int(bool(data.get("active", True)))
        if values["identification"]:
            dup = conn.execute(f"SELECT id FROM {table} WHERE identification = ? AND id IS NOT ?",
                               (values["identification"], party_id)).fetchone()
            if dup:
                raise ConflictError(f"Ya existe un {label} con esa identificación.",
                                    {"identification": "Identificación repetida."})
        now = iso()
        if party_id is None:
            cols = ", ".join(values)
            cur = conn.execute(f"INSERT INTO {table}({cols}, created_at, updated_at) VALUES ({', '.join('?' * len(values))}, ?, ?)",
                               (*values.values(), now, now))
            party_id = cur.lastrowid
            record(conn, actor, f"{label}.crear", table, party_id, {"nombre": values["name"]})
        else:
            current = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (party_id,)).fetchone()
            if not current:
                raise NotFoundError("Registro no encontrado.")
            if "version" in data and int(data["version"]) != current["version"]:
                raise ConflictError("Otra persona modificó este registro. Recargue y vuelva a intentarlo.")
            sets = ", ".join(f"{k} = ?" for k in values)
            conn.execute(f"UPDATE {table} SET {sets}, updated_at = ?, version = version + 1 WHERE id = ?",
                         (*values.values(), now, party_id))
            changes = {k: {"antes": current[k], "despues": v} for k, v in values.items() if current[k] != v}
            if changes:
                record(conn, actor, f"{label}.actualizar", table, party_id, changes)
        return dict(conn.execute(f"SELECT * FROM {table} WHERE id = ?", (party_id,)).fetchone())

    @staticmethod
    def _party(kind: str) -> tuple[str, str, str]:
        if kind not in PARTY_TABLES:
            raise NotFoundError("Tipo de tercero desconocido.")
        return PARTY_TABLES[kind]

    @staticmethod
    def _require_party_read(actor: Actor, kind: str) -> None:
        if kind == "clientes":
            if not any(actor.can(p) for p in ("terceros.gestionar", "ventas.vender", "documentos.crear", "finanzas.ver")):
                actor.require("terceros.gestionar")
        elif not any(actor.can(p) for p in ("terceros.gestionar", "finanzas.ver", "inventario.movimientos")):
            actor.require("terceros.gestionar")

    # ------------------------------------------------------------------ métodos de pago
    def payment_methods(self, actor: Actor, include_inactive: bool = False) -> list[dict]:
        with self.db.read() as conn:
            sql = ("SELECT m.*, a.code AS account_code, a.name AS account_name FROM payment_methods m"
                   " LEFT JOIN accounts a ON a.id = m.account_id")
            return [dict(r) for r in conn.execute(sql + ("" if include_inactive else " WHERE m.active = 1") + " ORDER BY sort_order, name")]

    def save_payment_method(self, actor: Actor, data: dict, method_id: int | None = None) -> dict:
        actor.require("gestion.configuracion")
        name = _text(data, "name", "El nombre", required=True, max_len=60)
        kind = data.get("kind", "otro")
        if kind not in ("efectivo", "tarjeta", "transferencia", "credito", "otro"):
            raise ValidationError("Tipo no válido.", {"kind": "Tipo de método no válido."})
        active = int(bool(data.get("active", True)))
        with self.db.tx() as conn:
            account = None
            if kind != "credito":
                code = (data.get("account_code") or "").strip()
                acc = conn.execute("SELECT id FROM accounts WHERE code = ? AND is_cash = 1 AND active = 1", (code,)).fetchone()
                if not acc:
                    raise ValidationError("Cuenta no válida.", {"account_code": "Elija una cuenta de caja o bancos."})
                account = acc[0]
            if method_id is None:
                code = slug(name) or "metodo"
                base, n = code, 2
                while conn.execute("SELECT 1 FROM payment_methods WHERE code = ?", (code,)).fetchone():
                    code, n = f"{base}_{n}", n + 1
                order = conn.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM payment_methods").fetchone()[0]
                method_id = conn.execute("INSERT INTO payment_methods(code, name, kind, account_id, active, sort_order)"
                                         " VALUES (?,?,?,?,?,?)", (code, name, kind, account, active, order)).lastrowid
                record(conn, actor, "metodo_pago.crear", "payment_method", method_id, {"nombre": name, "tipo": kind})
            else:
                if not conn.execute("UPDATE payment_methods SET name = ?, kind = ?, account_id = ?, active = ? WHERE id = ?",
                                    (name, kind, account, active, method_id)).rowcount:
                    raise NotFoundError("Método de pago no encontrado.")
                record(conn, actor, "metodo_pago.actualizar", "payment_method", method_id,
                       {"nombre": name, "tipo": kind, "activo": active})
            return dict(conn.execute("SELECT * FROM payment_methods WHERE id = ?", (method_id,)).fetchone())

    # ------------------------------------------------------------------ actividad
    def activity(self, actor: Actor, q: str = "", user_id: int | None = None, entity: str = "", date_from: str = "",
                 date_to: str = "", page: int = 1, page_size: int = 50) -> dict:
        if not actor.can("gestion.auditoria"):
            user_id = actor.id   # sin permiso de auditoría: solo "mis operaciones"
        where, params = [], []
        if user_id:
            where.append("user_id = ?")
            params.append(user_id)
        if entity:
            where.append("entity = ?")
            params.append(entity)
        if q:
            where.append("(action LIKE ? ESCAPE '\\' OR details LIKE ? ESCAPE '\\' OR username LIKE ? ESCAPE '\\')")
            params += [like(q)] * 3
        if date_from:
            where.append("created_at >= ?")
            params.append(date_from[:10])
        if date_to:
            where.append("created_at < date(?, '+1 day')")
            params.append(date_to[:10])
        sql = "SELECT * FROM audit_log" + (" WHERE " + " AND ".join(where) if where else "")
        with self.db.read() as conn:
            return paginate(conn, sql, params, sort="created_at", direction="desc", default_sort="created_at",
                            sortable={"created_at": "created_at"}, page=page, page_size=page_size)

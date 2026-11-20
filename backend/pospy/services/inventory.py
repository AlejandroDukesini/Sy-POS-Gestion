"""Productos y movimientos de inventario.

La existencia de un producto es la suma de sus movimientos (la base de datos lo garantiza con
triggers). Editar un producto nunca cambia su existencia ni borra historial: para eso están las
entradas, salidas y ajustes, que quedan con fecha, usuario, motivo, cantidades y asiento contable.
"""
from __future__ import annotations

import csv
import io
import sqlite3
from datetime import timedelta
from decimal import Decimal

from ..core.actor import Actor
from ..core.audit import record
from ..core.clock import iso, local_today, parse_date
from ..core.errors import ConflictError, NotFoundError, ValidationError
from ..core.money import from_cents, from_milli, parse_decimal, round_cents, to_bp, to_cents, to_milli
from ..core.query import like, paginate
from . import ledger
from .columns import ColumnService, typed
from .ledger import Line
from .open_items import AP, OpenItems
from .scopes import InventoryScopes

UNITS = ("und", "kg", "g", "l", "ml", "m", "cm", "caja", "paquete", "servicio")
ENTRY_COUNTERPARTS = {
    "compra_contado": "Compra de contado",
    "compra_credito": "Compra a crédito (crea cuenta por pagar)",
    "inventario_inicial": "Inventario inicial (aporte de capital)",
    "sobrante": "Sobrante encontrado",
}
EXIT_COUNTERPARTS = {
    "merma": "Merma, daño o pérdida",
    "consumo_interno": "Consumo interno",
}
# Categorías del panel de movimientos (sobre inventory_movements m).
CATEGORIES = {
    "entradas": "(m.kind IN ('inicial','entrada','anulacion_venta') OR (m.kind IN ('ajuste','conciliacion') AND m.qty_milli > 0))",
    "salidas": "(m.kind IN ('venta','salida') OR (m.kind IN ('ajuste','conciliacion') AND m.qty_milli < 0))",
    "devoluciones": "(m.kind = 'devolucion')",
}
PRODUCT_FIELDS = ("code", "description", "category_id", "unit", "price", "discount_price", "cost", "tax_rate",
                  "min_stock", "active", "external_ref")


class InventoryService:
    def __init__(self, db, settings, scopes: InventoryScopes | None = None):
        self.db = db
        self.settings = settings
        self.payables = OpenItems(db, settings, AP)
        self.scopes = scopes or InventoryScopes(db)
        self.columns = ColumnService(db, self.scopes)

    def _scope(self, actor: Actor, inventory: str | None) -> int | None:
        with self.db.read() as conn:
            return self.scopes.resolve(conn, actor, inventory)

    def _product_group(self, conn: sqlite3.Connection, actor: Actor, product_id: int) -> int | None:
        """Inventario del producto, si esta persona puede entrar a él; si no, «no encontrado»."""
        row = conn.execute("SELECT inventory_id FROM products WHERE id = ?", (product_id,)).fetchone()
        if not row:
            raise NotFoundError("Producto no encontrado.")
        self.scopes.check(conn, actor, row["inventory_id"])
        return row["inventory_id"]

    def _tz(self) -> str:
        return self.settings.get("empresa")["timezone"]

    # ------------------------------------------------------------------ consulta
    def list(self, actor: Actor, q: str = "", category_id: int | None = None, status: str = "activos",
             low_stock: bool = False, sort: str | None = None, direction: str | None = None, page: int = 1,
             page_size: int = 50, inventory: str | None = None) -> dict:
        actor.require("inventario.ver")
        where, params = ["p.inventory_id IS ?"], [self._scope(actor, inventory)]
        if status == "activos":
            where.append("p.active = 1")
        elif status == "inactivos":
            where.append("p.active = 0")
        if q:
            where.append("(p.code LIKE ? ESCAPE '\\' OR p.description LIKE ? ESCAPE '\\' OR EXISTS (SELECT 1 FROM"
                         " inventory_custom_values v JOIN inventory_columns ic ON ic.id = v.column_id WHERE v.product_id = p.id"
                         " AND ic.active = 1 AND v.value LIKE ? ESCAPE '\\'))")
            params += [like(q.strip())] * 3
        if category_id:
            where.append("p.category_id = ?")
            params.append(category_id)
        if low_stock:
            where.append("p.stock_milli <= p.min_stock_milli AND p.active = 1")
        sql = ("SELECT p.*, c.name AS category_name, (p.stock_milli <= p.min_stock_milli) AS low_stock"
               " FROM products p LEFT JOIN categories c ON c.id = p.category_id"
               + (" WHERE " + " AND ".join(where) if where else ""))
        with self.db.read() as conn:
            result = paginate(conn, sql, params, sort=sort, direction=direction, default_sort="code", page=page,
                              page_size=page_size, tiebreak="p.id", sortable={
                                  "code": "p.code COLLATE NOCASE", "description": "p.description COLLATE NOCASE",
                                  "price": "p.price_cents", "discount_price": "COALESCE(p.discount_price_cents, p.price_cents)",
                                  "cost": "p.cost_cents", "stock": "p.stock_milli", "updated_at": "p.updated_at"})
            custom = self.columns.values_for(conn, [p["id"] for p in result["items"]])
        result["items"] = [self._public(actor, p) for p in result["items"]]
        for p in result["items"]:
            p["custom"] = custom.get(p["id"], {})
        return result

    @staticmethod
    def _public(actor: Actor, product: dict) -> dict:
        product["low_stock"] = bool(product.get("low_stock")) and bool(product["active"])
        if not actor.can("inventario.costos"):
            product.pop("cost_cents", None)
        return product

    def get(self, actor: Actor, product_id: int) -> dict:
        actor.require("inventario.ver")
        with self.db.read() as conn:
            row = conn.execute("SELECT p.*, c.name AS category_name, (p.stock_milli <= p.min_stock_milli) AS low_stock,"
                               " cu.username AS created_by_name, uu.username AS updated_by_name FROM products p"
                               " LEFT JOIN categories c ON c.id = p.category_id LEFT JOIN users cu ON cu.id = p.created_by"
                               " LEFT JOIN users uu ON uu.id = p.updated_by WHERE p.id = ?", (product_id,)).fetchone()
            if not row:
                raise NotFoundError("Producto no encontrado.")
            self.scopes.check(conn, actor, row["inventory_id"])
            custom = self.columns.values_for(conn, [product_id])[product_id]
        product = self._public(actor, dict(row))
        product["custom"] = custom
        return product

    def lookup(self, actor: Actor, q: str, limit: int = 20, inventory: str | None = None) -> list[dict]:
        """Búsqueda rápida para vender o cotizar (en el inventario elegido): coincidencia exacta de código primero."""
        if not any(actor.can(p) for p in ("ventas.vender", "documentos.crear", "inventario.ver")):
            actor.require("inventario.ver")
        q = (q or "").strip()
        if not q:
            return []
        with self.db.read() as conn:
            inventory_id = self.scopes.resolve(conn, actor, inventory)
            rows = conn.execute(
                "SELECT p.id, p.code, p.description, p.unit, p.price_cents, p.discount_price_cents, p.tax_rate_bp,"
                " p.stock_milli, p.min_stock_milli FROM products p WHERE p.active = 1 AND p.inventory_id IS ? AND (p.code = ? COLLATE NOCASE"
                " OR p.code LIKE ? ESCAPE '\\' OR p.description LIKE ? ESCAPE '\\')"
                " ORDER BY (p.code = ? COLLATE NOCASE) DESC, p.description COLLATE NOCASE LIMIT ?",
                (inventory_id, q, like(q), like(q), q, min(50, max(1, limit)))).fetchall()
        return [dict(r) for r in rows]

    def history(self, actor: Actor, product_id: int | None = None, kind: str = "", date_from: str = "",
                date_to: str = "", page: int = 1, page_size: int = 50, inventory: str | None = None,
                category: str = "", user_id: int | None = None) -> dict:
        """Movimientos (más recientes primero). category: entradas | salidas; user_id: quién lo registró."""
        actor.require("inventario.ver")
        where, params = [], []
        if category:
            if category not in CATEGORIES:
                raise ValidationError("Tipo de movimiento no válido.")
            where.append(CATEGORIES[category])
        if user_id:
            where.append("m.user_id = ?")
            params.append(user_id)
        if product_id:
            with self.db.read() as conn:
                self._product_group(conn, actor, product_id)
            where.append("m.product_id = ?")
            params.append(product_id)
        else:
            where.append("p.inventory_id IS ?")
            params.append(self._scope(actor, inventory))
        if kind:
            where.append("m.kind = ?")
            params.append(kind)
        if date_from:
            where.append("m.created_at >= ?")
            params.append(date_from[:10])
        if date_to:
            where.append("m.created_at < date(?, '+1 day')")
            params.append(date_to[:10])
        sql = ("SELECT m.*, m.stock_after_milli - m.qty_milli AS stock_before_milli, p.code, p.description, p.unit,"
               " u.username, u.full_name,"
               " CASE m.reference_type WHEN 'venta' THEN (SELECT number FROM sales WHERE id = m.reference_id)"
               "  WHEN 'devolucion' THEN (SELECT number FROM sale_returns WHERE id = m.reference_id) END AS reference_number"
               " FROM inventory_movements m JOIN products p ON p.id = m.product_id LEFT JOIN users u ON u.id = m.user_id"
               + (" WHERE " + " AND ".join(where) if where else ""))
        with self.db.read() as conn:
            result = paginate(conn, sql, params, sort="id", direction="desc", default_sort="id", tiebreak="m.id", sortable={"id": "m.id"},
                              page=page, page_size=page_size)
        if not actor.can("inventario.costos"):
            for m in result["items"]:
                m.pop("unit_cost_cents", None)
        return result

    def returns(self, actor: Actor, inventory: str | None = None, date_from: str = "", date_to: str = "",
                product_id: int | None = None, user_id: int | None = None, condition: str = "", page: int = 1,
                page_size: int = 50) -> dict:
        """Productos devueltos por clientes, con la venta original y cuánto volvió realmente al inventario."""
        actor.require("inventario.ver")
        where, params = ["s.inventory_id IS ?"], [self._scope(actor, inventory)]
        for value, clause in ((date_from, "r.return_date >= ?"), (date_to, "r.return_date <= ?")):
            if value:
                where.append(clause)
                params.append(str(parse_date(value)))
        if product_id:
            where.append("sl.product_id = ?")
            params.append(product_id)
        if user_id:
            where.append("r.user_id = ?")
            params.append(user_id)
        if condition:
            if condition not in ("apto", "revision", "no_apto"):
                raise ValidationError("Estado no válido.")
            where.append("rl.condition = ?")
            params.append(condition)
        sql = ("SELECT rl.id, rl.qty_milli, rl.condition, rl.resolved_at, CASE WHEN rl.condition = 'apto' THEN rl.qty_milli ELSE 0 END"
               " AS restocked_milli, r.id AS return_id, r.number AS return_number, r.reason, r.return_date, r.created_at,"
               " r.refund_cents, s.id AS sale_id, s.number AS sale_number, sl.product_id, sl.code, sl.description,"
               " u.full_name AS user_name, ru.full_name AS resolved_by_name"
               " FROM sale_return_lines rl JOIN sale_returns r ON r.id = rl.return_id JOIN sales s ON s.id = r.sale_id"
               " JOIN sale_lines sl ON sl.id = rl.sale_line_id JOIN users u ON u.id = r.user_id"
               " LEFT JOIN users ru ON ru.id = rl.resolved_by WHERE " + " AND ".join(where))
        with self.db.read() as conn:
            return paginate(conn, sql, params, sort="id", direction="desc", default_sort="id", tiebreak="rl.id",
                            sortable={"id": "rl.id"}, page=page, page_size=page_size)

    def dashboard(self, actor: Actor, inventory: str | None = None, date_from: str = "", date_to: str = "",
                  product_id: int | None = None, user_id: int | None = None) -> dict:
        """Indicadores del inventario elegido para el periodo y filtros (datos reales de la base)."""
        actor.require("inventario.ver")
        with self.db.read() as conn:
            inventory_id = self.scopes.resolve(conn, actor, inventory)
            # Mismos filtros sobre movimientos (m), ventas (s) y devoluciones (r/sl).
            where, swhere, rwhere = ["p.inventory_id IS ?"], ["s.inventory_id IS ?"], ["s.inventory_id IS ?"]
            params, sparams, rparams = [inventory_id], [inventory_id], [inventory_id]

            def add(clause_m: str, clause_s: str, clause_r: str, value) -> None:
                where.append(clause_m)
                swhere.append(clause_s)
                rwhere.append(clause_r)
                params.append(value)
                sparams.append(value)
                rparams.append(value)

            for value, op in ((date_from, ">="), (date_to, "<=")):
                if value:
                    add(f"date(m.created_at) {op} ?", f"s.sale_date {op} ?", f"r.return_date {op} ?", str(parse_date(value)))
            if product_id:
                add("m.product_id = ?", "EXISTS (SELECT 1 FROM sale_lines x WHERE x.sale_id = s.id AND x.product_id = ?)",
                    "sl.product_id = ?", product_id)
            if user_id:
                add("m.user_id = ?", "s.user_id = ?", "r.user_id = ?", user_id)
            base = " FROM inventory_movements m JOIN products p ON p.id = m.product_id WHERE " + " AND ".join(where)
            counts = {}
            for name, clause in CATEGORIES.items():
                row = conn.execute(f"SELECT COUNT(*), COALESCE(SUM(ABS(m.qty_milli)), 0){base} AND {clause}", params).fetchone()
                counts[name] = {"count": row[0], "qty_milli": row[1]}
            ret = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(rl.qty_milli), 0), COALESCE(SUM(CASE WHEN rl.condition = 'apto' THEN rl.qty_milli END), 0),"
                " COALESCE(SUM(rl.condition = 'revision'), 0) FROM sale_return_lines rl JOIN sale_returns r ON r.id = rl.return_id"
                " JOIN sales s ON s.id = r.sale_id JOIN sale_lines sl ON sl.id = rl.sale_line_id WHERE " + " AND ".join(rwhere),
                rparams).fetchone()
            counts["devoluciones"] = {"count": ret[0], "qty_milli": ret[1], "restocked_milli": ret[2], "pending_review": ret[3]}
            sales = conn.execute("SELECT COUNT(*) FILTER (WHERE s.status = 'completada'), COUNT(*) FILTER (WHERE s.status = 'anulada'),"
                                 " COALESCE(SUM(s.total_cents) FILTER (WHERE s.status = 'completada'), 0) FROM sales s WHERE "
                                 + " AND ".join(swhere), sparams).fetchone()
            low = conn.execute("SELECT COUNT(*) FROM products WHERE active = 1 AND inventory_id IS ? AND stock_milli <= min_stock_milli",
                               (inventory_id,)).fetchone()[0]
            people = [dict(r) for r in conn.execute(
                "SELECT u.id, u.full_name, COUNT(*) AS movements, MAX(m.created_at) AS last_at"
                f"{base.replace(' WHERE ', ' JOIN users u ON u.id = m.user_id WHERE ', 1)} GROUP BY u.id ORDER BY movements DESC LIMIT 20",
                params)]
            info = self.scopes.describe(conn, inventory_id)
        return {"inventory": info, "counts": counts,
                "sales": {"completed": sales[0], "voided": sales[1], "total_cents": sales[2]} if actor.can("ventas.historial")
                else {"completed": sales[0], "voided": sales[1]},
                "low_stock": low, "people": people}

    def summary(self, actor: Actor, inventory: str | None = None) -> dict:
        actor.require("inventario.ver")
        with self.db.read() as conn:
            inventory_id = self.scopes.resolve(conn, actor, inventory)
            row = conn.execute("SELECT COUNT(*) AS products, SUM(stock_milli <= min_stock_milli) AS low_stock,"
                               " SUM(stock_milli <= 0) AS out_of_stock,"
                               " SUM(CASE WHEN stock_milli > 0 THEN stock_milli * cost_cents / 1000 ELSE 0 END) AS value_cents"
                               " FROM products WHERE active = 1 AND inventory_id IS ?", (inventory_id,)).fetchone()
        result = {"products": row["products"], "low_stock": row["low_stock"] or 0, "out_of_stock": row["out_of_stock"] or 0}
        if actor.can("inventario.costos"):
            result["value_cents"] = int(row["value_cents"] or 0)
        return result

    # ------------------------------------------------------------------ altas y ediciones
    def _validated(self, conn: sqlite3.Connection, data: dict, current: dict | None, inventory_id: int | None = None) -> dict:
        errors: dict[str, str] = {}
        merged = {**(current or {}), **{k: v for k, v in data.items() if k in PRODUCT_FIELDS}}

        def money(key: str, label: str, required: bool) -> int | None:
            raw = merged.get(key) if key in data or current is None else None
            if key not in data and current is not None:
                return current[f"{key}_cents"]
            if raw in (None, ""):
                if required:
                    errors[key] = f"{label} es obligatorio."
                return None
            value = parse_decimal(raw)
            if value is None or value < 0:
                errors[key] = f"{label}: escriba un valor numérico mayor o igual a cero."
                return None
            if value > Decimal("100000000000"):
                errors[key] = f"{label}: valor demasiado alto."
                return None
            return to_cents(value)

        code = str(merged.get("code") or "").strip()
        description = str(merged.get("description") or "").strip()
        if not code:
            errors["code"] = "El código es obligatorio."
        elif len(code) > 40:
            errors["code"] = "El código admite hasta 40 caracteres."
        if not description:
            errors["description"] = "La descripción es obligatoria."
        elif len(description) > 200:
            errors["description"] = "La descripción admite hasta 200 caracteres."
        price = money("price", "El precio sin descuento", True)
        discount_price = money("discount_price", "El precio con descuento", False)
        cost = money("cost", "El costo", False)
        if price is not None and discount_price is not None and discount_price > price:
            errors["discount_price"] = "El precio con descuento no puede ser mayor que el precio sin descuento."
        unit = str(merged.get("unit") or "und").strip()
        if unit not in UNITS:
            errors["unit"] = "Unidad no válida."
        tax = merged.get("tax_rate") if "tax_rate" in data or current is None else None
        tax_bp = current["tax_rate_bp"] if tax is None and current is not None else None
        if tax_bp is None:
            parsed = parse_decimal(tax if tax not in (None, "") else 0)
            if parsed is None or parsed < 0 or parsed > 100:
                errors["tax_rate"] = "La tarifa de IVA debe estar entre 0 y 100 %."
            else:
                tax_bp = to_bp(parsed)
        min_stock = merged.get("min_stock") if "min_stock" in data or current is None else None
        if min_stock is None and current is not None:
            min_milli = current["min_stock_milli"]
        else:
            parsed = parse_decimal(min_stock if min_stock not in (None, "") else self.settings.get("inventario")["default_min_stock"])
            if parsed is None or parsed < 0:
                errors["min_stock"] = "La existencia mínima debe ser un número mayor o igual a cero."
                min_milli = 0
            else:
                min_milli = to_milli(parsed)
        category_id = merged.get("category_id") or None
        if category_id is not None:
            try:
                category_id = int(category_id)
            except (TypeError, ValueError):
                category_id = -1
            if not conn.execute("SELECT 1 FROM categories WHERE id = ?", (category_id,)).fetchone():
                errors["category_id"] = "Seleccione una categoría válida."
        if code and not errors.get("code"):
            inventory_id = current["inventory_id"] if current else inventory_id
            dup = conn.execute("SELECT id FROM products WHERE code = ? AND inventory_id IS ? AND id IS NOT ?",
                               (code, inventory_id, current["id"] if current else None)).fetchone()
            if dup:
                errors["code"] = "Ya existe un producto con este código en este inventario."
        if errors:
            raise ValidationError("Revise los datos del producto.", errors)
        return {"code": code, "description": description, "category_id": category_id, "unit": unit,
                "price_cents": price, "discount_price_cents": discount_price, "cost_cents": cost or 0,
                "tax_rate_bp": tax_bp, "min_stock_milli": min_milli,
                "active": int(bool(merged.get("active", True))),
                "external_ref": (str(merged.get("external_ref") or "").strip() or None)}

    def create(self, actor: Actor, data: dict, inventory: str | None = None) -> dict:
        actor.require("inventario.editar")
        initial = parse_decimal(data.get("initial_stock")) if data.get("initial_stock") not in (None, "") else None
        if initial is not None:
            actor.require("inventario.movimientos")
            if initial < 0:
                raise ValidationError("Revise los datos.", {"initial_stock": "La existencia inicial no puede ser negativa."})
        with self.db.tx() as conn:
            inventory_id = self.scopes.resolve(conn, actor, inventory)
            self.scopes.require_active(conn, inventory_id)
            product_id = self.create_conn(conn, actor, data, inventory_id)
            if initial:
                product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
                self._entry(conn, actor, product, to_milli(initial), product["cost_cents"], "Existencia inicial",
                            "inventario_inicial", {}, None, kind="inicial")
        self.scopes.notify(inventory_id, "producto", product=product_id)
        return self.get(actor, product_id)

    def create_conn(self, conn: sqlite3.Connection, actor: Actor, data: dict, inventory_id: int | None = None) -> int:
        values = self._validated(conn, data, None, inventory_id)
        now = iso()
        cols = ", ".join(values)
        product_id = conn.execute(
            f"INSERT INTO products(inventory_id, {cols}, created_at, updated_at, created_by, updated_by)"
            f" VALUES (?, {', '.join('?' * len(values))}, ?, ?, ?, ?)",
            (inventory_id, *values.values(), now, now, actor.id, actor.id)).lastrowid
        custom = self.columns.set_values_conn(conn, actor, product_id, data.get("custom"), creating=True,
                                              keep_existing_on_empty=bool(data.get("_import")))
        record(conn, actor, "producto.crear", "product", product_id, {"codigo": values["code"],
                                                                      "descripcion": values["description"],
                                                                      **({"columnas": custom} if custom else {})})
        return product_id

    def update(self, actor: Actor, product_id: int, data: dict) -> dict:
        actor.require("inventario.editar")
        if "stock" in data or "stock_milli" in data:
            raise ValidationError("La existencia no se edita directamente: registre una entrada, salida o ajuste.")
        if "cost" in data and not actor.can("inventario.costos"):
            actor.require("inventario.costos")
        with self.db.tx() as conn:
            inventory_id = self._product_group(conn, actor, product_id)
            self.scopes.require_active(conn, inventory_id)
            changed = self.update_conn(conn, actor, product_id, data)
        if changed:
            self.scopes.notify(inventory_id, "producto", product=product_id)
        return self.get(actor, product_id)

    def update_conn(self, conn: sqlite3.Connection, actor: Actor, product_id: int, data: dict) -> dict:
        current = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if not current:
            raise NotFoundError("Producto no encontrado.")
        current = dict(current)
        if "version" in data and data["version"] is not None and int(data["version"]) != current["version"]:
            raise ConflictError("Otra persona modificó este producto. Recargue para ver los cambios.")
        values = self._validated(conn, data, current)
        changes = {k: {"antes": current[k], "despues": v} for k, v in values.items() if current[k] != v}
        if "custom" in data:
            custom = self.columns.set_values_conn(conn, actor, product_id, data["custom"], creating=False,
                                                  keep_existing_on_empty=bool(data.get("_import")))
            if custom:
                changes["columnas"] = custom
        if not changes:
            return {}
        sets = ", ".join(f"{k} = ?" for k in values)
        conn.execute(f"UPDATE products SET {sets}, updated_at = ?, updated_by = ?, version = version + 1 WHERE id = ?",
                     (*values.values(), iso(), actor.id, product_id))
        record(conn, actor, "producto.actualizar", "product", product_id, changes)
        return changes

    def set_active(self, actor: Actor, product_id: int, active: bool) -> dict:
        return self.update(actor, product_id, {"active": active})

    # ------------------------------------------------------------------ movimientos
    def apply_movement(self, conn: sqlite3.Connection, actor: Actor, product: sqlite3.Row | dict, kind: str, qty_milli: int,
                       reason: str, unit_cost_cents: int, reference: tuple[str, int] | None = None,
                       idempotency_key: str | None = None, allow_negative: bool | None = None) -> int:
        """Inserta un movimiento (la existencia cambia por trigger). No contabiliza: lo hace quien llama."""
        if qty_milli == 0:
            raise ValidationError("La cantidad no puede ser cero.")
        if not (reason or "").strip():
            raise ValidationError("Indique el motivo del movimiento.", {"reason": "El motivo es obligatorio."})
        stock, inventory_id = conn.execute("SELECT stock_milli, inventory_id FROM products WHERE id = ?", (product["id"],)).fetchone()
        self.scopes.require_active(conn, inventory_id)     # un inventario inactivo o archivado no registra operaciones
        after = stock + qty_milli
        if allow_negative is None:
            allow_negative = self.scopes.allow_negative(conn, inventory_id,
                                                        bool(self.settings.get("inventario", conn)["allow_negative_stock"]))
        if after < 0 and not allow_negative:
            raise ValidationError(
                f"Existencias insuficientes de {product['code']}: hay {from_milli(stock)} y se requieren {from_milli(-qty_milli)}.",
                {"qty": f"Disponible: {from_milli(stock)}"})
        ref_type, ref_id = reference or (None, None)
        return conn.execute(
            "INSERT INTO inventory_movements(product_id, kind, qty_milli, stock_after_milli, unit_cost_cents, reason,"
            " reference_type, reference_id, user_id, created_at, idempotency_key) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (product["id"], kind, qty_milli, after, unit_cost_cents, reason.strip()[:300], ref_type, ref_id, actor.id,
             iso(), idempotency_key)).lastrowid

    def register_movement(self, actor: Actor, product_id: int, data: dict, idempotency_key: str) -> dict:
        actor.require("inventario.movimientos")
        kind = data.get("kind")
        if kind not in ("entrada", "salida", "ajuste"):
            raise ValidationError("Tipo de movimiento no válido.", {"kind": "Elija entrada, salida o ajuste."})
        if not idempotency_key or len(idempotency_key) > 80:
            raise ValidationError("Falta la clave de idempotencia de la operación.")
        reason = (data.get("reason") or "").strip()
        if not reason:
            raise ValidationError("Indique el motivo.", {"reason": "El motivo es obligatorio."})
        with self.db.tx() as conn:
            inventory_id = self._product_group(conn, actor, product_id)
            done = conn.execute("SELECT id FROM inventory_movements WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
            if done:
                return {"duplicate": True, "movement_id": done[0], "product": self._product_conn(conn, product_id)}
            product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
            if not product["active"]:
                raise ValidationError("El producto está desactivado. Actívelo antes de mover existencias.")
            if kind == "ajuste":
                target = parse_decimal(data.get("counted_qty"))
                if target is None or target < 0:
                    raise ValidationError("Revise la cantidad.", {"counted_qty": "Escriba la cantidad contada (cero o más)."})
                delta = to_milli(target) - product["stock_milli"]
                if delta == 0:
                    raise ValidationError("La cantidad contada coincide con la existencia: no hay nada que ajustar.",
                                          {"counted_qty": "Sin diferencia."})
                move_id = self._adjust(conn, actor, product, delta, reason, idempotency_key)
            else:
                qty = parse_decimal(data.get("qty"))
                if qty is None or qty <= 0:
                    raise ValidationError("Revise la cantidad.", {"qty": "La cantidad debe ser mayor que cero."})
                qty_milli = to_milli(qty)
                if product["unit"] == "und" and qty_milli % 1000:
                    raise ValidationError("Revise la cantidad.", {"qty": "Este producto se maneja en unidades enteras."})
                counterpart = data.get("counterpart") or ("compra_contado" if kind == "entrada" else "merma")
                if kind == "entrada":
                    if counterpart not in ENTRY_COUNTERPARTS:
                        raise ValidationError("Origen no válido.", {"counterpart": "Elija el origen de la entrada."})
                    raw_cost = data.get("unit_cost")
                    cost = to_cents(raw_cost) if raw_cost not in (None, "") else product["cost_cents"]
                    if cost < 0:
                        raise ValidationError("Revise el costo.", {"unit_cost": "El costo no puede ser negativo."})
                    move_id = self._entry(conn, actor, product, qty_milli, cost, reason, counterpart, data, idempotency_key)
                else:
                    if counterpart not in EXIT_COUNTERPARTS:
                        raise ValidationError("Destino no válido.", {"counterpart": "Elija el destino de la salida."})
                    move_id = self._exit(conn, actor, product, qty_milli, reason, counterpart, idempotency_key)
            result = {"duplicate": False, "movement_id": move_id, "product": self._product_conn(conn, product_id)}
        self.scopes.notify(inventory_id, "movimiento", product=product_id)
        return result

    def _entry(self, conn: sqlite3.Connection, actor: Actor, product, qty_milli: int, unit_cost: int, reason: str,
               counterpart: str, data: dict, idempotency_key: str | None, kind: str = "entrada") -> int:
        stock = product["stock_milli"]
        # Costo promedio ponderado; con existencia negativa o cero, el costo de la entrada.
        if stock > 0 and product["cost_cents"]:
            new_cost = round_cents((Decimal(stock) * product["cost_cents"] + Decimal(qty_milli) * unit_cost) / (stock + qty_milli))
        else:
            new_cost = unit_cost
        move_id = self.apply_movement(conn, actor, product, kind, qty_milli, reason, unit_cost,
                                      idempotency_key=idempotency_key)
        if new_cost != product["cost_cents"]:
            conn.execute("UPDATE products SET cost_cents = ?, updated_at = ?, updated_by = ?, version = version + 1 WHERE id = ?",
                         (new_cost, iso(), actor.id, product["id"]))
        value = round_cents(Decimal(qty_milli) * unit_cost / 1000)
        today = local_today(self._tz())
        desc = f"{ENTRY_COUNTERPARTS[counterpart]}: {product['code']} × {from_milli(qty_milli)}"
        if counterpart == "compra_credito":
            try:
                supplier_id = int(data.get("supplier_id"))
            except (TypeError, ValueError):
                raise ValidationError("Faltan datos.", {"supplier_id": "Seleccione el proveedor."}) from None
            if value <= 0:
                raise ValidationError("Revise el costo.", {"unit_cost": "Una compra a crédito necesita costo unitario."})
            due = parse_date(data.get("due_date"), "Vencimiento") if data.get("due_date") else today + timedelta(days=30)
            self.payables.create_conn(conn, actor, supplier_id, value, today, due, desc,
                                      number=(data.get("invoice_number") or "").strip() or None,
                                      source_type="entrada_inventario", source_id=move_id, account=ledger.INVENTORY)
        elif value > 0:
            if counterpart == "compra_contado":
                method, account = ledger.method_account(conn, int(data.get("method_id") or 0))
                if account is None:
                    raise ValidationError("Método no válido.", {"method_id": "Para compras a crédito elija «Compra a crédito»."})
                credit = Line(account, credit=value, memo=method["name"])
            elif counterpart == "inventario_inicial":
                credit = Line(ledger.CAPITAL, credit=value)
            else:
                credit = Line(ledger.OTHER_INCOME, credit=value)
            ledger.post(conn, actor, today, desc, "movimiento", move_id, [Line(ledger.INVENTORY, debit=value), credit])
        record(conn, actor, f"inventario.{kind}", "product", product["id"],
               {"cantidad": str(from_milli(qty_milli)), "costo_unitario": str(from_cents(unit_cost)), "origen": counterpart,
                "motivo": reason, "movimiento": move_id})
        return move_id

    def _exit(self, conn: sqlite3.Connection, actor: Actor, product, qty_milli: int, reason: str, counterpart: str,
              idempotency_key: str | None) -> int:
        move_id = self.apply_movement(conn, actor, product, "salida", -qty_milli, reason, product["cost_cents"],
                                      idempotency_key=idempotency_key)
        value = round_cents(Decimal(qty_milli) * product["cost_cents"] / 1000)
        expense = ledger.INVENTORY_LOSS if counterpart == "merma" else "5195"
        ledger.post(conn, actor, local_today(self._tz()), f"{EXIT_COUNTERPARTS[counterpart]}: {product['code']} ×"
                    f" {from_milli(qty_milli)}", "movimiento", move_id,
                    [Line(expense, debit=value, memo=reason), Line(ledger.INVENTORY, credit=value)])
        record(conn, actor, "inventario.salida", "product", product["id"],
               {"cantidad": str(from_milli(qty_milli)), "destino": counterpart, "motivo": reason, "movimiento": move_id})
        return move_id

    def _adjust(self, conn: sqlite3.Connection, actor: Actor, product, delta: int, reason: str,
                idempotency_key: str | None, kind: str = "ajuste") -> int:
        move_id = self.apply_movement(conn, actor, product, kind, delta, reason, product["cost_cents"],
                                      idempotency_key=idempotency_key, allow_negative=True)
        value = round_cents(Decimal(abs(delta)) * product["cost_cents"] / 1000)
        lines = ([Line(ledger.INVENTORY, debit=value), Line(ledger.OTHER_INCOME, credit=value)] if delta > 0 else
                 [Line(ledger.INVENTORY_LOSS, debit=value), Line(ledger.INVENTORY, credit=value)])
        ledger.post(conn, actor, local_today(self._tz()), f"{'Sobrante' if delta > 0 else 'Faltante'} por {kind}:"
                    f" {product['code']} {from_milli(delta)}", "movimiento", move_id, lines)
        record(conn, actor, f"inventario.{kind}", "product", product["id"],
               {"diferencia": str(from_milli(delta)), "motivo": reason, "movimiento": move_id})
        return move_id

    def _product_conn(self, conn: sqlite3.Connection, product_id: int) -> dict:
        return dict(conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone())

    # ------------------------------------------------------------------ exportación
    def export(self, actor: Actor, fmt: str = "xlsx", inventory: str | None = None) -> tuple[bytes, str, str]:
        actor.require("inventario.importar")
        include_cost = actor.can("inventario.costos")
        with self.db.read() as conn:
            inventory_id = self.scopes.resolve(conn, actor, inventory)
            rows = conn.execute("SELECT p.*, c.name AS category FROM products p LEFT JOIN categories c ON c.id = p.category_id"
                                " WHERE p.inventory_id IS ? ORDER BY p.code COLLATE NOCASE", (inventory_id,)).fetchall()
            extra = self.columns.columns_conn(conn, inventory_id)
            custom = self.columns.values_for(conn, [r["id"] for r in rows])
        header = ["Código", "Descripción", "Categoría", "Unidad", "Precio sin descuento", "Precio con descuento"]
        header += ["Costo"] if include_cost else []
        header += ["IVA %", "Cantidad disponible", "Existencia mínima", "Activo"] + [c["name"] for c in extra]
        data = []
        for r in rows:
            line = [r["code"], r["description"], r["category"] or "", r["unit"], from_cents(r["price_cents"]),
                    from_cents(r["discount_price_cents"]) if r["discount_price_cents"] is not None else None]
            line += [from_cents(r["cost_cents"])] if include_cost else []
            line += [Decimal(r["tax_rate_bp"]) / 100, from_milli(r["stock_milli"]), from_milli(r["min_stock_milli"]),
                     "Sí" if r["active"] else "No"]
            line += [typed(c, custom[r["id"]].get(str(c["id"]))) for c in extra]
            data.append(line)
        stamp = local_today(self._tz()).isoformat()
        with self.db.tx() as conn:
            record(conn, actor, "inventario.exportar", "product", None, {"formato": fmt, "filas": len(data)})
        if fmt == "csv":
            buf = io.StringIO()
            writer = csv.writer(buf, delimiter=";")
            writer.writerow(header)
            for line in data:
                writer.writerow(["" if v is None else str(v).replace(".", ",") if isinstance(v, Decimal) else v for v in line])
            return ("﻿" + buf.getvalue()).encode("utf-8"), f"inventario-{stamp}.csv", "text/csv; charset=utf-8"
        import openpyxl
        from openpyxl.styles import Font, PatternFill
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Inventario"
        ws.append(header)
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1F2937")
        for line in data:
            ws.append([float(v) if isinstance(v, Decimal) else v for v in line])
        from openpyxl.utils import get_column_letter
        widths = [16, 44, 18, 9, 18, 18] + ([14] if include_cost else []) + [9, 18, 16, 8]
        widths += [40 if c["data_type"] == "texto_largo" else 18 for c in extra]
        for i, width in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = width
        ws.freeze_panes = "A2"
        out = io.BytesIO()
        wb.save(out)
        return (out.getvalue(), f"inventario-{stamp}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

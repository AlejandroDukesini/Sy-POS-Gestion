"""Punto de venta: venta, anulación y devoluciones.

Una venta es una sola transacción: líneas + salida de inventario + pagos + cuenta por cobrar (si
hay parte a crédito) + asientos. La clave de idempotencia la genera la interfaz por cada intento de
cobro: un doble clic o un reintento de red devuelve la venta ya registrada en lugar de duplicarla.

El comprobante que se imprime es un documento interno de venta: NO es una factura electrónica
DIAN. Si la empresa está obligada a facturar electrónicamente, debe hacerlo con su proveedor
tecnológico autorizado.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from ..core.actor import Actor
from ..core.audit import record
from ..core.clock import iso, local_today, parse_date
from ..core.errors import NotFoundError, ValidationError
from ..core.money import from_milli, parse_decimal, round_cents, to_cents, to_milli
from ..core.query import like, paginate
from ..core.sequences import next_number
from . import ledger, pricing
from .inventory import InventoryService
from .ledger import Line
from .open_items import AR, OpenItems


class SalesService:
    def __init__(self, db, settings, inventory: InventoryService):
        self.db = db
        self.settings = settings
        self.inventory = inventory
        self.receivables = OpenItems(db, settings, AR)

    def _tz(self) -> str:
        return self.settings.get("empresa")["timezone"]

    # ------------------------------------------------------------------ cotizar el carrito (sin guardar)
    def quote(self, actor: Actor, items: list[dict], payments: list[dict] | None = None) -> dict:
        if not (actor.can("ventas.vender") or actor.can("documentos.crear")):
            actor.require("ventas.vender")
        with self.db.read() as conn:
            lines, totals = pricing.price_items(conn, actor, items, self.settings.get("ventas", conn))
            allow_negative = self.settings.get("inventario", conn)["allow_negative_stock"]
        needed: dict[int, int] = defaultdict(int)
        for ln in lines:
            needed[ln.product_id] += ln.qty_milli
        warnings = []
        for ln in lines:
            if needed[ln.product_id] > ln.stock_milli:
                warnings.append({"product_id": ln.product_id, "code": ln.code,
                                 "message": f"{ln.code}: hay {from_milli(ln.stock_milli)} disponibles y se piden "
                                            f"{from_milli(needed[ln.product_id])}."})
        unique = {w["product_id"]: w for w in warnings}
        result = {**pricing.as_dict(lines, totals), "stock_warnings": list(unique.values()),
                  "can_sell": not unique or bool(allow_negative)}
        if payments is not None:
            result["payment_summary"] = self._payment_summary(payments, totals.total_cents)
        return result

    @staticmethod
    def _payment_summary(payments: list[dict], total: int) -> dict:
        """Vista previa de pagos para la interfaz (la validación definitiva ocurre al registrar la venta)."""
        paid = change = 0
        for p in payments:
            amount = parse_decimal(p.get("amount"))
            if amount is None or amount <= 0:
                continue
            paid += to_cents(amount)
            tendered = parse_decimal(p.get("tendered"))
            if tendered is not None and to_cents(tendered) > to_cents(amount):
                change += to_cents(tendered) - to_cents(amount)
        return {"paid_cents": paid, "remaining_cents": max(0, total - paid), "excess_cents": max(0, paid - total),
                "change_cents": change, "complete": paid == total}

    # ------------------------------------------------------------------ venta
    def checkout(self, actor: Actor, data: dict, idempotency_key: str) -> dict:
        actor.require("ventas.vender")
        if not idempotency_key or not 8 <= len(idempotency_key) <= 80:
            raise ValidationError("Falta la clave de idempotencia de la venta.")
        with self.db.tx() as conn:
            existing = conn.execute("SELECT id FROM sales WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
            if existing:
                return {"duplicate": True, **self._detail(conn, existing[0])}
            ventas = self.settings.get("ventas", conn)
            lines, totals = pricing.price_items(conn, actor, data.get("lines") or [], ventas)
            customer = self._customer(conn, data.get("customer_id"))
            payments, credit, change = self._validate_payments(conn, data.get("payments") or [], totals.total_cents)
            if credit and not customer:
                raise ValidationError("Una venta a crédito necesita un cliente.", {"customer_id": "Seleccione el cliente."})
            today = local_today(self._tz())
            number = next_number(conn, "venta")
            sale_id = conn.execute(
                "INSERT INTO sales(number, idempotency_key, customer_id, customer_name, customer_identification, gross_cents,"
                " discount_cents, total_cents, tax_cents, cost_cents, paid_cents, credit_cents, change_cents, notes, sale_date,"
                " user_id, created_at, source_document_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (number, idempotency_key, customer["id"] if customer else None, customer["name"] if customer else "",
                 (customer["identification"] or "") if customer else "", totals.gross_cents, totals.discount_cents,
                 totals.total_cents, totals.tax_cents, totals.cost_cents, totals.total_cents - credit, credit, change,
                 (data.get("notes") or "").strip()[:500], str(today), actor.id, iso(),
                 data.get("source_document_id") or None)).lastrowid
            for ln in lines:
                conn.execute(
                    "INSERT INTO sale_lines(sale_id, line_no, product_id, code, description, qty_milli, list_price_cents,"
                    " unit_price_cents, manual_discount_bp, gross_cents, discount_cents, net_cents, tax_rate_bp, tax_cents,"
                    " unit_cost_cents) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (sale_id, ln.line_no, ln.product_id, ln.code, ln.description, ln.qty_milli, ln.list_price_cents,
                     ln.unit_price_cents, ln.manual_discount_bp, ln.gross_cents, ln.discount_cents, ln.net_cents,
                     ln.tax_rate_bp, ln.tax_cents, ln.unit_cost_cents))
                product = conn.execute("SELECT * FROM products WHERE id = ?", (ln.product_id,)).fetchone()
                self.inventory.apply_movement(conn, actor, product, "venta", -ln.qty_milli, f"Venta {number}",
                                              ln.unit_cost_cents, reference=("venta", sale_id))
            for p in payments:
                conn.execute("INSERT INTO sale_payments(sale_id, method_id, amount_cents, tendered_cents, reference)"
                             " VALUES (?,?,?,?,?)", (sale_id, p["method"]["id"], p["amount"], p["tendered"], p["reference"]))
            if credit:
                days = customer["credit_days"] if customer else 30
                due = parse_date(data["due_date"], "Vencimiento") if data.get("due_date") else today + timedelta(days=days)
                self.receivables.create_conn(conn, actor, customer["id"], credit, today, due, f"Venta {number}",
                                             source_type="venta", source_id=sale_id, post_entry=False)
            self._post_sale(conn, actor, sale_id, number, today, totals, payments, credit, customer)
            record(conn, actor, "venta.registrar", "sale", sale_id,
                   {"numero": number, "total": totals.total_cents, "lineas": len(lines), "credito": credit})
            return {"duplicate": False, **self._detail(conn, sale_id)}

    def _customer(self, conn: sqlite3.Connection, customer_id) -> sqlite3.Row | None:
        if customer_id in (None, "", 0):
            return None
        row = conn.execute("SELECT * FROM customers WHERE id = ?", (int(customer_id),)).fetchone()
        if not row or not row["active"]:
            raise ValidationError("Cliente no válido.", {"customer_id": "Seleccione un cliente activo."})
        return row

    def _validate_payments(self, conn: sqlite3.Connection, raw: list[dict], total: int) -> tuple[list[dict], int, int]:
        if not raw:
            raise ValidationError("Registre el método de pago.", {"payments": "Agregue al menos un pago."})
        payments, errors, credit, change = [], {}, 0, 0
        for i, p in enumerate(raw):
            key = f"payments.{i}"
            try:
                method, _ = ledger.method_account(conn, int(p.get("method_id") or 0))
            except (ValidationError, TypeError, ValueError):
                errors[key] = "Método de pago no válido."
                continue
            amount = parse_decimal(p.get("amount"))
            if amount is None or amount <= 0:
                errors[key] = f"{method['name']}: el importe debe ser mayor que cero."
                continue
            amount_c = to_cents(amount)
            tendered = None
            if p.get("tendered") not in (None, ""):
                if method["kind"] != "efectivo":
                    errors[key] = "Solo en efectivo se registra el dinero recibido."
                    continue
                t = parse_decimal(p.get("tendered"))
                if t is None or to_cents(t) < amount_c:
                    errors[key] = "El efectivo recibido no puede ser menor que el importe."
                    continue
                tendered = to_cents(t)
                change += tendered - amount_c
            if method["kind"] == "credito":
                credit += amount_c
            payments.append({"method": method, "amount": amount_c, "tendered": tendered,
                             "reference": (p.get("reference") or "").strip()[:120]})
        if errors:
            raise ValidationError("Revise los pagos.", errors)
        paid = sum(p["amount"] for p in payments)
        if paid != total:
            diff = Decimal(total - paid) / 100
            raise ValidationError("Los pagos no coinciden con el total de la venta.",
                                  {"payments": f"{'Faltan' if diff > 0 else 'Sobran'} {abs(diff):.2f}."})
        return payments, credit, change

    def _post_sale(self, conn, actor, sale_id, number, day, totals, payments, credit, customer) -> None:
        by_account: dict[int, int] = defaultdict(int)
        for p in payments:
            if p["method"]["account_id"]:
                by_account[p["method"]["account_id"]] += p["amount"]
        lines = [Line(acc, debit=amount) for acc, amount in by_account.items()]
        if credit:
            lines.append(Line(ledger.RECEIVABLE, debit=credit, party_type="cliente", party_id=customer["id"]))
        lines += [Line(ledger.SALES, credit=totals.total_cents - totals.tax_cents), Line(ledger.VAT, credit=totals.tax_cents)]
        ledger.post(conn, actor, day, f"Venta {number}", "venta", sale_id, lines)
        ledger.post(conn, actor, day, f"Costo de venta {number}", "venta", sale_id,
                    [Line(ledger.COGS, debit=totals.cost_cents), Line(ledger.INVENTORY, credit=totals.cost_cents)],
                    purpose="costo")

    # ------------------------------------------------------------------ consulta
    def list(self, actor: Actor, q: str = "", status: str = "", date_from: str = "", date_to: str = "",
             page: int = 1, page_size: int = 50) -> dict:
        actor.require("ventas.historial")
        where, params = [], []
        if q:
            where.append("(s.number LIKE ? ESCAPE '\\' OR s.customer_name LIKE ? ESCAPE '\\')")
            params += [like(q)] * 2
        if status:
            where.append("s.status = ?")
            params.append(status)
        if date_from:
            where.append("s.sale_date >= ?")
            params.append(str(parse_date(date_from)))
        if date_to:
            where.append("s.sale_date <= ?")
            params.append(str(parse_date(date_to)))
        sql = ("SELECT s.id, s.number, s.status, s.customer_name, s.total_cents, s.credit_cents, s.sale_date, s.created_at,"
               " u.username, (SELECT COALESCE(SUM(total_cents), 0) FROM sale_returns r WHERE r.sale_id = s.id) AS returned_cents"
               " FROM sales s JOIN users u ON u.id = s.user_id" + (" WHERE " + " AND ".join(where) if where else ""))
        with self.db.read() as conn:
            return paginate(conn, sql, params, sort="id", direction="desc", default_sort="id",
                            tiebreak="s.id", sortable={"id": "s.id", "total": "s.total_cents"}, page=page, page_size=page_size)

    def get(self, actor: Actor, sale_id: int) -> dict:
        if not (actor.can("ventas.historial") or actor.can("ventas.vender")):
            actor.require("ventas.historial")
        with self.db.read() as conn:
            sale = self._detail(conn, sale_id)
        if not actor.can("ventas.historial") and sale["user_id"] != actor.id:
            actor.require("ventas.historial")
        return sale

    def _detail(self, conn: sqlite3.Connection, sale_id: int) -> dict:
        row = conn.execute("SELECT s.*, u.username, u.full_name AS seller_name FROM sales s JOIN users u ON u.id = s.user_id"
                           " WHERE s.id = ?", (sale_id,)).fetchone()
        if not row:
            raise NotFoundError("Venta no encontrada.")
        sale = dict(row)
        sale["lines"] = [dict(r) for r in conn.execute("SELECT * FROM sale_lines WHERE sale_id = ? ORDER BY line_no", (sale_id,))]
        for ln in sale["lines"]:
            ln.pop("unit_cost_cents", None)
        sale["payments"] = [dict(r) for r in conn.execute(
            "SELECT sp.*, m.name AS method_name, m.kind AS method_kind FROM sale_payments sp"
            " JOIN payment_methods m ON m.id = sp.method_id WHERE sale_id = ? ORDER BY sp.id", (sale_id,))]
        sale["returns"] = [dict(r) for r in conn.execute(
            "SELECT r.*, u.username, m.name AS refund_method_name FROM sale_returns r JOIN users u ON u.id = r.user_id"
            " LEFT JOIN payment_methods m ON m.id = r.refund_method_id WHERE sale_id = ? ORDER BY r.id", (sale_id,))]
        sale["receivable"] = next((dict(r) for r in conn.execute(
            "SELECT id, number, due_date, amount_cents, status FROM receivables WHERE source_type = 'venta' AND source_id = ?",
            (sale_id,))), None)
        sale["prints"] = conn.execute("SELECT COUNT(*) FROM print_jobs WHERE target_type = 'venta' AND target_id = ?"
                                      " AND status = 'ok'", (sale_id,)).fetchone()[0]
        sale.pop("cost_cents", None)
        return sale

    # ------------------------------------------------------------------ anulación
    def void(self, actor: Actor, sale_id: int, reason: str) -> dict:
        actor.require("ventas.anular")
        reason = (reason or "").strip()
        if not reason:
            raise ValidationError("Indique el motivo de la anulación.", {"reason": "El motivo es obligatorio."})
        with self.db.tx() as conn:
            sale = conn.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
            if not sale:
                raise NotFoundError("Venta no encontrada.")
            if sale["status"] == "anulada":
                raise ValidationError("La venta ya estaba anulada.")
            if conn.execute("SELECT 1 FROM sale_returns WHERE sale_id = ?", (sale_id,)).fetchone():
                raise ValidationError("La venta tiene devoluciones registradas: no se puede anular. Registre una devolución"
                                      " por las unidades restantes.")
            today = local_today(self._tz())
            if self.settings.get("ventas", conn)["void_same_day_only"] and sale["sale_date"] != str(today):
                raise ValidationError("Solo se pueden anular ventas del mismo día. Registre una devolución.")
            ar = conn.execute("SELECT id FROM receivables WHERE source_type = 'venta' AND source_id = ?", (sale_id,)).fetchone()
            if ar and conn.execute("SELECT 1 FROM receivable_payments WHERE receivable_id = ? AND voided_at IS NULL",
                                   (ar[0],)).fetchone():
                raise ValidationError("La venta a crédito tiene cobros registrados. Anule primero los cobros en Finanzas.")
            conn.execute("UPDATE sales SET status = 'anulada', voided_at = ?, voided_by = ?, void_reason = ? WHERE id = ?",
                         (iso(), actor.id, reason[:300], sale_id))
            for ln in conn.execute("SELECT * FROM sale_lines WHERE sale_id = ?", (sale_id,)).fetchall():
                product = conn.execute("SELECT * FROM products WHERE id = ?", (ln["product_id"],)).fetchone()
                self.inventory.apply_movement(conn, actor, product, "anulacion_venta", ln["qty_milli"],
                                              f"Anulación venta {sale['number']}: {reason}", ln["unit_cost_cents"],
                                              reference=("venta", sale_id), allow_negative=True)
            if ar:
                conn.execute("UPDATE receivables SET status = 'anulada' WHERE id = ?", (ar[0],))
            for entry in ledger.entries_for(conn, "venta", sale_id):
                if not entry["reverses_id"] and not entry["reversed_by_id"]:
                    ledger.reverse(conn, actor, entry["id"], today, f"anulación {sale['number']}")
            record(conn, actor, "venta.anular", "sale", sale_id, {"numero": sale["number"], "motivo": reason})
            return self._detail(conn, sale_id)

    # ------------------------------------------------------------------ devoluciones
    def register_return(self, actor: Actor, sale_id: int, data: dict, idempotency_key: str) -> dict:
        actor.require("ventas.anular")
        reason = (data.get("reason") or "").strip()
        if not reason:
            raise ValidationError("Indique el motivo de la devolución.", {"reason": "El motivo es obligatorio."})
        if not idempotency_key or not 8 <= len(idempotency_key) <= 80:
            raise ValidationError("Falta la clave de idempotencia de la devolución.")
        with self.db.tx() as conn:
            done = conn.execute("SELECT sale_id FROM sale_returns WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
            if done:
                return {"duplicate": True, **self._detail(conn, done[0])}
            sale = conn.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
            if not sale:
                raise NotFoundError("Venta no encontrada.")
            if sale["status"] == "anulada":
                raise ValidationError("La venta está anulada.")
            sale_lines = {r["id"]: r for r in conn.execute("SELECT * FROM sale_lines WHERE sale_id = ?", (sale_id,))}
            picked, errors = [], {}
            for i, item in enumerate(data.get("lines") or []):
                ln = sale_lines.get(int(item.get("sale_line_id") or 0))
                qty = parse_decimal(item.get("qty"))
                if not ln:
                    errors[f"lines.{i}"] = "Línea no pertenece a la venta."
                    continue
                if qty is None or qty <= 0:
                    continue
                qty_milli = to_milli(qty)
                available = ln["qty_milli"] - ln["returned_milli"]
                if qty_milli > available:
                    errors[f"lines.{i}"] = f"{ln['code']}: se pueden devolver como máximo {from_milli(available)}."
                    continue
                picked.append((ln, qty_milli))
            if errors:
                raise ValidationError(next(iter(errors.values())), errors)
            if not picked:
                raise ValidationError("Indique al menos una cantidad a devolver.", {"lines": "Sin cantidades."})
            today = local_today(self._tz())
            number = next_number(conn, "devolucion")
            computed = []
            for ln, qty_milli in picked:
                prior = conn.execute("SELECT COALESCE(SUM(net_cents),0), COALESCE(SUM(tax_cents),0), COALESCE(SUM(qty_milli),0)"
                                     " FROM sale_return_lines WHERE sale_line_id = ?", (ln["id"],)).fetchone()
                if prior[2] + qty_milli == ln["qty_milli"]:   # última devolución de la línea: lo que queda, sin residuos
                    net, tax = ln["net_cents"] - prior[0], ln["tax_cents"] - prior[1]
                else:
                    ratio = Decimal(qty_milli) / ln["qty_milli"]
                    net, tax = round_cents(ln["net_cents"] * ratio), round_cents(ln["tax_cents"] * ratio)
                cost = round_cents(Decimal(ln["unit_cost_cents"]) * qty_milli / 1000)
                computed.append((ln, qty_milli, net, tax, cost))
            total = sum(c[2] for c in computed)
            tax_total = sum(c[3] for c in computed)
            cost_total = sum(c[4] for c in computed)
            ar = conn.execute("SELECT id FROM receivables WHERE source_type = 'venta' AND source_id = ? AND status = 'vigente'",
                              (sale_id,)).fetchone()
            credit_applied = min(total, self.receivables.balance(conn, ar[0])) if ar else 0
            refund = total - credit_applied
            refund_method = None
            if refund:
                refund_account = None
                try:
                    refund_method, refund_account = ledger.method_account(conn, int(data.get("refund_method_id") or 0))
                except (TypeError, ValueError, ValidationError):
                    refund_method = None
                if not refund_method or refund_account is None:
                    raise ValidationError("Indique cómo se reembolsa el dinero.",
                                          {"refund_method_id": "Elija efectivo, tarjeta o transferencia."})
            return_id = conn.execute(
                "INSERT INTO sale_returns(number, idempotency_key, sale_id, reason, refund_method_id, total_cents, tax_cents,"
                " cost_cents, credit_applied_cents, refund_cents, return_date, user_id, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (number, idempotency_key, sale_id, reason[:300], refund_method["id"] if refund_method else None, total,
                 tax_total, cost_total, credit_applied, refund, str(today), actor.id, iso())).lastrowid
            for ln, qty_milli, net, tax, cost in computed:
                conn.execute("INSERT INTO sale_return_lines(return_id, sale_line_id, qty_milli, net_cents, tax_cents, cost_cents)"
                             " VALUES (?,?,?,?,?,?)", (return_id, ln["id"], qty_milli, net, tax, cost))
                conn.execute("UPDATE sale_lines SET returned_milli = returned_milli + ? WHERE id = ?", (qty_milli, ln["id"]))
                product = conn.execute("SELECT * FROM products WHERE id = ?", (ln["product_id"],)).fetchone()
                self.inventory.apply_movement(conn, actor, product, "devolucion", qty_milli,
                                              f"Devolución {number} (venta {sale['number']}): {reason}", ln["unit_cost_cents"],
                                              reference=("devolucion", return_id), allow_negative=True)
            if credit_applied:
                conn.execute("INSERT INTO receivable_credits(receivable_id, amount_cents, source_type, source_id, created_at)"
                             " VALUES (?,?,?,?,?)", (ar[0], credit_applied, "devolucion", return_id, iso()))
            lines = [Line(ledger.SALES_RETURNS, debit=total - tax_total), Line(ledger.VAT, debit=tax_total)]
            if refund:
                lines.append(Line(refund_account, credit=refund, memo=refund_method["name"]))
            if credit_applied:
                lines.append(Line(ledger.RECEIVABLE, credit=credit_applied, party_type="cliente", party_id=sale["customer_id"]))
            ledger.post(conn, actor, today, f"Devolución {number} de la venta {sale['number']}", "devolucion", return_id, lines)
            ledger.post(conn, actor, today, f"Reingreso al inventario {number}", "devolucion", return_id,
                        [Line(ledger.INVENTORY, debit=cost_total), Line(ledger.COGS, credit=cost_total)], purpose="costo")
            record(conn, actor, "venta.devolucion", "sale", sale_id, {"devolucion": number, "total": total, "motivo": reason,
                                                                     "reembolso": refund, "abono_cartera": credit_applied})
            return {"duplicate": False, "return_id": return_id, **self._detail(conn, sale_id)}

    # ------------------------------------------------------------------ resumen del día
    def day_summary(self, actor: Actor, day: str | None = None) -> dict:
        actor.require("ventas.historial")
        target = str(parse_date(day)) if day else str(local_today(self._tz()))
        with self.db.read() as conn:
            totals = dict(conn.execute(
                "SELECT COUNT(*) AS sales, COALESCE(SUM(total_cents), 0) AS total_cents, COALESCE(SUM(credit_cents), 0)"
                " AS credit_cents FROM sales WHERE sale_date = ? AND status = 'completada'", (target,)).fetchone())
            totals["by_method"] = [dict(r) for r in conn.execute(
                "SELECT m.name, m.kind, COALESCE(SUM(sp.amount_cents), 0) AS amount_cents, COUNT(*) AS count"
                " FROM sale_payments sp JOIN sales s ON s.id = sp.sale_id JOIN payment_methods m ON m.id = sp.method_id"
                " WHERE s.sale_date = ? AND s.status = 'completada' GROUP BY m.id ORDER BY m.sort_order", (target,))]
            totals["returns_cents"] = conn.execute("SELECT COALESCE(SUM(total_cents), 0) FROM sale_returns WHERE return_date = ?",
                                                   (target,)).fetchone()[0]
            totals["voided"] = conn.execute("SELECT COUNT(*) FROM sales WHERE sale_date = ? AND status = 'anulada'",
                                            (target,)).fetchone()[0]
        totals["date"] = target
        return totals


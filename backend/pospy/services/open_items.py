"""Cuentas por cobrar (AR) y por pagar (AP): un solo motor de partidas abiertas.

El saldo nunca se guarda: es importe − créditos (devoluciones) − pagos no anulados. Cada cobro o
pago tiene clave de idempotencia y su asiento; anularlo crea el reverso enlazado.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

from ..core.actor import Actor
from ..core.audit import record
from ..core.clock import iso, local_today, parse_date
from ..core.errors import ConflictError, NotFoundError, ValidationError
from ..core.money import to_cents
from ..core.sequences import next_number
from . import ledger
from .ledger import Line

BUCKETS = (("corriente", None, 0), ("1_30", 1, 30), ("31_60", 31, 60), ("61_90", 61, 90), ("mas_90", 91, None))


@dataclass(frozen=True)
class Kind:
    name: str               # cxc | cxp
    table: str
    payments: str
    fk: str                 # receivable_id | payable_id
    party_table: str
    party_col: str          # customer_id | supplier_id
    party_type: str         # cliente | proveedor
    control_account: str    # 1305 | 2205
    payment_source: str     # cobro | pago
    label: str


AR = Kind("cxc", "receivables", "receivable_payments", "receivable_id", "customers", "customer_id", "cliente",
          ledger.RECEIVABLE, "cobro", "cuenta por cobrar")
AP = Kind("cxp", "payables", "payable_payments", "payable_id", "suppliers", "supplier_id", "proveedor",
          ledger.PAYABLE, "pago", "cuenta por pagar")


def _balance_sql(k: Kind) -> str:
    credits = ("(SELECT COALESCE(SUM(amount_cents), 0) FROM receivable_credits c WHERE c.receivable_id = d.id)"
               if k is AR else "0")
    return (f"d.amount_cents - {credits} - (SELECT COALESCE(SUM(amount_cents), 0) FROM {k.payments} p"
            f" WHERE p.{k.fk} = d.id AND p.voided_at IS NULL)")


class OpenItems:
    def __init__(self, db, settings, kind: Kind):
        self.db = db
        self.settings = settings
        self.k = kind

    def _tz(self) -> str:
        return self.settings.get("empresa")["timezone"]

    # ------------------------------------------------------------------ consulta
    def balance(self, conn: sqlite3.Connection, item_id: int) -> int:
        row = conn.execute(f"SELECT {_balance_sql(self.k)} FROM {self.k.table} d WHERE d.id = ?", (item_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"La {self.k.label} no existe.")
        return int(row[0])

    def list(self, actor: Actor, status: str = "pendientes", party_id: int | None = None, q: str = "",
             as_of: str | None = None) -> list[dict]:
        actor.require("finanzas.ver")
        today = parse_date(as_of) if as_of else local_today(self._tz())
        k = self.k
        where, params = [], []
        if party_id:
            where.append(f"d.{k.party_col} = ?")
            params.append(party_id)
        if q:
            where.append("(t.name LIKE ? OR d.number LIKE ?)")
            params += [f"%{q}%", f"%{q}%"]
        sql = (f"SELECT d.*, t.name AS party_name, t.identification AS party_identification, {_balance_sql(k)} AS balance_cents"
               f" FROM {k.table} d JOIN {k.party_table} t ON t.id = d.{k.party_col}"
               + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY d.due_date, d.id")
        with self.db.read() as conn:
            items = [dict(r) for r in conn.execute(sql, params)]
        out = []
        for it in items:
            overdue = (today - date.fromisoformat(it["due_date"])).days
            it["days_overdue"] = max(0, overdue) if it["balance_cents"] > 0 else 0
            it["state"] = ("anulada" if it["status"] == "anulada" else "pagada" if it["balance_cents"] <= 0
                           else "vencida" if overdue > 0 else "por_vencer" if overdue >= -7 else "vigente")
            if status == "pendientes" and (it["state"] in ("anulada", "pagada")):
                continue
            if status == "vencidas" and it["state"] != "vencida":
                continue
            if status == "pagadas" and it["state"] != "pagada":
                continue
            out.append(it)
        return out

    def detail(self, actor: Actor, item_id: int) -> dict:
        actor.require("finanzas.ver")
        k = self.k
        with self.db.read() as conn:
            row = conn.execute(f"SELECT d.*, t.name AS party_name, {_balance_sql(k)} AS balance_cents FROM {k.table} d"
                               f" JOIN {k.party_table} t ON t.id = d.{k.party_col} WHERE d.id = ?", (item_id,)).fetchone()
            if not row:
                raise NotFoundError(f"La {k.label} no existe.")
            item = dict(row)
            item["payments"] = [dict(r) for r in conn.execute(
                f"SELECT p.*, m.name AS method_name, u.username FROM {k.payments} p JOIN payment_methods m ON m.id = p.method_id"
                f" LEFT JOIN users u ON u.id = p.user_id WHERE p.{k.fk} = ? ORDER BY p.id", (item_id,))]
            item["credits"] = [dict(r) for r in conn.execute(
                "SELECT * FROM receivable_credits WHERE receivable_id = ? ORDER BY id", (item_id,))] if k is AR else []
        return item

    def aging(self, actor: Actor, as_of: str | None = None) -> dict:
        items = self.list(actor, "pendientes", as_of=as_of)
        by_party: dict[int, dict] = {}
        totals = {b[0]: 0 for b in BUCKETS}
        for it in items:
            bucket = next(name for name, lo, hi in BUCKETS
                          if (lo is None and it["days_overdue"] <= 0) or
                          (lo is not None and it["days_overdue"] >= lo and (hi is None or it["days_overdue"] <= hi)))
            party = by_party.setdefault(it[self.k.party_col], {"party_id": it[self.k.party_col], "party_name": it["party_name"],
                                                               **{b[0]: 0 for b in BUCKETS}, "total": 0})
            party[bucket] += it["balance_cents"]
            party["total"] += it["balance_cents"]
            totals[bucket] += it["balance_cents"]
        amounts = [b[0] for b in BUCKETS] + ["total"]
        rows = [{"party_id": p["party_id"], "party_name": p["party_name"], **{f"{b}_cents": p[b] for b in amounts}}
                for p in sorted(by_party.values(), key=lambda p: -p["total"])]
        return {"as_of": str(parse_date(as_of) if as_of else local_today(self._tz())),
                "buckets": [b[0] for b in BUCKETS], "rows": rows,
                "totals": {f"{b}_cents": v for b, v in totals.items()} | {"total_cents": sum(totals.values())}}

    # ------------------------------------------------------------------ altas
    def create_conn(self, conn: sqlite3.Connection, actor: Actor, party_id: int, amount_cents: int, issue: date,
                    due: date, description: str, *, number: str | None = None, source_type: str = "manual",
                    source_id: int | None = None, account: str | int | None = None, post_entry: bool = True) -> int:
        k = self.k
        if amount_cents <= 0:
            raise ValidationError("El importe debe ser mayor que cero.", {"amount": "Importe mayor que cero."})
        if due < issue:
            raise ValidationError("Fechas no válidas.", {"due_date": "El vencimiento no puede ser anterior a la emisión."})
        party = conn.execute(f"SELECT * FROM {k.party_table} WHERE id = ?", (party_id,)).fetchone()
        if not party:
            raise ValidationError("Tercero no encontrado.", {k.party_col: "Seleccione un tercero válido."})
        if k is AR:
            number = number or next_number(conn, "cxc")
            item_id = conn.execute(
                "INSERT INTO receivables(number, customer_id, source_type, source_id, issue_date, due_date, amount_cents,"
                " description, income_account_id, user_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (number, party_id, source_type, source_id, str(issue), str(due), amount_cents, description,
                 ledger.account_id(conn, account) if account else None, actor.id, iso())).lastrowid
            if post_entry:
                ledger.post(conn, actor, issue, f"Cuenta por cobrar {number} · {party['name']}", "cxc", item_id, [
                    Line(k.control_account, debit=amount_cents, party_type=k.party_type, party_id=party_id),
                    Line(account or ledger.SALES, credit=amount_cents, memo=description)])
        else:
            if not number:
                raise ValidationError("Faltan datos.", {"number": "El número de la factura del proveedor es obligatorio."})
            if conn.execute("SELECT 1 FROM payables WHERE supplier_id = ? AND number = ?", (party_id, number)).fetchone():
                raise ConflictError("Esa factura del proveedor ya está registrada.", {"number": "Factura repetida."})
            debit_account = ledger.account_id(conn, account or ledger.INVENTORY)
            item_id = conn.execute(
                "INSERT INTO payables(supplier_id, number, issue_date, due_date, amount_cents, description, debit_account_id,"
                " source_type, source_id, user_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (party_id, number, str(issue), str(due), amount_cents, description, debit_account, source_type, source_id,
                 actor.id, iso())).lastrowid
            if post_entry:
                ledger.post(conn, actor, issue, f"Factura proveedor {number} · {party['name']}", "cxp", item_id, [
                    Line(debit_account, debit=amount_cents, memo=description),
                    Line(k.control_account, credit=amount_cents, party_type=k.party_type, party_id=party_id)])
        record(conn, actor, f"{k.name}.crear", k.table, item_id, {"tercero": party["name"], "importe": amount_cents,
                                                                 "vence": str(due)})
        return item_id

    def create(self, actor: Actor, data: dict) -> dict:
        actor.require("finanzas.registrar")
        k = self.k
        tz = self._tz()
        try:
            party_id = int(data.get(k.party_col))
        except (TypeError, ValueError):
            raise ValidationError("Faltan datos.", {k.party_col: "Seleccione el tercero."}) from None
        issue = parse_date(data.get("issue_date") or str(local_today(tz)), "Fecha de emisión")
        due = parse_date(data.get("due_date"), "Fecha de vencimiento") if data.get("due_date") else issue + timedelta(days=30)
        account = (data.get("account_code") or "").strip() or None
        if account:
            with self.db.read() as conn:
                acc = conn.execute("SELECT type FROM accounts WHERE code = ? AND active = 1", (account,)).fetchone()
            allowed = ("ingreso",) if k is AR else ("activo", "gasto", "costo")
            if not acc or acc["type"] not in allowed or account in (ledger.CASH, ledger.BANK, ledger.RECEIVABLE):
                raise ValidationError("Cuenta no válida.", {"account_code": "Elija una cuenta de " +
                                                            ("ingresos." if k is AR else "inventario, activo o gasto.")})
        with self.db.tx() as conn:
            item_id = self.create_conn(conn, actor, party_id, to_cents(data.get("amount")), issue, due,
                                       (data.get("description") or "").strip()[:300],
                                       number=(data.get("number") or "").strip() or None, account=account)
        return self.detail(actor, item_id)

    # ------------------------------------------------------------------ pagos
    def register_payment(self, actor: Actor, item_id: int, data: dict, idempotency_key: str) -> dict:
        actor.require("finanzas.registrar")
        k = self.k
        if not idempotency_key or len(idempotency_key) > 80:
            raise ValidationError("Falta la clave de idempotencia de la operación.")
        tz = self._tz()
        pay_date = parse_date(data.get("payment_date") or str(local_today(tz)), "Fecha de pago")
        amount = to_cents(data.get("amount"))
        with self.db.tx() as conn:
            existing = conn.execute(f"SELECT {k.fk} FROM {k.payments} WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
            if existing:
                return {"duplicate": True, **self._detail_conn(conn, existing[0])}
            item = conn.execute(f"SELECT * FROM {k.table} WHERE id = ?", (item_id,)).fetchone()
            if not item:
                raise NotFoundError(f"La {k.label} no existe.")
            if item["status"] == "anulada":
                raise ValidationError(f"La {k.label} está anulada.")
            balance = self.balance(conn, item_id)
            if amount <= 0:
                raise ValidationError("Importe no válido.", {"amount": "El importe debe ser mayor que cero."})
            if amount > balance:
                raise ValidationError("El pago supera el saldo pendiente.", {"amount": f"Saldo pendiente: {balance / 100:.2f}"})
            method, cash_account = ledger.method_account(conn, int(data.get("method_id") or 0))
            if cash_account is None:
                raise ValidationError("Método no válido.", {"method_id": "Elija efectivo, tarjeta, transferencia u otro con cuenta."})
            pay_id = conn.execute(
                f"INSERT INTO {k.payments}({k.fk}, idempotency_key, payment_date, amount_cents, method_id, reference, user_id,"
                " created_at) VALUES (?,?,?,?,?,?,?,?)",
                (item_id, idempotency_key, str(pay_date), amount, method["id"], (data.get("reference") or "")[:120],
                 actor.id, iso())).lastrowid
            party_id = item[k.party_col]
            control = Line(k.control_account, party_type=k.party_type, party_id=party_id)
            cash = Line(cash_account, memo=method["name"])
            if k is AR:
                cash.debit, control.credit = amount, amount
                desc = f"Cobro {item['number']}"
            else:
                control.debit, cash.credit = amount, amount
                desc = f"Pago factura proveedor {item['number']}"
            ledger.post(conn, actor, pay_date, desc, k.payment_source, pay_id, [cash, control])
            record(conn, actor, f"{k.name}.{k.payment_source}", k.table, item_id, {"importe": amount, "metodo": method["name"]})
            return {"duplicate": False, **self._detail_conn(conn, item_id)}

    def void_payment(self, actor: Actor, payment_id: int, reason: str) -> dict:
        actor.require("finanzas.registrar")
        k = self.k
        if not (reason or "").strip():
            raise ValidationError("Indique el motivo.", {"reason": "El motivo es obligatorio."})
        with self.db.tx() as conn:
            pay = conn.execute(f"SELECT * FROM {k.payments} WHERE id = ?", (payment_id,)).fetchone()
            if not pay:
                raise NotFoundError("Pago no encontrado.")
            if pay["voided_at"]:
                raise ValidationError("El pago ya estaba anulado.")
            conn.execute(f"UPDATE {k.payments} SET voided_at = ?, voided_by = ?, void_reason = ? WHERE id = ?",
                         (iso(), actor.id, reason.strip()[:300], payment_id))
            for entry in ledger.entries_for(conn, k.payment_source, payment_id):
                if not entry["reverses_id"] and not entry["reversed_by_id"]:
                    ledger.reverse(conn, actor, entry["id"], local_today(self._tz()), reason.strip())
            record(conn, actor, f"{k.name}.{k.payment_source}_anulado", k.table, pay[k.fk], {"pago": payment_id,
                                                                                            "motivo": reason.strip()})
            return self._detail_conn(conn, pay[k.fk])

    def void(self, actor: Actor, item_id: int, reason: str) -> dict:
        actor.require("finanzas.registrar")
        k = self.k
        if not (reason or "").strip():
            raise ValidationError("Indique el motivo.", {"reason": "El motivo es obligatorio."})
        with self.db.tx() as conn:
            item = conn.execute(f"SELECT * FROM {k.table} WHERE id = ?", (item_id,)).fetchone()
            if not item:
                raise NotFoundError(f"La {k.label} no existe.")
            if item["status"] == "anulada":
                raise ValidationError("Ya estaba anulada.")
            if k is AR and item["source_type"] == "venta":
                raise ValidationError("Esta cuenta proviene de una venta: anule o devuelva la venta.")
            if k is AP and item["source_type"] == "entrada_inventario":
                raise ValidationError("Esta cuenta proviene de una entrada de inventario: registre una salida para revertir"
                                      " las existencias y luego anule con un asiento manual si corresponde.")
            if conn.execute(f"SELECT 1 FROM {k.payments} WHERE {k.fk} = ? AND voided_at IS NULL", (item_id,)).fetchone():
                raise ValidationError("Tiene pagos registrados: anúlelos primero.")
            conn.execute(f"UPDATE {k.table} SET status = 'anulada' WHERE id = ?", (item_id,))
            for entry in ledger.entries_for(conn, k.name, item_id):
                if not entry["reverses_id"] and not entry["reversed_by_id"]:
                    ledger.reverse(conn, actor, entry["id"], local_today(self._tz()), reason.strip())
            record(conn, actor, f"{k.name}.anular", k.table, item_id, {"motivo": reason.strip()})
            return self._detail_conn(conn, item_id)

    def _detail_conn(self, conn: sqlite3.Connection, item_id: int) -> dict:
        row = conn.execute(f"SELECT d.*, {_balance_sql(self.k)} AS balance_cents FROM {self.k.table} d WHERE d.id = ?",
                           (item_id,)).fetchone()
        return dict(row)

    def alerts(self, actor: Actor, days: int = 7) -> dict:
        items = self.list(actor, "pendientes")
        return {"vencidas": [i for i in items if i["state"] == "vencida"],
                "por_vencer": [i for i in items if i["state"] == "por_vencer"]}

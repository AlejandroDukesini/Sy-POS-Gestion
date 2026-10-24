"""Informes financieros derivados del libro diario y operaciones contables manuales.

Ningún informe usa cifras guardadas aparte: todo sale de journal_lines (y de cartera/inventario para
las conciliaciones). Si faltan datos para un informe, se devuelve la lista `missing` en lugar de
inventar cifras. Es contabilidad de gestión: no sustituye la contabilidad oficial ni la
información exógena o la facturación electrónica ante la DIAN.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from ..core.actor import Actor
from ..core.audit import record
from ..core.clock import iso, local_today, parse_date
from ..core.errors import NotFoundError, ValidationError
from ..core.money import parse_decimal, round_cents, to_cents
from . import ledger
from .ledger import Line
from .open_items import AP, AR, OpenItems

DEBIT_NORMAL = {"activo", "costo", "gasto"}
CASH_FLOW_LABELS = {
    "venta": "Ventas cobradas al contado", "cobro": "Cobros de cartera (CxC)", "pago": "Pagos a proveedores (CxP)",
    "movimiento": "Compras de inventario de contado", "devolucion": "Reembolsos por devoluciones",
    "gasto": "Gastos pagados", "manual": "Asientos manuales (capital, préstamos, otros)",
}


def _month_start(d: date) -> date:
    return d.replace(day=1)


class FinanceService:
    def __init__(self, db, settings):
        self.db = db
        self.settings = settings
        self.ar = OpenItems(db, settings, AR)
        self.ap = OpenItems(db, settings, AP)

    def _today(self) -> date:
        return local_today(self.settings.get("empresa")["timezone"])

    def _range(self, date_from: str | None, date_to: str | None) -> tuple[date, date]:
        end = parse_date(date_to, "Fecha final") if date_to else self._today()
        start = parse_date(date_from, "Fecha inicial") if date_from else _month_start(end)
        if start > end:
            raise ValidationError("La fecha inicial es posterior a la final.", {"date_from": "Revise el periodo."})
        return start, end

    # ------------------------------------------------------------------ saldos
    @staticmethod
    def _balances(conn: sqlite3.Connection, until: date, since: date | None = None) -> dict[int, dict]:
        params: list = [str(until)]
        cond = "e.entry_date <= ?"
        if since:
            cond += " AND e.entry_date >= ?"
            params.append(str(since))
        rows = conn.execute(
            "SELECT a.id, a.code, a.name, a.type, a.is_cash, a.cost_behavior,"
            f" COALESCE(SUM(CASE WHEN {cond} THEN l.debit_cents END), 0) AS debit,"
            f" COALESCE(SUM(CASE WHEN {cond} THEN l.credit_cents END), 0) AS credit"
            " FROM accounts a LEFT JOIN journal_lines l ON l.account_id = a.id LEFT JOIN journal_entries e ON e.id = l.entry_id"
            " GROUP BY a.id ORDER BY a.code", params * 2).fetchall()
        out = {}
        for r in rows:
            natural = r["debit"] - r["credit"] if r["type"] in DEBIT_NORMAL else r["credit"] - r["debit"]
            out[r["id"]] = {**dict(r), "balance": natural}
        return out

    @staticmethod
    def _has_entries(conn: sqlite3.Connection, until: date) -> bool:
        return conn.execute("SELECT 1 FROM journal_entries WHERE entry_date <= ? LIMIT 1", (str(until),)).fetchone() is not None

    # ------------------------------------------------------------------ BS
    def balance_sheet(self, actor: Actor, as_of: str | None = None, compare_to: str | None = None) -> dict:
        actor.require("finanzas.ver")
        cut = parse_date(as_of, "Fecha de corte") if as_of else self._today()
        prev = parse_date(compare_to, "Fecha de comparación") if compare_to else None
        with self.db.read() as conn:
            current = self._balances(conn, cut)
            previous = self._balances(conn, prev) if prev else None
            has_data = self._has_entries(conn, cut)

        def section(kind: str, bal: dict) -> tuple[list[dict], int]:
            items = [{"code": a["code"], "name": a["name"], "balance_cents": a["balance"]}
                     for a in bal.values() if a["type"] == kind and a["balance"]]
            return items, sum(i["balance_cents"] for i in items)

        def build(bal: dict) -> dict:
            assets, ta = section("activo", bal)
            liabilities, tl = section("pasivo", bal)
            equity, te = section("patrimonio", bal)
            earnings = sum(a["balance"] for a in bal.values() if a["type"] == "ingreso") - \
                sum(a["balance"] for a in bal.values() if a["type"] in ("costo", "gasto"))
            if earnings:
                equity.append({"code": "", "name": "Resultado del ejercicio (no trasladado)", "balance_cents": earnings})
            te += earnings
            return {"assets": assets, "liabilities": liabilities, "equity": equity, "total_assets_cents": ta,
                    "total_liabilities_cents": tl, "total_equity_cents": te,
                    "difference_cents": ta - tl - te, "balanced": ta == tl + te}

        result = {"as_of": str(cut), "current": build(current), "missing": []}
        if previous is not None:
            result["compare_to"] = str(prev)
            result["previous"] = build(previous)
        if not has_data:
            result["missing"].append("No hay operaciones registradas hasta la fecha de corte. Registre el inventario inicial, "
                                     "el capital y las ventas para obtener un balance.")
        return result

    # ------------------------------------------------------------------ estado de resultados (base de BEP)
    def income_statement(self, actor: Actor, date_from: str | None = None, date_to: str | None = None) -> dict:
        actor.require("finanzas.ver")
        start, end = self._range(date_from, date_to)
        with self.db.read() as conn:
            bal = self._balances(conn, end, start)
        by_code = {a["code"]: a for a in bal.values()}
        gross_sales = by_code[ledger.SALES]["balance"]
        returns = -by_code[ledger.SALES_RETURNS]["balance"]
        other_income = sum(a["balance"] for a in bal.values() if a["type"] == "ingreso"
                           and a["code"] not in (ledger.SALES, ledger.SALES_RETURNS))
        cogs = sum(a["balance"] for a in bal.values() if a["type"] == "costo")
        expenses = [{"code": a["code"], "name": a["name"], "behavior": a["cost_behavior"], "balance_cents": a["balance"]}
                    for a in bal.values() if a["type"] == "gasto" and a["balance"]]
        net_sales = gross_sales - returns
        total_exp = sum(e["balance_cents"] for e in expenses)
        return {"date_from": str(start), "date_to": str(end), "gross_sales_cents": gross_sales, "returns_cents": returns,
                "net_sales_cents": net_sales, "cogs_cents": cogs, "gross_profit_cents": net_sales - cogs,
                "expenses": expenses, "total_expenses_cents": total_exp, "other_income_cents": other_income,
                "net_income_cents": net_sales - cogs - total_exp + other_income}

    # ------------------------------------------------------------------ BEP
    def break_even(self, actor: Actor, date_from: str | None = None, date_to: str | None = None,
                   overrides: dict | None = None) -> dict:
        actor.require("finanzas.ver")
        start, end = self._range(date_from, date_to)
        pnl = self.income_statement(actor, str(start), str(end))
        with self.db.read() as conn:
            units_sold = conn.execute(
                "SELECT COALESCE(SUM(l.qty_milli), 0) FROM sale_lines l JOIN sales s ON s.id = l.sale_id"
                " WHERE s.status = 'completada' AND s.sale_date BETWEEN ? AND ?", (str(start), str(end))).fetchone()[0]
            units_returned = conn.execute(
                "SELECT COALESCE(SUM(rl.qty_milli), 0) FROM sale_return_lines rl JOIN sale_returns r ON r.id = rl.return_id"
                " WHERE r.return_date BETWEEN ? AND ?", (str(start), str(end))).fetchone()[0]
        fixed = sum(e["balance_cents"] for e in pnl["expenses"] if e["behavior"] == "fijo")
        variable_exp = sum(e["balance_cents"] for e in pnl["expenses"] if e["behavior"] != "fijo")
        variable = pnl["cogs_cents"] + variable_exp
        units = Decimal(units_sold - units_returned) / 1000
        source = "contabilidad"
        missing: list[str] = []
        price_unit = Decimal(pnl["net_sales_cents"]) / units if units > 0 else None
        var_unit = Decimal(variable) / units if units > 0 else None
        o = {k: v for k, v in (overrides or {}).items() if v not in (None, "")}
        if o:
            source = "manual" if {"fixed_costs", "price", "variable_cost"} <= set(o) else "mixto"
            if "fixed_costs" in o:
                fixed = to_cents(o["fixed_costs"], "Costos fijos")
            if "price" in o:
                price_unit = Decimal(to_cents(o["price"], "Precio de venta"))
            if "variable_cost" in o:
                var_unit = Decimal(to_cents(o["variable_cost"], "Costo variable unitario"))
        if price_unit is None:
            missing.append("No hay ventas en el periodo: no se puede calcular el precio promedio por unidad. "
                           "Amplíe el periodo o escriba el precio de venta.")
        if var_unit is None:
            missing.append("No hay costo variable por unidad (sin ventas en el periodo). Escriba el costo variable unitario.")
        if fixed == 0:
            missing.append("No hay gastos fijos registrados en el periodo (cuentas de gasto marcadas como fijas). "
                           "Regístrelos en Contabilidad o escriba los costos fijos.")
        result = {"date_from": str(start), "date_to": str(end), "source": source, "fixed_costs_cents": fixed,
                  "variable_costs_cents": variable, "net_sales_cents": pnl["net_sales_cents"],
                  "units_sold": str(units.normalize()) if units else "0",
                  "price_unit_cents": round_cents(price_unit) if price_unit is not None else None,
                  "variable_unit_cents": round_cents(var_unit) if var_unit is not None else None,
                  "missing": missing}
        if price_unit is not None and var_unit is not None:
            margin = price_unit - var_unit
            result["contribution_margin_unit_cents"] = round_cents(margin)
            ratio = margin / price_unit if price_unit else Decimal(0)
            result["contribution_margin_ratio"] = f"{(ratio * 100).quantize(Decimal('0.01'))}"
            if margin <= 0:
                missing.append("El margen de contribución es cero o negativo: con estos precios y costos no existe punto "
                               "de equilibrio.")
            elif fixed > 0:
                be_units = Decimal(fixed) / margin
                result["break_even_units"] = str(be_units.quantize(Decimal("0.01")))
                result["break_even_sales_cents"] = round_cents(be_units * price_unit)
                if source == "contabilidad" and units > 0:
                    result["safety_margin_pct"] = str(((units - be_units) / units * 100).quantize(Decimal("0.01")))
        return result

    # ------------------------------------------------------------------ CF
    def cash_flow(self, actor: Actor, date_from: str | None = None, date_to: str | None = None,
                  projection_weeks: int = 8) -> dict:
        actor.require("finanzas.ver")
        start, end = self._range(date_from, date_to)
        length = (end - start).days + 1
        prev_end = start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=length - 1)
        with self.db.read() as conn:
            current = self._cash_period(conn, start, end)
            previous = self._cash_period(conn, prev_start, prev_end)
            accounts = [dict(r) for r in conn.execute("SELECT id, code, name FROM accounts WHERE is_cash = 1 ORDER BY code")]
        projection = self._projection(actor, projection_weeks, current["closing_cents"])
        missing = []
        if not current["inflows"] and not current["outflows"] and not current["opening_cents"]:
            missing.append("No hay movimientos de caja ni bancos en el periodo.")
        return {"date_from": str(start), "date_to": str(end), "accounts": accounts, "current": current,
                "previous": {**previous, "date_from": str(prev_start), "date_to": str(prev_end)},
                "projection": projection, "missing": missing}

    def _cash_period(self, conn: sqlite3.Connection, start: date, end: date) -> dict:
        opening = conn.execute(
            "SELECT COALESCE(SUM(l.debit_cents - l.credit_cents), 0) FROM journal_lines l JOIN journal_entries e"
            " ON e.id = l.entry_id JOIN accounts a ON a.id = l.account_id WHERE a.is_cash = 1 AND e.entry_date < ?",
            (str(start),)).fetchone()[0]
        rows = conn.execute(
            "SELECT e.source_type, e.entry_date, l.debit_cents, l.credit_cents, e.reverses_id FROM journal_lines l"
            " JOIN journal_entries e ON e.id = l.entry_id JOIN accounts a ON a.id = l.account_id"
            " WHERE a.is_cash = 1 AND e.entry_date BETWEEN ? AND ?", (str(start), str(end))).fetchall()
        inflow, outflow = defaultdict(int), defaultdict(int)
        by_month: dict[str, dict] = {}
        for r in rows:
            label = CASH_FLOW_LABELS.get(r["source_type"], r["source_type"])
            if r["reverses_id"]:
                label += " (reversos)"
            month = r["entry_date"][:7]
            m = by_month.setdefault(month, {"period": month, "in_cents": 0, "out_cents": 0})
            if r["debit_cents"]:
                inflow[label] += r["debit_cents"]
                m["in_cents"] += r["debit_cents"]
            else:
                outflow[label] += r["credit_cents"]
                m["out_cents"] += r["credit_cents"]
        total_in, total_out = sum(inflow.values()), sum(outflow.values())
        return {"opening_cents": opening,
                "inflows": [{"label": k, "amount_cents": v} for k, v in sorted(inflow.items(), key=lambda x: -x[1])],
                "outflows": [{"label": k, "amount_cents": v} for k, v in sorted(outflow.items(), key=lambda x: -x[1])],
                "total_in_cents": total_in, "total_out_cents": total_out, "net_cents": total_in - total_out,
                "closing_cents": opening + total_in - total_out,
                "by_month": [{**m, "net_cents": m["in_cents"] - m["out_cents"]} for m in sorted(by_month.values(),
                                                                                                key=lambda x: x["period"])]}

    def _projection(self, actor: Actor, weeks: int, opening: int) -> dict:
        """Proyección semanal: cobros esperados (saldos de CxC por vencimiento) − pagos esperados (CxP).

        Lo vencido se asume en la primera semana. No incluye ventas futuras ni gastos no registrados.
        """
        weeks = max(1, min(26, int(weeks)))
        today = self._today()
        buckets = [{"week_start": str(today + timedelta(days=7 * i)), "in_cents": 0, "out_cents": 0} for i in range(weeks)]

        def place(items: list[dict], key: str) -> None:
            for it in items:
                idx = max(0, (date.fromisoformat(it["due_date"]) - today).days // 7)
                if idx < weeks:
                    buckets[idx][key] += it["balance_cents"]

        place(self.ar.list(actor, "pendientes"), "in_cents")
        place(self.ap.list(actor, "pendientes"), "out_cents")
        balance = opening
        for b in buckets:
            b["net_cents"] = b["in_cents"] - b["out_cents"]
            balance += b["net_cents"]
            b["balance_cents"] = balance
        return {"opening_cents": opening, "weeks": buckets,
                "note": "Basada en cuentas por cobrar y por pagar registradas; no incluye ventas futuras ni gastos no registrados."}

    # ------------------------------------------------------------------ ACC: libro diario, mayor, balance de prueba
    def accounts(self, actor: Actor, include_inactive: bool = False) -> list[dict]:
        if not (actor.can("finanzas.ver") or actor.can("gestion.configuracion")):
            actor.require("finanzas.ver")
        with self.db.read() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM accounts" + ("" if include_inactive else " WHERE active = 1")
                                                  + " ORDER BY code")]

    def save_account(self, actor: Actor, data: dict, account_id: int | None = None) -> dict:
        actor.require("finanzas.registrar")
        code = (data.get("code") or "").strip()
        name = (data.get("name") or "").strip()
        kind = data.get("type")
        behavior = data.get("cost_behavior") or None
        errors = {}
        if not code.isdigit() or not 4 <= len(code) <= 10:
            errors["code"] = "Código numérico de 4 a 10 dígitos."
        if not name:
            errors["name"] = "El nombre es obligatorio."
        if kind not in ("activo", "pasivo", "patrimonio", "ingreso", "costo", "gasto"):
            errors["type"] = "Tipo de cuenta no válido."
        if behavior not in (None, "fijo", "variable") or (behavior and kind not in ("costo", "gasto")):
            errors["cost_behavior"] = "Solo los costos y gastos son fijos o variables."
        if errors:
            raise ValidationError("Revise la cuenta.", errors)
        is_cash = int(bool(data.get("is_cash")) and kind == "activo")
        with self.db.tx() as conn:
            if account_id is None:
                if conn.execute("SELECT 1 FROM accounts WHERE code = ?", (code,)).fetchone():
                    raise ValidationError("Código repetido.", {"code": "Ya existe una cuenta con ese código."})
                account_id = conn.execute("INSERT INTO accounts(code, name, type, is_cash, cost_behavior, created_at)"
                                          " VALUES (?,?,?,?,?,?)", (code, name, kind, is_cash, behavior, iso())).lastrowid
                record(conn, actor, "cuenta.crear", "account", account_id, {"codigo": code, "nombre": name})
            else:
                acc = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
                if not acc:
                    raise NotFoundError("Cuenta no encontrada.")
                used = conn.execute("SELECT 1 FROM journal_lines WHERE account_id = ? LIMIT 1", (account_id,)).fetchone()
                if (acc["system"] or used) and (code != acc["code"] or kind != acc["type"]):
                    raise ValidationError("Una cuenta del sistema o con movimientos no puede cambiar de código ni de tipo.")
                active = int(bool(data.get("active", True)))
                if acc["system"] and not active:
                    raise ValidationError("Las cuentas del sistema no se desactivan.")
                conn.execute("UPDATE accounts SET code = ?, name = ?, type = ?, is_cash = ?, cost_behavior = ?, active = ?"
                             " WHERE id = ?", (code, name, kind, is_cash, behavior, active, account_id))
                record(conn, actor, "cuenta.actualizar", "account", account_id, {"codigo": code, "nombre": name})
            return dict(conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone())

    def journal(self, actor: Actor, date_from: str | None = None, date_to: str | None = None, source: str = "",
                page: int = 1, page_size: int = 50) -> dict:
        actor.require("finanzas.ver")
        start, end = self._range(date_from, date_to)
        page, page_size = max(1, int(page)), min(200, max(1, int(page_size)))
        where, params = ["e.entry_date BETWEEN ? AND ?"], [str(start), str(end)]
        if source:
            where.append("e.source_type = ?")
            params.append(source)
        with self.db.read() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM journal_entries e WHERE {' AND '.join(where)}", params).fetchone()[0]
            entries = [dict(r) for r in conn.execute(
                f"SELECT e.*, u.username FROM journal_entries e LEFT JOIN users u ON u.id = e.user_id WHERE {' AND '.join(where)}"
                " ORDER BY e.entry_date DESC, e.id DESC LIMIT ? OFFSET ?", (*params, page_size, (page - 1) * page_size))]
            for e in entries:
                e["lines"] = [dict(r) for r in conn.execute(
                    "SELECT l.*, a.code, a.name FROM journal_lines l JOIN accounts a ON a.id = l.account_id"
                    " WHERE l.entry_id = ? ORDER BY l.debit_cents = 0, l.id", (e["id"],))]
        return {"date_from": str(start), "date_to": str(end), "items": entries, "total": total, "page": page,
                "page_size": page_size, "pages": max(1, -(-total // page_size))}

    def ledger_account(self, actor: Actor, account_code: str, date_from: str | None = None, date_to: str | None = None) -> dict:
        actor.require("finanzas.ver")
        start, end = self._range(date_from, date_to)
        with self.db.read() as conn:
            acc = conn.execute("SELECT * FROM accounts WHERE code = ?", (account_code,)).fetchone()
            if not acc:
                raise NotFoundError("Cuenta no encontrada.")
            sign = 1 if acc["type"] in DEBIT_NORMAL else -1
            opening = conn.execute("SELECT COALESCE(SUM(debit_cents - credit_cents), 0) FROM journal_lines l"
                                   " JOIN journal_entries e ON e.id = l.entry_id WHERE l.account_id = ? AND e.entry_date < ?",
                                   (acc["id"], str(start))).fetchone()[0] * sign
            rows = [dict(r) for r in conn.execute(
                "SELECT l.*, e.entry_date, e.description, e.source_type, e.source_id,"
                " (SELECT 1 FROM reconciliation_items ri WHERE ri.journal_line_id = l.id) AS reconciled"
                " FROM journal_lines l JOIN journal_entries e ON e.id = l.entry_id WHERE l.account_id = ?"
                " AND e.entry_date BETWEEN ? AND ? ORDER BY e.entry_date, l.id", (acc["id"], str(start), str(end)))]
        balance = opening
        for r in rows:
            balance += (r["debit_cents"] - r["credit_cents"]) * sign
            r["balance_cents"] = balance
        return {"account": dict(acc), "date_from": str(start), "date_to": str(end), "opening_cents": opening,
                "lines": rows, "closing_cents": balance}

    def trial_balance(self, actor: Actor, as_of: str | None = None) -> dict:
        actor.require("finanzas.ver")
        cut = parse_date(as_of) if as_of else self._today()
        with self.db.read() as conn:
            bal = self._balances(conn, cut)
        rows = [{"code": a["code"], "name": a["name"], "type": a["type"], "debit_cents": a["debit"], "credit_cents": a["credit"],
                 "balance_cents": a["balance"]} for a in bal.values() if a["debit"] or a["credit"]]
        td, tc = sum(r["debit_cents"] for r in rows), sum(r["credit_cents"] for r in rows)
        return {"as_of": str(cut), "rows": rows, "total_debit_cents": td, "total_credit_cents": tc, "balanced": td == tc}

    # ------------------------------------------------------------------ ACC: registro de operaciones
    def manual_entry(self, actor: Actor, data: dict, idempotency_key: str) -> dict:
        actor.require("finanzas.registrar")
        if not idempotency_key:
            raise ValidationError("Falta la clave de idempotencia.")
        description = (data.get("description") or "").strip()
        if not description:
            raise ValidationError("Describa la operación.", {"description": "La descripción es obligatoria."})
        day = parse_date(data.get("entry_date") or str(self._today()), "Fecha")
        lines, errors = [], {}
        for i, raw in enumerate(data.get("lines") or []):
            debit = parse_decimal(raw.get("debit") or 0)
            credit = parse_decimal(raw.get("credit") or 0)
            if debit is None or credit is None or debit < 0 or credit < 0 or (debit and credit) or not (debit or credit):
                errors[f"lines.{i}"] = f"Línea {i + 1}: escriba un valor en Débito o en Crédito (no en ambos)."
                continue
            lines.append(Line(str(raw.get("account_code") or "").strip(), debit=to_cents(debit), credit=to_cents(credit),
                              memo=(raw.get("memo") or "")[:200]))
        if errors:
            raise ValidationError("Revise las líneas del asiento.", errors)
        if len(lines) < 2:
            raise ValidationError("Un asiento necesita al menos dos líneas.", {"lines": "Agregue débitos y créditos."})
        with self.db.tx() as conn:
            done = conn.execute("SELECT id FROM journal_entries WHERE source_type = 'manual' AND purpose = ?",
                                (f"manual:{idempotency_key}",)).fetchone()
            if done:
                return {"duplicate": True, "entry_id": done[0]}
            entry = ledger.post(conn, actor, day, description, "manual", None, lines, purpose=f"manual:{idempotency_key}")
            record(conn, actor, "contabilidad.asiento_manual", "journal_entry", entry, {"descripcion": description})
        return {"duplicate": False, "entry_id": entry}

    def register_expense(self, actor: Actor, data: dict, idempotency_key: str) -> dict:
        """Gasto pagado de inmediato: Dr cuenta de gasto · Cr Caja/Bancos del método de pago."""
        actor.require("finanzas.registrar")
        if not idempotency_key:
            raise ValidationError("Falta la clave de idempotencia.")
        description = (data.get("description") or "").strip()
        if not description:
            raise ValidationError("Describa el gasto.", {"description": "La descripción es obligatoria."})
        day = parse_date(data.get("entry_date") or str(self._today()), "Fecha")
        amount = to_cents(data.get("amount"), "Importe")
        if amount <= 0:
            raise ValidationError("Importe no válido.", {"amount": "El importe debe ser mayor que cero."})
        with self.db.tx() as conn:
            done = conn.execute("SELECT id FROM journal_entries WHERE source_type = 'gasto' AND purpose = ?",
                                (f"gasto:{idempotency_key}",)).fetchone()
            if done:
                return {"duplicate": True, "entry_id": done[0]}
            acc = conn.execute("SELECT * FROM accounts WHERE code = ? AND active = 1", (data.get("account_code"),)).fetchone()
            if not acc or acc["type"] not in ("gasto", "costo"):
                raise ValidationError("Cuenta no válida.", {"account_code": "Elija una cuenta de gasto."})
            method, cash = ledger.method_account(conn, int(data.get("method_id") or 0))
            if cash is None:
                raise ValidationError("Método no válido.", {"method_id": "Para gastos a crédito registre una cuenta por pagar."})
            entry = ledger.post(conn, actor, day, description, "gasto", None,
                                [Line(acc["id"], debit=amount, memo=description), Line(cash, credit=amount, memo=method["name"])],
                                purpose=f"gasto:{idempotency_key}")
            record(conn, actor, "contabilidad.gasto", "journal_entry", entry, {"cuenta": acc["code"], "importe": amount})
        return {"duplicate": False, "entry_id": entry}

    def reverse_entry(self, actor: Actor, entry_id: int, reason: str) -> dict:
        actor.require("finanzas.registrar")
        if not (reason or "").strip():
            raise ValidationError("Indique el motivo.", {"reason": "El motivo es obligatorio."})
        with self.db.tx() as conn:
            entry = conn.execute("SELECT * FROM journal_entries WHERE id = ?", (entry_id,)).fetchone()
            if not entry:
                raise NotFoundError("Asiento no encontrado.")
            if entry["source_type"] not in ("manual", "gasto"):
                raise ValidationError("Este asiento lo generó una operación (venta, cobro, inventario…): revierta la "
                                      "operación desde su módulo para mantener la trazabilidad.")
            new_id = ledger.reverse(conn, actor, entry_id, self._today(), reason.strip())
            record(conn, actor, "contabilidad.reverso", "journal_entry", entry_id, {"reverso": new_id, "motivo": reason.strip()})
        return {"entry_id": new_id}

    # ------------------------------------------------------------------ conciliaciones
    def unreconciled(self, actor: Actor, account_code: str, until: str | None = None) -> dict:
        actor.require("finanzas.ver")
        cut = parse_date(until) if until else self._today()
        with self.db.read() as conn:
            acc = conn.execute("SELECT * FROM accounts WHERE code = ? AND is_cash = 1", (account_code,)).fetchone()
            if not acc:
                raise NotFoundError("Cuenta de caja o bancos no encontrada.")
            lines = [dict(r) for r in conn.execute(
                "SELECT l.id, l.debit_cents, l.credit_cents, l.memo, e.entry_date, e.description FROM journal_lines l"
                " JOIN journal_entries e ON e.id = l.entry_id WHERE l.account_id = ? AND e.entry_date <= ?"
                " AND l.id NOT IN (SELECT journal_line_id FROM reconciliation_items) ORDER BY e.entry_date, l.id",
                (acc["id"], str(cut)))]
            reconciled = conn.execute(
                "SELECT COALESCE(SUM(l.debit_cents - l.credit_cents), 0) FROM journal_lines l JOIN reconciliation_items ri"
                " ON ri.journal_line_id = l.id WHERE l.account_id = ?", (acc["id"],)).fetchone()[0]
            history = [dict(r) for r in conn.execute("SELECT r.*, u.username FROM reconciliations r LEFT JOIN users u"
                                                     " ON u.id = r.user_id WHERE account_id = ? ORDER BY r.id DESC",
                                                     (acc["id"],))]
        return {"account": dict(acc), "until": str(cut), "lines": lines, "reconciled_balance_cents": reconciled,
                "history": history}

    def reconcile(self, actor: Actor, data: dict) -> dict:
        actor.require("finanzas.registrar")
        statement_date = parse_date(data.get("statement_date"), "Fecha del extracto")
        statement_balance = to_cents(data.get("statement_balance"), "Saldo del extracto")
        line_ids = [int(x) for x in data.get("line_ids") or []]
        with self.db.tx() as conn:
            acc = conn.execute("SELECT * FROM accounts WHERE code = ? AND is_cash = 1", (data.get("account_code"),)).fetchone()
            if not acc:
                raise ValidationError("Cuenta no válida.", {"account_code": "Elija una cuenta de caja o bancos."})
            for lid in line_ids:
                ok = conn.execute("SELECT 1 FROM journal_lines l JOIN journal_entries e ON e.id = l.entry_id WHERE l.id = ?"
                                  " AND l.account_id = ? AND e.entry_date <= ? AND l.id NOT IN"
                                  " (SELECT journal_line_id FROM reconciliation_items)",
                                  (lid, acc["id"], str(statement_date))).fetchone()
                if not ok:
                    raise ValidationError("Un movimiento seleccionado no es válido o ya estaba conciliado.")
            book = conn.execute("SELECT COALESCE(SUM(l.debit_cents - l.credit_cents), 0) FROM journal_lines l"
                                " JOIN journal_entries e ON e.id = l.entry_id WHERE l.account_id = ? AND e.entry_date <= ?",
                                (acc["id"], str(statement_date))).fetchone()[0]
            prior = conn.execute("SELECT COALESCE(SUM(l.debit_cents - l.credit_cents), 0) FROM journal_lines l"
                                 " JOIN reconciliation_items ri ON ri.journal_line_id = l.id WHERE l.account_id = ?",
                                 (acc["id"],)).fetchone()[0]
            selected = sum(conn.execute("SELECT debit_cents - credit_cents FROM journal_lines WHERE id = ?", (lid,)).fetchone()[0]
                           for lid in line_ids)
            reconciled = prior + selected
            rec_id = conn.execute(
                "INSERT INTO reconciliations(account_id, statement_date, statement_balance_cents, book_balance_cents,"
                " reconciled_balance_cents, difference_cents, notes, user_id, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (acc["id"], str(statement_date), statement_balance, book, reconciled, statement_balance - reconciled,
                 (data.get("notes") or "")[:500], actor.id, iso())).lastrowid
            conn.executemany("INSERT INTO reconciliation_items(reconciliation_id, journal_line_id) VALUES (?,?)",
                             [(rec_id, lid) for lid in line_ids])
            record(conn, actor, "contabilidad.conciliacion", "reconciliation", rec_id,
                   {"cuenta": acc["code"], "diferencia": statement_balance - reconciled, "movimientos": len(line_ids)})
            return dict(conn.execute("SELECT * FROM reconciliations WHERE id = ?", (rec_id,)).fetchone())

    def integrity(self, actor: Actor) -> dict:
        """Verificaciones cruzadas: libro cuadrado, inventario contable vs. valorizado, cartera vs. cuenta de control."""
        actor.require("finanzas.ver")
        with self.db.read() as conn:
            td, tc = conn.execute("SELECT COALESCE(SUM(debit_cents), 0), COALESCE(SUM(credit_cents), 0) FROM journal_lines").fetchone()
            unbalanced = conn.execute("SELECT COUNT(*) FROM (SELECT entry_id FROM journal_lines GROUP BY entry_id"
                                      " HAVING SUM(debit_cents) <> SUM(credit_cents))").fetchone()[0]
            inv_ledger = conn.execute("SELECT COALESCE(SUM(debit_cents - credit_cents), 0) FROM journal_lines l JOIN accounts a"
                                      " ON a.id = l.account_id WHERE a.code = ?", (ledger.INVENTORY,)).fetchone()[0]
            inv_valued = conn.execute("SELECT COALESCE(SUM(stock_milli * cost_cents), 0) FROM products").fetchone()[0] // 1000
            stock_mismatch = conn.execute(
                "SELECT COUNT(*) FROM products p WHERE p.stock_milli <> (SELECT COALESCE(SUM(qty_milli), 0)"
                " FROM inventory_movements m WHERE m.product_id = p.id)").fetchone()[0]

            def control(code: str) -> int:
                sign = 1 if code == ledger.RECEIVABLE else -1
                return sign * conn.execute("SELECT COALESCE(SUM(debit_cents - credit_cents), 0) FROM journal_lines l"
                                           " JOIN accounts a ON a.id = l.account_id WHERE a.code = ?", (code,)).fetchone()[0]
            ar_ledger, ap_ledger = control(ledger.RECEIVABLE), control(ledger.PAYABLE)
        ar_items = sum(i["balance_cents"] for i in self.ar.list(actor, "pendientes"))
        ap_items = sum(i["balance_cents"] for i in self.ap.list(actor, "pendientes"))
        checks = [
            {"name": "Débitos = créditos", "ok": td == tc and unbalanced == 0, "detail": f"{unbalanced} asientos descuadrados"},
            {"name": "Existencias = suma de movimientos", "ok": stock_mismatch == 0,
             "detail": f"{stock_mismatch} productos con diferencias"},
            {"name": "Inventario contable vs. valorizado (existencia × costo promedio)", "ok": abs(inv_ledger - inv_valued) <= 100,
             "ledger_cents": inv_ledger, "items_cents": inv_valued, "difference_cents": inv_ledger - inv_valued,
             "detail": "Diferencias pequeñas se deben al redondeo del costo promedio; grandes, a entradas sin costo o"
                       " existencias negativas."},
            {"name": "Cartera (CxC) vs. cuenta 1305", "ok": ar_ledger == ar_items, "ledger_cents": ar_ledger,
             "items_cents": ar_items, "difference_cents": ar_ledger - ar_items},
            {"name": "Proveedores (CxP) vs. cuenta 2205", "ok": ap_ledger == ap_items, "ledger_cents": ap_ledger,
             "items_cents": ap_items, "difference_cents": ap_ledger - ap_items},
        ]
        return {"checks": checks, "ok": all(c["ok"] for c in checks)}

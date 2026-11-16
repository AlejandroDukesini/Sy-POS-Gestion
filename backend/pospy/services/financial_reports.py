"""Finanzas › Informes: cuánto dinero ingresó al negocio en un periodo, con cierres habituales o anticipados.

Fuentes (solo lectura; este servicio NUNCA escribe en ventas, pagos, devoluciones, cartera, asientos
ni inventario):

  Ventas registradas  sales (status = 'completada', por sale_date): bruto, descuentos, total, crédito.
  Devoluciones        sale_returns (por return_date): total devuelto, reembolso pagado y abono a cartera.
  Dinero recibido     sale_payments de métodos que no son crédito (cada pago aparece una sola vez; el
                      cambio entregado no se suma porque amount_cents es el importe aplicado a la venta)
                      + receivable_payments no anulados (por payment_date)
                      + otros ingresos cobrados (asientos que acreditan cuentas de ingreso distintas de
                        ventas y que mueven caja o bancos)
                      − reembolsos de devoluciones (por return_date y método).
  Verificación        movimiento de las cuentas de caja y bancos en el libro diario para ventas, cobros
                      y devoluciones; si difiere del cálculo operativo se muestra la diferencia.

Un informe guardado es una instantánea inmutable (JSON) con su huella sha256. Si las operaciones del
periodo cambian después, se genera una revisión nueva; la anterior se conserva como 'reemplazado'.
"""
from __future__ import annotations

import calendar
import hashlib
import json
import sqlite3
from datetime import date, timedelta

from ..core.actor import Actor
from ..core.audit import record
from ..core.clock import iso, local_today, parse_date
from ..core.errors import ConflictError, NotFoundError, ValidationError
from ..core.money import to_cents
from ..core.sequences import next_number
from . import ledger

KINDS = ("diario", "semanal", "mensual", "anual", "personalizado")
KIND_LABELS = {"diario": "Diario", "semanal": "Semanal", "mensual": "Mensual", "anual": "Anual",
               "personalizado": "Personalizado"}
CLOSURE_LABELS = {"habitual": "Cierre habitual", "anticipado": "Cierre anticipado", "personalizado": "Periodo personalizado"}
NOTE_CATEGORIES = ("general", "incidencia", "diferencia_caja", "aclaracion", "extraordinaria")
NOTE_LABELS = {"general": "Observación general", "incidencia": "Incidencia", "diferencia_caja": "Diferencia de caja",
               "aclaracion": "Aclaración sobre ingresos", "extraordinaria": "Situación extraordinaria"}
WEEKDAYS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")
WEEKDAY_LABELS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MONTHS = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
          "noviembre", "diciembre")
METHOD_KINDS = ("efectivo", "transferencia", "tarjeta", "otro")
METHOD_KIND_LABELS = {"efectivo": "Efectivo", "transferencia": "Transferencias", "tarjeta": "Tarjetas", "otro": "Otros medios"}
MAX_DAYS = 1100
MIN_DATE = date(2000, 1, 1)
SALE_ACCOUNTS = (ledger.SALES, ledger.SALES_RETURNS)


def _month_end(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _long(d: date) -> str:
    return f"{d.day} de {MONTHS[d.month - 1]} de {d.year}"


def _sha(figures: dict) -> str:
    return hashlib.sha256(json.dumps(figures, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class FinancialReportService:
    def __init__(self, db, settings):
        self.db = db
        self.settings = settings

    # ------------------------------------------------------------------ calendario
    def _today(self) -> date:
        return local_today(self.settings.get("empresa")["timezone"])

    def week_start(self, conn: sqlite3.Connection | None = None) -> str:
        return self.settings.get("informes", conn)["week_start"]

    def _week_of(self, d: date, week_start: str) -> tuple[date, date]:
        offset = (d.weekday() - WEEKDAYS.index(week_start)) % 7
        start = d - timedelta(days=offset)
        return start, start + timedelta(days=6)

    def presets(self, actor: Actor) -> dict:
        actor.require("finanzas.ver")
        today = self._today()
        ws = self.week_start()
        week_from, week_to = self._week_of(today, ws)
        last_week_from = week_from - timedelta(days=7)
        month_from = today.replace(day=1)
        last_month_to = month_from - timedelta(days=1)
        year_from = date(today.year, 1, 1)
        items = [
            ("ayer", "Ayer", "diario", today - timedelta(days=1), today - timedelta(days=1)),
            ("hoy", "Hoy", "diario", today, today),
            ("semana_actual", "Semana actual", "semanal", week_from, today),
            ("semana_pasada", "Semana pasada", "semanal", last_week_from, last_week_from + timedelta(days=6)),
            ("mes_actual", "Mes actual", "mensual", month_from, today),
            ("mes_pasado", "Mes pasado", "mensual", last_month_to.replace(day=1), last_month_to),
            ("anio_actual", "Año actual", "anual", year_from, today),
            ("anio_pasado", "Año pasado", "anual", date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)),
        ]
        return {"today": str(today), "week_start": ws, "week_start_label": WEEKDAY_LABELS[WEEKDAYS.index(ws)],
                "presets": [{"key": k, "label": label, "kind": kind, "date_from": str(a), "date_to": str(b)}
                            for k, label, kind, a, b in items]}

    def _period(self, kind: str, date_from: str | None, date_to: str | None, week_start: str) -> dict:
        """Valida el intervalo y lo clasifica. El intervalo elegido manda sobre el periodo habitual."""
        if kind not in KINDS:
            raise ValidationError("Tipo de informe no válido.", {"kind": "Elija diario, semanal, mensual, anual o personalizado."})
        start = parse_date(date_from, "Fecha inicial")
        end = parse_date(date_to, "Fecha final")
        today = self._today()
        if start < MIN_DATE:
            raise ValidationError("La fecha inicial es demasiado antigua.", {"date_from": "Use una fecha desde el año 2000."})
        if start > end:
            raise ValidationError("La fecha inicial es posterior a la final.", {"date_to": "Debe ser igual o posterior a la inicial."})
        if end > today:
            raise ValidationError("El informe no puede incluir fechas futuras.",
                                  {"date_to": f"Use una fecha hasta hoy ({today.strftime('%d/%m/%Y')})."})
        days = (end - start).days + 1
        if days > MAX_DAYS:
            raise ValidationError("El periodo es demasiado largo.", {"date_to": f"Máximo {MAX_DAYS} días por informe."})
        if kind == "diario":
            if start != end:
                raise ValidationError("Un informe diario cubre un solo día.", {"date_to": "Use la misma fecha inicial y final."})
            natural_end = end
        elif kind == "semanal":
            week_from, natural_end = self._week_of(start, week_start)
            if start != week_from:
                label = WEEKDAY_LABELS[WEEKDAYS.index(week_start)]
                raise ValidationError("La semana no empieza en el día configurado.",
                                      {"date_from": f"La semana del negocio empieza el {label}. Use el tipo «personalizado»"
                                                    " para otros intervalos."})
            if end > natural_end:
                raise ValidationError("Un informe semanal cubre como máximo 7 días.",
                                      {"date_to": f"La semana termina el {natural_end.strftime('%d/%m/%Y')}."})
        elif kind == "mensual":
            natural_end = _month_end(start)
            if start.day != 1 or end > natural_end:
                raise ValidationError("Un informe mensual va del día 1 hasta, como máximo, el último día del mes.",
                                      {"date_from": "Empiece el día 1 y termine dentro del mismo mes."})
        elif kind == "anual":
            natural_end = date(start.year, 12, 31)
            if (start.month, start.day) != (1, 1) or end > natural_end:
                raise ValidationError("Un informe anual va del 1 de enero hasta, como máximo, el 31 de diciembre.",
                                      {"date_from": "Empiece el 1 de enero y termine dentro del mismo año."})
        else:
            natural_end = end
        period_days = (natural_end - start).days + 1
        if kind == "personalizado":
            closure = "personalizado"
        else:
            closure = "anticipado" if end < natural_end else "habitual"
        return {"kind": kind, "start": start, "end": end, "days": days, "period_days": period_days,
                "natural_end": natural_end, "closure": closure, "in_progress": end >= today}

    @staticmethod
    def _default_name(p: dict) -> str:
        start, end, kind = p["start"], p["end"], p["kind"]
        if kind == "diario":
            name = f"Informe diario del {_long(start)}"
        elif kind == "semanal":
            name = f"Informe semanal del {_long(start)} al {_long(p['natural_end'])}"
        elif kind == "mensual":
            name = f"Informe mensual de {MONTHS[start.month - 1]} de {start.year}"
        elif kind == "anual":
            name = f"Informe anual {start.year}"
        else:
            name = f"Informe del {_long(start)} al {_long(end)}"
        if p["closure"] == "anticipado":
            name += f" (cierre anticipado al {_long(end)})"
        return name

    def _previous(self, p: dict) -> tuple[date, date]:
        start, end, kind = p["start"], p["end"], p["kind"]
        if kind == "diario":
            return start - timedelta(days=1), end - timedelta(days=1)
        if kind == "semanal":
            return start - timedelta(days=7), end - timedelta(days=7)
        if kind == "mensual":
            prev_start = _add_months(start, -1)
            prev_end = _month_end(prev_start) if end == _month_end(end) else min(_add_months(end, -1), _month_end(prev_start))
            return prev_start, prev_end
        if kind == "anual":
            return date(start.year - 1, 1, 1), _add_months(end, -12)
        length = p["days"]
        return start - timedelta(days=length), start - timedelta(days=1)

    # ------------------------------------------------------------------ cálculo
    @staticmethod
    def _figures(conn: sqlite3.Connection, start: date, end: date) -> dict:
        a, b = str(start), str(end)
        sales = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(gross_cents),0), COALESCE(SUM(discount_cents),0), COALESCE(SUM(total_cents),0),"
            " COALESCE(SUM(tax_cents),0), COALESCE(SUM(credit_cents),0) FROM sales"
            " WHERE status = 'completada' AND sale_date BETWEEN ? AND ?", (a, b)).fetchone()
        voided = conn.execute("SELECT COUNT(*), COALESCE(SUM(total_cents),0) FROM sales"
                              " WHERE status = 'anulada' AND sale_date BETWEEN ? AND ?", (a, b)).fetchone()
        returns = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(total_cents),0), COALESCE(SUM(tax_cents),0), COALESCE(SUM(refund_cents),0),"
            " COALESCE(SUM(credit_applied_cents),0) FROM sale_returns WHERE return_date BETWEEN ? AND ?", (a, b)).fetchone()

        methods: dict[int, dict] = {}

        def method(row) -> dict:
            return methods.setdefault(row["id"], {"method_id": row["id"], "name": row["name"], "kind": row["kind"],
                                                  "sales_cents": 0, "collections_cents": 0, "refunds_cents": 0, "count": 0})

        days: dict[str, dict] = {}

        def day(d: str) -> dict:
            return days.setdefault(d, {"day": d, "sales": 0, "sales_total_cents": 0, "returns_cents": 0,
                                       "received_cents": 0})

        for r in conn.execute(
                "SELECT m.id, m.name, m.kind, s.sale_date, COUNT(*) AS n, SUM(p.amount_cents) AS amount FROM sale_payments p"
                " JOIN sales s ON s.id = p.sale_id JOIN payment_methods m ON m.id = p.method_id"
                " WHERE s.status = 'completada' AND s.sale_date BETWEEN ? AND ? AND m.kind <> 'credito'"
                " GROUP BY m.id, s.sale_date", (a, b)):
            m = method(r)
            m["sales_cents"] += r["amount"]
            m["count"] += r["n"]
            day(r["sale_date"])["received_cents"] += r["amount"]
        collections_by_source = {"venta": 0, "manual": 0}
        for r in conn.execute(
                "SELECT m.id, m.name, m.kind, p.payment_date, d.source_type, COUNT(*) AS n, SUM(p.amount_cents) AS amount"
                " FROM receivable_payments p JOIN receivables d ON d.id = p.receivable_id"
                " JOIN payment_methods m ON m.id = p.method_id"
                " WHERE p.voided_at IS NULL AND p.payment_date BETWEEN ? AND ? GROUP BY m.id, p.payment_date, d.source_type",
                (a, b)):
            m = method(r)
            m["collections_cents"] += r["amount"]
            m["count"] += r["n"]
            collections_by_source[r["source_type"]] = collections_by_source.get(r["source_type"], 0) + r["amount"]
            day(r["payment_date"])["received_cents"] += r["amount"]
        for r in conn.execute(
                "SELECT m.id, m.name, m.kind, r.return_date, SUM(r.refund_cents) AS amount FROM sale_returns r"
                " JOIN payment_methods m ON m.id = r.refund_method_id"
                " WHERE r.refund_cents > 0 AND r.return_date BETWEEN ? AND ? GROUP BY m.id, r.return_date", (a, b)):
            method(r)["refunds_cents"] += r["amount"]
            day(r["return_date"])["received_cents"] -= r["amount"]
        for r in conn.execute(
                "SELECT sale_date, COUNT(*) AS n, SUM(total_cents) AS total FROM sales"
                " WHERE status = 'completada' AND sale_date BETWEEN ? AND ? GROUP BY sale_date", (a, b)):
            d = day(r["sale_date"])
            d["sales"], d["sales_total_cents"] = r["n"], r["total"]
        for r in conn.execute("SELECT return_date, SUM(total_cents) AS total FROM sale_returns"
                              " WHERE return_date BETWEEN ? AND ? GROUP BY return_date", (a, b)):
            day(r["return_date"])["returns_cents"] = r["total"]

        # Otros ingresos: asientos (no de ventas, devoluciones ni cobros) que acreditan cuentas de ingreso
        # distintas de ventas. Se registran por su valor; se consideran recibidos solo si mueven caja o bancos.
        other_registered = other_received = 0
        other_items = []
        for r in conn.execute(
                "SELECT e.id, e.entry_date, e.description, e.source_type,"
                " SUM(CASE WHEN a.type = 'ingreso' AND a.code NOT IN (?, ?) THEN l.credit_cents - l.debit_cents ELSE 0 END) AS inc,"
                " SUM(CASE WHEN a.is_cash = 1 THEN l.debit_cents - l.credit_cents ELSE 0 END) AS cash"
                " FROM journal_entries e JOIN journal_lines l ON l.entry_id = e.id JOIN accounts a ON a.id = l.account_id"
                " WHERE e.entry_date BETWEEN ? AND ? AND e.source_type NOT IN ('venta', 'devolucion', 'cobro')"
                " GROUP BY e.id HAVING inc <> 0 ORDER BY e.entry_date, e.id", (*SALE_ACCOUNTS, a, b)):
            inc, cash = r["inc"], r["cash"]
            received = min(inc, cash) if inc > 0 and cash > 0 else max(inc, cash) if inc < 0 and cash < 0 else 0
            other_registered += inc
            other_received += received
            other_items.append({"date": r["entry_date"], "description": r["description"], "registered_cents": inc,
                                "received_cents": received})
            if received:
                day(r["entry_date"])["received_cents"] += received

        journal_cash = conn.execute(
            "SELECT COALESCE(SUM(l.debit_cents - l.credit_cents), 0) FROM journal_lines l JOIN journal_entries e ON e.id = l.entry_id"
            " JOIN accounts a ON a.id = l.account_id WHERE a.is_cash = 1 AND e.entry_date BETWEEN ? AND ?"
            " AND e.source_type IN ('venta', 'devolucion', 'cobro')", (a, b)).fetchone()[0]

        sales_count, gross, discounts, sales_total, sales_tax, credit = sales
        received_sales = sum(m["sales_cents"] for m in methods.values())
        collections = sum(m["collections_cents"] for m in methods.values())
        refunds = returns[3]
        operational_cash = received_sales + collections - refunds
        by_method = sorted(methods.values(), key=lambda m: (METHOD_KINDS.index(m["kind"]) if m["kind"] in METHOD_KINDS else 9,
                                                             m["name"]))
        for m in by_method:
            m["net_cents"] = m["sales_cents"] + m["collections_cents"] - m["refunds_cents"]
        by_kind = []
        for k in METHOD_KINDS:
            rows = [m for m in by_method if m["kind"] == k]
            if rows:
                by_kind.append({"kind": k, "label": METHOD_KIND_LABELS[k], "net_cents": sum(m["net_cents"] for m in rows)})
        if other_received:
            by_kind.append({"kind": "otros_ingresos", "label": "Otros ingresos (no ventas)", "net_cents": other_received})
        summary = {
            "gross_sales_cents": gross, "discounts_cents": discounts, "sales_total_cents": sales_total,
            "returns_cents": returns[1], "returns_count": returns[0], "net_sales_cents": sales_total - returns[1],
            "net_tax_cents": sales_tax - returns[2], "credit_sales_cents": credit,
            "returns_credit_applied_cents": returns[4], "other_income_registered_cents": other_registered,
            "received_sales_cents": received_sales, "collections_cents": collections,
            "collections_from_sales_cents": collections_by_source.get("venta", 0),
            "collections_other_cents": collections - collections_by_source.get("venta", 0),
            "other_income_received_cents": other_received, "refunds_paid_cents": refunds,
            "total_received_cents": operational_cash + other_received,
            "sales_count": sales_count, "voided_count": voided[0], "voided_total_cents": voided[1],
        }
        return {"summary": summary, "by_method": by_method, "by_kind": by_kind,
                "by_day": [days[k] for k in sorted(days)], "other_income": other_items,
                "cash_check": {"operational_cents": operational_cash, "journal_cents": journal_cash,
                               "difference_cents": journal_cash - operational_cash}}

    def _build(self, conn: sqlite3.Connection, p: dict) -> dict:
        figures = self._figures(conn, p["start"], p["end"])
        s = figures["summary"]
        active = [d for d in figures["by_day"] if d["sales"] or d["received_cents"] or d["returns_cents"]]
        activity = {"sales_count": s["sales_count"],
                    "average_ticket_cents": round(s["sales_total_cents"] / s["sales_count"]) if s["sales_count"] else None,
                    "days_with_activity": len(active), "days_without_activity": p["days"] - len(active),
                    "best_day": None, "worst_day": None}
        if active:
            best = max(active, key=lambda d: (d["received_cents"], d["day"]))
            activity["best_day"] = {"day": best["day"], "received_cents": best["received_cents"]}
            if len(active) > 1:
                worst = min(active, key=lambda d: (d["received_cents"], d["day"]))
                activity["worst_day"] = {"day": worst["day"], "received_cents": worst["received_cents"]}
        prev_start, prev_end = self._previous(p)
        prev = self._figures(conn, prev_start, prev_end)["summary"]
        comparison = {"date_from": str(prev_start), "date_to": str(prev_end), "days": (prev_end - prev_start).days + 1,
                      "rows": []}
        for key, label in (("net_sales_cents", "Ventas netas"), ("total_received_cents", "Total recibido"),
                           ("sales_count", "Cantidad de ventas")):
            cur, old = s[key], prev[key]
            row = {"key": key.removesuffix("_cents"), "label": label, "is_money": key.endswith("_cents"),
                   "change_pct": None if old == 0 else str(round((cur - old) * 100 / abs(old), 1))}
            if key.endswith("_cents"):
                row.update({"current_cents": cur, "previous_cents": old, "difference_cents": cur - old})
            else:
                row.update({"current": cur, "previous": old, "difference": cur - old})
            comparison["rows"].append(row)
        comparison["previous_empty"] = not prev["sales_count"] and not prev["total_received_cents"]
        return {**figures, "activity": activity, "comparison": comparison}

    def _payload(self, conn: sqlite3.Connection, p: dict, week_start: str) -> dict:
        data = self._build(conn, p)
        hashed = {k: data[k] for k in ("summary", "by_method", "by_day", "other_income", "cash_check")}
        return {"period": {"kind": p["kind"], "kind_label": KIND_LABELS[p["kind"]], "closure": p["closure"],
                           "closure_label": CLOSURE_LABELS[p["closure"]], "date_from": str(p["start"]),
                           "date_to": str(p["end"]), "days": p["days"], "period_days": p["period_days"],
                           "natural_end": str(p["natural_end"]), "in_progress": p["in_progress"],
                           "week_start": week_start},
                "data": data, "sha256": _sha(hashed)}

    def preview(self, actor: Actor, kind: str, date_from: str | None, date_to: str | None) -> dict:
        actor.require("finanzas.ver")
        with self.db.read() as conn:
            ws = self.week_start(conn)
            p = self._period(kind, date_from, date_to, ws)
            payload = self._payload(conn, p, ws)
            payload["suggested_name"] = self._default_name(p)
            payload["same_period"] = self._same_period(conn, str(p["start"]), str(p["end"]))
            payload["generated_at"] = iso()
            return payload

    @staticmethod
    def _same_period(conn: sqlite3.Connection, start: str, end: str, exclude_root: int | None = None) -> list[dict]:
        rows = conn.execute(
            "SELECT id, number, name, closure, revision, generated_at, total_received_cents, COALESCE(root_id, id) AS root"
            " FROM financial_reports WHERE date_from = ? AND date_to = ? AND status = 'vigente' ORDER BY id",
            (start, end)).fetchall()
        return [dict(r) for r in rows if r["root"] != exclude_root]

    # ------------------------------------------------------------------ guardado e historial
    def save(self, actor: Actor, data: dict, idempotency_key: str) -> dict:
        actor.require("finanzas.ver", "finanzas.cierres")
        if not idempotency_key or not 8 <= len(idempotency_key) <= 80:
            raise ValidationError("Falta la clave de idempotencia del informe.")
        name = (data.get("name") or "").strip()
        notes = (data.get("notes") or "").strip()
        if len(name) > 160:
            raise ValidationError("Nombre demasiado largo.", {"name": "Máximo 160 caracteres."})
        if len(notes) > 4000:
            raise ValidationError("Observaciones demasiado largas.", {"notes": "Máximo 4000 caracteres."})
        with self.db.tx() as conn:
            done = conn.execute("SELECT id FROM financial_reports WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
            if done:
                return {"duplicate": True, **self._detail(conn, done[0])}
            ws = self.week_start(conn)
            p = self._period(data.get("kind") or "", data.get("date_from"), data.get("date_to"), ws)
            same = self._same_period(conn, str(p["start"]), str(p["end"]))
            if same and not data.get("allow_same_period"):
                raise ConflictError(
                    "Ya hay un informe guardado para este mismo periodo: "
                    + ", ".join(f"{r['number']} ({r['name']})" for r in same)
                    + ". Si es un cierre independiente, confirme para guardarlo también.",
                    {"same_period": ", ".join(r["number"] for r in same)})
            payload = self._payload(conn, p, ws)
            report_id = self._insert(conn, actor, p, name or self._default_name(p), payload, idempotency_key)
            if notes:
                self._insert_note(conn, actor, report_id, "general", notes, None)
            record(conn, actor, "informe.generar", "financial_report", report_id,
                   {"periodo": f"{p['start']} a {p['end']}", "tipo": p["kind"], "cierre": p["closure"],
                    "total_recibido": payload["data"]["summary"]["total_received_cents"],
                    "mismo_periodo_que": [r["number"] for r in same]})
            return {"duplicate": False, **self._detail(conn, report_id)}

    def _insert(self, conn, actor, p, name, payload, idempotency_key, revision=1, root_id=None, previous_id=None) -> int:
        s = payload["data"]["summary"]
        snapshot = json.dumps({"period": payload["period"], "data": payload["data"]}, ensure_ascii=False, sort_keys=True)
        return conn.execute(
            "INSERT INTO financial_reports(number, idempotency_key, name, kind, closure, date_from, date_to, days, period_days,"
            " in_progress, week_start, data, data_sha256, net_sales_cents, total_received_cents, sales_count, revision,"
            " root_id, previous_id, generated_by, generated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (next_number(conn, "informe"), idempotency_key, name[:160], p["kind"], p["closure"], str(p["start"]), str(p["end"]),
             p["days"], p["period_days"], int(p["in_progress"]), payload["period"]["week_start"], snapshot, payload["sha256"],
             s["net_sales_cents"], s["total_received_cents"], s["sales_count"], revision, root_id, previous_id, actor.id,
             iso())).lastrowid

    def list(self, actor: Actor, kind: str = "", date_from: str = "", date_to: str = "", q: str = "",
             include_replaced: bool = False) -> dict:
        actor.require("finanzas.ver")
        where, params = [], []
        if kind:
            if kind not in KINDS:
                raise ValidationError("Tipo de informe no válido.")
            where.append("r.kind = ?")
            params.append(kind)
        if date_from:
            where.append("r.date_to >= ?")
            params.append(str(parse_date(date_from, "Desde")))
        if date_to:
            where.append("r.date_from <= ?")
            params.append(str(parse_date(date_to, "Hasta")))
        if q.strip():
            where.append("(r.name LIKE ? ESCAPE '\\' OR r.number LIKE ? ESCAPE '\\')")
            text = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            params += [text, text]
        if not include_replaced:
            where.append("r.status = 'vigente'")
        sql = ("SELECT r.id, r.number, r.name, r.kind, r.closure, r.date_from, r.date_to, r.days, r.period_days, r.in_progress,"
               " r.generated_at, r.total_received_cents, r.net_sales_cents, r.sales_count, r.status, r.revision,"
               " COALESCE(u.full_name, u.username, '') AS generated_by_name,"
               " (SELECT COUNT(*) FROM financial_report_notes n WHERE n.report_id = r.id) AS notes_count,"
               " (SELECT COUNT(*) FROM financial_reports o WHERE o.date_from = r.date_from AND o.date_to = r.date_to"
               "   AND o.status = 'vigente' AND COALESCE(o.root_id, o.id) <> COALESCE(r.root_id, r.id)) AS same_period_count"
               " FROM financial_reports r LEFT JOIN users u ON u.id = r.generated_by"
               + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY r.date_to DESC, r.id DESC LIMIT 500")
        with self.db.read() as conn:
            items = [dict(r) for r in conn.execute(sql, params)]
        for it in items:
            it["kind_label"] = KIND_LABELS[it["kind"]]
            it["closure_label"] = CLOSURE_LABELS[it["closure"]]
            it["in_progress"] = bool(it["in_progress"])
        return {"items": items}

    def _get(self, conn: sqlite3.Connection, report_id: int) -> sqlite3.Row:
        row = conn.execute("SELECT r.*, COALESCE(u.full_name, u.username, '') AS generated_by_name FROM financial_reports r"
                           " LEFT JOIN users u ON u.id = r.generated_by WHERE r.id = ?", (report_id,)).fetchone()
        if not row:
            raise NotFoundError("Informe no encontrado.")
        return row

    def _detail(self, conn: sqlite3.Connection, report_id: int, check_changes: bool = False) -> dict:
        r = self._get(conn, report_id)
        snapshot = json.loads(r["data"])
        root = r["root_id"] or r["id"]
        revisions = [dict(x) for x in conn.execute(
            "SELECT id, number, revision, status, generated_at, total_received_cents FROM financial_reports"
            " WHERE id = ? OR root_id = ? ORDER BY revision", (root, root))]
        notes = [dict(n) for n in conn.execute(
            "SELECT n.*, COALESCE(u.full_name, u.username, '') AS author, COALESCE(v.full_name, v.username, '') AS editor"
            " FROM financial_report_notes n LEFT JOIN users u ON u.id = n.created_by LEFT JOIN users v ON v.id = n.updated_by"
            " WHERE n.report_id = ? ORDER BY n.id", (report_id,))]
        for n in notes:
            n["category_label"] = NOTE_LABELS[n["category"]]
        result = {"id": r["id"], "number": r["number"], "name": r["name"], "status": r["status"], "revision": r["revision"],
                  "generated_at": r["generated_at"], "generated_by_name": r["generated_by_name"], "sha256": r["data_sha256"],
                  "replaced_by_id": r["replaced_by_id"], "previous_id": r["previous_id"],
                  "period": snapshot["period"], "data": snapshot["data"], "notes": notes, "revisions": revisions,
                  "same_period": self._same_period(conn, r["date_from"], r["date_to"], exclude_root=root),
                  "company": self.settings.get("empresa", conn)["name"]}
        if check_changes:
            p = self._period_from_row(r)
            current = self._payload(conn, p, r["week_start"])
            result["changed"] = current["sha256"] != r["data_sha256"]
            if result["changed"]:
                old, new = snapshot["data"]["summary"], current["data"]["summary"]
                result["changes"] = [{"key": k.removesuffix("_cents"), "saved_cents": old[k], "current_cents": new[k]}
                                     for k in ("net_sales_cents", "total_received_cents", "returns_cents", "refunds_paid_cents")
                                     if old[k] != new[k]]
                if old["sales_count"] != new["sales_count"]:
                    result["changes"].append({"key": "sales_count", "saved": old["sales_count"], "current": new["sales_count"]})
        return result

    def _period_from_row(self, r: sqlite3.Row) -> dict:
        start, end = date.fromisoformat(r["date_from"]), date.fromisoformat(r["date_to"])
        natural_end = start + timedelta(days=r["period_days"] - 1)
        return {"kind": r["kind"], "start": start, "end": end, "days": r["days"], "period_days": r["period_days"],
                "natural_end": natural_end, "closure": r["closure"], "in_progress": end >= self._today()}

    def detail(self, actor: Actor, report_id: int) -> dict:
        actor.require("finanzas.ver")
        with self.db.read() as conn:
            return self._detail(conn, report_id, check_changes=True)

    def revise(self, actor: Actor, report_id: int, reason: str) -> dict:
        """Regenera el informe con los datos actuales como revisión nueva; la anterior queda intacta y reemplazada."""
        actor.require("finanzas.ver", "finanzas.cierres")
        reason = (reason or "").strip()
        if not reason:
            raise ValidationError("Indique el motivo de la revisión.", {"reason": "El motivo es obligatorio."})
        with self.db.tx() as conn:
            r = self._get(conn, report_id)
            if r["status"] != "vigente":
                raise ConflictError("Este informe ya fue reemplazado por una revisión posterior.")
            p = self._period_from_row(r)
            payload = self._payload(conn, p, r["week_start"])
            if payload["sha256"] == r["data_sha256"]:
                raise ValidationError("Las operaciones del periodo no cambiaron: no hace falta una revisión.")
            root = r["root_id"] or r["id"]
            new_id = self._insert(conn, actor, p, r["name"], payload, None, r["revision"] + 1, root, r["id"])
            conn.execute("UPDATE financial_reports SET status = 'reemplazado', replaced_by_id = ? WHERE id = ?", (new_id, r["id"]))
            for n in conn.execute("SELECT * FROM financial_report_notes WHERE report_id = ? ORDER BY id", (r["id"],)).fetchall():
                conn.execute("INSERT INTO financial_report_notes(report_id, category, body, amount_cents, copied_from_id,"
                             " created_by, created_at, updated_by, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                             (new_id, n["category"], n["body"], n["amount_cents"], n["id"], n["created_by"], n["created_at"],
                              n["updated_by"], n["updated_at"]))
            self._insert_note(conn, actor, new_id, "aclaracion",
                              f"Revisión {r['revision'] + 1} de {r['number']}: {reason[:500]}", None)
            old, new = json.loads(r["data"])["data"]["summary"], payload["data"]["summary"]
            record(conn, actor, "informe.revisar", "financial_report", new_id,
                   {"reemplaza": r["number"], "revision": r["revision"] + 1, "motivo": reason,
                    "total_recibido": {"antes": old["total_received_cents"], "despues": new["total_received_cents"]},
                    "ventas_netas": {"antes": old["net_sales_cents"], "despues": new["net_sales_cents"]}})
            return self._detail(conn, new_id)

    # ------------------------------------------------------------------ observaciones
    @staticmethod
    def _note_values(data: dict) -> tuple[str, str, int | None]:
        category = data.get("category") or "general"
        if category not in NOTE_CATEGORIES:
            raise ValidationError("Categoría no válida.", {"category": "Elija una categoría de la lista."})
        body = (data.get("body") or "").strip()
        if not body:
            raise ValidationError("Escriba la observación.", {"body": "La observación es obligatoria."})
        if len(body) > 4000:
            raise ValidationError("Observación demasiado larga.", {"body": "Máximo 4000 caracteres."})
        amount = None
        if data.get("amount") not in (None, ""):
            try:
                amount = to_cents(data["amount"])
            except (ValidationError, ValueError, TypeError, ArithmeticError):
                raise ValidationError("Importe no válido.", {"amount": "Escriba un número (ej.: -15.000)."}) from None
        return category, body, amount

    @staticmethod
    def _insert_note(conn, actor, report_id, category, body, amount) -> int:
        now = iso()
        return conn.execute("INSERT INTO financial_report_notes(report_id, category, body, amount_cents, created_by, created_at,"
                            " updated_by, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                            (report_id, category, body, amount, actor.id, now, actor.id, now)).lastrowid

    def _editable(self, conn, report_id: int) -> sqlite3.Row:
        r = self._get(conn, report_id)
        if r["status"] != "vigente":
            raise ConflictError("El informe fue reemplazado por una revisión: agregue las observaciones en la revisión vigente.")
        return r

    def add_note(self, actor: Actor, report_id: int, data: dict) -> dict:
        actor.require("finanzas.ver", "finanzas.cierres")
        category, body, amount = self._note_values(data)
        with self.db.tx() as conn:
            r = self._editable(conn, report_id)
            note_id = self._insert_note(conn, actor, report_id, category, body, amount)
            record(conn, actor, "informe.observacion_crear", "financial_report", report_id,
                   {"informe": r["number"], "observacion": note_id, "categoria": category, "texto": body, "importe": amount})
            return self._detail(conn, report_id)

    def update_note(self, actor: Actor, report_id: int, note_id: int, data: dict) -> dict:
        actor.require("finanzas.ver", "finanzas.cierres")
        category, body, amount = self._note_values(data)
        with self.db.tx() as conn:
            r = self._editable(conn, report_id)
            n = conn.execute("SELECT * FROM financial_report_notes WHERE id = ? AND report_id = ?", (note_id, report_id)).fetchone()
            if not n:
                raise NotFoundError("Observación no encontrada.")
            if data.get("version") is not None and int(data["version"]) != n["version"]:
                raise ConflictError("Otra persona modificó esta observación. Recargue e intente de nuevo.")
            conn.execute("UPDATE financial_report_notes SET category = ?, body = ?, amount_cents = ?, updated_by = ?,"
                         " updated_at = ?, version = version + 1 WHERE id = ?", (category, body, amount, actor.id, iso(), note_id))
            record(conn, actor, "informe.observacion_editar", "financial_report", report_id,
                   {"informe": r["number"], "observacion": note_id,
                    "antes": {"categoria": n["category"], "texto": n["body"], "importe": n["amount_cents"]},
                    "despues": {"categoria": category, "texto": body, "importe": amount}})
            return self._detail(conn, report_id)

    def delete_note(self, actor: Actor, report_id: int, note_id: int) -> dict:
        actor.require("finanzas.ver", "finanzas.cierres")
        with self.db.tx() as conn:
            r = self._editable(conn, report_id)
            n = conn.execute("SELECT * FROM financial_report_notes WHERE id = ? AND report_id = ?", (note_id, report_id)).fetchone()
            if not n:
                raise NotFoundError("Observación no encontrada.")
            conn.execute("DELETE FROM financial_report_notes WHERE id = ?", (note_id,))
            record(conn, actor, "informe.observacion_eliminar", "financial_report", report_id,
                   {"informe": r["number"], "observacion": note_id, "categoria": n["category"], "texto": n["body"],
                    "importe": n["amount_cents"]})
            return self._detail(conn, report_id)

    # ------------------------------------------------------------------ exportación
    def export(self, actor: Actor, report_id: int, fmt: str) -> tuple[bytes, str, str]:
        actor.require("finanzas.ver")
        from ..documents import report_export
        with self.db.read() as conn:
            report = self._detail(conn, report_id)
            empresa = self.settings.get("empresa", conn)
        safe = report["number"]
        if fmt == "pdf":
            return report_export.to_pdf(report, empresa), f"{safe}.pdf", "application/pdf"
        if fmt == "xlsx":
            return (report_export.to_xlsx(report, empresa), f"{safe}.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        raise ValidationError("Formato no válido: use pdf o xlsx.")

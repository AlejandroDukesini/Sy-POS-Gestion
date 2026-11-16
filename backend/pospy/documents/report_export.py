"""Exportación de informes financieros guardados a PDF y Excel (.xlsx).

Ambos formatos se construyen con las mismas tablas (`_tables`) a partir de la instantánea guardada
del informe: no se recalcula nada, así el archivo coincide con lo que se guardó y se ve en pantalla.
"""
from __future__ import annotations

import io
from datetime import date
from zoneinfo import ZoneInfo

from ..core.clock import parse_iso
from .simple_pdf import SimplePDF


class Money(int):
    """Importe en centavos (para que el PDF lo formatee y el Excel lo escriba como número)."""


def _fmt_money(cents: int, symbol: str) -> str:
    negative = cents < 0
    integer, frac = divmod(abs(int(cents)), 100)
    body = f"{integer:,}".replace(",", ".") + (f",{frac:02d}" if frac else "")
    return f"{'-' if negative else ''}{symbol} {body}"


def _d(value: str | None) -> str:
    if not value:
        return "—"
    y, m, d = value[:10].split("-")
    return f"{d}/{m}/{y}"


def _dt(value: str, tz: str) -> str:
    try:
        return parse_iso(value).astimezone(ZoneInfo(tz)).strftime("%d/%m/%Y %H:%M")
    except (ValueError, KeyError):
        return value


WEEKDAY = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def _day_label(value: str) -> str:
    return f"{WEEKDAY[date.fromisoformat(value).weekday()]} {_d(value)}"


def identification(report: dict, empresa: dict) -> list[tuple[str, str]]:
    p = report["period"]
    tz = empresa.get("timezone") or "America/Bogota"
    coverage = f"{p['days']} día(s)"
    if p["closure"] == "anticipado":
        coverage += f" de {p['period_days']} del periodo {p['kind_label'].lower()} (termina el {_d(p['natural_end'])})"
    rows = [
        ("Informe", f"{report['number']} · revisión {report['revision']}"),
        ("Periodo", f"Del {_d(p['date_from'])} al {_d(p['date_to'])}"),
        ("Días cubiertos", coverage),
        ("Tipo de informe", p["kind_label"]),
        ("Tipo de cierre", p["closure_label"]),
        ("Generado", _dt(report["generated_at"], tz)),
        ("Generado por", report.get("generated_by_name") or "—"),
        ("Estado", "Vigente" if report["status"] == "vigente" else "Reemplazado por una revisión posterior"),
        ("Huella de las cifras (SHA-256)", report["sha256"][:16] + "…"),
    ]
    if p["in_progress"]:
        rows.insert(3, ("Aviso", "Generado con el periodo aún en curso: operaciones posteriores no están incluidas."))
    return rows


def _tables(report: dict) -> list[dict]:
    """Tablas del informe: celdas str, int o Money (centavos)."""
    data = report["data"]
    s = data["summary"]
    a = data["activity"]
    M = Money
    tables = [
        {"key": "ventas", "title": "Ventas registradas", "headers": ["Concepto", "Valor"], "align": "lr",
         "widths": [3, 1], "rows": [
             ["Ingresos brutos por ventas (antes de descuentos)", M(s["gross_sales_cents"])],
             ["Descuentos aplicados", M(-s["discounts_cents"])],
             ["= Ventas registradas", M(s["sales_total_cents"])],
             [f"Devoluciones ({s['returns_count']})", M(-s["returns_cents"])],
             ["= Ingresos netos por ventas", M(s["net_sales_cents"])],
             ["Parte de las ventas a crédito (aún no cobrada en la venta)", M(s["credit_sales_cents"])],
             ["IVA incluido en las ventas netas", M(s["net_tax_cents"])],
             ["Otros ingresos registrados (no ventas)", M(s["other_income_registered_cents"])],
         ], "total_last": False},
        {"key": "recibido", "title": "Dinero efectivamente recibido", "headers": ["Concepto", "Valor"], "align": "lr",
         "widths": [3, 1], "rows": [
             ["Cobrado en las ventas del periodo (sin crédito)", M(s["received_sales_cents"])],
             ["Cobros de cartera (cuentas por cobrar)", M(s["collections_cents"])],
             ["Otros ingresos recibidos en caja o bancos", M(s["other_income_received_cents"])],
             ["Reembolsos pagados por devoluciones", M(-s["refunds_paid_cents"])],
             ["= Total de ingresos recibidos", M(s["total_received_cents"])],
         ], "total_last": True},
        {"key": "metodos", "title": "Desglose por método de pago",
         "headers": ["Método", "Tipo", "Ventas", "Cobros de cartera", "Reembolsos", "Neto recibido"], "align": "llrrrr",
         "widths": [2.2, 1.3, 1.5, 1.5, 1.4, 1.6],
         "rows": [[m["name"], m["kind"], M(m["sales_cents"]), M(m["collections_cents"]), M(-m["refunds_cents"]),
                   M(m["net_cents"])] for m in data["by_method"]]
         + ([["Otros ingresos (no ventas)", "asientos", M(0), M(0), M(0), M(s["other_income_received_cents"])]]
            if s["other_income_received_cents"] else [])
         + [["Total", "", M(s["received_sales_cents"]), M(s["collections_cents"]), M(-s["refunds_paid_cents"]),
             M(s["total_received_cents"])]], "total_last": True},
    ]
    stats = [["Cantidad de ventas", a["sales_count"]],
             ["Ticket promedio", M(a["average_ticket_cents"]) if a["average_ticket_cents"] is not None else "Sin ventas"],
             ["Días con movimientos", a["days_with_activity"]],
             ["Días sin movimientos", a["days_without_activity"]]]
    if a["best_day"]:
        stats.append([f"Día con mayores ingresos: {_day_label(a['best_day']['day'])}", M(a["best_day"]["received_cents"])])
    if a["worst_day"]:
        stats.append([f"Día con menores ingresos: {_day_label(a['worst_day']['day'])}", M(a["worst_day"]["received_cents"])])
    if s["voided_count"]:
        stats.append([f"Ventas anuladas (no suman): {s['voided_count']}", M(s["voided_total_cents"])])
    tables.append({"key": "actividad", "title": "Resumen de actividad", "headers": ["Indicador", "Valor"], "align": "lr",
                   "widths": [3, 1], "rows": stats, "total_last": False})
    c = data["comparison"]
    comp_rows = []
    for r in c["rows"]:
        if r["is_money"]:
            comp_rows.append([r["label"], M(r["current_cents"]), M(r["previous_cents"]), M(r["difference_cents"]),
                              f"{r['change_pct'].replace('.', ',')} %" if r["change_pct"] is not None else "—"])
        else:
            comp_rows.append([r["label"], r["current"], r["previous"], r["difference"],
                              f"{r['change_pct'].replace('.', ',')} %" if r["change_pct"] is not None else "—"])
    tables.append({"key": "comparacion",
                   "title": f"Comparación con el periodo anterior equivalente ({_d(c['date_from'])} al {_d(c['date_to'])})",
                   "headers": ["Indicador", "Este periodo", "Periodo anterior", "Diferencia", "Variación"], "align": "lrrrr",
                   "widths": [2, 1.5, 1.5, 1.5, 1], "rows": comp_rows, "total_last": False})
    tables.append({"key": "dias", "title": "Detalle de ingresos por día (solo días con movimientos)",
                   "headers": ["Día", "Ventas", "Ventas registradas", "Devoluciones", "Ingresos recibidos"], "align": "lrrrr",
                   "widths": [2, 0.8, 1.5, 1.4, 1.6],
                   "rows": [[_day_label(d["day"]), d["sales"], M(d["sales_total_cents"]), M(-d["returns_cents"]),
                             M(d["received_cents"])] for d in data["by_day"]]
                   + [["Total", s["sales_count"], M(s["sales_total_cents"]), M(-s["returns_cents"]),
                       M(s["total_received_cents"])]], "total_last": True})
    if data["other_income"]:
        tables.append({"key": "otros", "title": "Otros ingresos registrados (asientos)",
                       "headers": ["Fecha", "Descripción", "Registrado", "Recibido"], "align": "llrr", "widths": [1, 3, 1.3, 1.3],
                       "rows": [[_d(o["date"]), o["description"], M(o["registered_cents"]), M(o["received_cents"])]
                                for o in data["other_income"]], "total_last": False})
    cc = data["cash_check"]
    tables.append({"key": "verificacion", "title": "Verificación con el libro de caja y bancos", "headers": ["Concepto", "Valor"],
                   "align": "lr", "widths": [3, 1], "rows": [
                       ["Calculado desde ventas, cobros y reembolsos", M(cc["operational_cents"])],
                       ["Movimiento de caja y bancos en el libro diario (ventas, cobros y devoluciones)", M(cc["journal_cents"])],
                       ["Diferencia", M(cc["difference_cents"])]], "total_last": True})
    return tables


def _notes_rows(report: dict, tz: str) -> list[list]:
    return [[n["category_label"], n["body"], Money(n["amount_cents"]) if n["amount_cents"] is not None else "",
             n.get("author") or "", _dt(n["created_at"], tz)] for n in report["notes"]]


EXPLANATION = (
    "Ventas registradas: ventas completadas con fecha de venta en el periodo (las anuladas no suman). Dinero recibido: "
    "pagos de esas ventas con métodos distintos de crédito, más cobros de cartera y otros ingresos que entraron a caja o "
    "bancos en el periodo, menos reembolsos pagados. Cada pago se cuenta una sola vez; el cambio entregado al cliente no "
    "se suma. Las devoluciones se registran en la fecha en que ocurren.")


# ------------------------------------------------------------------ PDF
def to_pdf(report: dict, empresa: dict) -> bytes:
    symbol = empresa.get("currency_symbol") or "$"
    tz = empresa.get("timezone") or "America/Bogota"
    pdf = SimplePDF(title=report["name"])
    pdf.footer = f"{empresa.get('name') or ''} · {report['number']} · revisión {report['revision']}"[:90]

    def cell(v) -> str:
        if isinstance(v, Money):
            return _fmt_money(int(v), symbol)
        return str(v)

    pdf.paragraph(empresa.get("name") or "", 16, bold=True, gap=0)
    sub = " · ".join(x for x in (empresa.get("legal_name"), empresa.get("tax_id") and f"NIT {empresa['tax_id']}",
                                  empresa.get("city")) if x)
    if sub:
        pdf.paragraph(sub, 9, color=(0.35, 0.35, 0.35), gap=2)
    pdf.y -= 6
    pdf.paragraph(report["name"], 14, bold=True, gap=2)
    if report["period"]["closure"] == "anticipado":
        pdf.paragraph(f"CIERRE ANTICIPADO: cubre {report['period']['days']} de {report['period']['period_days']} días del "
                      f"periodo {report['period']['kind_label'].lower()}. No es un periodo completo.", 10, bold=True,
                      color=(0.6, 0.25, 0), gap=2)
    if report["status"] != "vigente":
        pdf.paragraph("Este informe fue reemplazado por una revisión posterior; se conserva por trazabilidad.", 10, bold=True,
                      color=(0.7, 0, 0), gap=2)
    pdf.table(["Identificación del cierre", ""], [[k, v] for k, v in identification(report, empresa)], [1.3, 3], ["l", "l"])
    for t in _tables(report):
        pdf.heading(t["title"], 12)
        pdf.table(t["headers"], [[cell(v) for v in r] for r in t["rows"]], t["widths"], list(t["align"]),
                  bold_last=t["total_last"])
    pdf.heading("Observaciones del administrador", 12)
    notes = _notes_rows(report, tz)
    if notes:
        pdf.table(["Categoría", "Observación", "Importe", "Autor", "Fecha"], [[cell(v) for v in r] for r in notes],
                  [1.3, 3.5, 1.1, 1.1, 1.2], list("llrll"))
    else:
        pdf.paragraph("Sin observaciones.", 10, color=(0.35, 0.35, 0.35))
    pdf.heading("Cómo se calcula", 11)
    pdf.paragraph(EXPLANATION, 8.5, color=(0.3, 0.3, 0.3))
    return pdf.output()


# ------------------------------------------------------------------ Excel
def to_xlsx(report: dict, empresa: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    tz = empresa.get("timezone") or "America/Bogota"
    symbol = empresa.get("currency_symbol") or "$"
    money_fmt = f'"{symbol}" #,##0.00;-"{symbol}" #,##0.00'
    bold = Font(bold=True)
    head_fill = PatternFill("solid", fgColor="E5E7EB")
    wb = Workbook()
    tables = {t["key"]: t for t in _tables(report)}

    def put(ws, row: int, values: list, is_bold: bool = False, fill=None) -> None:
        for col, v in enumerate(values, start=1):
            c = ws.cell(row=row, column=col)
            if isinstance(v, Money):
                c.value = int(v) / 100
                c.number_format = money_fmt
            else:
                c.value = v
                if isinstance(v, str) and v.startswith("="):
                    c.data_type = "s"  # texto escrito por una persona: nunca una fórmula
            if is_bold:
                c.font = bold
            if fill:
                c.fill = fill
            c.alignment = Alignment(vertical="top", wrap_text=isinstance(v, str) and len(v) > 40)

    def block(ws, row: int, t: dict) -> int:
        ws.cell(row=row, column=1, value=t["title"]).font = Font(bold=True, size=12)
        row += 1
        put(ws, row, t["headers"], True, head_fill)
        for i, r in enumerate(t["rows"]):
            row += 1
            put(ws, row, r, t["total_last"] and i == len(t["rows"]) - 1)
        return row + 2

    def widths(ws, values: list[int]) -> None:
        for i, w in enumerate(values, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w

    ws = wb.active
    ws.title = "Resumen"
    ws.cell(row=1, column=1, value=(empresa.get("name") or "").lstrip("=")).font = Font(bold=True, size=14)
    ws.cell(row=2, column=1, value=report["name"].lstrip("=")).font = Font(bold=True, size=12)
    row = 4
    for k, v in identification(report, empresa):
        put(ws, row, [k, v])
        ws.cell(row=row, column=1).font = bold
        row += 1
    row += 1
    for key in ("ventas", "recibido", "actividad", "comparacion", "verificacion"):
        row = block(ws, row, tables[key])
    ws.cell(row=row, column=1, value=EXPLANATION).alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
    ws.row_dimensions[row].height = 75
    widths(ws, [58, 20, 20, 20, 14])

    ws = wb.create_sheet("Detalle de ingresos")
    row = block(ws, 1, tables["dias"])
    if "otros" in tables:
        block(ws, row, tables["otros"])
    widths(ws, [24, 40, 20, 20, 20])

    ws = wb.create_sheet("Métodos de pago")
    block(ws, 1, tables["metodos"])
    widths(ws, [30, 16, 18, 20, 18, 20])

    ws = wb.create_sheet("Observaciones")
    put(ws, 1, ["Categoría", "Observación", "Importe", "Autor", "Fecha"], True, head_fill)
    notes = _notes_rows(report, tz)
    for i, r in enumerate(notes, start=2):
        put(ws, i, r)
        ws.cell(row=i, column=2).alignment = Alignment(wrap_text=True, vertical="top")
    if not notes:
        ws.cell(row=2, column=1, value="Sin observaciones.")
    widths(ws, [26, 70, 16, 22, 18])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


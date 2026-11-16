"""Finanzas › Informes: periodos, cálculos (ventas vs. dinero recibido), cierres anticipados, historial,
revisiones, observaciones, exportación PDF/Excel, persistencia e integridad de los registros originales.

Escenario con fecha simulada: «hoy» es el viernes 13/11/2026 y la semana del negocio empieza el lunes.
  30/10  venta 1 und de contado (efectivo 18.000)
  09/11  venta 2 und: efectivo 20.000 (recibe 50.000, cambio 30.000) + transferencia 16.000
  12/11  venta 1 und a crédito (18.000) · venta 1 und de contado (efectivo 18.000)
  13/11  devolución de la venta de contado del 12/11 (reembolso en efectivo 18.000)
         cobro de cartera 10.000 por transferencia · otro ingreso (asiento manual) 5.000 en caja
         venta de 1 und anulada el mismo día (no suma)
"""
from __future__ import annotations

import hashlib
import re
import zlib
from datetime import date
from io import BytesIO

import pytest
from openpyxl import load_workbook

from pospy.config import Config
from pospy.context import AppContext
from pospy.core.errors import ConflictError, PermissionDenied, ValidationError

from .conftest import EMPLOYEE_PASSWORD, key, login

MODULES = ("sales", "open_items", "finance", "financial_reports", "inventory", "documents", "reports")
TODAY = date(2026, 11, 13)


@pytest.fixture()
def clock(monkeypatch):
    import importlib

    def set_today(d: date):
        for name in MODULES:
            monkeypatch.setattr(importlib.import_module(f"pospy.services.{name}"), "local_today", lambda tz=None, d=d: d)
    set_today(TODAY)
    return set_today


def sell(ctx, actor, product, qty, payments, **extra):
    return ctx.sales.checkout(actor, {"lines": [{"product_id": product["id"], "qty": qty}], "payments": payments, **extra},
                              key())


@pytest.fixture()
def scenario(ctx, admin, product, clock, cash_id, bank_id, credit_id):
    clock(date(2026, 10, 30))
    sell(ctx, admin, product, "1", [{"method_id": cash_id, "amount": "18000"}])
    clock(date(2026, 11, 9))
    sell(ctx, admin, product, "2", [{"method_id": cash_id, "amount": "20000", "tendered": "50000"},
                                    {"method_id": bank_id, "amount": "16000"}])
    clock(date(2026, 11, 12))
    customer = ctx.catalog.save_party(admin, "clientes", {"name": "Taller Gómez", "identification": "800", "credit_days": 15})
    credit_sale = sell(ctx, admin, product, "1", [{"method_id": credit_id, "amount": "18000"}], customer_id=customer["id"])
    cash_sale = sell(ctx, admin, product, "1", [{"method_id": cash_id, "amount": "18000"}])
    clock(TODAY)
    ctx.sales.register_return(admin, cash_sale["id"], {"reason": "Defecto", "refund_method_id": cash_id,
                                                       "lines": [{"sale_line_id": cash_sale["lines"][0]["id"], "qty": "1"}]}, key())
    ctx.receivables.register_payment(admin, credit_sale["receivable"]["id"], {"amount": "10000", "method_id": bank_id}, key())
    ctx.finance.manual_entry(admin, {"description": "Arriendo de vitrina", "lines": [
        {"account_code": "1105", "debit": "5000"}, {"account_code": "4295", "credit": "5000"}]}, key())
    voided = sell(ctx, admin, product, "1", [{"method_id": cash_id, "amount": "18000"}])
    ctx.sales.void(admin, voided["id"], "Error de digitación")
    return {"cash_id": cash_id, "bank_id": bank_id}


def snapshot(ctx) -> dict:
    """Huella de todos los registros originales que un informe NO debe tocar."""
    tables = ("sales", "sale_lines", "sale_payments", "sale_returns", "sale_return_lines", "receivables", "receivable_payments",
              "receivable_credits", "payables", "payable_payments", "journal_entries", "journal_lines", "inventory_movements",
              "products", "customers")
    with ctx.db.read() as conn:
        return {t: hashlib.sha256(repr([tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY id")]).encode()).hexdigest()
                for t in tables}


def preview(ctx, admin, kind, a, b):
    return ctx.financial_reports.preview(admin, kind, a, b)


def summary(ctx, admin, kind, a, b):
    return preview(ctx, admin, kind, a, b)["data"]["summary"]


# ------------------------------------------------------------------ periodos y accesos rápidos
def test_presets_compute_ranges(ctx, admin, clock):
    p = {x["key"]: (x["kind"], x["date_from"], x["date_to"]) for x in ctx.financial_reports.presets(admin)["presets"]}
    assert p == {"ayer": ("diario", "2026-11-12", "2026-11-12"), "hoy": ("diario", "2026-11-13", "2026-11-13"),
                 "semana_actual": ("semanal", "2026-11-09", "2026-11-13"),
                 "semana_pasada": ("semanal", "2026-11-02", "2026-11-08"),
                 "mes_actual": ("mensual", "2026-11-01", "2026-11-13"), "mes_pasado": ("mensual", "2026-10-01", "2026-10-31"),
                 "anio_actual": ("anual", "2026-01-01", "2026-11-13"), "anio_pasado": ("anual", "2025-01-01", "2025-12-31")}
    # Cambio de año y de mes: «hoy» es el viernes 1/1/2027.
    clock(date(2027, 1, 1))
    p = {x["key"]: (x["date_from"], x["date_to"]) for x in ctx.financial_reports.presets(admin)["presets"]}
    assert p["ayer"] == ("2026-12-31", "2026-12-31")
    assert p["semana_actual"] == ("2026-12-28", "2027-01-01")
    assert p["semana_pasada"] == ("2026-12-21", "2026-12-27")
    assert p["mes_pasado"] == ("2026-12-01", "2026-12-31") and p["anio_pasado"] == ("2026-01-01", "2026-12-31")
    # El inicio de semana se configura en Settings (aquí: domingo).
    ctx.settings.update("informes", {"week_start": "domingo"}, admin)
    clock(TODAY)
    p = {x["key"]: (x["date_from"], x["date_to"]) for x in ctx.financial_reports.presets(admin)["presets"]}
    assert p["semana_actual"] == ("2026-11-08", "2026-11-13") and p["semana_pasada"] == ("2026-11-01", "2026-11-07")
    every = ctx.financial_reports.presets(admin)["presets"]
    for x in every:  # todos los accesos rápidos generan un informe válido
        assert preview(ctx, admin, x["kind"], x["date_from"], x["date_to"])["period"]["date_to"] == x["date_to"]


def test_period_validation_and_closure_type(ctx, admin, clock):
    fr = ctx.financial_reports
    for kind, a, b, field in (("diario", "2026-11-12", "2026-11-13", "date_to"), ("semanal", "2026-11-10", "2026-11-13", "date_from"),
                              ("semanal", "2026-11-02", "2026-11-09", "date_to"), ("mensual", "2026-11-02", "2026-11-13", "date_from"),
                              ("mensual", "2026-10-01", "2026-11-01", "date_from"), ("anual", "2026-02-01", "2026-11-13", "date_from"),
                              ("personalizado", "2026-11-13", "2026-11-12", "date_to"),
                              ("personalizado", "2026-11-01", "2026-11-14", "date_to"),
                              ("personalizado", "2026-13-01", "2026-11-12", None), ("personalizado", "", "2026-11-12", None),
                              ("personalizado", "1999-12-31", "2000-01-02", "date_from"), ("trimestral", "2026-11-01", "2026-11-02", "kind")):
        with pytest.raises(ValidationError) as err:
            fr.preview(admin, kind, a, b)
        if field:
            assert field in err.value.fields, (kind, a, b, err.value.fields)
    weekly = fr.preview(admin, "semanal", "2026-11-02", "2026-11-08")["period"]
    assert (weekly["closure"], weekly["days"], weekly["period_days"], weekly["in_progress"]) == ("habitual", 7, 7, False)
    early = fr.preview(admin, "semanal", "2026-11-09", "2026-11-13")
    assert (early["period"]["closure"], early["period"]["days"], early["period"]["period_days"]) == ("anticipado", 5, 7)
    assert early["period"]["natural_end"] == "2026-11-15"
    assert "cierre anticipado al 13 de noviembre de 2026" in early["suggested_name"]
    month = fr.preview(admin, "mensual", "2026-10-01", "2026-10-31")["period"]
    assert month["closure"] == "habitual" and month["period_days"] == 31
    assert fr.preview(admin, "mensual", "2026-11-01", "2026-11-13")["period"]["closure"] == "anticipado"
    assert fr.preview(admin, "personalizado", "2026-11-05", "2026-11-13")["period"]["closure"] == "personalizado"
    today = fr.preview(admin, "diario", "2026-11-13", "2026-11-13")["period"]
    assert today["closure"] == "habitual" and today["in_progress"] is True


# ------------------------------------------------------------------ cálculos
def test_daily_reports_yesterday_and_today(ctx, admin, scenario):
    y = summary(ctx, admin, "diario", "2026-11-12", "2026-11-12")
    assert (y["sales_count"], y["gross_sales_cents"], y["discounts_cents"], y["sales_total_cents"]) == (2, 4000000, 400000, 3600000)
    assert y["credit_sales_cents"] == 1800000 and y["received_sales_cents"] == 1800000
    assert y["returns_cents"] == 0 and y["net_sales_cents"] == 3600000 and y["total_received_cents"] == 1800000
    t = summary(ctx, admin, "diario", "2026-11-13", "2026-11-13")
    # La venta anulada no suma; la devolución se registra el día en que ocurre (hoy), no el de la venta.
    assert (t["sales_count"], t["sales_total_cents"], t["voided_count"], t["voided_total_cents"]) == (0, 0, 1, 1800000)
    assert (t["returns_cents"], t["refunds_paid_cents"], t["net_sales_cents"]) == (1800000, 1800000, -1800000)
    assert (t["collections_cents"], t["collections_from_sales_cents"]) == (1000000, 1000000)
    assert (t["other_income_registered_cents"], t["other_income_received_cents"]) == (500000, 500000)
    assert t["total_received_cents"] == 1000000 + 500000 - 1800000


def test_week_breakdown_without_double_counting(ctx, admin, scenario):
    rep = preview(ctx, admin, "semanal", "2026-11-09", "2026-11-13")
    s, data = rep["data"]["summary"], rep["data"]
    assert (s["sales_count"], s["gross_sales_cents"], s["discounts_cents"], s["sales_total_cents"]) == (3, 8000000, 800000, 7200000)
    assert (s["returns_cents"], s["net_sales_cents"]) == (1800000, 5400000)
    # Venta con dos métodos y cambio: se recibe 36.000 (no 50.000 entregados ni 36.000 dos veces).
    assert s["received_sales_cents"] == 2000000 + 1600000 + 1800000
    assert s["total_received_cents"] == 5400000 + 1000000 + 500000 - 1800000 == 5100000
    methods = {m["kind"]: m for m in data["by_method"]}
    assert (methods["efectivo"]["sales_cents"], methods["efectivo"]["refunds_cents"], methods["efectivo"]["net_cents"]) == (
        3800000, 1800000, 2000000)
    assert (methods["transferencia"]["sales_cents"], methods["transferencia"]["collections_cents"],
            methods["transferencia"]["net_cents"]) == (1600000, 1000000, 2600000)
    assert "credito" not in methods
    assert {k["kind"]: k["net_cents"] for k in data["by_kind"]} == {"efectivo": 2000000, "transferencia": 2600000,
                                                                     "otros_ingresos": 500000}
    assert sum(k["net_cents"] for k in data["by_kind"]) == s["total_received_cents"]
    # Días: solo los que tienen movimientos (no se rellenan días vacíos) y suman el total.
    assert [d["day"] for d in data["by_day"]] == ["2026-11-09", "2026-11-12", "2026-11-13"]
    assert sum(d["received_cents"] for d in data["by_day"]) == s["total_received_cents"]
    a = data["activity"]
    assert a["average_ticket_cents"] == 2400000 and a["days_with_activity"] == 3 and a["days_without_activity"] == 2
    assert a["best_day"] == {"day": "2026-11-09", "received_cents": 3600000}
    assert a["worst_day"] == {"day": "2026-11-13", "received_cents": -300000}
    # Verificación con el libro de caja: cuadra (la venta anulada y su reverso son del mismo día).
    assert data["cash_check"]["difference_cents"] == 0
    assert data["cash_check"]["operational_cents"] == data["cash_check"]["journal_cents"] == 4600000


def test_month_year_custom_and_comparison(ctx, admin, scenario):
    last_month = preview(ctx, admin, "mensual", "2026-10-01", "2026-10-31")
    assert last_month["data"]["summary"]["sales_total_cents"] == 1800000
    assert last_month["data"]["comparison"]["date_from"] == "2026-09-01" and last_month["data"]["comparison"]["date_to"] == "2026-09-30"
    cur = preview(ctx, admin, "mensual", "2026-11-01", "2026-11-13")
    assert cur["data"]["summary"]["total_received_cents"] == 5100000
    comp = cur["data"]["comparison"]
    assert (comp["date_from"], comp["date_to"]) == ("2026-10-01", "2026-10-13")  # mismo tramo del mes anterior
    assert comp["rows"][1]["previous_cents"] == 0 and comp["rows"][1]["change_pct"] is None and comp["previous_empty"]
    week = preview(ctx, admin, "semanal", "2026-11-09", "2026-11-13")["data"]["comparison"]
    assert (week["date_from"], week["date_to"]) == ("2026-11-02", "2026-11-06")  # lunes a viernes anterior
    custom = preview(ctx, admin, "personalizado", "2026-10-30", "2026-11-09")
    assert custom["data"]["summary"]["sales_total_cents"] == 1800000 + 3600000  # cruza el cambio de mes
    comp = custom["data"]["comparison"]
    assert (comp["date_from"], comp["date_to"]) == ("2026-10-19", "2026-10-29")
    year = summary(ctx, admin, "anual", "2026-01-01", "2026-11-13")
    assert year["sales_total_cents"] == 1800000 + 7200000 and year["total_received_cents"] == 1800000 + 5100000
    nov = preview(ctx, admin, "personalizado", "2026-11-09", "2026-11-13")["data"]["comparison"]["rows"][0]
    assert nov["key"] == "net_sales" and nov["previous_cents"] == 0


def test_empty_periods(ctx, admin, scenario):
    for kind, a, b in (("semanal", "2026-11-02", "2026-11-08"), ("anual", "2025-01-01", "2025-12-31")):
        rep = preview(ctx, admin, kind, a, b)
        s, act = rep["data"]["summary"], rep["data"]["activity"]
        assert s["total_received_cents"] == 0 and s["sales_count"] == 0 and rep["data"]["by_day"] == []
        assert act["average_ticket_cents"] is None and act["best_day"] is None and act["worst_day"] is None
        assert rep["data"]["by_method"] == [] and rep["data"]["cash_check"]["difference_cents"] == 0


def test_cash_difference_is_shown_not_hidden(ctx, admin, scenario, clock, product, cash_id):
    """Una venta de ayer anulada hoy: el informe de ayer ya no la cuenta, pero el libro de caja de ayer sí la tiene."""
    clock(date(2026, 11, 12))
    sale = sell(ctx, admin, product, "1", [{"method_id": cash_id, "amount": "18000"}])
    clock(TODAY)
    ctx.sales.void(admin, sale["id"], "Cliente desistió")
    check = preview(ctx, admin, "diario", "2026-11-12", "2026-11-12")["data"]["cash_check"]
    assert check["difference_cents"] == 1800000


# ------------------------------------------------------------------ guardado, historial, revisiones y observaciones
def test_save_history_duplicates_and_persistence(ctx, admin, scenario, tmp_path):
    before = snapshot(ctx)
    fr = ctx.financial_reports
    k = key()
    saved = fr.save(admin, {"kind": "semanal", "date_from": "2026-11-09", "date_to": "2026-11-13", "notes": "Cierre el viernes por festivo"}, k)
    assert saved["number"] == "INF-00001" and saved["period"]["closure"] == "anticipado" and saved["status"] == "vigente"
    assert saved["data"]["summary"]["total_received_cents"] == 5100000 and saved["generated_by_name"] == "Administradora"
    assert [n["body"] for n in saved["notes"]] == ["Cierre el viernes por festivo"]
    assert fr.save(admin, {"kind": "semanal", "date_from": "2026-11-09", "date_to": "2026-11-13"}, k)["duplicate"] is True
    with pytest.raises(ConflictError, match="INF-00001"):
        fr.save(admin, {"kind": "semanal", "date_from": "2026-11-09", "date_to": "2026-11-13"}, key())
    second = fr.save(admin, {"kind": "personalizado", "date_from": "2026-11-09", "date_to": "2026-11-13", "name": "Cierre independiente",
                             "allow_same_period": True}, key())
    assert second["number"] == "INF-00002" and [r["number"] for r in second["same_period"]] == ["INF-00001"]
    fr.save(admin, {"kind": "mensual", "date_from": "2026-10-01", "date_to": "2026-10-31"}, key())
    hist = fr.list(admin)["items"]
    assert [h["number"] for h in hist] == ["INF-00002", "INF-00001", "INF-00003"]
    assert hist[1]["same_period_count"] == 1 and hist[1]["notes_count"] == 1 and hist[1]["closure_label"] == "Cierre anticipado"
    assert [h["number"] for h in fr.list(admin, kind="mensual")["items"]] == ["INF-00003"]
    assert [h["number"] for h in fr.list(admin, date_from="2026-10-15", date_to="2026-10-20")["items"]] == ["INF-00003"]
    assert [h["number"] for h in fr.list(admin, q="independiente")["items"]] == ["INF-00002"]
    assert snapshot(ctx) == before  # guardar informes no toca ventas, pagos, caja, asientos ni inventario
    # Persistencia: otra instancia del programa sobre la misma carpeta de datos.
    again = AppContext(Config.from_env(data_dir=ctx.config.data_dir, web_dist=tmp_path / "no-dist", master_key="prueba"))
    reloaded = again.financial_reports.detail(admin, saved["id"])
    assert reloaded["data"] == saved["data"] and reloaded["changed"] is False and len(reloaded["notes"]) == 1


def test_revision_keeps_original_and_notes(ctx, admin, scenario, clock, product, cash_id):
    fr = ctx.financial_reports
    clock(date(2026, 11, 12))
    original = fr.save(admin, {"kind": "diario", "date_from": "2026-11-12", "date_to": "2026-11-12"}, key())
    fr.add_note(admin, original["id"], {"category": "diferencia_caja", "body": "Faltaron 2.000 en caja", "amount": "-2000"})
    assert fr.detail(admin, original["id"])["changed"] is False
    with pytest.raises(ValidationError, match="no cambiaron"):
        fr.revise(admin, original["id"], "Revisar")
    # Se corrige una transacción del periodo después de guardar el informe.
    sale = sell(ctx, admin, product, "1", [{"method_id": cash_id, "amount": "18000"}])
    clock(TODAY)
    d = fr.detail(admin, original["id"])
    assert d["changed"] is True and d["data"]["summary"]["total_received_cents"] == 1800000  # no se sobrescribe
    assert {c["key"] for c in d["changes"]} >= {"total_received", "net_sales", "sales_count"}
    with pytest.raises(ValidationError):
        fr.revise(admin, original["id"], "  ")
    rev = fr.revise(admin, original["id"], "Venta registrada tarde")
    assert rev["revision"] == 2 and rev["previous_id"] == original["id"] and rev["status"] == "vigente"
    assert rev["data"]["summary"]["total_received_cents"] == 3600000
    assert [n["category"] for n in rev["notes"]] == ["diferencia_caja", "aclaracion"] and rev["notes"][0]["amount_cents"] == -200000
    old = fr.detail(admin, original["id"])
    assert old["status"] == "reemplazado" and old["replaced_by_id"] == rev["id"]
    assert old["data"]["summary"]["total_received_cents"] == 1800000  # cifras originales conservadas
    assert [r["revision"] for r in old["revisions"]] == [1, 2]
    with pytest.raises(ConflictError):
        fr.revise(admin, original["id"], "otra vez")
    with pytest.raises(ConflictError):
        fr.add_note(admin, original["id"], {"body": "x"})
    assert [h["id"] for h in fr.list(admin)["items"]] == [rev["id"]]
    assert {h["id"] for h in fr.list(admin, include_replaced=True)["items"]} == {rev["id"], original["id"]}
    assert sale["status"] == "completada"
    # La base impide modificar o borrar las cifras guardadas.
    with ctx.db.tx() as conn, pytest.raises(Exception, match="revisión"):
        conn.execute("UPDATE financial_reports SET total_received_cents = 0 WHERE id = ?", (original["id"],))
    with ctx.db.tx() as conn, pytest.raises(Exception, match="no se eliminan"):
        conn.execute("DELETE FROM financial_reports WHERE id = ?", (original["id"],))


def test_notes_crud_and_audit(ctx, admin, scenario):
    fr = ctx.financial_reports
    rep = fr.save(admin, {"kind": "diario", "date_from": "2026-11-13", "date_to": "2026-11-13"}, key())
    with pytest.raises(ValidationError):
        fr.add_note(admin, rep["id"], {"body": "  "})
    with pytest.raises(ValidationError):
        fr.add_note(admin, rep["id"], {"category": "otra", "body": "x"})
    with pytest.raises(ValidationError):
        fr.add_note(admin, rep["id"], {"body": "x", "amount": "abc"})
    r = fr.add_note(admin, rep["id"], {"category": "incidencia", "body": "Se fue la luz 2 horas"})
    note = r["notes"][0]
    r = fr.update_note(admin, rep["id"], note["id"], {"category": "extraordinaria", "body": "Corte de luz de 2 horas",
                                                     "version": note["version"]})
    assert r["notes"][0]["category"] == "extraordinaria" and r["notes"][0]["version"] == 2
    with pytest.raises(ConflictError):
        fr.update_note(admin, rep["id"], note["id"], {"body": "viejo", "version": 1})
    r = fr.delete_note(admin, rep["id"], note["id"])
    assert r["notes"] == []
    with ctx.db.read() as conn:
        actions = [x[0] for x in conn.execute("SELECT action FROM audit_log WHERE entity = 'financial_report' ORDER BY id")]
        deleted = conn.execute("SELECT details FROM audit_log WHERE action = 'informe.observacion_eliminar'").fetchone()[0]
    assert actions == ["informe.generar", "informe.observacion_crear", "informe.observacion_editar", "informe.observacion_eliminar"]
    assert "Corte de luz" in deleted


# ------------------------------------------------------------------ exportación
def _pdf_text(content: bytes) -> str:
    assert content.startswith(b"%PDF-1.4") and content.rstrip().endswith(b"%%EOF")
    xref = int(re.search(rb"startxref\n(\d+)", content).group(1))
    assert content[xref:xref + 4] == b"xref"
    count = int(re.search(rb"xref\n0 (\d+)", content).group(1))
    offsets = re.findall(rb"(\d{10}) 00000 n ", content[xref:])
    assert len(offsets) == count - 1
    for n, off in enumerate(offsets, start=1):
        assert content[int(off):int(off) + len(f"{n} 0 obj")] == f"{n} 0 obj".encode()
    text = b""
    for m in re.finditer(rb"stream\n(.*?)\nendstream", content, re.S):
        text += zlib.decompress(m.group(1))
    return b" ".join(re.findall(rb"\((.*?)\) Tj", text)).decode("cp1252")


def test_export_pdf_and_excel(ctx, admin, scenario):
    fr = ctx.financial_reports
    ctx.settings.update("empresa", {"name": "Ferretería El Tornillo", "tax_id": "900123"}, admin)
    rep = fr.save(admin, {"kind": "semanal", "date_from": "2026-11-09", "date_to": "2026-11-13",
                          "notes": "Cierre anticipado por festivo"}, key())
    fr.add_note(admin, rep["id"], {"category": "diferencia_caja", "body": "=SUMA(A1) sobrante", "amount": "1500"})
    before = snapshot(ctx)
    pdf, name, mime = fr.export(admin, rep["id"], "pdf")
    assert name == "INF-00001.pdf" and mime == "application/pdf"
    text = _pdf_text(pdf)
    for expected in ("Ferretería El Tornillo", "CIERRE ANTICIPADO", "5 de 7 días", "Del 09/11/2026 al 13/11/2026",
                     "Total de ingresos recibidos", "$ 51.000", "Transferencia", "Ticket promedio", "$ 24.000",
                     "Cierre anticipado por festivo", "Diferencia de caja", "Comparación con el periodo anterior",
                     "Administradora", "Verificación con el libro de caja"):
        assert expected in text, expected
    xlsx, name, _ = fr.export(admin, rep["id"], "xlsx")
    assert name == "INF-00001.xlsx"
    wb = load_workbook(BytesIO(xlsx))
    assert wb.sheetnames == ["Resumen", "Detalle de ingresos", "Métodos de pago", "Observaciones"]
    values = [c for row in wb["Resumen"].iter_rows(values_only=True) for c in row if c is not None]
    assert "Ferretería El Tornillo" in values and 51000 in values and "Cierre anticipado" in values
    days = [r for r in wb["Detalle de ingresos"].iter_rows(values_only=True)]
    total = next(r for r in days if r[0] == "Total")
    assert days[2][0] == "lunes 09/11/2026" and total[4] == 51000
    assert days[-1][1] == "Arriendo de vitrina" and days[-1][3] == 5000  # hoja de otros ingresos
    methods = [r for r in wb["Métodos de pago"].iter_rows(values_only=True)]
    assert methods[-1][0] == "Total" and methods[-1][5] == 51000
    notes = [r for r in wb["Observaciones"].iter_rows(values_only=True)]
    assert notes[2][1] == "=SUMA(A1) sobrante" and notes[2][2] == 1500  # texto, no fórmula
    assert wb["Observaciones"]["B3"].data_type == "s"
    with pytest.raises(ValidationError):
        fr.export(admin, rep["id"], "docx")
    assert snapshot(ctx) == before


# ------------------------------------------------------------------ API y permisos
def test_api_flow_and_permissions(client, ctx, admin, employee, scenario):
    login(client)
    presets = client.get("/api/finance/reports/presets").json()
    assert presets["week_start"] == "lunes" and len(presets["presets"]) == 8
    body = {"kind": "semanal", "date_from": "2026-11-09", "date_to": "2026-11-13"}
    pv = client.post("/api/finance/reports/preview", json=body).json()
    assert pv["data"]["summary"]["total_received"] == "51000.00" and pv["period"]["closure"] == "anticipado"
    assert client.post("/api/finance/reports", json=body).status_code == 422  # sin Idempotency-Key
    r = client.post("/api/finance/reports", json=body, headers={"Idempotency-Key": key()})
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    dup = client.post("/api/finance/reports", json=body, headers={"Idempotency-Key": key()})
    assert dup.status_code == 409 and "INF-00001" in dup.json()["detail"]
    assert client.post("/api/finance/reports", json={**body, "allow_same_period": True},
                       headers={"Idempotency-Key": key()}).status_code == 200
    assert len(client.get("/api/finance/reports").json()["items"]) == 2
    assert client.get("/api/finance/reports?kind=semanal&date_from=2026-11-10").json()["items"][0]["total_received"] == "51000.00"
    n = client.post(f"/api/finance/reports/{rid}/notes", json={"category": "aclaracion", "body": "ok"}).json()
    assert n["notes"][0]["category_label"] == "Aclaración sobre ingresos"
    pdf = client.get(f"/api/finance/reports/{rid}/export/pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert 'filename="INF-00001.pdf"' in pdf.headers["content-disposition"]
    assert client.get(f"/api/finance/reports/{rid}/export/xlsx").status_code == 200
    assert client.get("/api/finance/reports/999").status_code == 404
    assert client.get("/api/finance/ar").status_code == 200  # la ruta existente de cartera sigue funcionando
    # Empleado sin permisos de finanzas: nada. Con «finanzas.ver»: consulta, pero no guarda ni anota.
    client.cookies.clear()
    login(client, "empleado", EMPLOYEE_PASSWORD)
    assert client.get("/api/finance/reports").status_code == 403
    assert client.post("/api/finance/reports/preview", json=body).status_code == 403
    ctx.users.update(admin, employee.id, {"permissions": ["finanzas.ver"]})
    login(client, "empleado", EMPLOYEE_PASSWORD)
    assert client.get(f"/api/finance/reports/{rid}").status_code == 200
    assert client.post("/api/finance/reports", json={**body, "allow_same_period": True},
                       headers={"Idempotency-Key": key()}).status_code == 403
    assert client.post(f"/api/finance/reports/{rid}/notes", json={"body": "x"}).status_code == 403
    ctx.users.update(admin, employee.id, {"permissions": ["finanzas.ver", "finanzas.cierres"]})
    login(client, "empleado", EMPLOYEE_PASSWORD)
    assert client.post(f"/api/finance/reports/{rid}/notes", json={"body": "x"}).status_code == 200
    with pytest.raises(PermissionDenied):
        ctx.financial_reports.list(employee)  # actor antiguo, sin permisos


def test_settings_week_start_is_validated(ctx, admin):
    with pytest.raises(ValidationError):
        ctx.settings.update("informes", {"week_start": "feriado"}, admin)
    assert ctx.settings.get("informes")["week_start"] == "lunes"

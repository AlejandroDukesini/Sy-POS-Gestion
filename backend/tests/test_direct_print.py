"""Impresión directa en impresoras de Windows (sin Excel), documentos sin Microsoft Excel, datos opcionales,
descuento máximo de 20 % e impresora predeterminada configurable."""
from __future__ import annotations

import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import openpyxl
import pytest

from pospy.core.errors import ValidationError
from pospy.documents import engine
from pospy.documents import templates as legacy
from pospy.documents.layout_pdf import page_count, render_pdf
from pospy.documents.layout_xlsx import write_xlsx
from pospy.printing.printers import list_printers

from .conftest import key
from .test_canvas import _png

DOCS = Path(__file__).resolve().parents[2] / "docs"
COT = DOCS / "COTIZACIÓNv3.7.2.xlsm"


@pytest.fixture()
def printed(monkeypatch):
    """Sustituye la impresora real: registra lo que se habría impreso."""
    calls = []

    def fake(final, images, printer, copies=1, title="", output_file=None):
        calls.append({"final": final, "images": images, "printer": printer, "copies": copies, "title": title})
        return {"printer": printer, "copies": copies, "pages": 1}
    monkeypatch.setattr("pospy.printing.gdi.print_layout", fake)
    monkeypatch.setattr("pospy.services.documents.print_layout", fake)
    return calls


def _values(final: dict) -> list:
    return [c.get("v") for c in final["cells"].values() if c.get("v") not in (None, "")]


def test_any_missing_data_never_breaks_a_template():
    """Todos los datos son opcionales: vacíos o ausentes, la plantilla se genera igual (PDF y Excel)."""
    keys = [k for g in engine.FIELDS.values() for k in g]
    n = len(keys)
    layout = {"cols": [20], "rows": [15] * (n + 1), "cells": {f"A{i + 1}": {"v": "", "s": 1} for i in range(n + 1)},
              "styles": [{}, {"fmt": "dd/mm/yyyy"}], "merges": [], "images": [], "page": {"paper": "letter"}}
    bindings = {"cells": {f"A{i + 1}": {"field": k} for i, k in enumerate(keys)}}
    bindings["cells"][f"A{n + 1}"] = {"expr": "total"}
    for data in (engine.DocData(header={}, lines=[]), engine.DocData(header={k: None for k in keys}, lines=[{}])):
        final, totals = engine.render(layout, bindings, data)
        assert totals["total"] == 0
        assert render_pdf(final)[0].startswith(b"%PDF") and write_xlsx(final, {}, "x")[:2] == b"PK"


def test_sales_discount_max_is_20_percent(ctx, admin, product, cash_id):
    assert ctx.settings.get("ventas")["max_manual_discount_pct"] == 20
    ok = ctx.sales.checkout(admin, {"lines": [{"product_id": product["id"], "qty": "1", "discount_pct": "20"}],
                                    "payments": [{"method_id": cash_id, "amount": "14400"}]}, key())
    assert ok["discount_cents"] > 0
    with pytest.raises(ValidationError, match="20 %"):
        ctx.sales.checkout(admin, {"lines": [{"product_id": product["id"], "qty": "1", "discount_pct": "21"}],
                                   "payments": [{"method_id": cash_id, "amount": "18000"}]}, key())


def test_migration_moves_factory_discount_to_20(ctx, admin):
    from pospy.migrations import v014_printers
    with ctx.db.tx() as conn:
        conn.execute("INSERT INTO settings(key, value, updated_at) VALUES ('ventas', ?, '') ON CONFLICT(key) DO UPDATE"
                     " SET value = excluded.value", ('{"max_manual_discount_pct": 10, "prices_include_tax": true}',))
        conn.execute(v014_printers.DISCOUNT_SQL)
    assert ctx.settings.get("ventas")["max_manual_discount_pct"] == 20
    ctx.settings.update("ventas", {"max_manual_discount_pct": 15}, admin)
    with ctx.db.tx() as conn:
        conn.execute(v014_printers.DISCOUNT_SQL)
    assert ctx.settings.get("ventas")["max_manual_discount_pct"] == 15        # un valor elegido se respeta


def _sale_template(ctx, admin, kind="recibo", printer=""):
    t = ctx.print_templates.create_blank(admin, {"name": f"Plantilla {kind}", "kind": kind, "designer": "canvas"})
    ctx.print_templates.save(admin, t["public_id"], {"layout": t["layout"], "bindings": {}, "activate": True})
    ctx.print_templates.update_meta(admin, t["public_id"], {"is_default": True, "printer": printer})
    return t


def test_direct_print_sale_with_template_and_printer_priority(ctx, admin, employee, product, cash_id, printed):
    t = _sale_template(ctx, admin, "venta")
    sale = ctx.sales.checkout(admin, {"lines": [{"product_id": product["id"], "qty": "2"}],
                                      "payments": [{"method_id": cash_id, "amount": "36000"}]}, key())
    ctx.settings.update("impresion", {"default_printer": "Laser Oficina"}, admin)
    out = ctx.print_templates.render_sale(admin, sale["id"], kind="venta", fmt="print", copies=2)
    assert out["printer"] == "Laser Oficina" and printed[-1]["copies"] == 2           # predeterminada de Configuración
    assert "Martillo de uña" in _values(printed[-1]["final"])                         # datos reales de la venta
    ctx.print_templates.update_meta(admin, t["public_id"], {"printer": "Termica Caja"})
    assert ctx.print_templates.render_sale(admin, sale["id"], kind="venta", fmt="print")["printer"] == "Termica Caja"
    assert ctx.print_templates.render_sale(admin, sale["id"], kind="venta", fmt="print", printer="Otra")["printer"] == "Otra"
    with ctx.db.read() as conn:
        jobs = conn.execute("SELECT printer, mode, status FROM print_jobs WHERE target_type = 'venta' ORDER BY id").fetchall()
    assert [tuple(j) for j in jobs] == [("Laser Oficina", "directa", "ok"), ("Termica Caja", "directa", "ok"), ("Otra", "directa", "ok")]
    assert ctx.print_templates.get(admin, t["public_id"])["printer"] == "Termica Caja"
    with pytest.raises(Exception):                                                 # el empleado no configura impresoras
        ctx.print_templates.update_meta(employee, t["public_id"], {"printer": "X"})


def test_print_error_is_logged_and_reported(ctx, admin, product, cash_id, monkeypatch):
    from pospy.printing.printers import PrintError

    def broken(*args, **kwargs):
        raise PrintError("La impresora está desconectada.")
    monkeypatch.setattr("pospy.printing.gdi.print_layout", broken)
    _sale_template(ctx, admin, "venta", printer="Termica")
    sale = ctx.sales.checkout(admin, {"lines": [{"product_id": product["id"], "qty": "1"}],
                                      "payments": [{"method_id": cash_id, "amount": "18000"}]}, key())
    with pytest.raises(PrintError, match="desconectada"):
        ctx.print_templates.render_sale(admin, sale["id"], kind="venta", fmt="print")
    with ctx.db.read() as conn:
        assert conn.execute("SELECT status, error FROM print_jobs").fetchone()["status"] == "error"


def test_pos_receipt_in_template_mode(ctx, admin, product, cash_id, printed):
    from pospy.printing.printers import PrintError
    ctx.settings.update("impresion", {"receipt_mode": "plantilla", "default_printer": "Cualquiera"}, admin)
    sale = ctx.sales.checkout(admin, {"lines": [{"product_id": product["id"], "qty": "1"}],
                                      "payments": [{"method_id": cash_id, "amount": "18000"}]}, key())
    with pytest.raises(PrintError, match="plantilla de recibo"):
        ctx.printing.print_receipt(admin, sale["id"])
    _sale_template(ctx, admin, "recibo")
    out = ctx.printing.print_receipt(admin, sale["id"], 1)
    assert out["mode"] == "plantilla" and out["printer"] == "Cualquiera" and out["template"] == "Plantilla recibo"


def test_documents_use_template_engine_without_excel(ctx, admin, product, printed):
    with ctx.db.read() as conn:
        types = {r["code"]: r["id"] for r in conn.execute("SELECT id, code FROM document_types")}
    t = ctx.print_templates.create_blank(admin, {"name": "Cotización", "kind": "documento", "designer": "canvas",
                                                 "document_type_id": types["cotizacion"]})
    ctx.print_templates.save(admin, t["public_id"], {"layout": t["layout"], "bindings": {}, "activate": True})
    ctx.print_templates.update_meta(admin, t["public_id"], {"is_default": True})
    doc = ctx.documents.create(admin, {"type_id": types["cotizacion"], "customer_name": "Taller Ruiz",
                                       "lines": [{"product_id": product["id"], "qty": "3"}]}, key())
    pv = ctx.documents.preview(admin, doc["id"])
    assert pv["engine"] == "plantilla" and pv["template"] == "Cotización"
    pdf, meta = ctx.print_templates.document_preview(admin, doc["id"])
    assert pdf.startswith(b"%PDF") and meta["pages"] == 1
    assert not ctx.print_templates.outputs(admin, "documento", doc["id"])          # la vista previa no registra emisión
    xlsx = ctx.documents.generate(admin, doc["id"])
    ws = openpyxl.load_workbook(xlsx).active
    assert "Taller Ruiz" in [c.value for r in ws.iter_rows() for c in r]
    assert ctx.documents.pdf(admin, doc["id"]).read_bytes().startswith(b"%PDF")
    ctx.settings.update("impresion", {"default_printer": "Laser"}, admin)
    assert ctx.documents.print(admin, doc["id"])["printer"] == "Laser"
    assert "Taller Ruiz" in _values(printed[-1]["final"])


def test_legacy_excel_with_images_and_macros_filled_without_excel(tmp_path):
    """Plantillas de «Tipos de documento» con imágenes/macros: antes exigían Microsoft Excel. Ahora se rellenan
    escribiendo solo las celdas del XML; dibujos, macros y fórmulas se conservan."""
    cells = {"A1": {"v": "COTIZACIÓN"}, "B2": {"v": "{{numero}}"}, "B3": {"v": "{{cliente_nombre}}"},
             "A5": {"v": "{{linea.cantidad}}"}, "B5": {"v": "{{linea.descripcion}}"}, "C5": {"v": "{{linea.total}}"},
             "C10": {"v": "{{total}}"}}
    tpl = tmp_path / "plantilla.xlsx"
    tpl.write_bytes(write_xlsx({"cols": [10, 30, 12], "rows": [15] * 10, "cells": cells, "styles": [{}], "merges": [],
                                "images": [{"file": "logo.png", "row": 0, "col": 2, "w": 30, "h": 15}], "page": {}},
                               {"logo.png": _png(20, 10)}, "Cotización"))
    from pospy.documents.excel_safety import unsupported_parts
    assert unsupported_parts(tpl)                                              # antes: «se necesita Microsoft Excel»
    m = legacy.scan(tpl, set())
    assert m.fields["numero"] == "B2" and m.line_row == 5
    header = {"numero": "COT-9", "cliente_nombre": "ACME & <Hijos>", "total": 30.0}
    lines = [{"cantidad": 1.0, "descripcion": "Uno", "total": 10.0}, {"cantidad": 2.0, "descripcion": "=Dos", "total": 20.0}]
    m.capacity = 4
    out = tmp_path / "salida.xlsx"
    legacy.render(tpl, m, out, header, lines, {"paper": "letter", "margins_cm": 1, "fit_width": True})
    names = zipfile.ZipFile(out).namelist()
    assert any(n.startswith("xl/media/") for n in names) and any(n.startswith("xl/drawings/") for n in names)
    ws2 = openpyxl.load_workbook(out).active
    assert (ws2["B2"].value, ws2["B3"].value, ws2["B6"].value, ws2["C6"].value) == ("COT-9", "ACME & <Hijos>", "=Dos", 20)
    assert ws2["B6"].data_type == "s"                                         # un texto con «=» no se vuelve fórmula
    assert ws2.page_setup.paperSize in (1, "1") and ws2.sheet_properties.pageSetUpPr.fitToPage
    final, images = legacy.render_layout(tpl, m, header, lines, {"paper": "a4"})
    assert final["page"]["paper"] == "a4" and "ACME & <Hijos>" in _values(final) and images
    assert page_count(render_pdf(final, images)[0]) == 1


@pytest.mark.skipif(not COT.exists(), reason="Excel de referencia no disponible en docs/")
def test_real_cotizacion_xlsm_legacy_fill_keeps_drawing_and_macros(tmp_path):
    tpl = tmp_path / "cot.xlsm"
    legacy.write_cells_xml(COT, tpl, "Hoja1", {"A15": "{{linea.cantidad}}", "C15": "{{linea.descripcion}}",
                                               "E15": "{{linea.total}}", "B9": "N° {{numero}}"})
    m = legacy.scan(tpl, set())
    m.fields.update({"cliente_nombre": "B8", "total": "E29"})
    m.manual += ["cliente_nombre", "total"]
    out = tmp_path / "salida.xlsm"
    legacy.render(tpl, m, out, {"numero": "COT-7", "cliente_nombre": "TALLER", "total": 50.0},
                  [{"cantidad": 1.0, "descripcion": "ANILLO", "total": 50.0}], {})
    names = zipfile.ZipFile(out).namelist()
    assert "xl/vbaProject.bin" in names and any(n.startswith("xl/drawings/") for n in names) and "xl/calcChain.xml" not in names
    ws = openpyxl.load_workbook(out, keep_vba=True)["Hoja1"]
    assert (ws["B8"].value, ws["B9"].value, ws["C15"].value) == ("TALLER", "N° COT-7", "ANILLO")


def _pdf_printer() -> str | None:
    if sys.platform != "win32":
        return None
    names = [p["name"] for p in list_printers()["printers"]]
    return "Microsoft Print to PDF" if "Microsoft Print to PDF" in names else None


@pytest.mark.skipif(_pdf_printer() is None, reason="Requiere Windows con «Microsoft Print to PDF»")
def test_gdi_prints_template_on_a_real_windows_printer(tmp_path):
    from pospy.documents.canvas import compile_canvas, default_canvas, sanitize_canvas
    from pospy.printing.gdi import print_layout
    layout, bindings, _ = compile_canvas(sanitize_canvas(default_canvas("roll80"), set()))
    data = engine.demo_data(25)
    data.demo = False
    final, _ = engine.render(layout, bindings, data)
    out = Path(tempfile.gettempdir()) / f"pospy-gdi-{os.getpid()}.pdf"
    out.unlink(missing_ok=True)
    result = print_layout(final, {}, "Microsoft Print to PDF", 1, "Prueba POS", str(out))
    for _ in range(20):
        if out.exists() and out.stat().st_size > 1000:
            break
        time.sleep(0.5)
    assert result["printer"] == "Microsoft Print to PDF" and out.read_bytes()[:4] == b"%PDF"
    out.unlink(missing_ok=True)


def test_legacy_template_without_optional_fields_still_generates(tmp_path):
    """«Válido hasta», «Elaborado por», número… ninguno es obligatorio: sin casilla, simplemente no se imprimen."""
    tpl = tmp_path / "simple.xlsx"
    tpl.write_bytes(write_xlsx({"cols": [20, 20], "rows": [15] * 3, "cells": {"A1": {"v": "Cliente: {{cliente_nombre}}"}},
                               "styles": [{}], "merges": [], "images": [], "page": {}}, {}, "Hoja"))
    m = legacy.scan(tpl, set())
    assert legacy.validate(tpl, m) == [] and not m.line_row
    out = tmp_path / "salida.xlsx"
    legacy.render(tpl, m, out, {"cliente_nombre": "ACME", "fecha_validez": "", "vendedor": ""},
                  [{"cantidad": 1.0, "descripcion": "X"}], {})
    assert openpyxl.load_workbook(out).active["A1"].value == "Cliente: ACME"

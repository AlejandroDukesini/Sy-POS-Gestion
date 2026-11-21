"""Plantillas de lienzo (editor visual): compilación, papeles, productos dinámicos, PDF, Excel real,
protección contra fórmulas, imágenes, guardar y reabrir (prompt 8)."""
from __future__ import annotations

import io
import zipfile

import openpyxl
import pytest

from pospy.core.errors import ValidationError
from pospy.documents import engine
from pospy.documents.canvas import compile_canvas, default_canvas, sanitize_canvas
from pospy.documents.layout_pdf import page_count, render_pdf
from pospy.documents.layout_xlsx import write_xlsx

from .conftest import key

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360f8cfc0000003010100c9fe92ef0000000049454e44ae426082")


def _final(canvas: dict, lines: int, **header):
    layout, bindings, notes = compile_canvas(sanitize_canvas(canvas, {"img-logo.png"}))
    data = engine.demo_data(lines)
    data.demo = False
    data.header.update(header)
    return engine.render(layout, bindings, data)


@pytest.mark.parametrize("paper", ["roll80", "roll58", "a4", "letter", "custom"])
def test_papers_short_and_long_documents(paper):
    c = default_canvas(paper)
    if paper == "custom":
        c["page"].update(width_mm=100, height_mm=150, auto_height=False)
    for n in (1, 60):
        final, totals = _final(c, n)
        pdf, _ = render_pdf(final, {})
        assert pdf.startswith(b"%PDF")
        pages = page_count(pdf)
        if paper.startswith("roll"):
            assert pages == 1                                   # rollo: una tira continua que crece
        elif n == 60:
            assert pages > 1                                    # hoja fija: varias páginas sin cortar filas
        expected = sum((ln["valor"] for ln in engine.compute(engine.demo_data(n), "0")[0]), start=type(totals["total"])(0))
        assert totals["total"] == expected


def test_excel_is_real_keeps_layout_images_and_blocks_formulas():
    c = default_canvas()
    c["elements"].append({"id": "logo", "type": "image", "x": 20, "y": 80, "w": 30, "h": 30, "z": 99,
                          "image": {"file": "img-logo.png", "keep_ratio": True}})
    final, _ = _final(c, 30, cliente_nombre='=HYPERLINK("http://x","y")')
    data = write_xlsx(final, {"img-logo.png": PNG}, "Recibo")
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert "xl/drawings/drawing1.xml" in names and any(n.startswith("xl/media/") for n in names)   # imagen incrustada
    ws = openpyxl.load_workbook(io.BytesIO(data)).active
    values = [c.value for r in ws.iter_rows() for c in r if c.value is not None]
    assert "PRODUCTO DEMO 30" in values and any("HYPERLINK" in str(v) for v in values)
    sheet = zipfile.ZipFile(io.BytesIO(data)).read("xl/worksheets/sheet1.xml").decode()
    assert "<f>" not in sheet                                   # ningún texto quedó como fórmula
    assert ws.merged_cells.ranges and ws.print_area and ws.sheet_view.showGridLines is False
    assert ws.page_setup.fitToWidth == 1                        # rollo: todo el ancho en una página


def test_invalid_canvas_is_rejected():
    c = default_canvas()
    c["elements"].append({"id": "x", "type": "variable", "x": 1, "y": 1, "w": 10, "h": 5, "field": "inventado"})
    c["elements"].append({"id": "t2", "type": "table", "x": 1, "y": 90, "w": 50, "h": 10, "table": {"columns": []}})
    with pytest.raises(Exception) as exc:
        sanitize_canvas(c, set())
    text = str(exc.value)
    assert "inventado" in text and ("una tabla" in text or "columna" in text)


def test_service_canvas_save_reopen_preview_and_sale_excel(ctx, admin, product, cash_id):
    t = ctx.print_templates.create_blank(admin, {"name": "Recibo lienzo", "kind": "venta", "designer": "canvas"})
    assert t["designer"] == "canvas" and not t["problems"]
    layout = t["layout"]
    layout["page"].update(paper="roll58", width_mm=58)
    layout["elements"][0]["text"]["size"] = 15
    with pytest.raises(ValidationError):
        ctx.print_templates.save(admin, t["public_id"], {"layout": {**layout, "elements": [{"type": "nada"}]}, "bindings": {}})
    saved = ctx.print_templates.save(admin, t["public_id"], {"layout": layout, "bindings": {}, "activate": True})
    again = ctx.print_templates.get(admin, t["public_id"])
    assert again["layout"]["page"]["paper"] == "roll58" and again["layout"]["elements"][0]["text"]["size"] == 15
    assert saved["loaded_version"] == 2
    pdf, meta = ctx.print_templates.preview(admin, t["public_id"], {"lines": 40})
    assert pdf.startswith(b"%PDF") and meta["pages"] == 1
    xlsx, name = ctx.print_templates.preview_xlsx(admin, t["public_id"], {"lines": 5})
    assert xlsx[:2] == b"PK" and name.endswith(".xlsx")
    ctx.print_templates.update_meta(admin, t["public_id"], {"is_default": True})
    sale = ctx.sales.checkout(admin, {"lines": [{"product_id": product["id"], "qty": "2"}],
                                      "payments": [{"method_id": cash_id, "amount": "36000"}]}, key())
    out = ctx.print_templates.render_sale(admin, sale["id"], fmt="xlsx")
    ws = openpyxl.load_workbook(io.BytesIO(out["xlsx"])).active
    values = [c.value for r in ws.iter_rows() for c in r if c.value is not None]
    assert "Martillo de uña" in values and 36000 in values      # datos reales de la venta, total calculado
    assert ctx.print_templates.render_sale(admin, sale["id"])["pages"] == 1

"""Plantillas de lienzo (editor visual): compilación, papeles, productos dinámicos, PDF, Excel real,
protección contra fórmulas, imágenes, guardar y reabrir (prompt 8)."""
from __future__ import annotations

import io
import zipfile

import openpyxl
import pytest

from pospy.core.errors import NotFoundError, PermissionDenied, ValidationError
from pospy.documents import engine
from pospy.documents.canvas import compile_canvas, default_canvas, sanitize_canvas
from pospy.documents.layout import LayoutError
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


def test_thermal_printable_width_is_real_and_configurable():
    c = sanitize_canvas(default_canvas("roll80"), set())
    assert c["page"]["printable_width_mm"] == 72 and c["page"]["margins"]["l"] == 4      # no se asume 80 mm útiles
    assert all(e["x"] >= 4 and e["x"] + e["w"] <= 76.01 for e in c["elements"])
    raw = default_canvas("roll80")
    raw["page"]["printable_width_mm"] = 64
    c = sanitize_canvas(raw, set())
    assert c["page"]["margins"]["l"] == c["page"]["margins"]["r"] == 8
    raw["page"]["printable_width_mm"] = 5
    with pytest.raises(LayoutError):
        sanitize_canvas(raw, set())
    assert sanitize_canvas(default_canvas("roll58"), set())["page"]["printable_width_mm"] == 48


def test_real_sale_preview_payment_method_template_export_and_logo(ctx, admin, product, cash_id, tmp_path):
    t = ctx.print_templates.create_blank(admin, {"name": "Recibo pago", "kind": "venta", "designer": "canvas", "paper": "roll58"})
    layout = t["layout"]
    assert layout["page"]["paper"] == "roll58"
    layout["elements"].append({"id": "pm", "type": "variable", "x": 5, "y": 90, "w": 48, "h": 5, "field": "metodo_pago",
                               "text": {"size": 8}})
    ctx.print_templates.save(admin, t["public_id"], {"layout": layout, "bindings": {}, "activate": True})
    sale = ctx.sales.checkout(admin, {"lines": [{"product_id": product["id"], "qty": "1"}],
                                      "payments": [{"method_id": cash_id, "amount": "18000"}]}, key())
    with ctx.db.read() as conn:
        before = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        stock = conn.execute("SELECT stock_milli FROM products WHERE id = ?", (product["id"],)).fetchone()[0]
    xlsx, _ = ctx.print_templates.preview_xlsx(admin, t["public_id"], {"sale_id": sale["id"]})
    values = [c.value for r in openpyxl.load_workbook(io.BytesIO(xlsx)).active.iter_rows() for c in r if c.value is not None]
    assert "Martillo de uña" in values and any("Efectivo" in str(v) for v in values)
    pdf, _ = ctx.print_templates.preview(admin, t["public_id"], {"sale_id": sale["id"]})
    assert pdf.startswith(b"%PDF")
    with ctx.db.read() as conn:      # la vista previa con venta real no registra ni modifica nada
        assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == before
        assert conn.execute("SELECT stock_milli FROM products WHERE id = ?", (product["id"],)).fetchone()[0] == stock
    data, name = ctx.print_templates.template_xlsx(admin, t["public_id"])
    ws = openpyxl.load_workbook(io.BytesIO(data)).active
    texts = [str(c.value) for r in ws.iter_rows() for c in r if c.value is not None]
    assert "{Descripción}" in texts and name == "Recibo_pago.xlsx" and ws.sheet_view.showGridLines is False
    with pytest.raises(ValidationError):
        ctx.print_templates.add_company_logo(admin, t["public_id"], tmp_path)
    (tmp_path / "logo.png").write_bytes(_png(40, 20))
    img = ctx.print_templates.add_company_logo(admin, t["public_id"], tmp_path)
    for bad_name, bad in (("logo.exe", _png(4, 4)), ("x.png", b"MZ no es imagen"), ("big.png", _png(6001, 1))):
        with pytest.raises(ValidationError):
            ctx.print_templates.add_image(admin, t["public_id"], bad_name, bad)
    assert img["file"].startswith("img-") and img["file"].endswith(".png")


def _png(w: int, h: int) -> bytes:
    """PNG RGB válido (con CRC correctos) para probar la validación de imágenes."""
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b"".join(bytes(1) + bytes(3 * w) for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def test_canvas_permissions_employee_cannot_design(ctx, admin, employee, tmp_path):
    t = ctx.print_templates.create_blank(admin, {"name": "Solo admin", "kind": "venta", "designer": "canvas"})
    (tmp_path / "logo.png").write_bytes(_png(10, 10))
    for call in (lambda: ctx.print_templates.create_blank(employee, {"name": "X", "kind": "venta", "designer": "canvas"}),
                 lambda: ctx.print_templates.save(employee, t["public_id"], {"layout": t["layout"], "bindings": {}}),
                 lambda: ctx.print_templates.template_xlsx(employee, t["public_id"]),
                 lambda: ctx.print_templates.add_company_logo(employee, t["public_id"], tmp_path),
                 lambda: ctx.print_templates.preview_xlsx(employee, t["public_id"], {"lines": 2})):
        with pytest.raises((PermissionDenied, NotFoundError)):
            call()

"""Plantillas de impresión: importación de Excel, vinculaciones, tabla de productos dinámica, cálculos con
descuento, paginación, editor (guardar y reabrir), versiones, documentos emitidos, permisos y grupos.

Las pruebas con los Excel reales de la empresa (docs/*.xlsm) se omiten si los archivos no están: esa
carpeta no se versiona porque contiene datos del negocio."""
from __future__ import annotations

import hashlib
import io
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest
from openpyxl.styles import Border, Font, Side

from pospy.core.errors import NotFoundError, PermissionDenied, ValidationError
from pospy.documents import engine
from pospy.documents.layout import compile_expr, format_value, parse_cell
from pospy.documents.layout_pdf import page_count, render_pdf
from pospy.documents.xlsx_import import import_sheet, inspect, suggest_bindings

from .conftest import key, main_inventory
from .test_groups import _employee, _token

DOCS = Path(__file__).resolve().parents[2] / "docs"
COT = DOCS / "COTIZACIÓNv3.7.2.xlsm"
ORD = DOCS / "ORDEN-CASARENAULTv3.4.2.xlsm"
real_files = pytest.mark.skipif(not (COT.exists() and ORD.exists()), reason="Excel de referencia no disponibles en docs/")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def synthetic_xlsx(rows: int = 5) -> bytes:
    """Libro con encabezado, tabla de productos con fórmulas, totales y pie (como una cotización real)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Cotización"
    thin = Side(style="thin")
    ws["A1"] = "MI NEGOCIO"
    ws.merge_cells("A1:E1")
    ws["A1"].font = Font(size=18, bold=True)
    ws["A3"], ws["A4"] = "Fecha", "Cliente"
    ws["B3"] = "=TODAY()"
    ws["B4"] = 2222222
    for col, text in zip("ABCDE", ["CANT", "COD", "DESCRIPCION", "V/UNI", "VALOR"], strict=True):
        ws[f"{col}6"] = text
    for r in range(7, 7 + rows):
        for col in "ABCDE":
            ws[f"{col}{r}"].border = Border(bottom=thin)
        ws[f"E{r}"] = f'=IF(AND(ISNUMBER(A{r}),ISNUMBER(D{r})),A{r}*D{r},"")'
        ws[f"E{r}"].number_format = '"$"#,##0'
    ws["A7"], ws["B7"], ws["C7"], ws["D7"] = 1, "0257", "VARILLA DE EJEMPLO", 28000
    end = 6 + rows
    ws[f"C{end + 2}"], ws[f"E{end + 2}"] = "Subtotal", f"=SUM(E7:E{end})"
    ws[f"C{end + 3}"], ws[f"E{end + 3}"] = "TOTAL A PAGAR", f"=E{end + 2}"
    ws[f"A{end + 5}"] = "Firma del recibidor"
    ws[f"A{end + 7}"] = "GRACIAS POR SU COMPRA"
    ws.merge_cells(f"A{end + 7}:E{end + 7}")
    ws.print_area = f"A1:E{end + 7}"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------ motor (sin base de datos)
def test_formats_and_safe_calculations():
    assert format_value(56000, '_-"$"\\ * #,##0.00_-;\\-"$"\\ * #,##0.00_-;_-"$"\\ * "-"??_-;_-@_-') == "$ 56.000,00"
    assert format_value(0.2, "0%") == "20%"
    assert format_value(0.5, "[$-F400]h:mm:ss\\ AM/PM") == "12:00:00 p. m."
    tree = compile_expr("SUMA(cantidad*precio) - REDONDEAR(subtotal*descuento_pct/100; 2)", engine.TOTAL_KEYS,
                        set(engine.LINE_FIELDS))
    assert tree
    for bad in ("__import__('os')", "cantidad*precio", "precio ** 2", "open(1)", "1;2", "subtotal +"):
        with pytest.raises(ValueError):
            compile_expr(bad, engine.TOTAL_KEYS, set(engine.LINE_FIELDS))


def test_synthetic_import_dynamic_rows_and_footer_not_overwritten(tmp_path):
    path = tmp_path / "plantilla.xlsx"
    path.write_bytes(synthetic_xlsx(rows=5))
    layout, _, notes = import_sheet(path, "Cotización")
    bindings, hints = suggest_bindings(layout)
    assert bindings["products"]["start"] == 7 and bindings["products"]["end"] == 11
    assert bindings["cells"]["B4"]["field"] == "cliente_identificacion"
    assert bindings["cells"]["E13"] == {"expr": "subtotal"} and bindings["cells"]["E14"] == {"expr": "total"}
    assert any("B3" in h for h in hints) or bindings["cells"].get("B3")
    for n in (1, 5, 30, 100):
        data = engine.demo_data(n)
        data.demo = False
        final, totals = engine.render(layout, bindings, data)
        expected = sum((Decimal(1 + i % 3) * Decimal(5000 * (1 + i % 4)) for i in range(n)), Decimal(0))
        assert totals["subtotal"] == expected == totals["total"]
        shift = max(0, n - 5)
        cells = final["cells"]
        assert cells[f"E{13 + shift}"]["v"] == expected
        assert cells[f"A{16 + shift}"]["v"] == "Firma del recibidor"
        assert f"A{18 + shift}:E{18 + shift}" in final["merges"]
        assert final["page"]["print_area"] == f"A1:E{18 + shift}"
        values = [cells.get(f"E{7 + i}", {}).get("v") for i in range(max(n, 5))]
        assert all(v not in (None, "") for v in values[:n]) and all(v in (None, "") for v in values[n:])
        assert "VARILLA DE EJEMPLO" not in str(cells)            # los datos de ejemplo del archivo no se repiten
        pdf, _ = render_pdf(final, {})
        assert pdf.startswith(b"%PDF") and page_count(pdf) >= 1


def test_client_identification_fallback_and_real_print_time(tmp_path):
    path = tmp_path / "p.xlsx"
    path.write_bytes(synthetic_xlsx())
    layout, _, _ = import_sheet(path, "Cotización")
    bindings, _ = suggest_bindings(layout)
    data = engine.demo_data(1)
    final, _ = engine.render(layout, bindings, data)
    assert final["cells"]["B4"]["v"] == "222222222222"             # sin identificación: valor alternativo
    data.header["cliente_identificacion"] = "1094000111"
    final, _ = engine.render(layout, bindings, data)
    assert final["cells"]["B4"]["v"] == "1094000111"
    bindings["cells"]["D3"] = {"field": "hora_impresion"}
    moment = datetime(2026, 11, 18, 15, 4, 5)
    final, _ = engine.render(layout, bindings, engine.DocData(header={}, lines=[], printed_at=moment))
    assert final["cells"]["D3"]["v"] == "3:04:05 p. m."             # hora real de generación, no la del archivo


def test_order_discount_applied_once():
    lines = [{"cantidad": Decimal(2), "precio": Decimal(30000)}, {"cantidad": Decimal(1), "precio": Decimal(40000)}]
    lines_out, totals = engine.compute(engine.DocData(lines=lines), "20")
    assert totals["subtotal"] == Decimal(100000)
    assert totals["descuento"] == Decimal(20000) and totals["total"] == Decimal(80000)
    assert [ln["valor"] for ln in lines_out] == [Decimal(60000), Decimal(40000)]   # precios y cantidades intactos


def test_invalid_bindings_are_reported():
    layout = {"cols": [10] * 3, "rows": [15] * 10, "cells": {}, "styles": [{}], "merges": [], "images": [], "page": {}}
    problems = engine.validate(layout, {"cells": {"Z99": {"field": "numero"}, "A1": {"field": "inventado"},
                                                  "A2": {"expr": "x+1"}}, "products": {"start": 5, "end": 50,
                                                                                         "columns": {"A": {"field": "codigo"}}}})
    text = " ".join(problems)
    assert "Z99" in text and "inventado" in text and "x" in text and "fuera del diseño" in text


@real_files
def test_real_cotizacion_import_preserves_design_and_original(tmp_path):
    before = _sha(COT)
    info = inspect(COT)
    assert [s["name"] for s in info["sheets"]] == ["Hoja1", "Hoja2", "Hoja3"] and info["has_macros"]
    layout, images, notes = import_sheet(COT, "Hoja1")
    assert _sha(COT) == before                                     # el archivo original no se toca
    assert len(layout["merges"]) == 29 and "D7:E7" in layout["merges"] and "B8:E8" in layout["merges"]
    assert len(layout["images"]) == 1 and layout["images"][0]["crop"]["l"] > 0.15 and list(images.values())[0][:2] == b"\xff\xd8"
    assert round(layout["cols"][2], 1) == 31.9 and layout["rows"][0] == 282.0
    styles = layout["styles"]
    e15 = styles[layout["cells"]["E15"]["s"]]
    assert e15["font"]["name"] == "Arial" and e15["font"]["size"] == 20 and e15["font"]["b"] and "$" in e15["fmt"]
    a14 = styles[layout["cells"]["A14"]["s"]]
    assert a14["border"]["b"][0] == "mediumDashed"
    assert layout["page"]["paper"] == "roll80" and layout["page"]["scale"] == 33 and layout["page"]["print_area"] == "A1:E47"
    bindings, _ = suggest_bindings(layout)
    assert bindings["cells"]["B8"] == {"field": "cliente_identificacion", "fallback": "222222222222"}
    assert bindings["cells"]["D7"] == {"field": "hora_impresion"} and bindings["cells"]["B7"] == {"field": "fecha_larga"}
    assert (bindings["products"]["start"], bindings["products"]["end"]) == (15, 25)
    assert {k: v.get("field", v.get("expr")) for k, v in bindings["products"]["columns"].items()} == {
        "A": "cantidad", "B": "codigo", "C": "descripcion", "D": "precio", "E": "cantidad*precio"}
    assert bindings["cells"]["E28"] == {"expr": "subtotal"} and bindings["cells"]["E29"] == {"expr": "total"}
    for n, pages_letter in ((1, 1), (10, 1), (30, None), (100, None)):
        final, totals = engine.render(layout, bindings, engine.demo_data(n))
        shift = max(0, n - 11)
        assert final["cells"][f"E{28 + shift}"]["v"] == totals["subtotal"]
        assert final["cells"][f"A{33 + shift}"]["v"] == "Firma del recibidor"
        assert final["cells"][f"A{45 + shift}"]["v"] == "CASA RENAULT ARMENIA"
        pdf, _ = render_pdf(final, images)
        assert page_count(pdf) == 1                                # rollo: una tira continua
    layout["page"].update(paper="letter", fit_width=True, repeat_rows="14:14")
    final, _ = engine.render(layout, bindings, engine.demo_data(100))
    pdf, _ = render_pdf(final, images)
    assert page_count(pdf) > 3                                     # carta: varias páginas, sin cortar filas


@real_files
def test_real_orden_suggests_20_percent_discount():
    layout, images, notes = import_sheet(ORD, "Hoja1")
    assert any("E17:XFD17" in n for n in notes)                    # combinación hasta XFD recortada y avisada
    bindings, _ = suggest_bindings(layout, "orden")
    assert bindings["discount_pct"] == "20"
    assert bindings["cells"]["E31"] == {"expr": "subtotal"} and bindings["cells"]["E33"] == {"expr": "descuento"}
    assert bindings["cells"]["E34"] == {"expr": "total"}
    data = engine.DocData(lines=[{"cantidad": Decimal(2), "codigo": "0910", "descripcion": "ANILLO", "precio": Decimal(50000)}])
    final, totals = engine.render(layout, bindings, data)
    assert (final["cells"]["E31"]["v"], final["cells"]["E33"]["v"], final["cells"]["E34"]["v"]) == (
        Decimal(100000), Decimal(20000), Decimal(80000))


# ------------------------------------------------------------------ servicio, API, permisos y grupos
@pytest.fixture()
def types(ctx):
    with ctx.db.read() as conn:
        return {r["code"]: r["id"] for r in conn.execute("SELECT id, code FROM document_types")}


def _import(ctx, admin, content: bytes, name: str, doc_type: int, inventory: str | None = None, sheet: str = "Cotización"):
    staged = ctx.print_templates.inspect_upload(admin, f"{name}.xlsx", content)
    return ctx.print_templates.import_excel(admin, {"token": staged["token"], "sheet": sheet, "name": name,
                                                    "kind": "documento", "document_type_id": doc_type}, inventory)


def test_import_save_version_default_and_emitted_document_history(ctx, admin, types, product):
    content = synthetic_xlsx()
    t = _import(ctx, admin, content, "Cotización base", types["cotizacion"])
    assert t["active"] == 0 and t["loaded_version"] == 1 and not t["problems"]       # borrador hasta confirmarla
    original, _ = ctx.print_templates.original(admin, t["public_id"])
    assert original.read_bytes() == content and t["original_sha256"] == hashlib.sha256(content).hexdigest()
    pid = t["public_id"]
    with pytest.raises(ValidationError):                                             # inactiva: no puede ser predeterminada
        ctx.print_templates.update_meta(admin, pid, {"is_default": True})
    saved = ctx.print_templates.save(admin, pid, {"layout": t["layout"], "bindings": t["bindings"], "activate": True,
                                                  "note": "Confirmada"})
    assert saved["active"] == 1 and saved["loaded_version"] == 2
    ctx.print_templates.update_meta(admin, pid, {"is_default": True})
    doc = ctx.documents.create(admin, {"type_id": types["cotizacion"], "customer_name": "Taller Ruiz",
                                       "lines": [{"product_id": product["id"], "qty": "3"}]}, key())
    path = ctx.documents.pdf(admin, doc["id"])                                       # el PDF usa la plantilla nueva
    assert path.suffix == ".pdf" and path.read_bytes().startswith(b"%PDF")
    emitted = ctx.print_templates.outputs(admin, "documento", doc["id"])
    assert len(emitted) == 1 and emitted[0]["template_version"] == 2
    first_pdf = ctx.print_templates.output_file(admin, emitted[0]["id"]).read_bytes()
    # Editar la plantilla crea otra versión y no cambia lo ya emitido
    layout = saved["layout"]
    layout["cells"]["A1"]["v"] = "OTRO NOMBRE"
    ctx.print_templates.save(admin, pid, {"layout": layout, "bindings": saved["bindings"]})
    assert ctx.print_templates.output_file(admin, emitted[0]["id"]).read_bytes() == first_pdf
    with ctx.db.read() as conn:
        snap = conn.execute("SELECT data FROM print_outputs WHERE id = ?", (emitted[0]["id"],)).fetchone()[0]
        assert "Taller Ruiz" in snap and '"subtotal": "54000.00"' in snap
        with pytest.raises(Exception, match="no se modifican"):
            conn.execute("UPDATE print_template_versions SET note = 'x'")


def test_editor_blank_template_roundtrip_and_preview(ctx, admin, types):
    t = ctx.print_templates.create_blank(admin, {"name": "Orden desde cero", "kind": "documento",
                                                 "document_type_id": types["orden"]})
    pid = t["public_id"]
    layout = t["layout"]
    layout["styles"] = [{}, {"font": {"b": True, "size": 14, "color": "#1D4ED8"}, "fill": "#EEF2F7", "h": "center",
                             "border": {"b": ["thin", "#000000"]}}, {"fmt": '"$"#,##0', "h": "right"}]
    layout["cells"] = {"A1": {"v": "ORDEN", "s": 1}, "A3": {"v": "Cliente", "s": 1}, "A5": {"v": "CANT", "s": 1},
                       "C5": {"v": "DESCRIPCION", "s": 1}, "F5": {"v": "VALOR", "s": 1}, "E9": {"v": "Subtotal"},
                       "E10": {"v": "Descuento"}, "E11": {"v": "Total"}, "F9": {"s": 2}, "F10": {"s": 2}, "F11": {"s": 2}}
    layout["merges"] = ["A1:F1", "B3:D3"]
    layout["cols"][2] = 40
    layout["rows"][0] = 30
    layout["page"].update(paper="a4", repeat_rows="5:5", margins={"l": 1, "r": 1, "t": 1, "b": 1})
    bindings = {"discount_pct": "20", "cells": {"B3": {"field": "cliente_nombre", "fallback": "CONSUMIDOR FINAL"},
                                                "F9": {"field": "subtotal"}, "F10": {"field": "descuento"},
                                                "F11": {"expr": "subtotal - descuento"}},
                "products": {"start": 6, "end": 7, "header_row": 5,
                             "columns": {"A": {"field": "cantidad"}, "C": {"field": "descripcion"}, "F": {"expr": "cantidad*precio"}}}}
    with pytest.raises(ValidationError):                       # combinaciones superpuestas
        ctx.print_templates.save(admin, pid, {"layout": {**layout, "merges": ["A1:F1", "B1:C2"]}, "bindings": bindings})
    with pytest.raises(ValidationError):                       # fórmula con variable desconocida
        ctx.print_templates.save(admin, pid, {"layout": layout, "bindings": {**bindings, "cells": {"F9": {"expr": "x*2"}}}})
    saved = ctx.print_templates.save(admin, pid, {"layout": layout, "bindings": bindings, "activate": True})
    again = ctx.print_templates.get(admin, pid)
    assert again["layout"]["merges"] == ["A1:F1", "B3:D3"] and again["layout"]["cols"][2] == 40
    assert again["layout"]["styles"][1]["fill"] == "#EEF2F7" and again["bindings"]["products"]["start"] == 6
    assert [v["number"] for v in again["versions"]] == [2, 1] and saved["active"] == 1
    pdf, meta = ctx.print_templates.preview(admin, pid, {"lines": 80})
    assert pdf.startswith(b"%PDF") and meta["pages"] >= 2 and meta["totals"]["descuento"] != "0.00"
    assert b"DEMOSTRACI" in pdf or meta["pages"]               # la vista previa lleva la marca de demostración
    copy = ctx.print_templates.duplicate(admin, pid)
    assert copy["name"].endswith("(copia)") and copy["layout"]["merges"] == ["A1:F1", "B3:D3"]
    ctx.print_templates.delete(admin, copy["public_id"])
    with pytest.raises(NotFoundError):
        ctx.print_templates.get(admin, copy["public_id"])


def test_permissions_and_group_isolation(ctx, admin, employee, types, product):
    with pytest.raises(PermissionDenied):
        ctx.print_templates.create_blank(employee, {"name": "x", "kind": "venta"})
    g = ctx.groups.create(admin, {"name": "Sucursal Armenia"})
    group = g["group"]["public_id"]
    gid = ctx.inventories.create(admin, {"name": "Sucursal Armenia", "group": group})["key"]
    caro = _employee(ctx, admin, "caro", "Caro Caja", "Vitrina clara 55z")
    ctx.groups.accept(employee, _token(ctx.groups.create_invitation(admin, group, {"max_uses": 5})["url"]))
    t = _import(ctx, admin, synthetic_xlsx(), "Del grupo", types["cotizacion"], gid)
    assert ctx.print_templates.list(admin, gid)[0]["public_id"] == t["public_id"]
    assert ctx.print_templates.list(admin, main_inventory(ctx, admin)) == []
    with pytest.raises(NotFoundError):
        ctx.print_templates.list(caro, gid)
    with pytest.raises(NotFoundError):
        ctx.print_templates.image(caro, t["public_id"], "img1.jpg")
    assert ctx.print_templates.list(employee) == []           # el empleado solo ve las activas de su grupo
    ctx.print_templates.save(admin, t["public_id"], {"layout": t["layout"], "bindings": t["bindings"], "activate": True})
    assert [x["name"] for x in ctx.print_templates.list(employee)] == ["Del grupo"]


def test_sale_pdf_with_template_and_upload_validation(ctx, admin, product, cash_id):
    with pytest.raises(ValidationError):
        ctx.print_templates.inspect_upload(admin, "virus.xlsx", b"MZ\x90\x00 no es un zip")
    with pytest.raises(ValidationError):
        ctx.print_templates.inspect_upload(admin, "macro.xls", b"PK")
    staged = ctx.print_templates.inspect_upload(admin, "venta.xlsx", synthetic_xlsx())
    assert staged["sheets"][0]["name"] == "Cotización" and staged["sheets"][0]["formulas"] > 0
    t = ctx.print_templates.import_excel(admin, {"token": staged["token"], "sheet": "Cotización", "kind": "venta"})
    ctx.print_templates.save(admin, t["public_id"], {"layout": t["layout"], "bindings": t["bindings"], "activate": True})
    ctx.print_templates.update_meta(admin, t["public_id"], {"is_default": True})
    sale = ctx.sales.checkout(admin, {"lines": [{"product_id": product["id"], "qty": "2"}],
                                      "payments": [{"method_id": cash_id, "amount": "36000"}]}, key())
    result = ctx.print_templates.render_sale(admin, sale["id"])
    assert result["pages"] == 1 and result["totals"]["total"] == "36000.00"
    with pytest.raises(ValidationError):                       # una importación ya usada no se puede repetir
        ctx.print_templates.import_excel(admin, {"token": staged["token"], "sheet": "Cotización", "kind": "venta"})


def test_xml_with_doctype_is_rejected(tmp_path):
    import zipfile
    src = io.BytesIO(synthetic_xlsx())
    out = tmp_path / "malo.xlsx"
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "xl/workbook.xml":
                decl = re.match(rb"<\?xml[^>]*\?>", data)      # openpyxl no siempre escribe la declaración
                cut = decl.end() if decl else 0
                data = data[:cut] + b'<!DOCTYPE x [<!ENTITY a "aaaa">]>' + data[cut:]
            zout.writestr(item, data)
    with pytest.raises(Exception, match="DOCTYPE|no permitido|XML"):
        import_sheet(out, "Cotización")


def test_http_endpoints(client, ctx, admin, types):
    from .conftest import login
    login(client)
    r = client.post("/api/print-templates/inspect", files={"file": ("cot.xlsx", synthetic_xlsx(), "application/octet-stream")})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    r = client.post("/api/print-templates/import", json={"token": token, "sheet": "Cotización", "name": "HTTP",
                                                         "kind": "documento", "document_type_id": types["cotizacion"]})
    assert r.status_code == 200, r.text
    pid = r.json()["public_id"]
    r = client.post(f"/api/print-templates/{pid}/preview", json={"lines": 12})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")
    assert client.get("/api/print-templates/catalog").json()["fields"][0]["group"] == "Empresa"
    assert client.get(f"/api/print-templates/{pid}/original").status_code == 200
    assert client.get("/api/print-templates/..%2F..%2Fpospy.db").status_code == 404
    assert client.get(f"/api/print-templates/{pid}/images/..%5C..%5Cpospy.db").status_code == 404
    assert parse_cell("B8") == (8, 2)

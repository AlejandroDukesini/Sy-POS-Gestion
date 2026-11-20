"""Excel (.xlsx) real a partir de un diseño completado («layout»): el mismo que produce el PDF.

- Celdas con sus valores (números como números, con su formato), estilos (fuente, tamaño, negrita,
  cursiva, subrayado, color, relleno, alineación, ajuste, reducción, giro), bordes y combinaciones.
- Anchos de columna y altos de fila exactos; área de impresión, márgenes, orientación, papel (carta,
  oficio, A4, A5), ajuste a una página de ancho cuando corresponde, sin líneas de cuadrícula y filas de
  títulos repetidas.
- Imágenes incrustadas como imágenes de Excel (no como fondo ni como captura): openpyxl necesita PIL para
  eso, que no está instalado, así que el dibujo se escribe directamente en el paquete OOXML.

Seguridad: el texto nunca se interpreta como fórmula (un nombre de cliente «=HIPERVINCULO(…)» queda como
texto). El archivo no lleva macros.
"""
from __future__ import annotations

import io
import re
import zipfile
from decimal import Decimal
from typing import Any
from xml.sax.saxutils import escape

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.pagebreak import Break

from .layout import parse_range

PAPER_CODES = {"letter": 1, "legal": 5, "a4": 9, "a5": 11}
EMU_PER_PT = 12700
CM_PER_INCH = 2.54
FORMULA_START = ("=", "+", "-", "@")


def _font(f: dict) -> Font:
    color = (f.get("color") or "#000000").lstrip("#")
    return Font(name=f.get("name") or "Calibri", size=float(f.get("size") or 11), bold=bool(f.get("b")),
                italic=bool(f.get("i")), underline="single" if f.get("u") else None, color="FF" + color.upper())


def _side(spec) -> Side:
    if not spec:
        return Side()
    style, color = spec
    return Side(style=style, color="FF" + str(color).lstrip("#").upper())


def _apply_style(cell, st: dict) -> None:
    if not st:
        return
    if st.get("font"):
        cell.font = _font(st["font"])
    if st.get("fill"):
        cell.fill = PatternFill("solid", fgColor="FF" + st["fill"].lstrip("#").upper())
    rot = {90: 90, 270: 180}.get(st.get("rot") or 0, 0)
    if any(st.get(k) for k in ("h", "v", "wrap", "shrink", "rot")):
        cell.alignment = Alignment(horizontal=st.get("h") or None, vertical=st.get("v") or "bottom",
                                   wrap_text=bool(st.get("wrap")), shrink_to_fit=bool(st.get("shrink")), text_rotation=rot)
    if st.get("fmt"):
        cell.number_format = st["fmt"]
    b = st.get("border") or {}
    if b:
        cell.border = Border(left=_side(b.get("l")), right=_side(b.get("r")), top=_side(b.get("t")), bottom=_side(b.get("b")))


def _value(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    return v


def write_xlsx(layout: dict, images: dict[str, bytes] | None = None, title: str = "Documento") -> bytes:
    images = images or {}
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = re.sub(r"[\[\]:*?/\\]", " ", title)[:31] or "Documento"
    for i, w in enumerate(layout["cols"], start=1):
        dim = ws.column_dimensions[get_column_letter(i)]
        if w <= 0:
            dim.hidden = True
        else:
            dim.width = float(w)
    for r, h in enumerate(layout["rows"], start=1):
        dim = ws.row_dimensions[r]
        if h <= 0:
            dim.hidden = True
        else:
            dim.height = float(h)
    styles = layout.get("styles") or [{}]
    for ref, cell_def in layout["cells"].items():
        cell = ws[ref]
        v = _value(cell_def.get("v"))
        if v not in (None, ""):
            cell.value = v
            if isinstance(v, str) and v.startswith(FORMULA_START):
                cell.data_type = "s"            # texto, nunca fórmula (protección contra inyección)
        s = cell_def.get("s", 0)
        if isinstance(s, int) and 0 < s < len(styles):
            _apply_style(cell, styles[s])
    for m in layout.get("merges", []):
        ws.merge_cells(m)
    page = layout.get("page") or {}
    ws.sheet_view.showGridLines = False
    ws.print_options.gridLines = False
    ws.page_setup.orientation = "landscape" if page.get("orientation") == "landscape" else "portrait"
    paper = page.get("paper") or "letter"
    if paper in PAPER_CODES:
        ws.page_setup.paperSize = PAPER_CODES[paper]
    margins = page.get("margins") or {}
    ws.page_margins.left = float(margins.get("l", 1.5)) / CM_PER_INCH
    ws.page_margins.right = float(margins.get("r", 1.5)) / CM_PER_INCH
    ws.page_margins.top = float(margins.get("t", 1.5)) / CM_PER_INCH
    ws.page_margins.bottom = float(margins.get("b", 1.5)) / CM_PER_INCH
    ws.page_margins.header = ws.page_margins.footer = 0
    roll = paper.startswith("roll") or (paper == "custom" and not page.get("height_mm"))
    if page.get("fit_width") or roll:
        # Rollo o ajuste: todo el ancho en una página; el alto crece hacia abajo sin cortes forzados.
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
    else:
        ws.page_setup.scale = int(page.get("scale") or 100)
    if roll:
        ws.print_options.horizontalCentered = True
    area = page.get("print_area")
    if area:
        r1, c1, r2, c2 = parse_range(area)
        ws.print_area = f"{get_column_letter(c1)}{r1}:{get_column_letter(min(c2, len(layout['cols'])))}{min(r2, len(layout['rows']))}"
    if page.get("repeat_rows"):
        a, b = str(page["repeat_rows"]).split(":")
        ws.print_title_rows = f"{a}:{b}"
    for brk in page.get("row_breaks") or []:
        ws.row_breaks.append(Break(id=int(brk)))
    if page.get("header"):
        ws.oddHeader.center.text = str(page["header"])
    if page.get("footer"):
        ws.oddFooter.center.text = str(page["footer"]).replace("&P", "&P").replace("&N", "&N")
    buf = io.BytesIO()
    wb.save(buf)
    data = buf.getvalue()
    pics = [img for img in layout.get("images", []) if img.get("file") in images]
    if pics:
        data = _embed_images(data, pics, images)
    return data


def _embed_images(xlsx: bytes, pics: list[dict], files: dict[str, bytes]) -> bytes:
    """Agrega un dibujo con las imágenes a la primera hoja (OOXML de SpreadsheetDrawing)."""
    src = zipfile.ZipFile(io.BytesIO(xlsx))
    out_buf = io.BytesIO()
    anchors, drels, media = [], [], {}
    for i, img in enumerate(pics, start=1):
        data = files[img["file"]]
        ext = "png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "jpeg"
        name = f"image{i}.{ext}"
        media[f"xl/media/{name}"] = data
        drels.append(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"'
                     f' Target="../media/{name}"/>')
        crop = img.get("crop") or {}
        src_rect = ""
        if crop:
            src_rect = "<a:srcRect " + " ".join(f'{k}="{int(round(float(v) * 100000))}"' for k, v in crop.items()) + "/>"
        anchors.append(
            f'<xdr:oneCellAnchor><xdr:from><xdr:col>{int(img["col"])}</xdr:col><xdr:colOff>{int(img.get("col_off", 0) * EMU_PER_PT)}'
            f'</xdr:colOff><xdr:row>{int(img["row"])}</xdr:row><xdr:rowOff>{int(img.get("row_off", 0) * EMU_PER_PT)}</xdr:rowOff>'
            f'</xdr:from><xdr:ext cx="{int(img["w"] * EMU_PER_PT)}" cy="{int(img["h"] * EMU_PER_PT)}"/>'
            f'<xdr:pic><xdr:nvPicPr><xdr:cNvPr id="{i + 1}" name="{escape(str(img.get("id") or f"Imagen {i}"))}"/>'
            f'<xdr:cNvPicPr><a:picLocks noChangeAspect="1"/></xdr:cNvPicPr></xdr:nvPicPr>'
            f'<xdr:blipFill><a:blip r:embed="rId{i}"/>{src_rect}<a:stretch><a:fillRect/></a:stretch></xdr:blipFill>'
            f'<xdr:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{int(img["w"] * EMU_PER_PT)}" cy="{int(img["h"] * EMU_PER_PT)}"/>'
            f'</a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr></xdr:pic><xdr:clientData/></xdr:oneCellAnchor>')
    drawing = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"'
               ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
               ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' + "".join(anchors) + "</xdr:wsDr>")
    drawing_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(drels)
                    + "</Relationships>")
    sheet_rels_path = "xl/worksheets/_rels/sheet1.xml.rels"
    rel_drawing = ('<Relationship Id="rIdDrawing1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing"'
                   ' Target="../drawings/drawing1.xml"/>')
    with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as dst:
        names = src.namelist()
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "[Content_Types].xml":
                text = data.decode("utf-8")
                for ext, mime in (("png", "image/png"), ("jpeg", "image/jpeg")):
                    if f'Extension="{ext}"' not in text:
                        text = text.replace("<Default ", f'<Default Extension="{ext}" ContentType="{mime}"/><Default ', 1)
                text = text.replace("</Types>", '<Override PartName="/xl/drawings/drawing1.xml"'
                                    ' ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/></Types>')
                data = text.encode("utf-8")
            elif item.filename == "xl/worksheets/sheet1.xml":
                text = data.decode("utf-8")
                if 'xmlns:r="' not in text[:600]:
                    text = re.sub(r"<worksheet ", '<worksheet xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" ',
                                  text, count=1)
                text = text.replace("</worksheet>", '<drawing r:id="rIdDrawing1"/></worksheet>')
                data = text.encode("utf-8")
            elif item.filename == sheet_rels_path:
                data = data.decode("utf-8").replace("</Relationships>", rel_drawing + "</Relationships>").encode("utf-8")
            dst.writestr(item, data)
        if sheet_rels_path not in names:
            dst.writestr(sheet_rels_path, '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + rel_drawing
                         + "</Relationships>")
        dst.writestr("xl/drawings/drawing1.xml", drawing)
        dst.writestr("xl/drawings/_rels/drawing1.xml.rels", drawing_rels)
        for path, data in media.items():
            dst.writestr(path, data)
    return out_buf.getvalue()

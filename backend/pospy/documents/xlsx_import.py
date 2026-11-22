"""Importación de libros Excel (.xlsx / .xlsm) al modelo de plantillas («layout»).

Se lee con openpyxl (estilos, combinaciones, valores y fórmulas) y, directamente del XML del archivo,
lo que openpyxl no conserva: imágenes con su posición y recorte, y la paleta de colores del tema.
El archivo NUNCA se modifica y las macros (vbaProject.bin) no se cargan ni se ejecutan: solo se
informa que existen.
"""
from __future__ import annotations

import colorsys
import posixpath
import re
import unicodedata
import zipfile
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import openpyxl
from openpyxl.styles.colors import COLOR_INDEX

from .excel_safety import ExcelError, ensure_workbook
from .layout import col_index, col_letter, col_points, default_page, parse_cell, parse_range, range_ref, to_serial

NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}
EMU_PER_PT = 12700
MAX_ROWS, MAX_COLS = 2000, 60
PAPER_CODES = {1: "letter", 5: "legal", 9: "a4", 11: "a5"}
IMAGE_TYPES = {".jpeg": "image/jpeg", ".jpg": "image/jpeg", ".png": "image/png"}
MAX_UNCOMPRESSED = 60 * 1024 * 1024


# ------------------------------------------------------------------ utilidades del paquete
def _xml(data: bytes) -> ET.Element:
    """Analiza una parte del paquete. OOXML nunca usa DOCTYPE ni entidades: si aparecen, se rechaza el archivo
    (evita ataques de expansión de entidades y entidades externas)."""
    upper = data.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ExcelError("El archivo contiene XML no permitido (DOCTYPE o entidades).")
    return ET.fromstring(data)  # noqa: S314 - sin DOCTYPE no hay entidades que expandir


def _check_zip(path: Path) -> zipfile.ZipFile:
    ensure_workbook(path)
    zf = zipfile.ZipFile(path)
    total = sum(i.file_size for i in zf.infolist())
    if total > MAX_UNCOMPRESSED:
        zf.close()
        raise ExcelError("El archivo descomprimido es demasiado grande para ser una plantilla.")
    for info in zf.infolist():
        name = info.filename
        if name.startswith("/") or ".." in name.split("/"):
            zf.close()
            raise ExcelError("El archivo tiene rutas internas no válidas.")
    return zf


def _rels(zf: zipfile.ZipFile, part: str) -> dict[str, str]:
    folder, name = posixpath.split(part)
    rels_path = posixpath.join(folder, "_rels", name + ".rels")
    if rels_path not in zf.namelist():
        return {}
    root = _xml(zf.read(rels_path))
    out = {}
    for rel in root.findall("rel:Relationship", NS):
        target = rel.get("Target", "")
        full = posixpath.normpath(posixpath.join(folder, target)) if not target.startswith("/") else target[1:]
        out[rel.get("Id")] = full
    return out


def _sheet_parts(zf: zipfile.ZipFile) -> dict[str, str]:
    root = _xml(zf.read("xl/workbook.xml"))
    rels = _rels(zf, "xl/workbook.xml")
    out = {}
    for sh in root.findall("main:sheets/main:sheet", NS):
        rid = sh.get(f"{{{NS['r']}}}id")
        if rid in rels:
            out[sh.get("name")] = rels[rid]
    return out


def _theme_colors(zf: zipfile.ZipFile) -> list[str]:
    """Colores del tema en el orden de los índices de Excel (0 = lt1, 1 = dk1, 2 = lt2, 3 = dk2, 4-9 acentos…)."""
    default = ["FFFFFF", "000000", "E7E6E6", "44546A", "4472C4", "ED7D31", "A5A5A5", "FFC000", "5B9BD5", "70AD47",
               "0563C1", "954F72"]
    name = next((n for n in zf.namelist() if n.startswith("xl/theme/") and n.endswith(".xml")), None)
    if not name:
        return default
    try:
        scheme = _xml(zf.read(name)).find(".//a:clrScheme", NS)
        order = ["dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6", "hlink",
                 "folHlink"]
        found = {}
        for key in order:
            el = scheme.find(f"a:{key}", NS)
            child = el[0] if el is not None and len(el) else None
            if child is not None:
                found[key] = (child.get("lastClr") or child.get("val") or "").upper()
        seq = [found.get(k) for k in ["lt1", "dk1", "lt2", "dk2", *order[4:]]]
        return [c if c and len(c) == 6 else d for c, d in zip(seq, default, strict=True)]
    except (ET.ParseError, AttributeError):
        return default


def _tint(hex6: str, tint: float) -> str:
    if not tint:
        return hex6
    r, g, b = (int(hex6[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, lum, s = colorsys.rgb_to_hls(r, g, b)
    lum = lum * (1 + tint) if tint < 0 else lum * (1 - tint) + tint
    r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, lum)), s)
    return "".join(f"{round(v * 255):02X}" for v in (r, g, b))


def _color(c, theme: list[str]) -> str | None:
    if c is None:
        return None
    try:
        kind = c.type
        if kind == "rgb" and isinstance(c.rgb, str) and len(c.rgb) >= 6:
            if len(c.rgb) == 8 and c.rgb[:2] == "00" and c.rgb != "00000000":
                return "#" + c.rgb[2:]
            return None if c.rgb == "00000000" else "#" + c.rgb[-6:]
        if kind == "theme" and isinstance(c.theme, int) and 0 <= c.theme < len(theme):
            return "#" + _tint(theme[c.theme], float(c.tint or 0))
        if kind == "indexed" and isinstance(c.indexed, int) and c.indexed < len(COLOR_INDEX):
            if c.indexed in (64, 65):   # color del sistema (automático)
                return None
            return "#" + COLOR_INDEX[c.indexed][-6:]
    except (AttributeError, TypeError, ValueError):
        return None
    return None


def _norm(text: Any) -> str:
    text = unicodedata.normalize("NFD", str(text or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text).strip().upper().rstrip(":")


# ------------------------------------------------------------------ inspección del libro
def inspect(path: Path) -> dict:
    """Hojas del libro con lo necesario para elegir la correcta (no elige ninguna automáticamente)."""
    path = Path(path)
    with _check_zip(path) as zf:
        names = zf.namelist()
        parts = _sheet_parts(zf)
        has_macros = "xl/vbaProject.bin" in names
        drawings = {}
        for sheet, part in parts.items():
            drawings[sheet] = sum(1 for t in _rels(zf, part).values() if "/drawings/" in t)
    wb = openpyxl.load_workbook(path, data_only=False, keep_vba=False)
    try:
        sheets = []
        for ws in wb.worksheets:
            used = sum(1 for row in ws.iter_rows(max_row=min(ws.max_row, MAX_ROWS), max_col=min(ws.max_column, MAX_COLS))
                       for c in row if c.value is not None)
            formulas = sum(1 for row in ws.iter_rows(max_row=min(ws.max_row, MAX_ROWS), max_col=min(ws.max_column, MAX_COLS))
                           for c in row if isinstance(c.value, str) and c.value.startswith("="))
            area = _print_area(ws)
            sample = [str(c.value)[:40] for row in ws.iter_rows(max_row=min(ws.max_row, 30), max_col=min(ws.max_column, 12))
                      for c in row if isinstance(c.value, str) and not c.value.startswith("=")][:8]
            sheets.append({
                "name": ws.title, "state": ws.sheet_state, "dimensions": ws.dimensions, "used_cells": used,
                "formulas": formulas, "merged": len(ws.merged_cells.ranges), "images": drawings.get(ws.title, 0),
                "print_area": area or "", "sample": sample,
            })
    finally:
        wb.close()
    return {"sheets": sheets, "has_macros": has_macros,
            "notes": (["El archivo contiene macros (VBA): se conservan en el archivo original guardado, pero POS-PY nunca"
                       " las ejecuta ni las usa para generar documentos."] if has_macros else [])}


def _print_area(ws) -> str:
    area = ws.print_area
    if not area:
        return ""
    first = str(area).split(",")[0]
    try:
        return range_ref(*parse_range(first))
    except ValueError:
        return ""


# ------------------------------------------------------------------ importación de una hoja
def import_sheet(path: Path, sheet: str) -> tuple[dict, dict[str, bytes], list[str]]:
    """Convierte la hoja en un layout. Devuelve (layout, imágenes {archivo: bytes}, avisos)."""
    path = Path(path)
    notes: list[str] = []
    with _check_zip(path) as zf:
        parts = _sheet_parts(zf)
        if sheet not in parts:
            raise ExcelError(f"La hoja «{sheet}» no existe en el archivo.")
        theme = _theme_colors(zf)
        images, image_files = _images(zf, parts[sheet], notes)
    wb = openpyxl.load_workbook(path, data_only=False, keep_vba=False)
    cached_wb = openpyxl.load_workbook(path, data_only=True, keep_vba=False)
    try:
        ws, cws = wb[sheet], cached_wb[sheet]
        area = _print_area(ws)
        if area:
            r1, c1, r2, c2 = parse_range(area)
        else:
            r1, c1, r2, c2 = 1, 1, *_used_bounds(ws)
            area = range_ref(r1, c1, r2, c2)
            notes.append(f"La hoja no tiene área de impresión: se usa {area}.")
        if r2 > MAX_ROWS or c2 > MAX_COLS:
            notes.append(f"La hoja se recortó a {MAX_COLS} columnas y {MAX_ROWS} filas.")
            r2, c2 = min(r2, MAX_ROWS), min(c2, MAX_COLS)
            area = range_ref(r1, c1, r2, c2)
        fmt = ws.sheet_format
        default_w = fmt.defaultColWidth if fmt.defaultColWidth is not None else (fmt.baseColWidth or 8) + 0.71
        cols = [float(default_w)] * c2
        for dim in ws.column_dimensions.values():
            lo, hi = dim.min or 0, dim.max or 0
            for c in range(max(1, lo), min(c2, hi) + 1):
                cols[c - 1] = 0.0 if dim.hidden else float(dim.width if dim.width is not None else default_w)
        default_h = float(fmt.defaultRowHeight or 15)
        rows = []
        for r in range(1, r2 + 1):
            dim = ws.row_dimensions.get(r)
            if dim is not None and dim.hidden:
                rows.append(0.0)
            elif dim is not None and dim.height is not None:
                rows.append(float(dim.height))
            elif fmt.zeroHeight:
                rows.append(0.0)
            else:
                rows.append(default_h)
        styles: list[dict] = [{}]
        style_index: dict[str, int] = {"{}": 0}
        cells: dict[str, dict] = {}
        for row in ws.iter_rows(min_row=r1, max_row=r2, min_col=c1, max_col=c2):
            for cell in row:
                st = _style(cell, theme)
                key = repr(sorted(st.items()))
                if key not in style_index:
                    style_index[key] = len(styles)
                    styles.append(st)
                s = style_index[key]
                value = cell.value
                entry: dict[str, Any] = {}
                if isinstance(value, str) and value.startswith("="):
                    entry["f"] = value
                    value = cws.cell(row=cell.row, column=cell.column).value
                if isinstance(value, (datetime, date, time)):
                    value = to_serial(value)
                if value is not None and value != "":
                    entry["v"] = value if isinstance(value, (int, float, str)) else str(value)
                if entry or s:
                    if s:
                        entry["s"] = s
                    cells[cell.coordinate] = entry
        merges = []
        for rng in ws.merged_cells.ranges:
            a1, b1, a2, b2 = rng.min_row, rng.min_col, min(rng.max_row, r2), min(rng.max_col, c2)
            if a1 > r2 or b1 > c2 or a2 < r1 or b2 < c1:
                continue
            if (a1, b1) != (a2, b2):
                merges.append(range_ref(a1, b1, a2, b2))
            if rng.max_col > c2 or rng.max_row > r2:
                notes.append(f"La combinación {rng.coord} sale del área de impresión; se recortó a {range_ref(a1, b1, a2, b2)}.")
        page = _page(ws, cols, area, notes)
        outside = sum(1 for row in ws.iter_rows(max_row=min(ws.max_row, MAX_ROWS), max_col=min(ws.max_column, MAX_COLS))
                      for c in row if c.value is not None and not (r1 <= c.row <= r2 and c1 <= c.column <= c2))
        if outside:
            notes.append(f"{outside} celda(s) con contenido fuera del área de impresión no forman parte de la plantilla.")
    finally:
        wb.close()
        cached_wb.close()
    layout = {"v": 1, "cols": cols, "rows": rows, "cells": cells, "styles": styles, "merges": merges,
              "images": images, "page": page}
    return layout, image_files, notes


def _used_bounds(ws) -> tuple[int, int]:
    last_r = last_c = 1
    for row in ws.iter_rows(max_row=min(ws.max_row, MAX_ROWS), max_col=min(ws.max_column, MAX_COLS)):
        for c in row:
            if c.value is not None:
                last_r, last_c = max(last_r, c.row), max(last_c, c.column)
    return last_r, last_c


def _style(cell, theme: list[str]) -> dict:
    st: dict[str, Any] = {}
    f = cell.font
    if f is not None:
        font = {}
        if f.name and f.name != "Calibri":
            font["name"] = f.name
        if f.sz and float(f.sz) != 11:
            font["size"] = float(f.sz)
        if f.b:
            font["b"] = True
        if f.i:
            font["i"] = True
        if f.u and f.u != "none":
            font["u"] = True
        if (color := _color(f.color, theme)) and color.upper() != "#000000":
            font["color"] = color
        if font:
            st["font"] = font
    if cell.fill is not None and cell.fill.fill_type == "solid":
        if (bg := _color(cell.fill.fgColor, theme)):
            st["fill"] = bg
    al = cell.alignment
    if al is not None:
        if al.horizontal in ("left", "center", "right", "centerContinuous", "justify", "fill", "distributed"):
            st["h"] = {"centerContinuous": "center", "justify": "left", "fill": "left", "distributed": "center"}.get(
                al.horizontal, al.horizontal)
        if al.vertical in ("top", "center", "bottom", "justify", "distributed"):
            if al.vertical != "bottom":
                st["v"] = "center" if al.vertical in ("center", "justify", "distributed") else "top"
        if al.wrap_text:
            st["wrap"] = True
    if cell.number_format and cell.number_format != "General":
        st["fmt"] = cell.number_format
    border = {}
    for side, key in (("left", "l"), ("right", "r"), ("top", "t"), ("bottom", "b")):
        sd = getattr(cell.border, side, None)
        if sd is not None and sd.style:
            border[key] = [sd.style, _color(sd.color, theme) or "#000000"]
    if border:
        st["border"] = border
    return st


def _page(ws, cols: list[float], area: str, notes: list[str]) -> dict:
    page = default_page()
    ps = ws.page_setup
    page["orientation"] = "landscape" if ps.orientation == "landscape" else "portrait"
    try:
        scale = int(ps.scale or 100)
    except (TypeError, ValueError):
        scale = 100
    page["scale"] = max(10, min(400, scale))
    pr = ws.sheet_properties.pageSetUpPr
    page["fit_width"] = bool(pr is not None and pr.fitToPage and (ps.fitToWidth or 1) >= 1)
    m = ws.page_margins
    page["margins"] = {k: round(float(getattr(m, attr) or 0) * 2.54, 2)
                       for k, attr in (("l", "left"), ("r", "right"), ("t", "top"), ("b", "bottom"))}
    page["print_area"] = area
    _, c1, _, c2 = parse_range(area)
    printed_pt = sum(col_points(w) for w in cols[c1 - 1:c2]) * (page["scale"] / 100)
    try:
        code = int(ps.paperSize or 1)
    except (TypeError, ValueError):
        code = 1
    if code in PAPER_CODES:
        page["paper"] = PAPER_CODES[code]
    elif printed_pt <= 240:
        page["paper"] = "roll80"
        notes.append(f"El papel del archivo (código {code}) no es estándar y el ancho impreso es de unos "
                     f"{printed_pt / 72 * 25.4:.0f} mm: se configuró como rollo de 80 mm. Puede cambiarlo.")
    else:
        page["paper"] = "letter"
        notes.append(f"El papel del archivo (código {code}) no es estándar: se configuró tamaño carta. Puede cambiarlo.")
    if ws.print_title_rows:
        try:
            a, b = str(ws.print_title_rows).replace("$", "").split(":")
            page["repeat_rows"] = f"{int(a)}:{int(b)}"
        except ValueError:
            pass
    page["row_breaks"] = sorted({int(b.id) for b in ws.row_breaks.brk if b.id})
    hdr = []
    for part in ("left", "center", "right"):
        h = getattr(ws.oddHeader, part, None)
        if h is not None and h.text:
            hdr.append(h.text)
    page["header"] = " · ".join(hdr)
    ftr = []
    for part in ("left", "center", "right"):
        f = getattr(ws.oddFooter, part, None)
        if f is not None and f.text:
            ftr.append(f.text)
    page["footer"] = " · ".join(ftr)
    return page


def _images(zf: zipfile.ZipFile, sheet_part: str, notes: list[str]) -> tuple[list[dict], dict[str, bytes]]:
    images, files = [], {}
    for target in _rels(zf, sheet_part).values():
        if "/drawings/" not in target or target not in zf.namelist():
            continue
        drels = _rels(zf, target)
        root = _xml(zf.read(target))
        for anchor in list(root):
            tag = anchor.tag.split("}")[-1]
            if tag not in ("twoCellAnchor", "oneCellAnchor", "absoluteAnchor"):
                continue
            blip = anchor.find(".//a:blip", NS)
            if blip is None:
                notes.append("Hay formas o gráficos que no son imágenes; no se incluyen en la plantilla.")
                continue
            media = drels.get(blip.get(f"{{{NS['r']}}}embed"))
            ext = posixpath.splitext(media or "")[1].lower()
            if not media or media not in zf.namelist() or ext not in IMAGE_TYPES:
                notes.append(f"La imagen {posixpath.basename(media or '?')} tiene un formato no soportado (use JPG o PNG).")
                continue
            frm = anchor.find("xdr:from", NS)
            if frm is None:
                continue
            col = int(frm.findtext("xdr:col", "0", NS))
            row = int(frm.findtext("xdr:row", "0", NS))
            col_off = int(frm.findtext("xdr:colOff", "0", NS)) / EMU_PER_PT
            row_off = int(frm.findtext("xdr:rowOff", "0", NS)) / EMU_PER_PT
            size = anchor.find(".//a:xfrm/a:ext", NS)
            if size is None:
                size = anchor.find("xdr:ext", NS)
            if size is None:
                continue
            w, h = int(size.get("cx", "0")) / EMU_PER_PT, int(size.get("cy", "0")) / EMU_PER_PT
            crop = {}
            src = anchor.find(".//a:srcRect", NS)
            if src is not None:
                crop = {k: int(src.get(k, "0")) / 100000 for k in ("l", "t", "r", "b") if src.get(k)}
            image_id = f"img{len(images) + 1}"
            name = f"{image_id}{'.jpg' if ext in ('.jpg', '.jpeg') else '.png'}"
            files[name] = zf.read(media)
            images.append({"id": image_id, "file": name, "mime": IMAGE_TYPES[ext], "col": col, "col_off": round(col_off, 2),
                           "row": row, "row_off": round(row_off, 2), "w": round(w, 2), "h": round(h, 2), "crop": crop})
    return images, files


# ------------------------------------------------------------------ vinculaciones sugeridas
HEADER_WORDS = {
    "cantidad": ("CANT", "CANTIDAD", "CANT.", "UND", "UNIDADES"),
    "codigo": ("COD", "CODIGO", "COD.", "REF", "REFERENCIA"),
    "descripcion": ("DESCRIPCION", "DETALLE", "PRODUCTO", "ARTICULO", "CONCEPTO"),
    "precio": ("V/UNI", "V/UNIT", "VR UNIT", "VR. UNIT", "VALOR UNITARIO", "PRECIO", "PRECIO UNITARIO", "P/UNIT", "V. UNITARIO"),
    "valor": ("VALOR", "TOTAL", "IMPORTE", "VR TOTAL", "VALOR TOTAL", "SUBTOTAL LINEA"),
}


def _value_cell_right(layout: dict, row: int, col: int) -> str | None:
    """Celda de valor a la derecha de un rótulo (salta la combinación del rótulo)."""
    end_col = col
    for m in layout["merges"]:
        a1, b1, a2, b2 = parse_range(m)
        if a1 == row and b1 == col:
            end_col = b2
    target = end_col + 1
    if target > len(layout["cols"]):
        return None
    return f"{col_letter(target)}{row}"


def suggest_bindings(layout: dict, kind: str = "") -> tuple[dict, list[str]]:
    """Propone vinculaciones a partir de los rótulos del diseño. El usuario las confirma o cambia."""
    cells = layout["cells"]
    notes: list[str] = []
    by_pos: dict[tuple[int, int], dict] = {}
    for ref, c in cells.items():
        m = re.match(r"([A-Z]+)(\d+)", ref)
        by_pos[(int(m.group(2)), col_index(m.group(1)))] = c
    bindings: dict[str, Any] = {"cells": {}, "products": None, "discount_pct": "0"}
    # 1. Encabezado de la tabla de productos
    header_row, columns = 0, {}
    for (r, c), cell in sorted(by_pos.items()):
        text = _norm(cell.get("v"))
        for fld, words in HEADER_WORDS.items():
            if text in words and fld not in columns.values():
                if header_row in (0, r):
                    header_row = r
                    columns[col_letter(c)] = fld
        if header_row and r > header_row:
            break
    if header_row and len(columns) >= 3:
        first = header_row + 1
        value_col = next((k for k, v in columns.items() if v == "valor"), None)
        last = first
        if value_col:
            vc = col_index(value_col)
            r = first
            while r <= len(layout["rows"]):
                f = (by_pos.get((r, vc)) or {}).get("f", "")
                if f and re.search(rf"[A-Z]+{r}\b", f.replace("$", "")):
                    last = r
                    r += 1
                else:
                    break
        product_columns = {}
        for letter, fld in columns.items():
            product_columns[letter] = {"expr": "cantidad*precio"} if fld == "valor" else {"field": fld}
        bindings["products"] = {"start": first, "end": max(first, last), "columns": product_columns, "header_row": header_row}
        notes.append(f"Tabla de productos: filas {first} a {max(first, last)} (encabezado en la fila {header_row}). "
                     "Se repetirá por cada producto; si hay más, el contenido de abajo se desplaza.")
    products = bindings["products"]
    # 2. Rótulos conocidos
    seen_total_area = False
    for (r, c), cell in sorted(by_pos.items()):
        if products and products["start"] <= r <= products["end"]:
            continue
        text = _norm(cell.get("v"))
        if not text:
            continue
        target = _value_cell_right(layout, r, c)
        if not target or target in bindings["cells"]:
            continue
        tcell = cells.get(target, {})
        sample = tcell.get("v")
        if text == "FECHA":
            if "TODAY" in str(tcell.get("f", "")).upper() or "HOY" in str(tcell.get("f", "")).upper():
                bindings["cells"][target] = {"field": "fecha_larga"}
            else:
                bindings["cells"][target] = {"field": "fecha"}
            nxt = _value_cell_right(layout, r, parse_cell(target)[1])
            ncell = cells.get(nxt or "", {})
            if nxt and isinstance(ncell.get("v"), float) and 0 <= ncell["v"] < 1:
                bindings["cells"][nxt] = {"field": "hora_impresion"}
        elif text in ("CLIENTE", "SENOR", "SENORES", "SR", "SRES"):
            if isinstance(sample, (int, float)) or re.fullmatch(r"[\d.\-\s]+", str(sample or "")):
                bindings["cells"][target] = {"field": "cliente_identificacion", "fallback": "222222222222"}
            else:
                bindings["cells"][target] = {"field": "cliente_nombre", "fallback": ""}
        elif text in ("NIT", "C.C", "CC", "NIT/CC", "IDENTIFICACION", "CEDULA", "NIT O CC"):
            bindings["cells"][target] = {"field": "cliente_identificacion", "fallback": "222222222222"}
        elif text in ("TELEFONO", "TEL", "CELULAR"):
            bindings["cells"][target] = {"field": "cliente_telefono", "fallback": ""}
        elif text in ("DIRECCION",):
            bindings["cells"][target] = {"field": "cliente_direccion", "fallback": ""}
        elif text == "SUBTOTAL":
            seen_total_area = True
            bindings["cells"][_total_cell(layout, r, target, products)] = {"expr": "subtotal"}
        elif text.startswith("DESCUENTO") and seen_total_area:
            cell_ref_ = _total_cell(layout, r, target, products)
            value = cells.get(cell_ref_, {}).get("v")
            if isinstance(value, (int, float)) and 0 < value < 1:
                bindings["discount_pct"] = str(round(value * 100, 4)).rstrip("0").rstrip(".")
                bindings["cells"][cell_ref_] = {"expr": "descuento_pct/100"}
            else:
                bindings["cells"][cell_ref_] = {"expr": "descuento"}
        elif text in ("VALOR", "VALOR DESCUENTO", "VR DESCUENTO") and seen_total_area:
            bindings["cells"][_total_cell(layout, r, target, products)] = {"expr": "descuento"}
        elif text in ("TOTAL A PAGAR", "TOTAL", "TOTAL PAGAR", "NETO A PAGAR") and seen_total_area:
            bindings["cells"][_total_cell(layout, r, target, products)] = {"expr": "total"}
    if bindings["discount_pct"] != "0" and "descuento" not in {b.get("expr") for b in bindings["cells"].values()}:
        notes.append("Se detectó un porcentaje de descuento pero no la celda del valor descontado.")
    # 3. Fórmulas de Excel que quedan sin vincular
    linked = set(bindings["cells"])
    for ref, c in cells.items():
        if "f" in c and ref not in linked:
            r = int(re.sub(r"\D", "", ref))
            if products and products["start"] <= r <= products["end"]:
                continue
            notes.append(f"{ref} tiene la fórmula de Excel {c['f'][:60]}: POS-PY no ejecuta fórmulas de Excel. "
                         "Vincúlela a un campo o cálculo, o se imprimirá el último valor guardado en el archivo.")
    if kind == "orden" and bindings["discount_pct"] == "0":
        bindings["discount_pct"] = "20"
        notes.append("Plantilla de ORDEN: descuento inicial del 20 % (configurable).")
    return bindings, notes


def _total_cell(layout: dict, row: int, fallback: str, products: dict | None) -> str:
    """En la zona de totales el valor suele estar en la columna del «valor» de los productos."""
    if products:
        value_col = next((k for k, v in products["columns"].items() if v.get("expr")), None)
        if value_col:
            return f"{value_col}{row}"
    return fallback

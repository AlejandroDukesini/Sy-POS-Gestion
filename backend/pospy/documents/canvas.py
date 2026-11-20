"""Plantillas de LIENZO (editor visual libre): modelo en milímetros y su compilación al modelo «layout».

El lienzo es la fuente de verdad del diseño: hoja física (80/58 mm, A4, carta o personalizada),
márgenes y elementos posicionados libremente (texto, variable, imagen, línea, rectángulo, espacio y la
tabla de productos). Para imprimir, previsualizar y generar Excel se COMPILA a una cuadrícula:

- Los bordes de todos los elementos definen las columnas y filas (anchos y altos exactos en mm).
- Cada texto o variable ocupa un rango combinado con su estilo; una variable es una vinculación.
- Líneas y rectángulos se vuelven bordes y rellenos de celdas; las imágenes quedan flotantes en su
  posición exacta (en Excel, como imágenes incrustadas).
- La tabla de productos es el bloque dinámico del motor: una fila de títulos y una fila modelo que se
  repite por cada producto; todo lo que está debajo se desplaza y el documento crece.

Así la vista previa (PDF), los documentos reales y el Excel salen del MISMO modelo y las MISMAS reglas
(engine.render). Las coordenadas del lienzo se miden desde la esquina superior izquierda del papel.
"""
from __future__ import annotations

import re
from typing import Any

from .engine import FIELDS, LINE_FIELDS
from .layout import LayoutError, cell_ref, col_letter, range_ref

PT_PER_MM = 72 / 25.4
PAPERS = {"roll80": (80.0, 0.0), "roll58": (58.0, 0.0), "a4": (210.0, 297.0), "letter": (215.9, 279.4), "custom": (0.0, 0.0)}
ELEMENT_TYPES = ("text", "variable", "image", "line", "rect", "spacer", "table")
HEADER_KEYS = {k for g in FIELDS.values() for k in g}
MONEY_FIELDS = {k for g in FIELDS.values() for k, (_, t) in g.items() if t == "money"} | {"precio", "precio_lista", "valor",
                                                                                          "descuento_linea"}
MAX_ELEMENTS = 300
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


# ------------------------------------------------------------------ modelo inicial
def default_canvas(paper: str = "roll80") -> dict:
    """Recibo inicial con variables reales del sistema (no contiene datos ficticios)."""
    w = PAPERS.get(paper, PAPERS["roll80"])[0] or 80.0
    inner = w - 6
    els = [
        _el("e1", "variable", 3, 4, inner, 7, field="empresa_nombre", text={"size": 13, "bold": True, "align": "center"}),
        _el("e2", "variable", 3, 11, inner, 5, field="empresa_nit", text={"size": 8, "align": "center"}),
        _el("e3", "variable", 3, 16, inner, 5, field="empresa_direccion", text={"size": 8, "align": "center"}),
        _el("e4", "line", 3, 23, inner, 1, line={"thickness": 0.75, "style": "dashed", "color": "#000000", "orientation": "h"}),
        _el("e5", "text", 3, 25, 18, 5, text={"content": "Número:", "size": 8, "bold": True}),
        _el("e6", "variable", 21, 25, inner - 18, 5, field="numero", text={"size": 8}),
        _el("e7", "text", 3, 30, 18, 5, text={"content": "Fecha:", "size": 8, "bold": True}),
        _el("e8", "variable", 21, 30, inner - 18, 5, field="fecha_hora_impresion", text={"size": 8}),
        _el("e9", "text", 3, 35, 18, 5, text={"content": "Cliente:", "size": 8, "bold": True}),
        _el("e10", "variable", 21, 35, inner - 18, 5, field="cliente_nombre", text={"size": 8}, fallback="CONSUMIDOR FINAL"),
        _el("e11", "table", 3, 42, inner, 11, table=default_table(inner)),
        _el("e12", "text", 3, 56, inner * 0.55, 5, text={"content": "Subtotal", "size": 9, "align": "right"}),
        _el("e13", "variable", 3 + inner * 0.55, 56, inner * 0.45, 5, field="subtotal", text={"size": 9, "align": "right"}),
        _el("e14", "text", 3, 61, inner * 0.55, 6, text={"content": "TOTAL", "size": 11, "bold": True, "align": "right"}),
        _el("e15", "variable", 3 + inner * 0.55, 61, inner * 0.45, 6, field="total", text={"size": 11, "bold": True, "align": "right"}),
        _el("e16", "variable", 3, 70, inner, 8, field="empresa_pie", text={"size": 7, "align": "center", "overflow": "wrap"}),
    ]
    return {"kind": "canvas", "v": 1, "page": default_page(paper), "grid": {"size_mm": 1, "snap": True, "show": True},
            "discount_pct": "0", "elements": els}


def default_page(paper: str = "roll80") -> dict:
    w, h = PAPERS.get(paper, PAPERS["roll80"])
    roll = paper.startswith("roll")
    return {"paper": paper if paper in PAPERS else "roll80", "width_mm": w or 80.0, "height_mm": h or 120.0,
            "orientation": "portrait", "unit": "mm", "auto_height": roll,
            "margins": {"t": 2.0, "r": 2.0, "b": 2.0, "l": 2.0} if roll else {"t": 10.0, "r": 10.0, "b": 10.0, "l": 10.0}}


def default_table(width: float) -> dict:
    cols = [("cantidad", "Cant", 0.14, "center"), ("descripcion", "Descripción", 0.46, "left"), ("precio", "V. unit", 0.2, "right"),
            ("valor", "Valor", 0.2, "right")]
    return {"columns": [{"field": f, "header": h, "width_mm": round(width * r, 2), "align": a} for f, h, r, a in cols],
            "header": {"show": True, "bold": True, "fill": "#EEEEEE", "size": 8}, "size": 8, "header_height_mm": 5,
            "row_height_mm": 5, "borders": "horizontal", "border_color": "#000000", "wrap": True}


def _el(eid: str, etype: str, x: float, y: float, w: float, h: float, **props) -> dict:
    base = {"id": eid, "type": etype, "x": round(x, 2), "y": round(y, 2), "w": round(w, 2), "h": round(h, 2), "z": int(eid[1:]),
            "locked": False, "hidden": False, "rotation": 0}
    if etype in ("text", "variable"):
        base["text"] = {"content": "", "font": "Arial", "size": 9, "bold": False, "italic": False, "underline": False,
                        "color": "#000000", "align": "left", "valign": "center", "overflow": "wrap", **props.pop("text", {})}
    base.update(props)
    return base


# ------------------------------------------------------------------ validación
def _num(v: Any, lo: float, hi: float, name: str, problems: list[str]) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        problems.append(f"{name}: no es un número.")
        return lo
    if x != x or not lo <= x <= hi:
        problems.append(f"{name}: debe estar entre {lo:g} y {hi:g}.")
        return max(lo, min(hi, x)) if x == x else lo
    return x


def _color(v: Any, default: str = "#000000") -> str:
    return str(v).upper() if v and _HEX.match(str(v)) else default


def sanitize_canvas(raw: Any, image_files: set[str]) -> dict:
    """Valida y normaliza un lienzo recibido del editor. Lanza LayoutError con los problemas."""
    problems: list[str] = []
    if not isinstance(raw, dict) or raw.get("kind") != "canvas":
        raise LayoutError(["El diseño del lienzo no es válido."])
    page_in = raw.get("page") if isinstance(raw.get("page"), dict) else {}
    paper = page_in.get("paper") if page_in.get("paper") in PAPERS else "roll80"
    page = default_page(paper)
    page["width_mm"] = round(_num(page_in.get("width_mm", page["width_mm"]), 30, 1200, "Ancho del papel (mm)", problems), 2)
    page["height_mm"] = round(_num(page_in.get("height_mm", page["height_mm"]), 20, 5000, "Alto del papel (mm)", problems), 2)
    page["orientation"] = "landscape" if page_in.get("orientation") == "landscape" else "portrait"
    page["unit"] = page_in.get("unit") if page_in.get("unit") in ("mm", "cm", "in") else "mm"
    page["auto_height"] = bool(page_in.get("auto_height")) if paper.startswith("roll") or paper == "custom" else False
    m = page_in.get("margins") if isinstance(page_in.get("margins"), dict) else {}
    page["margins"] = {k: round(_num(m.get(k, page["margins"][k]), 0, 60, "Márgenes (mm)", problems), 2) for k in ("t", "r", "b", "l")}
    if page["margins"]["l"] + page["margins"]["r"] >= page["width_mm"] - 5:
        problems.append("Los márgenes laterales no dejan espacio para imprimir.")
    grid_in = raw.get("grid") if isinstance(raw.get("grid"), dict) else {}
    grid = {"size_mm": round(_num(grid_in.get("size_mm", 1), 0.5, 20, "Cuadrícula (mm)", problems), 2),
            "snap": bool(grid_in.get("snap", True)), "show": bool(grid_in.get("show", True))}
    elements = []
    seen: set[str] = set()
    items = raw.get("elements") if isinstance(raw.get("elements"), list) else []
    if len(items) > MAX_ELEMENTS:
        raise LayoutError([f"El diseño admite hasta {MAX_ELEMENTS} elementos."])
    tables = 0
    for i, e in enumerate(items):
        if not isinstance(e, dict) or e.get("type") not in ELEMENT_TYPES:
            problems.append(f"Elemento {i + 1}: tipo no válido.")
            continue
        eid = re.sub(r"[^A-Za-z0-9_-]", "", str(e.get("id") or f"e{i + 1}"))[:20] or f"e{i + 1}"
        if eid in seen:
            eid = f"{eid}-{i}"
        seen.add(eid)
        label = f"Elemento {eid}"
        out: dict[str, Any] = {
            "id": eid, "type": e["type"],
            "x": round(_num(e.get("x", 0), -500, 1500, f"{label}: X", problems), 2),
            "y": round(_num(e.get("y", 0), -500, 6000, f"{label}: Y", problems), 2),
            "w": round(_num(e.get("w", 10), 0.2, 1500, f"{label}: ancho", problems), 2),
            "h": round(_num(e.get("h", 5), 0.2, 6000, f"{label}: alto", problems), 2),
            "z": int(_num(e.get("z", i), -10000, 10000, f"{label}: capa", problems)),
            "locked": bool(e.get("locked")), "hidden": bool(e.get("hidden")),
            "rotation": int(e.get("rotation") or 0) if int(e.get("rotation") or 0) in (0, 90, 270) else 0,
        }
        if e.get("name"):
            out["name"] = str(e["name"])[:60]
        if e["type"] in ("text", "variable"):
            t = e.get("text") if isinstance(e.get("text"), dict) else {}
            out["text"] = {
                "content": str(t.get("content") or "")[:2000], "font": str(t.get("font") or "Arial")[:40],
                "size": round(_num(t.get("size", 9), 4, 120, f"{label}: tamaño de letra", problems), 1),
                "bold": bool(t.get("bold")), "italic": bool(t.get("italic")), "underline": bool(t.get("underline")),
                "color": _color(t.get("color")), "align": t.get("align") if t.get("align") in ("left", "center", "right") else "left",
                "valign": t.get("valign") if t.get("valign") in ("top", "center", "bottom") else "center",
                "overflow": t.get("overflow") if t.get("overflow") in ("wrap", "shrink", "overflow") else "wrap",
                "fill": _color(t.get("fill"), "") if t.get("fill") else "",
            }
            if e["type"] == "variable":
                field = str(e.get("field") or "")
                if field not in HEADER_KEYS:
                    problems.append(f"{label}: variable desconocida «{field}».")
                out["field"] = field
                out["fallback"] = str(e.get("fallback") or "")[:200]
                out["format"] = str(e.get("format") or "")[:60]
        elif e["type"] == "image":
            img = e.get("image") if isinstance(e.get("image"), dict) else {}
            if img.get("file") not in image_files:
                problems.append(f"{label}: la imagen no existe en la plantilla. Vuelva a subirla.")
            crop = img.get("crop") if isinstance(img.get("crop"), dict) else {}
            out["image"] = {"file": img.get("file"), "keep_ratio": bool(img.get("keep_ratio", True)),
                            "crop": {k: round(_num(crop[k], 0, 0.9, f"{label}: recorte", problems), 4) for k in ("l", "t", "r", "b") if k in crop}}
        elif e["type"] == "line":
            ln = e.get("line") if isinstance(e.get("line"), dict) else {}
            out["line"] = {"orientation": "v" if ln.get("orientation") == "v" else "h",
                           "thickness": round(_num(ln.get("thickness", 0.75), 0.25, 6, f"{label}: grosor", problems), 2),
                           "style": ln.get("style") if ln.get("style") in ("solid", "dashed", "dotted", "double") else "solid",
                           "color": _color(ln.get("color"))}
        elif e["type"] == "rect":
            rc = e.get("rect") if isinstance(e.get("rect"), dict) else {}
            out["rect"] = {"border_width": round(_num(rc.get("border_width", 0.75), 0, 6, f"{label}: borde", problems), 2),
                           "border_style": rc.get("border_style") if rc.get("border_style") in ("solid", "dashed", "dotted") else "solid",
                           "border_color": _color(rc.get("border_color")), "fill": _color(rc.get("fill"), "") if rc.get("fill") else ""}
        elif e["type"] == "table":
            tables += 1
            out["table"] = _clean_table(e.get("table"), label, problems)
        elements.append(out)
    if tables > 1:
        problems.append("Solo puede haber una tabla de productos por plantilla.")
    try:
        pct = float(str(raw.get("discount_pct") or "0").replace(",", "."))
        if not 0 <= pct <= 100:
            raise ValueError
    except ValueError:
        problems.append("El descuento de la plantilla debe estar entre 0 y 100.")
        pct = 0.0
    if problems:
        raise LayoutError(problems[:30])
    return {"kind": "canvas", "v": 1, "page": page, "grid": grid, "discount_pct": f"{pct:g}", "elements": elements}


def _clean_table(raw: Any, label: str, problems: list[str]) -> dict:
    t = raw if isinstance(raw, dict) else {}
    cols = []
    for j, c in enumerate((t.get("columns") or [])[:8]):
        if not isinstance(c, dict):
            continue
        field = str(c.get("field") or "")
        if field not in LINE_FIELDS:
            problems.append(f"{label}: columna {j + 1} con dato desconocido «{field}».")
            continue
        cols.append({"field": field, "header": str(c.get("header") or LINE_FIELDS[field][0])[:40],
                     "width_mm": round(_num(c.get("width_mm", 10), 2, 1000, f"{label}: ancho de columna", problems), 2),
                     "align": c.get("align") if c.get("align") in ("left", "center", "right") else "left"})
    if not cols:
        problems.append(f"{label}: la tabla de productos necesita al menos una columna.")
    header = t.get("header") if isinstance(t.get("header"), dict) else {}
    return {"columns": cols,
            "header": {"show": bool(header.get("show", True)), "bold": bool(header.get("bold", True)),
                       "fill": _color(header.get("fill"), "") if header.get("fill") else "",
                       "size": round(_num(header.get("size", 8), 4, 40, f"{label}: tamaño de títulos", problems), 1)},
            "size": round(_num(t.get("size", 8), 4, 40, f"{label}: tamaño de letra", problems), 1),
            "header_height_mm": round(_num(t.get("header_height_mm", 5), 2, 60, f"{label}: alto de títulos", problems), 2),
            "row_height_mm": round(_num(t.get("row_height_mm", 5), 2, 60, f"{label}: alto de fila", problems), 2),
            "borders": t.get("borders") if t.get("borders") in ("none", "horizontal", "all") else "horizontal",
            "border_color": _color(t.get("border_color")), "wrap": bool(t.get("wrap", True))}


# ------------------------------------------------------------------ compilación al modelo «layout»
def _border_style(thickness: float, style: str) -> str:
    if style == "double":
        return "double"
    if style == "dashed":
        return "dashed" if thickness < 1 else "mediumDashed"
    if style == "dotted":
        return "dotted"
    return "thin" if thickness <= 0.6 else "medium" if thickness <= 1.4 else "thick"


def _width_chars(mm: float) -> float:
    """Ancho en mm → unidades de carácter de Excel (inversa de layout.col_points)."""
    px = round(mm * PT_PER_MM / 0.75)
    if px <= 0:
        return 0.0
    return round(px / 12, 4) if px < 12 else round((px - 5) / 7, 4)


def _edges(values: list[float], lo: float, hi: float) -> list[float]:
    pts = sorted({round(min(max(v, lo), hi), 1) for v in values} | {lo, hi})
    out = [pts[0]]
    for p in pts[1:]:
        if p - out[-1] >= 0.3:          # bordes casi iguales se unifican (evita columnas diminutas)
            out.append(p)
        else:
            out[-1] = p if p == hi else out[-1]
    if out[-1] != hi:
        out[-1] = hi
    return out


def _index(edges: list[float], v: float) -> int:
    """Índice (0 = primera columna/fila) del borde más cercano a v."""
    return min(range(len(edges)), key=lambda i: abs(edges[i] - v))


def content_height(canvas: dict) -> float:
    """Alto ocupado por el contenido (mm, desde el borde del papel) + margen inferior."""
    bottom = max((e["y"] + e["h"] for e in canvas["elements"] if not e.get("hidden")), default=20.0)
    return round(bottom + canvas["page"]["margins"]["b"], 2)


def compile_canvas(canvas: dict) -> tuple[dict, dict, list[str]]:
    """Lienzo → (layout, vinculaciones, avisos). El layout usa el mismo motor que las plantillas de Excel."""
    page = canvas["page"]
    m = page["margins"]
    width = page["width_mm"] if page["orientation"] == "portrait" or page["paper"].startswith("roll") else page["height_mm"]
    height = page["height_mm"] if page["orientation"] == "portrait" or page["paper"].startswith("roll") else page["width_mm"]
    if page.get("auto_height"):
        height = max(content_height(canvas), 30.0)
    area_w, area_h = width - m["l"] - m["r"], height - m["t"] - m["b"]
    notes: list[str] = []
    visible = sorted([e for e in canvas["elements"] if not e.get("hidden")], key=lambda e: e.get("z", 0))
    boxes = []
    for e in visible:
        x, y = e["x"] - m["l"], e["y"] - m["t"]
        if x < -0.5 or y < -0.5 or x + e["w"] > area_w + 0.5 or (not page.get("auto_height") and y + e["h"] > area_h + 0.5):
            notes.append(f"«{e.get('name') or e['id']}» sale del área imprimible: se recorta al borde.")
        boxes.append((e, max(0.0, x), max(0.0, y), min(area_w, x + e["w"]), max(0.0, min(area_h, y + e["h"]) if not page.get("auto_height") else y + e["h"])))
    xs, ys = [], []
    for e, x1, y1, x2, y2 in boxes:
        if e["type"] == "image":
            continue
        xs += [x1, x2]
        ys += [y1, y2]
        if e["type"] == "table":
            t = e["table"]
            acc = x1
            for c in t["columns"]:
                acc += c["width_mm"]
                xs.append(min(acc, x2))
            hh = t["header_height_mm"] if t["header"]["show"] else 0
            ys += [y1 + hh, y1 + hh + t["row_height_mm"]]
    xe = _edges(xs, 0.0, round(area_w, 1))
    ye = _edges(ys, 0.0, round(max(area_h, max((b[4] for b in boxes), default=0.0)), 1))
    cols = [_width_chars(xe[i + 1] - xe[i]) for i in range(len(xe) - 1)] or [10.0]
    rows = [round((ye[i + 1] - ye[i]) * PT_PER_MM, 2) for i in range(len(ye) - 1)] or [15.0]
    styles: list[dict] = [{}]
    style_ix: dict[str, int] = {"{}": 0}
    cells: dict[str, dict] = {}
    merges: list[str] = []
    taken: dict[tuple[int, int], str] = {}
    bindings: dict[str, Any] = {"cells": {}, "products": None, "discount_pct": canvas.get("discount_pct") or "0"}
    images: list[dict] = []

    def sid(st: dict) -> int:
        key = repr(sorted(st.items()))
        if key not in style_ix:
            style_ix[key] = len(styles)
            styles.append(st)
        return style_ix[key]

    def patch_style(r: int, c: int, fn) -> None:
        ref = cell_ref(r, c)
        cell = cells.setdefault(ref, {})
        st = dict(styles[cell.get("s", 0)])
        st = fn(st)
        cell["s"] = sid(st)

    def rect_cells(x1: float, y1: float, x2: float, y2: float) -> tuple[int, int, int, int]:
        c1, c2 = _index(xe, x1) + 1, max(_index(xe, x2), _index(xe, x1) + 1)
        r1, r2 = _index(ye, y1) + 1, max(_index(ye, y2), _index(ye, y1) + 1)
        return r1, c1, r2, c2

    def place(e: dict, r1: int, c1: int, r2: int, c2: int) -> bool:
        area = [(r, c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)]
        clash = {taken[p] for p in area if p in taken}
        if clash:
            notes.append(f"«{e.get('name') or e['id']}» se superpone con otro elemento con texto: en Excel queda solo el de "
                         "la capa superior. Sepárelos para conservar ambos.")
            for p in area:
                if p in taken:
                    owner = taken[p]
                    merges[:] = [mg for mg in merges if not mg.startswith(owner + "|")]
        for p in area:
            taken[p] = e["id"]
        if (r1, c1) != (r2, c2):
            merges.append(f"{e['id']}|{range_ref(r1, c1, r2, c2)}")
        return True

    def text_style(t: dict, extra: dict | None = None) -> dict:
        font = {"size": t["size"]}
        if t.get("font") and t["font"] != "Calibri":
            font["name"] = t["font"]
        for k_src, k_dst in (("bold", "b"), ("italic", "i"), ("underline", "u")):
            if t.get(k_src):
                font[k_dst] = True
        if t.get("color") and t["color"] != "#000000":
            font["color"] = t["color"]
        st = {"font": font, "h": t.get("align", "left"), "v": t.get("valign", "center")}
        if t.get("overflow") == "wrap":
            st["wrap"] = True
        elif t.get("overflow") == "shrink":
            st["shrink"] = True
        if t.get("fill"):
            st["fill"] = t["fill"]
        st.update(extra or {})
        return st

    for e, x1, y1, x2, y2 in boxes:
        kind = e["type"]
        if kind == "spacer":
            continue
        if kind == "image":
            ci = max(0, _index(xe, x1) if xe[_index(xe, x1)] <= x1 else _index(xe, x1) - 1)
            ri = max(0, _index(ye, y1) if ye[_index(ye, y1)] <= y1 else _index(ye, y1) - 1)
            crop = e["image"].get("crop") or {}
            images.append({"id": e["id"], "file": e["image"]["file"], "col": ci, "row": ri,
                           "col_off": round((x1 - xe[ci]) * PT_PER_MM, 2), "row_off": round((y1 - ye[ri]) * PT_PER_MM, 2),
                           "w": round((x2 - x1) * PT_PER_MM, 2), "h": round((y2 - y1) * PT_PER_MM, 2), "crop": crop})
            continue
        r1, c1, r2, c2 = rect_cells(x1, y1, x2, y2)
        if kind in ("text", "variable"):
            t = e["text"]
            extra = {}
            if e.get("rotation"):
                extra["rot"] = e["rotation"]
            if kind == "variable":
                fmt = e.get("format") or ('"$"#,##0' if e["field"] in MONEY_FIELDS else "")
                if fmt:
                    extra["fmt"] = fmt
            place(e, r1, c1, r2, c2)
            ref = cell_ref(r1, c1)
            cells[ref] = {"s": sid(text_style(t, extra))}
            if kind == "text":
                if t["content"]:
                    cells[ref]["v"] = t["content"]
            else:
                b = {"field": e["field"]}
                if e.get("fallback"):
                    b["fallback"] = e["fallback"]
                if e.get("format") and FIELDS.get("Operación", {}).get(e["field"], ("", ""))[1] in ("date", "time", "datetime"):
                    b["format"] = e["format"]
                bindings["cells"][ref] = b
                label = next((lbl for g in FIELDS.values() for k, (lbl, _) in g.items() if k == e["field"]), e["field"])
                cells[ref]["v"] = "{" + label + "}"
            for r in range(r1, r2 + 1):
                for c in range(c1, c2 + 1):
                    if (r, c) != (r1, c1) and t.get("fill"):
                        patch_style(r, c, lambda st, f=t["fill"]: {**st, "fill": f})
        elif kind == "line":
            ln = e["line"]
            style = [_border_style(ln["thickness"], ln["style"]), ln["color"]]
            if ln["orientation"] == "h":
                yy = (y1 + y2) / 2
                r = _index(ye, yy)
                for c in range(c1, c2 + 1):
                    if r >= 1:
                        patch_style(r, c, lambda st, s_=style: {**st, "border": {**(st.get("border") or {}), "b": s_}})
                    else:
                        patch_style(1, c, lambda st, s_=style: {**st, "border": {**(st.get("border") or {}), "t": s_}})
            else:
                xx = (x1 + x2) / 2
                c = _index(xe, xx)
                for r in range(r1, r2 + 1):
                    if c >= 1:
                        patch_style(r, c, lambda st, s_=style: {**st, "border": {**(st.get("border") or {}), "r": s_}})
                    else:
                        patch_style(r, 1, lambda st, s_=style: {**st, "border": {**(st.get("border") or {}), "l": s_}})
        elif kind == "rect":
            rc = e["rect"]
            style = [_border_style(rc["border_width"], rc["border_style"]), rc["border_color"]] if rc["border_width"] > 0 else None
            for r in range(r1, r2 + 1):
                for c in range(c1, c2 + 1):
                    def fn(st, r=r, c=c, rc=rc, style=style, r1=r1, r2=r2, c1=c1, c2=c2):
                        st = dict(st)
                        if rc.get("fill"):
                            st["fill"] = rc["fill"]
                        if style:
                            b = dict(st.get("border") or {})
                            if r == r1:
                                b["t"] = style
                            if r == r2:
                                b["b"] = style
                            if c == c1:
                                b["l"] = style
                            if c == c2:
                                b["r"] = style
                            st["border"] = b
                        return st
                    patch_style(r, c, fn)
        elif kind == "table":
            t = e["table"]
            hh = t["header_height_mm"] if t["header"]["show"] else 0
            header_row = _index(ye, y1) + 1 if hh else 0
            prow = _index(ye, y1 + hh) + 1
            line = [_border_style(0.5, "solid"), t["border_color"]]
            acc = x1
            product_cols: dict[str, dict] = {}
            for col in t["columns"]:
                a, acc = acc, min(acc + col["width_mm"], x2)
                ca, cb = _index(xe, a) + 1, max(_index(xe, acc), _index(xe, a) + 1)
                letter = col_letter(ca)
                money = col["field"] in MONEY_FIELDS
                b_all = t["borders"] == "all"
                border = {"b": line} if t["borders"] != "none" else {}
                if b_all:
                    border = {"t": line, "b": line, "l": line, "r": line}
                if header_row:
                    hst = {"font": {"size": t["header"]["size"], **({"b": True} if t["header"]["bold"] else {})},
                           "h": col["align"], "v": "center", "wrap": True, **({"fill": t["header"]["fill"]} if t["header"]["fill"] else {}),
                           **({"border": border} if border else {})}
                    for c in range(ca, cb + 1):
                        taken[(header_row, c)] = e["id"]
                        cells[cell_ref(header_row, c)] = {"s": sid(hst)}
                    cells[cell_ref(header_row, ca)]["v"] = col["header"]
                    if cb > ca:
                        merges.append(f"{e['id']}|{range_ref(header_row, ca, header_row, cb)}")
                pst = {"font": {"size": t["size"]}, "h": col["align"], "v": "top" if t["wrap"] else "center",
                       **({"wrap": True} if t["wrap"] and not money else {}), **({"fmt": '"$"#,##0'} if money else {}),
                       **({"border": border} if border else {})}
                for c in range(ca, cb + 1):
                    taken[(prow, c)] = e["id"]
                    cells[cell_ref(prow, c)] = {"s": sid(pst)}
                if cb > ca:
                    merges.append(f"{e['id']}|{range_ref(prow, ca, prow, cb)}")
                product_cols[letter] = {"expr": "cantidad*precio"} if col["field"] == "valor" else {"field": col["field"]}
            bindings["products"] = {"start": prow, "end": prow, "header_row": header_row, "columns": product_cols, "merge_rows": True}
    layout = {
        "v": 1, "cols": cols, "rows": rows, "cells": cells, "styles": styles,
        "merges": [m.split("|", 1)[1] for m in merges], "images": images,
        "page": {"paper": "roll80" if page["paper"] == "roll80" else "roll58" if page["paper"] == "roll58" else
                 page["paper"] if page["paper"] in ("a4", "letter") else "custom",
                 "orientation": page["orientation"], "width_mm": width, "height_mm": 0 if page.get("auto_height") else height,
                 "margins": {k: round(v / 10, 3) for k, v in m.items()}, "scale": 100, "fit_width": False,
                 "print_area": range_ref(1, 1, len(rows), len(cols)),
                 "repeat_rows": f"{bindings['products']['header_row']}:{bindings['products']['header_row']}"
                 if bindings["products"] and bindings["products"]["header_row"] else "",
                 "header": "", "footer": "", "row_breaks": [], "hide_gridlines": True},
    }
    if layout["page"]["paper"] == "custom" and page.get("auto_height"):
        layout["page"]["paper"] = "custom"
        layout["page"]["height_mm"] = 0
    return layout, bindings, notes

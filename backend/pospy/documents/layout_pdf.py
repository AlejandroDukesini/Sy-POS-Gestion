"""PDF de un diseño ya completado (layout), sin dependencias externas.

Dibuja rellenos, texto (Helvetica, compatible en métricas con Arial), bordes por lado, celdas
combinadas e imágenes JPEG/PNG con su recorte. Pagina sin cortar filas ni celdas combinadas,
repite las filas de encabezado configuradas y respeta saltos de página manuales. El papel de rollo
(80 o 58 mm) es una sola tira continua del alto del contenido.

Limitaciones conocidas: las fuentes se sustituyen por Helvetica; no hay texto girado, degradados,
formato condicional ni gráficos de Excel.
"""
from __future__ import annotations

import re
import struct
import zlib
from typing import Any

from .layout import PAPERS_MM, cell_ref, col_points, format_value, parse_range
from .simple_pdf import _escape, text_width

MM = 72 / 25.4
CM = 72 / 2.54
MAX_PAGE_PT = 14000          # límite práctico de alto de página PDF (rollo continuo)
PAD = 2.0
BORDER_W = {"hair": 0.25, "thin": 0.5, "dotted": 0.5, "dashed": 0.5, "dashDot": 0.5, "dashDotDot": 0.5,
            "medium": 1.0, "mediumDashed": 1.0, "mediumDashDot": 1.0, "mediumDashDotDot": 1.0, "slantDashDot": 1.0,
            "thick": 1.5, "double": 1.5}
DASH = {"dotted": "[1 1]", "dashed": "[3 2]", "mediumDashed": "[4 2]", "dashDot": "[3 1 1 1]", "mediumDashDot": "[4 1 1 1]",
        "dashDotDot": "[3 1 1 1 1 1]", "mediumDashDotDot": "[4 1 1 1 1 1]", "slantDashDot": "[4 1 1 1]"}


def _rgb(color: str | None, default: tuple[float, float, float] = (0, 0, 0)) -> tuple[float, float, float]:
    if not color or not isinstance(color, str) or len(color) != 7:
        return default
    try:
        return tuple(int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))  # type: ignore[return-value]
    except ValueError:
        return default


# ------------------------------------------------------------------ imágenes
class ImageError(ValueError):
    pass


def _jpeg_info(data: bytes) -> tuple[int, int, int, bool]:
    i, adobe = 2, False
    if data[:2] != b"\xff\xd8":
        raise ImageError("JPEG no válido")
    while i < len(data) - 9:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker == 0xEE and data[i + 4:i + 9] == b"Adobe":
            adobe = True
        if marker in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            comps = data[i + 9]
            return w, h, comps, adobe
        i += 2 + length
    raise ImageError("JPEG sin dimensiones")


def _unfilter(raw: bytes, width: int, height: int, bpp: int) -> bytes:
    stride = width * bpp
    out = bytearray()
    prev = bytearray(stride)
    pos = 0
    for _ in range(height):
        ftype = raw[pos]
        line = bytearray(raw[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            if ftype == 1:
                line[x] = (line[x] + a) & 0xFF
            elif ftype == 2:
                line[x] = (line[x] + b) & 0xFF
            elif ftype == 3:
                line[x] = (line[x] + ((a + b) >> 1)) & 0xFF
            elif ftype == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 0xFF
        out += line
        prev = line
    return bytes(out)


def _png_objects(data: bytes) -> tuple[dict, bytes | None]:
    """Devuelve (diccionario de la imagen + flujo, máscara alfa) para un PNG de 8 bits sin entrelazado."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ImageError("PNG no válido")
    pos, idat, plte = 8, bytearray(), b""
    width = height = depth = ctype = interlace = 0
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", chunk)
        elif kind == b"PLTE":
            plte = chunk
        elif kind == b"IDAT":
            idat += chunk
        pos += 12 + length
    if depth != 8 or interlace:
        raise ImageError("PNG con profundidad distinta de 8 bits o entrelazado")
    if ctype in (0, 2, 3):
        colors = {0: 1, 2: 3, 3: 1}[ctype]
        space = (b"/DeviceGray" if ctype == 0 else b"/DeviceRGB" if ctype == 2 else
                 b"[/Indexed /DeviceRGB %d <%s>]" % (len(plte) // 3 - 1, plte.hex().encode()))
        return {"w": width, "h": height, "space": space, "bpc": 8, "filter": b"/FlateDecode",
                "parms": b"<< /Predictor 15 /Colors %d /BitsPerComponent 8 /Columns %d >>" % (colors, width),
                "data": bytes(idat)}, None
    if ctype in (4, 6):
        bpp = 2 if ctype == 4 else 4
        pixels = _unfilter(zlib.decompress(bytes(idat)), width, height, bpp)
        color = bytearray()
        alpha = bytearray()
        n = bpp - 1
        for i in range(0, len(pixels), bpp):
            color += pixels[i:i + n]
            alpha.append(pixels[i + n])
        return {"w": width, "h": height, "space": b"/DeviceGray" if ctype == 4 else b"/DeviceRGB", "bpc": 8,
                "filter": b"/FlateDecode", "parms": b"", "data": zlib.compress(bytes(color))}, zlib.compress(bytes(alpha))
    raise ImageError("Tipo de PNG no soportado")


# ------------------------------------------------------------------ geometría y paginación
class _Geometry:
    def __init__(self, layout: dict):
        self.layout = layout
        page = layout.get("page") or {}
        area = page.get("print_area") or f"A1:{_last_ref(layout)}"
        self.r1, self.c1, self.r2, self.c2 = parse_range(area)
        self.r2 = min(self.r2, len(layout["rows"]))
        self.c2 = min(self.c2, len(layout["cols"]))
        self.colw = [0.0] + [col_points(w) for w in layout["cols"]]
        self.rowh = [0.0] + [float(h) for h in layout["rows"]]
        self.colx = [0.0] * (len(self.colw) + 1)          # x de la columna c (desde la columna 1)
        for c in range(1, len(self.colw)):
            self.colx[c + 1] = self.colx[c] + self.colw[c]
        self.merge_of: dict[tuple[int, int], tuple[int, int, int, int]] = {}
        for m in layout.get("merges", []):
            a1, b1, a2, b2 = parse_range(m)
            for r in range(a1, a2 + 1):
                for c in range(b1, b2 + 1):
                    self.merge_of[(r, c)] = (a1, b1, a2, b2)
        self.width = self.colx[self.c2 + 1] - self.colx[self.c1]

    def x(self, c: int) -> float:
        return self.colx[c] - self.colx[self.c1]


def _last_ref(layout: dict) -> str:
    return cell_ref(max(1, len(layout["rows"])), max(1, len(layout["cols"])))


def _paper(page: dict) -> tuple[float, float, bool]:
    paper = page.get("paper") or "letter"
    if paper == "custom":
        w, h = float(page.get("width_mm") or 215.9), float(page.get("height_mm") or 279.4)
    else:
        w, h = PAPERS_MM.get(paper, PAPERS_MM["letter"])
    roll = paper.startswith("roll") or h == 0
    w_pt, h_pt = w * MM, h * MM
    if page.get("orientation") == "landscape" and not roll:
        w_pt, h_pt = h_pt, w_pt
    return w_pt, h_pt, roll


def paginate(geo: _Geometry, avail: float, repeat: tuple[int, int] | None, breaks: set[int],
             repeat_until: int = 0) -> list[list[int]]:
    """Filas de cada página (sin cortar filas ni combinaciones verticales). Las filas de encabezado se repiten
    en las páginas siguientes mientras queden filas de la tabla (repeat_until = última fila de productos)."""
    pages: list[list[int]] = []
    current: list[int] = []
    used = 0.0
    rep_rows = [r for r in range(repeat[0], repeat[1] + 1)] if repeat else []
    rep_h = sum(geo.rowh[r] for r in rep_rows if r <= geo.r2)
    r = geo.r1
    while r <= geo.r2:
        # bloque indivisible: la fila más las filas de una combinación vertical que empieza en ella
        end = r
        for c in range(geo.c1, geo.c2 + 1):
            m = geo.merge_of.get((r, c))
            if m and m[0] == r:
                end = max(end, min(m[2], geo.r2))
        block = list(range(r, end + 1))
        bh = sum(geo.rowh[x] for x in block)
        if current and used + bh > avail:
            pages.append(current)
            current = [x for x in rep_rows if x < r] if not repeat_until or r <= repeat_until else []
            used = rep_h if current else 0.0
        current += block
        used += bh
        if any(x in breaks for x in block) and r != geo.r2:
            pages.append(current)
            current = [x for x in rep_rows if x <= end] if not repeat_until or end < repeat_until else []
            used = sum(geo.rowh[x] for x in current)
        r = end + 1
    if current:
        pages.append(current)
    return pages or [[]]


# ------------------------------------------------------------------ dibujo
class _Canvas:
    def __init__(self):
        self.ops: list[bytes] = []

    def add(self, op: bytes) -> None:
        self.ops.append(op)


def _font_ref(font: dict) -> bytes:
    b, i = bool(font.get("b")), bool(font.get("i"))
    return b"/F4" if b and i else b"/F2" if b else b"/F3" if i else b"/F1"


def _wrap(text: str, size: float, width: float, bold: bool) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        current = ""
        for word in paragraph.split(" "):
            candidate = f"{current} {word}" if current else word
            if text_width(candidate, size, bold) <= width or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def _draw_page(cv: _Canvas, geo: _Geometry, rows: list[int], layout: dict, image_names: dict[str, bytes]) -> None:
    """Dibuja las filas en coordenadas del diseño (x a la derecha, y hacia abajo; se invierte con -y)."""
    styles = layout["styles"]
    cells = layout["cells"]
    ypos: dict[int, float] = {}
    y = 0.0
    for r in rows:
        ypos[r] = y
        y += geo.rowh[r]
    on_page = set(rows)

    def style_of(r: int, c: int) -> dict:
        cell = cells.get(_ref(r, c)) or {}
        s = cell.get("s", 0)
        return styles[s] if isinstance(s, int) and 0 <= s < len(styles) else {}

    def region(r: int, c: int) -> tuple[float, float, float, float] | None:
        m = geo.merge_of.get((r, c))
        if m:
            if (r, c) != (m[0], m[1]):
                return None
            rws = [x for x in range(m[0], m[2] + 1) if x in on_page]
            x0, x1 = geo.x(m[1]), geo.x(min(m[3], geo.c2) + 1)
            return x0, ypos[r], x1 - x0, sum(geo.rowh[x] for x in rws)
        return geo.x(c), ypos[r], geo.colw[c], geo.rowh[r]

    visible_cols = [c for c in range(geo.c1, geo.c2 + 1) if geo.colw[c] > 0]

    def free(r: int, c: int) -> bool:
        cell = cells.get(_ref(r, c)) or {}
        return geo.c1 <= c <= geo.c2 and (r, c) not in geo.merge_of and cell.get("v") in (None, "")

    def overflow_box(r: int, c: int, box: tuple, value: Any, st: dict) -> tuple:
        """Como Excel: el texto sin ajuste se extiende sobre celdas vacías vecinas; los números no se desbordan."""
        if st.get("wrap") or not isinstance(value, str) or (r, c) in geo.merge_of:
            return box
        bx, by, bw, bh = box
        align = st.get("h") or "left"
        left, right = c, c
        if align in ("left", "center"):
            while free(r, right + 1):
                right += 1
        if align in ("right", "center"):
            while free(r, left - 1):
                left -= 1
        x0, x1 = geo.x(left), geo.x(right) + geo.colw[right]
        return x0, by, x1 - x0, bh

    # 1. rellenos
    for r in rows:
        if geo.rowh[r] <= 0:
            continue
        for c in visible_cols:
            st = style_of(r, c)
            if st.get("fill") and (box := region(r, c)):
                cr, cg, cb = _rgb(st["fill"], (1, 1, 1))
                bx, by, bw, bh = box
                cv.add(b"%.3f %.3f %.3f rg %.2f %.2f %.2f %.2f re f" % (cr, cg, cb, bx, -(by + bh), bw, bh))
    # 2. texto
    for r in rows:
        if geo.rowh[r] <= 0:
            continue
        for c in visible_cols:
            cell = cells.get(_ref(r, c))
            if not cell or cell.get("v") in (None, ""):
                continue
            box = region(r, c)
            if not box:
                continue
            st = style_of(r, c)
            _draw_text(cv, cell["v"], st, box, overflow_box(r, c, box, cell["v"], st))
    # 3. bordes (los lados interiores de una combinación no se dibujan)
    for r in rows:
        if geo.rowh[r] <= 0:
            continue
        for c in visible_cols:
            border = style_of(r, c).get("border") or {}
            if not border:
                continue
            x0, x1 = geo.x(c), geo.x(c) + geo.colw[c]
            y0, y1 = ypos[r], ypos[r] + geo.rowh[r]
            m = geo.merge_of.get((r, c))
            for side, (style, color) in border.items():
                if m and ((side == "l" and c != m[1]) or (side == "r" and c != m[3])
                          or (side == "t" and r != m[0]) or (side == "b" and r != m[2])):
                    continue
                seg = {"l": (x0, y0, x0, y1), "r": (x1, y0, x1, y1), "t": (x0, y0, x1, y0), "b": (x0, y1, x1, y1)}[side]
                cr, cg, cb = _rgb(color)
                dash = DASH.get(style, "[]").encode()
                cv.add(b"%.3f %.3f %.3f RG %.2f w %s 0 d %.2f %.2f m %.2f %.2f l S" % (
                    cr, cg, cb, BORDER_W.get(style, 0.5), dash, seg[0], -seg[1], seg[2], -seg[3]))
    cv.add(b"[] 0 d")
    # 4. imágenes (sobre las celdas, como en Excel)
    for img in layout.get("images", []):
        row = img["row"] + 1
        if row not in ypos or img["file"] not in image_names:
            continue
        col = img["col"] + 1
        if col < geo.c1 or col > geo.c2:
            continue
        x = geo.x(col) + img.get("col_off", 0)
        y = ypos[row] + img.get("row_off", 0)
        w, h = img["w"], img["h"]
        crop = img.get("crop") or {}
        fw = w / max(0.01, 1 - crop.get("l", 0) - crop.get("r", 0))
        fh = h / max(0.01, 1 - crop.get("t", 0) - crop.get("b", 0))
        ix, iy = x - crop.get("l", 0) * fw, y - crop.get("t", 0) * fh
        name = image_names[img["file"]]
        cv.add(b"q %.2f %.2f %.2f %.2f re W n %.2f 0 0 %.2f %.2f %.2f cm /%s Do Q" % (
            x, -(y + h), w, h, fw, fh, ix, -(iy + fh), name))


def _ref(r: int, c: int) -> str:
    return cell_ref(r, c)


def _draw_text(cv: _Canvas, value: Any, st: dict, box: tuple[float, float, float, float],
               clip_box: tuple[float, float, float, float] | None = None) -> None:
    font = st.get("font") or {}
    size = float(font.get("size") or 11)
    bold = bool(font.get("b"))
    text = format_value(value, st.get("fmt")) if not isinstance(value, str) else value
    if not text:
        return
    numeric = not isinstance(value, str)
    bx, by, bw, bh = box
    h_align = st.get("h") or ("right" if numeric else "left")
    v_align = st.get("v") or "bottom"
    lines = _wrap(text, size, max(1.0, bw - 2 * PAD), bold) if st.get("wrap") else text.split("\n")
    leading = size * 1.17
    block = leading * len(lines)
    if v_align == "top":
        top = by + PAD
    elif v_align == "center":
        top = by + (bh - block) / 2
    else:
        top = by + bh - PAD - block
    cr, cg, cb = _rgb(font.get("color"))
    cx, cy, cw, ch = clip_box or box
    cv.add(b"q %.2f %.2f %.2f %.2f re W n" % (cx, -(cy + ch), cw, ch))
    for i, ln in enumerate(lines):
        tw = text_width(ln, size, bold)
        if h_align == "center":
            tx = bx + (bw - tw) / 2
        elif h_align == "right":
            tx = bx + bw - PAD - tw
        else:
            tx = bx + PAD
        baseline = top + leading * i + size * 0.93
        cv.add(b"BT %s %.2f Tf %.3f %.3f %.3f rg %.2f %.2f Td (%s) Tj ET" % (
            _font_ref(font), size, cr, cg, cb, tx, -baseline, _escape(ln)))
        if font.get("u"):
            cv.add(b"%.3f %.3f %.3f RG %.2f w %.2f %.2f m %.2f %.2f l S" % (
                cr, cg, cb, max(0.4, size / 18), tx, -(baseline + size * 0.12), tx + tw, -(baseline + size * 0.12)))
    cv.add(b"Q")


# ------------------------------------------------------------------ documento
def render_pdf(layout: dict, images: dict[str, bytes] | None = None, title: str = "Documento") -> tuple[bytes, list[str]]:
    """PDF del diseño ya completado. Devuelve (bytes, avisos)."""
    images = images or {}
    notes: list[str] = []
    page = layout.get("page") or {}
    geo = _Geometry(layout)
    pw, ph, roll = _paper(page)
    margins = page.get("margins") or {}
    ml, mr = float(margins.get("l", 1.5)) * CM, float(margins.get("r", 1.5)) * CM
    mt, mb = float(margins.get("t", 1.5)) * CM, float(margins.get("b", 1.5)) * CM
    printable_w = max(36.0, pw - ml - mr)
    scale = max(0.1, min(4.0, float(page.get("scale") or 100) / 100))
    if page.get("fit_width"):                      # como Excel: ajustar al ancho solo reduce, nunca amplía
        scale = min(1.0, printable_w / max(1.0, geo.width))
    elif geo.width * scale > printable_w + 0.5:
        scale = printable_w / max(1.0, geo.width)
        notes.append("El diseño no cabía en el ancho del papel con la escala configurada: se ajustó al ancho.")
    header_h = 10.0 if page.get("header") else 0.0
    footer_h = 10.0 if page.get("footer") else 0.0
    repeat = None
    if page.get("repeat_rows"):
        try:
            a, b = (int(x) for x in str(page["repeat_rows"]).split(":"))
            repeat = (min(a, b), max(a, b))
        except ValueError:
            notes.append("Las filas que se repiten no son válidas; se ignoran.")
    breaks = set(int(b) for b in page.get("row_breaks") or [])
    if roll:
        avail = (MAX_PAGE_PT - mt - mb - header_h - footer_h) / scale
    else:
        avail = max(20.0, (ph - mt - mb - header_h - footer_h) / scale)
    pages = paginate(geo, avail, repeat, breaks, int(page.get("repeat_until") or 0))

    # recursos de imagen
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog = add(b"")
    pages_id = add(b"")
    fonts = [add(b"<< /Type /Font /Subtype /Type1 /BaseFont /%s /Encoding /WinAnsiEncoding >>" % n)
             for n in (b"Helvetica", b"Helvetica-Bold", b"Helvetica-Oblique", b"Helvetica-BoldOblique")]
    xobjects: dict[str, bytes] = {}
    xobject_refs: dict[bytes, int] = {}
    for i, (fname, data) in enumerate(images.items(), start=1):
        name = b"Im%d" % i
        try:
            if data[:2] == b"\xff\xd8":
                w, h, comps, adobe = _jpeg_info(data)
                space = {1: b"/DeviceGray", 3: b"/DeviceRGB", 4: b"/DeviceCMYK"}.get(comps, b"/DeviceRGB")
                decode = b" /Decode [1 0 1 0 1 0 1 0]" if comps == 4 and adobe else b""
                ref = add(b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace %s /BitsPerComponent 8"
                          b" /Filter /DCTDecode%s /Length %d >>\nstream\n" % (w, h, space, decode, len(data)) + data + b"\nendstream")
            else:
                info, alpha = _png_objects(data)
                smask = b""
                if alpha is not None:
                    sm = add(b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceGray"
                             b" /BitsPerComponent 8 /Filter /FlateDecode /Length %d >>\nstream\n" % (
                                 info["w"], info["h"], len(alpha)) + alpha + b"\nendstream")
                    smask = b" /SMask %d 0 R" % sm
                parms = b" /DecodeParms %s" % info["parms"] if info["parms"] else b""
                ref = add(b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace %s /BitsPerComponent 8"
                          b" /Filter %s%s%s /Length %d >>\nstream\n" % (info["w"], info["h"], info["space"], info["filter"],
                                                                        parms, smask, len(info["data"]))
                          + info["data"] + b"\nendstream")
        except (ImageError, struct.error, zlib.error, IndexError) as exc:
            notes.append(f"No se pudo incluir la imagen {fname}: {exc}.")
            continue
        xobjects[fname] = name
        xobject_refs[name] = ref

    kids = []
    total = len(pages)
    demo = bool(layout.get("demo"))
    for n, rows in enumerate(pages, start=1):
        content_h = sum(geo.rowh[r] for r in rows) * scale
        page_h = (content_h + mt + mb + header_h + footer_h) if roll else ph
        cv = _Canvas()
        cv.add(b"q %.4f 0 0 %.4f %.2f %.2f cm" % (scale, scale, ml, page_h - mt - header_h))
        _draw_page(cv, geo, rows, layout, xobjects)
        cv.add(b"Q")
        for text, y in ((page.get("header"), page_h - mt - 8), (page.get("footer"), mb + 2)):
            if text:
                t = str(text).replace("&P", str(n)).replace("&N", str(total)).replace("&[Página]", str(n))
                tw = text_width(t, 7)
                cv.add(b"BT /F1 7 Tf 0.3 0.3 0.3 rg %.2f %.2f Td (%s) Tj ET" % ((pw - tw) / 2, y, _escape(t)))
        if demo:
            size = max(14.0, min(48.0, pw / 9))
            tw = text_width("DEMOSTRACIÓN", size, True)
            cv.add(b"BT /F2 %.1f Tf 0.96 0.78 0.78 rg 0.7071 0.7071 -0.7071 0.7071 %.2f %.2f Tm (%s) Tj ET" % (
                size, (pw - tw * 0.7071) / 2, page_h / 2 - tw * 0.35, _escape("DEMOSTRACIÓN")))
            cv.add(b"BT /F2 7 Tf 0.75 0.1 0.1 rg %.2f %.2f Td (%s) Tj ET" % (
                4.0, page_h - 9, _escape("DATOS DE DEMOSTRACIÓN — NO ES UN DOCUMENTO REAL")))
        stream = zlib.compress(b"\n".join(cv.ops))
        content = add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(stream) + stream + b"\nendstream")
        xo = b" ".join(b"/%s %d 0 R" % (k, v) for k, v in xobject_refs.items())
        kids.append(add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] /Resources << /Font << /F1 %d 0 R"
                        b" /F2 %d 0 R /F3 %d 0 R /F4 %d 0 R >>%s >> /Contents %d 0 R >>" % (
                            pages_id, pw, page_h, *fonts, (b" /XObject << " + xo + b" >>") if xo else b"", content)))
    objects[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id
    objects[pages_id - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % k for k in kids), len(kids))
    info = add(b"<< /Title (%s) /Producer (POS-PY) >>" % _escape(title))
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, catalog, info, xref)
    return bytes(out), notes


def page_count(pdf: bytes) -> int:
    m = re.search(rb"/Type /Pages /Kids \[[^\]]*\] /Count (\d+)", pdf)
    return int(m.group(1)) if m else 0

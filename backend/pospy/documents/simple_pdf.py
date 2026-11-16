"""Escritor PDF mínimo (PDF 1.4) para informes de texto y tablas, sin dependencias externas.

Usa las fuentes estándar Helvetica y Helvetica-Bold (no se incrustan) con codificación WinAnsi, que
cubre el español (tildes, ñ, ¿, ¡). Los anchos de carácter son los de las métricas AFM de Adobe para
alinear importes a la derecha. Solo dibuja texto, líneas y rectángulos: suficiente para informes.
"""
from __future__ import annotations

import unicodedata
import zlib

PAGE_W, PAGE_H = 595.28, 841.89  # A4 en puntos

_HELV = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278] + [556] * 10 + [
    278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556,
    278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334,
    260, 334, 584]
_BOLD = [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278] + [556] * 10 + [
    333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556, 333, 556, 611, 556, 611, 556,
    333, 611, 611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389,
    280, 389, 584]


def _clean(text: str) -> str:
    """Texto representable en WinAnsi (cp1252); lo demás se sustituye por '?'."""
    return str(text).encode("cp1252", errors="replace").decode("cp1252")


def text_width(text: str, size: float, bold: bool = False) -> float:
    table = _BOLD if bold else _HELV
    total = 0
    for ch in _clean(text):
        code = ord(ch)
        if 32 <= code <= 126:
            total += table[code - 32]
        else:
            base = unicodedata.normalize("NFD", ch)[0]
            total += table[ord(base) - 32] if 32 <= ord(base) <= 126 else 556
    return total * size / 1000


def _escape(text: str) -> bytes:
    raw = _clean(text).encode("cp1252", errors="replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


class SimplePDF:
    def __init__(self, title: str = "", margin: float = 42):
        self.title = title
        self.margin = margin
        self.pages: list[list[bytes]] = []
        self.y = 0.0
        self.footer = ""
        self.new_page()

    # ------------------------------------------------------------------ páginas
    def new_page(self) -> None:
        self.pages.append([])
        self.y = PAGE_H - self.margin

    def ensure(self, height: float) -> None:
        if self.y - height < self.margin + 24:
            self.new_page()

    @property
    def width(self) -> float:
        return PAGE_W - 2 * self.margin

    # ------------------------------------------------------------------ primitivas
    def text(self, x: float, y: float, text: str, size: float = 10, bold: bool = False,
             color: tuple[float, float, float] = (0, 0, 0)) -> None:
        font = b"/F2" if bold else b"/F1"
        r, g, b = color
        self.pages[-1].append(b"BT %s %.2f Tf %.3f %.3f %.3f rg %.2f %.2f Td (%s) Tj ET" % (
            font, size, r, g, b, x, y, _escape(text)))

    def line(self, x1: float, y1: float, x2: float, y2: float, width: float = 0.5, gray: float = 0.75) -> None:
        self.pages[-1].append(b"%.3f G %.2f w %.2f %.2f m %.2f %.2f l S" % (gray, width, x1, y1, x2, y2))

    def rect(self, x: float, y: float, w: float, h: float, gray: float = 0.94) -> None:
        self.pages[-1].append(b"%.3f g %.2f %.2f %.2f %.2f re f 0 g" % (gray, x, y, w, h))

    # ------------------------------------------------------------------ bloques
    def wrap(self, text: str, size: float, max_width: float, bold: bool = False) -> list[str]:
        lines: list[str] = []
        for paragraph in str(text).splitlines() or [""]:
            current = ""
            for word in paragraph.split(" "):
                candidate = f"{current} {word}".strip() if current else word
                if text_width(candidate, size, bold) <= max_width:
                    current = candidate
                    continue
                if current:
                    lines.append(current)
                while text_width(word, size, bold) > max_width and len(word) > 1:
                    cut = len(word)
                    while cut > 1 and text_width(word[:cut], size, bold) > max_width:
                        cut -= 1
                    lines.append(word[:cut])
                    word = word[cut:]
                current = word
            lines.append(current)
        return lines

    def paragraph(self, text: str, size: float = 10, bold: bool = False, gap: float = 4,
                  color: tuple[float, float, float] = (0, 0, 0)) -> None:
        for ln in self.wrap(text, size, self.width, bold):
            self.ensure(size + 3)
            self.y -= size + 3
            self.text(self.margin, self.y, ln, size, bold, color)
        self.y -= gap

    def heading(self, text: str, size: float = 13) -> None:
        self.ensure(size + 28)
        self.y -= 10
        self.paragraph(text, size, bold=True, gap=2)
        self.line(self.margin, self.y, PAGE_W - self.margin, self.y, 0.8, 0.55)
        self.y -= 6

    def table(self, headers: list[str], rows: list[list[str]], widths: list[float], align: list[str],
              size: float = 9, bold_last: bool = False) -> None:
        total = sum(widths)
        widths = [w * self.width / total for w in widths]
        row_h = size + 7

        def draw(cells: list[str], bold: bool, shade: bool) -> None:
            wrapped = [self.wrap(c, size, w - 8, bold) for c, w in zip(cells, widths, strict=True)]
            height = max(len(w) for w in wrapped) * (size + 2) + 5
            self.ensure(height)
            if shade:
                self.rect(self.margin, self.y - height, self.width, height)
            x = self.margin
            for lines, w, a in zip(wrapped, widths, align, strict=True):
                ty = self.y - size - 2
                for ln in lines:
                    tx = x + w - 4 - text_width(ln, size, bold) if a == "r" else x + 4
                    self.text(tx, ty, ln, size, bold)
                    ty -= size + 2
                x += w
            self.y -= height
            self.line(self.margin, self.y, PAGE_W - self.margin, self.y, 0.3, 0.8)

        self.ensure(row_h * 2)
        draw(headers, True, True)
        for i, r in enumerate(rows):
            draw(r, bold_last and i == len(rows) - 1, False)
        self.y -= 6

    # ------------------------------------------------------------------ salida
    def output(self) -> bytes:
        objects: list[bytes] = []

        def add(body: bytes) -> int:
            objects.append(body)
            return len(objects)

        catalog = add(b"")
        pages_id = add(b"")
        f1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        f2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        kids = []
        count = len(self.pages)
        for n, ops in enumerate(self.pages, start=1):
            footer = f"{self.footer}  ·  Página {n} de {count}" if self.footer else f"Página {n} de {count}"
            ops = [*ops, b"BT /F1 8 Tf 0.4 0.4 0.4 rg %.2f %.2f Td (%s) Tj ET" % (
                self.margin, self.margin - 14, _escape(footer))]
            stream = zlib.compress(b"\n".join(ops))
            content = add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(stream) + stream + b"\nendstream")
            kids.append(add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] /Resources << /Font << /F1 %d 0 R"
                            b" /F2 %d 0 R >> >> /Contents %d 0 R >>" % (pages_id, PAGE_W, PAGE_H, f1, f2, content)))
        objects[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id
        objects[pages_id - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
            b" ".join(b"%d 0 R" % k for k in kids), count)
        info = add(b"<< /Title (%s) /Producer (POS-PY) >>" % _escape(self.title))
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for i, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
        out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
        out += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n" % (
            len(objects) + 1, catalog, info, xref)
        out += b"%%EOF\n"
        return bytes(out)

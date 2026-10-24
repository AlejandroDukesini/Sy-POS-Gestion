"""Comprobante de venta en ESC/POS para impresoras térmicas (DIGITALPOS y compatibles, 58/80 mm).

Usa comandos ESC/POS estándar (inicializar, alineación, negrita, doble alto, corte, cajón). El
texto se codifica en CP858 (Latin-1 con €, tabla 19 en la mayoría de modelos), que incluye tildes y ñ.
"""
from __future__ import annotations

import textwrap

ESC, GS = b"\x1b", b"\x1d"
INIT = ESC + b"@"
CODEPAGE = ESC + b"t" + bytes([19])
LEFT, CENTER, RIGHT = ESC + b"a\x00", ESC + b"a\x01", ESC + b"a\x02"
BOLD_ON, BOLD_OFF = ESC + b"E\x01", ESC + b"E\x00"
DOUBLE_ON, DOUBLE_OFF = GS + b"!\x11", GS + b"!\x00"
CUT = GS + b"V\x41\x03"
DRAWER = ESC + b"p\x00\x19\xfa"


def _enc(text: str) -> bytes:
    return text.encode("cp858", errors="replace")


class Ticket:
    def __init__(self, width: int):
        self.width = width
        self.buf = bytearray(INIT + CODEPAGE)

    def raw(self, data: bytes) -> Ticket:
        self.buf += data
        return self

    def line(self, text: str = "", align: bytes = LEFT, bold: bool = False, double: bool = False) -> Ticket:
        width = self.width // 2 if double else self.width
        chunks = textwrap.wrap(text, width) or [""]
        self.buf += align + (BOLD_ON if bold else b"") + (DOUBLE_ON if double else b"")
        for chunk in chunks:
            self.buf += _enc(chunk) + b"\n"
        self.buf += (DOUBLE_OFF if double else b"") + (BOLD_OFF if bold else b"") + LEFT
        return self

    def pair(self, left: str, right: str, bold: bool = False) -> Ticket:
        space = self.width - len(right) - 1
        left = left[:space] if len(left) > space else left
        return self.line(left + " " * (self.width - len(left) - len(right)) + right, bold=bold)

    def rule(self, char: str = "-") -> Ticket:
        return self.line(char * self.width)

    def finish(self, cut: bool, drawer: bool) -> bytes:
        self.buf += b"\n\n\n"
        if drawer:
            self.buf += DRAWER
        if cut:
            self.buf += CUT
        return bytes(self.buf)


def plain_text(data: bytes) -> str:
    """Texto legible del ticket (para pruebas y vista previa), sin comandos de control."""
    out, i = bytearray(), 0
    while i < len(data):
        b = data[i]
        if data[i:i + 1] == ESC:
            i += {b"@": 2, b"t": 3, b"a": 3, b"E": 3, b"p": 5}.get(data[i + 1:i + 2], 2)
            continue
        if data[i:i + 1] == GS:
            i += {b"!": 3, b"V": 4}.get(data[i + 1:i + 2], 2)
            continue
        out.append(b)
        i += 1
    return out.decode("cp858", errors="replace")

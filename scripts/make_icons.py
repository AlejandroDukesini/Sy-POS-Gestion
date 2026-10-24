"""Genera los iconos de POS-PY (PWA y escritorio) sin dependencias externas.

  python scripts/make_icons.py [#color]

Escribe frontend/public/icons/*.png, frontend/public/icons/icon.svg y desktop/src-tauri/app-icon.png
(1024 px; con ella `npm run tauri icon` en desktop/ genera icon.ico y el resto de tamaños).
Para usar el logotipo de la empresa, sustituya app-icon.png por uno propio de 1024×1024 y repita.
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def hex_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def draw(size: int, bg: tuple[int, int, int], maskable: bool = False) -> bytes:
    """Cuadro redondeado de color con un comprobante blanco y renglones (RGBA)."""
    radius = 0 if maskable else size * 0.22
    pad = size * (0.26 if maskable else 0.2)
    left, right = size * 0.5 - (size - 2 * pad) * 0.36, size * 0.5 + (size - 2 * pad) * 0.36
    top, bottom = pad, size - pad
    teeth = 6
    tooth_h = (right - left) / teeth / 2
    lines = [top + (bottom - top) * f for f in (0.22, 0.38, 0.54)]
    rows = bytearray()
    for y in range(size):
        rows.append(0)
        for x in range(size):
            cx, cy = x + 0.5, y + 0.5
            inside = True
            if radius:
                dx = max(radius - cx, 0, cx - (size - radius))
                dy = max(radius - cy, 0, cy - (size - radius))
                inside = dx * dx + dy * dy <= radius * radius
            if not inside:
                rows += b"\x00\x00\x00\x00"
                continue
            color = bg
            if left <= cx <= right and top <= cy <= bottom:
                phase = ((cx - left) / ((right - left) / teeth)) % 1
                edge = bottom - tooth_h * (1 - abs(phase * 2 - 1))
                if cy <= edge:
                    color = (255, 255, 255)
                    for i, ly in enumerate(lines):
                        width = 0.75 if i < 2 else 0.45
                        if abs(cy - ly) <= size * 0.022 and left + (right - left) * 0.14 <= cx <= left + (right - left) * (0.14 + width * 0.86):
                            color = bg
            rows += bytes(color) + b"\xff"
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b"")


SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="POS-PY">
<rect width="64" height="64" rx="14" fill="{c}"/>
<path d="M19 13h26v38l-4.33-3-4.34 3-4.33-3-4.33 3-4.34-3L19 51z" fill="#fff"/>
<rect x="23" y="20" width="18" height="3" rx="1.5" fill="{c}"/><rect x="23" y="27" width="18" height="3" rx="1.5" fill="{c}"/>
<rect x="23" y="34" width="11" height="3" rx="1.5" fill="{c}"/></svg>
"""


def main() -> None:
    color = sys.argv[1] if len(sys.argv) > 1 else "#1d4ed8"
    rgb = hex_rgb(color)
    icons = ROOT / "frontend" / "public" / "icons"
    icons.mkdir(parents=True, exist_ok=True)
    (icons / "icon-192.png").write_bytes(draw(192, rgb))
    (icons / "icon-512.png").write_bytes(draw(512, rgb))
    (icons / "icon-maskable-512.png").write_bytes(draw(512, rgb, maskable=True))
    (icons / "apple-touch-icon.png").write_bytes(draw(180, rgb, maskable=True))
    (icons / "icon.svg").write_text(SVG.format(c=color), encoding="utf-8")
    tauri = ROOT / "desktop" / "src-tauri"
    tauri.mkdir(parents=True, exist_ok=True)
    (tauri / "app-icon.png").write_bytes(draw(1024, rgb))
    print("Iconos generados en", icons, "y", tauri / "app-icon.png")


if __name__ == "__main__":
    main()

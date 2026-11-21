"""Impresión directa de plantillas en CUALQUIER impresora de Windows (térmica, láser, tinta, PDF…), sin Excel
ni visor de PDF.

Usa la misma planificación y el mismo dibujo que el PDF (documents/layout_pdf.plan y draw_page) con un
«pintor» GDI: lo que se ve en la vista previa es lo que sale impreso. Texto en Arial (mismas métricas que la
Helvetica del PDF), imágenes JPEG/PNG con GDI+ (incluido en Windows), líneas con su estilo (guiones/puntos).

Papel: en hojas (Carta, A4…) se pide al controlador el tamaño y la orientación de la plantilla. En rollos
térmicos se usa el papel configurado en el controlador; si el contenido es más alto que la página del
controlador se divide sin cortar filas. Los márgenes se aplican desde el borde físico del papel (se descuenta la
zona que la impresora no puede imprimir).
"""
from __future__ import annotations

import ctypes
import os
import re
import tempfile
from ctypes import wintypes
from typing import Any

from ..documents.layout_pdf import BORDER_W, MM, _rgb, draw_page, paginate, plan, text_width  # noqa: F401
from .printers import PrintError, find_printer, system_printing_available

PAPER_CODES = {"letter": 1, "legal": 5, "a4": 9, "a5": 11}
_DASH = {"dotted": (1, 1), "dashed": (3, 2), "mediumDashed": (4, 2), "dashDot": (3, 1, 1, 1), "mediumDashDot": (4, 1, 1, 1),
         "dashDotDot": (3, 1, 1, 1, 1, 1), "mediumDashDotDot": (4, 1, 1, 1, 1, 1), "slantDashDot": (4, 1, 1, 1)}
# GetDeviceCaps
HORZRES, VERTRES, LOGPIXELSX, LOGPIXELSY = 8, 10, 88, 90
PHYSICALOFFSETX, PHYSICALOFFSETY = 112, 113


def _colorref(rgb: tuple) -> int:
    r, g, b = (max(0, min(255, round(v * 255))) for v in rgb)
    return r | (g << 8) | (b << 16)


class _GdiPlus:
    """Dibujo de imágenes con GDI+ (gdiplus.dll de Windows) vía ctypes."""

    class _Startup(ctypes.Structure):
        _fields_ = [("GdiplusVersion", ctypes.c_uint32), ("DebugEventCallback", ctypes.c_void_p),
                    ("SuppressBackgroundThread", ctypes.c_int), ("SuppressExternalCodecs", ctypes.c_int)]

    def __init__(self):
        self.lib = ctypes.WinDLL("gdiplus")
        self.token = ctypes.c_size_t()
        si = self._Startup(1, None, 0, 0)
        if self.lib.GdiplusStartup(ctypes.byref(self.token), ctypes.byref(si), None) != 0:
            raise PrintError("Windows no pudo iniciar GDI+ para dibujar las imágenes.")
        self.images: dict[str, tuple[ctypes.c_void_p, int, int]] = {}
        self.tmp = tempfile.mkdtemp(prefix="pospy-print-")

    def load(self, key: str, data: bytes) -> None:
        path = os.path.join(self.tmp, re.sub(r"[^A-Za-z0-9_.-]", "_", key) or "img")
        with open(path, "wb") as fh:
            fh.write(data)
        img = ctypes.c_void_p()
        if self.lib.GdipLoadImageFromFile(ctypes.c_wchar_p(path), ctypes.byref(img)) != 0:
            return
        w, h = ctypes.c_uint(), ctypes.c_uint()
        self.lib.GdipGetImageWidth(img, ctypes.byref(w))
        self.lib.GdipGetImageHeight(img, ctypes.byref(h))
        self.images[key] = (img, w.value, h.value)

    def draw(self, hdc: int, key: str, dst: tuple[int, int, int, int], src: tuple[float, float, float, float]) -> None:
        if key not in self.images:
            return
        img, _, _ = self.images[key]
        g = ctypes.c_void_p()
        if self.lib.GdipCreateFromHDC(wintypes.HDC(hdc), ctypes.byref(g)) != 0:
            return
        try:
            self.lib.GdipSetInterpolationMode(g, 7)          # alta calidad bicúbica
            self.lib.GdipDrawImageRectRect(g, img, ctypes.c_float(dst[0]), ctypes.c_float(dst[1]), ctypes.c_float(dst[2]),
                                           ctypes.c_float(dst[3]), ctypes.c_float(src[0]), ctypes.c_float(src[1]),
                                           ctypes.c_float(src[2]), ctypes.c_float(src[3]), 2, None, None, None)
        finally:
            self.lib.GdipDeleteGraphics(g)

    def size(self, key: str) -> tuple[int, int]:
        _, w, h = self.images.get(key, (None, 0, 0))
        return w, h

    def close(self) -> None:
        for img, _, _ in self.images.values():
            self.lib.GdipDisposeImage(img)
        self.images.clear()
        self.lib.GdiplusShutdown(self.token)
        for name in os.listdir(self.tmp):
            try:
                os.unlink(os.path.join(self.tmp, name))
            except OSError:
                pass
        try:
            os.rmdir(self.tmp)
        except OSError:
            pass


class GdiPainter:
    """Pintor sobre un DC de Windows. Coordenadas del diseño (puntos) → píxeles del dispositivo."""

    def __init__(self, dc, gdip: _GdiPlus, kx: float, ky: float, ox: float, oy: float):
        import win32con
        self.dc, self.gdip = dc, gdip
        self.kx, self.ky, self.ox, self.oy = kx, ky, ox, oy
        self.fonts: dict[tuple, Any] = {}
        self.pens: dict[tuple, Any] = {}
        dc.SetBkMode(win32con.TRANSPARENT)
        dc.SetTextAlign(win32con.TA_BASELINE | win32con.TA_LEFT)
        self.hdc = dc.GetSafeHdc()

    def _x(self, x: float) -> int:
        return int(round(self.ox + x * self.kx))

    def _y(self, y: float) -> int:
        return int(round(self.oy + y * self.ky))

    def fill(self, x: float, y: float, w: float, h: float, rgb: tuple) -> None:
        self.dc.FillSolidRect((self._x(x), self._y(y), self._x(x + w), self._y(y + h)), _colorref(rgb))

    def _pen(self, rgb: tuple, width: float):
        import win32con
        import win32ui
        px = max(1, int(round(width * self.kx)))
        key = (_colorref(rgb), px)
        if key not in self.pens:
            self.pens[key] = win32ui.CreatePen(win32con.PS_SOLID, px, key[0])
        return self.pens[key]

    def line(self, x1: float, y1: float, x2: float, y2: float, rgb: tuple, width: float, style: str = "") -> None:
        self.dc.SelectObject(self._pen(rgb, width))
        pattern = _DASH.get(style)
        if not pattern:
            self.dc.MoveTo((self._x(x1), self._y(y1)))
            self.dc.LineTo((self._x(x2), self._y(y2)))
            if style == "double":
                off = max(1.0, width) * 1.5
                dx, dy = (0, off) if y1 == y2 else (off, 0)
                self.dc.MoveTo((self._x(x1 + dx), self._y(y1 + dy)))
                self.dc.LineTo((self._x(x2 + dx), self._y(y2 + dy)))
            return
        # guiones dibujados a mano: los lápices GDI gruesos no admiten estilos
        length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        if length <= 0:
            return
        ux, uy = (x2 - x1) / length, (y2 - y1) / length
        scale = max(1.0, width * 2)
        pos, i, on = 0.0, 0, True
        while pos < length:
            seg = pattern[i % len(pattern)] * scale
            end = min(length, pos + seg)
            if on:
                self.dc.MoveTo((self._x(x1 + ux * pos), self._y(y1 + uy * pos)))
                self.dc.LineTo((self._x(x1 + ux * end), self._y(y1 + uy * end)))
            pos, i, on = end, i + 1, not on

    def end_lines(self) -> None:
        pass

    def clip(self, x: float, y: float, w: float, h: float) -> None:
        self.dc.SaveDC()
        self.dc.IntersectClipRect((self._x(x), self._y(y), self._x(x + w), self._y(y + h)))

    def unclip(self) -> None:
        self.dc.RestoreDC(-1)
        import win32con
        self.dc.SetBkMode(win32con.TRANSPARENT)
        self.dc.SetTextAlign(win32con.TA_BASELINE | win32con.TA_LEFT)

    def _font(self, font: dict, size: float, escapement: int = 0):
        import win32ui
        key = (bool(font.get("b")), bool(font.get("i")), round(size * self.ky), escapement)
        if key not in self.fonts:
            self.fonts[key] = win32ui.CreateFont({"name": "Arial", "height": -max(1, key[2]), "weight": 700 if key[0] else 400,
                                                 "italic": 1 if key[1] else 0, "escapement": escapement, "orientation": escapement,
                                                 "quality": 5})
        return self.fonts[key]

    def text(self, font: dict, size: float, rgb: tuple, x: float, baseline: float, s: str) -> None:
        self.dc.SelectObject(self._font(font, size))
        self.dc.SetTextColor(_colorref(rgb))
        self.dc.TextOut(self._x(x), self._y(baseline), s)

    def text_rotated(self, font: dict, size: float, rgb: tuple, rot: int, x: float, y: float, s: str) -> None:
        self.dc.SelectObject(self._font(font, size, 900 if rot == 90 else 2700))
        self.dc.SetTextColor(_colorref(rgb))
        self.dc.TextOut(self._x(x), self._y(y), s)

    def image(self, key: Any, x: float, y: float, w: float, h: float, fx: float, fy: float, fw: float, fh: float) -> None:
        iw, ih = self.gdip.size(key)
        if not iw or not ih or fw <= 0 or fh <= 0:
            return
        src = ((x - fx) / fw * iw, (y - fy) / fh * ih, w / fw * iw, h / fh * ih)
        dst = (self._x(x), self._y(y), self._x(x + w) - self._x(x), self._y(y + h) - self._y(y))
        self.gdip.draw(self.hdc, key, dst, src)


def _open_dc(printer: str, page: dict, roll: bool):
    """DC de la impresora con el papel y la orientación de la plantilla (en hojas)."""
    import pywintypes
    import win32con
    import win32gui
    import win32print
    import win32ui
    devmode = None
    try:
        handle = win32print.OpenPrinter(printer)
        try:
            devmode = win32print.GetPrinter(handle, 2)["pDevMode"]
        finally:
            win32print.ClosePrinter(handle)
    except pywintypes.error:
        devmode = None
    if devmode is not None and not roll:
        code = PAPER_CODES.get(str(page.get("paper") or "").lower())
        if code:
            devmode.PaperSize = code
            devmode.Fields |= win32con.DM_PAPERSIZE
        devmode.Orientation = 2 if page.get("orientation") == "landscape" else 1
        devmode.Fields |= win32con.DM_ORIENTATION
    try:
        hdc = win32gui.CreateDC("WINSPOOL", printer, devmode)
    except pywintypes.error as exc:
        raise PrintError(f"Windows no permitió usar la impresora «{printer}»: {exc}") from exc
    return win32ui.CreateDCFromHandle(hdc)


def print_layout(final: dict, images: dict[str, bytes], printer: str, copies: int = 1, title: str = "Documento",
                 output_file: str | None = None) -> dict:
    """Imprime un diseño ya completado. output_file solo para impresoras virtuales (p. ej. «Microsoft Print to PDF»)."""
    if not system_printing_available():
        raise PrintError("La impresión directa requiere Windows con pywin32 en el equipo del servidor.")
    name = find_printer(printer)
    pl = plan(final)
    geo, page = pl["geo"], pl["page"]
    dc = _open_dc(name, page, pl["roll"])
    gdip = _GdiPlus()
    try:
        dpx, dpy = dc.GetDeviceCaps(LOGPIXELSX), dc.GetDeviceCaps(LOGPIXELSY)
        offx, offy = dc.GetDeviceCaps(PHYSICALOFFSETX), dc.GetDeviceCaps(PHYSICALOFFSETY)
        horz, vert = dc.GetDeviceCaps(HORZRES), dc.GetDeviceCaps(VERTRES)
        scale = pl["scale"]
        # Que el diseño quepa en el ancho que la impresora realmente imprime.
        printable_pt = (horz + offx) * 72 / dpx - pl["ml"] - pl["mr"]
        usable_pt = horz * 72 / dpx
        if geo.width * scale > max(printable_pt, usable_pt) + 0.5:
            scale = max(0.1, usable_pt / max(1.0, geo.width))
        kx, ky = dpx / 72 * scale, dpy / 72 * scale
        ox = max(0.0, pl["ml"] * dpx / 72 - offx)
        oy = max(0.0, (pl["mt"] + pl["header_h"]) * dpy / 72 - offy)
        pages = pl["pages"]
        if pl["roll"]:                               # rollo: dividir según el alto de página del controlador
            avail = max(20.0, (vert / dpy * 72 - pl["mt"] - pl["mb"] - pl["header_h"] - pl["footer_h"]) / scale)
            repeat = None
            pages = paginate(geo, avail, repeat, set(), int(page.get("repeat_until") or 0))
        keys = {}
        for fname, data in images.items():
            gdip.load(fname, data)
            keys[fname] = fname
        copies = max(1, min(20, int(copies or 1)))
        dc.StartDoc(title[:60], output_file) if output_file else dc.StartDoc(title[:60])
        total = len(pages)
        for _ in range(copies):
            for n, rows in enumerate(pages, start=1):
                dc.StartPage()
                painter = GdiPainter(dc, gdip, kx, ky, ox, oy)
                draw_page(painter, geo, rows, final, keys)
                for text, at_top in ((page.get("header"), True), (page.get("footer"), False)):
                    if text:
                        t = str(text).replace("&P", str(n)).replace("&N", str(total)).replace("&[Página]", str(n))
                        foot = GdiPainter(dc, gdip, dpx / 72, dpy / 72, 0, 0)
                        y = (pl["mt"] + 7) if at_top else (vert / dpy * 72 - pl["mb"])
                        x = max(0.0, (horz / dpx * 72 - text_width(t, 7)) / 2)
                        foot.text({}, 7, (0.3, 0.3, 0.3), x, y, t)
                dc.EndPage()
        dc.EndDoc()
        return {"printer": name, "copies": copies, "pages": total}
    except Exception as exc:  # noqa: BLE001
        try:
            dc.AbortDoc()
        except Exception:  # noqa: BLE001
            pass
        if isinstance(exc, PrintError):
            raise
        raise PrintError(f"No se pudo imprimir en «{name}»: {exc}") from exc
    finally:
        gdip.close()
        dc.DeleteDC()

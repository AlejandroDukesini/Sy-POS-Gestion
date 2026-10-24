"""Automatización de Microsoft Excel (COM, solo Windows): escritura de máxima fidelidad, PDF e impresión.

openpyxl reescribe el libro y pierde imágenes, gráficos y formas. Cuando la plantilla los tiene
se usa Excel instalado en el equipo, que conserva el archivo tal como lo diseñó la empresa.
"""
from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .excel_safety import ExcelError

_com_lock = threading.Lock()
PAPER = {"letter": 1, "legal": 5, "a4": 9, "a5": 11}
VIRTUAL_PRINTERS = ("microsoft print to pdf", "microsoft xps document writer", "onenote", "fax")


def com_available() -> bool:
    try:
        import winreg

        import win32com.client  # noqa: F401
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Excel.Application"))
        return True
    except (ImportError, OSError):
        return False


@contextmanager
def excel_app() -> Iterator[Any]:
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise ExcelError("Falta el paquete pywin32 para usar Microsoft Excel.") from exc
    with _com_lock:
        pythoncom.CoInitialize()
        app = None
        try:
            try:
                app = win32com.client.DispatchEx("Excel.Application")
            except Exception as exc:  # noqa: BLE001
                raise ExcelError("Microsoft Excel no está disponible en este equipo.") from exc
            app.Visible = False
            app.DisplayAlerts = False
            app.ScreenUpdating = False
            yield app
        finally:
            if app is not None:
                try:
                    app.Quit()
                except Exception:  # noqa: BLE001
                    pass
            pythoncom.CoUninitialize()


def apply_page_setup(ws, setup: dict) -> None:
    ps = ws.PageSetup
    ps.Orientation = 2 if setup.get("orientation") == "landscape" else 1
    try:
        ps.PaperSize = PAPER.get(str(setup.get("paper", "letter")).lower(), 1)
    except Exception:  # noqa: BLE001 - la impresora puede no admitir el tamaño
        pass
    points = float(setup.get("margins_cm", 1.5)) * 28.3465
    ps.LeftMargin = ps.RightMargin = ps.TopMargin = ps.BottomMargin = points
    if setup.get("fit_width", True):
        ps.Zoom = False
        ps.FitToPagesWide = 1
        ps.FitToPagesTall = False
    else:
        ps.Zoom = max(10, min(400, int(setup.get("scale", 100))))


def write_cells(path: Path, sheet: str, cells: dict[str, Any], setup: dict) -> None:
    with excel_app() as app:
        wb = app.Workbooks.Open(str(Path(path).resolve()), UpdateLinks=0)
        try:
            ws = wb.Worksheets(sheet)
            for coord, value in cells.items():
                ws.Range(coord).Value = "" if value is None else value
            apply_page_setup(ws, setup)
            wb.Save()
        finally:
            wb.Close(SaveChanges=False)


def export_pdf(xlsx: Path, pdf: Path) -> Path:
    if not com_available():
        raise ExcelError("Para generar PDF se necesita Microsoft Excel instalado en el equipo del servidor.")
    xlsx, pdf = Path(xlsx).resolve(), Path(pdf).resolve()
    if pdf.exists():
        try:
            pdf.unlink()
        except PermissionError as exc:
            raise ExcelError(f"El PDF {pdf.name} está abierto en otro programa; ciérrelo.") from exc
    with excel_app() as app:
        wb = app.Workbooks.Open(str(xlsx), ReadOnly=True, UpdateLinks=0)
        try:
            wb.ExportAsFixedFormat(0, str(pdf))
        finally:
            wb.Close(SaveChanges=False)
    if not pdf.exists() or pdf.stat().st_size == 0:
        raise ExcelError("Excel no generó el PDF.")
    return pdf


def _printer_port(name: str) -> str:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows NT\CurrentVersion\Devices") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value).split(",")[-1]
    except OSError:
        return ""


def print_workbook(xlsx: Path, printer: str, copies: int, setup: dict) -> None:
    if not printer:
        raise ExcelError("Seleccione una impresora para este tipo de documento.")
    if printer.lower().startswith(VIRTUAL_PRINTERS):
        raise ExcelError(f"«{printer}» es una impresora virtual que abre diálogos; descargue el PDF en su lugar.")
    if not com_available():
        raise ExcelError("Para imprimir plantillas Excel directamente se necesita Microsoft Excel instalado. "
                         "Use la vista previa e imprima desde el navegador.")
    port = _printer_port(printer)
    candidates = [f"{printer} en {port}", f"{printer} on {port}", printer] if port else [printer]
    with excel_app() as app:
        wb = app.Workbooks.Open(str(Path(xlsx).resolve()), ReadOnly=True, UpdateLinks=0)
        try:
            last_error = None
            for candidate in candidates:
                try:
                    app.ActivePrinter = candidate
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
            else:
                raise ExcelError(f"Excel no reconoce la impresora «{printer}» ({last_error}). Verifique que esté instalada.")
            for ws in wb.Worksheets:
                apply_page_setup(ws, setup)
            wb.PrintOut(Copies=max(1, int(copies)))
        finally:
            wb.Close(SaveChanges=False)

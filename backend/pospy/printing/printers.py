"""Impresoras del sistema (Windows, vía pywin32) y envío RAW de comandos ESC/POS.

Las impresoras listadas son las del equipo donde corre el backend. En la aplicación de escritorio
(Tauri) es el mismo equipo del usuario; en una instalación web en red es el equipo servidor. Desde
un navegador remoto la impresión directa no es posible: se usa la vista de impresión del navegador.
"""
from __future__ import annotations

import sys

from ..core.errors import DomainError


class PrintError(DomainError):
    title = "No se pudo imprimir"


def system_printing_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import win32print  # noqa: F401
        return True
    except ImportError:
        return False


def list_printers() -> dict:
    if not system_printing_available():
        return {"available": False, "printers": [], "default": "",
                "reason": "La impresión directa requiere Windows con pywin32 en el equipo del servidor."}
    import win32print
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    printers = []
    for item in win32print.EnumPrinters(flags, None, 2):
        printers.append({"name": item["pPrinterName"], "driver": item.get("pDriverName", ""),
                         "port": item.get("pPortName", ""), "status": int(item.get("Status", 0))})
    try:
        default = win32print.GetDefaultPrinter()
    except Exception:  # noqa: BLE001
        default = ""
    return {"available": True, "printers": printers, "default": default, "reason": ""}


def find_printer(name: str) -> str:
    """Devuelve el nombre exacto instalado (sin distinguir mayúsculas; admite coincidencia parcial única)."""
    info = list_printers()
    if not info["available"]:
        raise PrintError(info["reason"])
    names = [p["name"] for p in info["printers"]]
    exact = [n for n in names if n.lower() == name.lower()]
    if exact:
        return exact[0]
    partial = [n for n in names if name.lower() in n.lower()]
    if len(partial) == 1:
        return partial[0]
    if not names:
        raise PrintError("No hay impresoras instaladas en este equipo.")
    raise PrintError(f"No se encontró la impresora «{name}». Instálela en Windows o elija otra en Configuración.",
                     {"printer": "Impresoras disponibles: " + ", ".join(names)})


def print_raw(printer: str, data: bytes, job_name: str) -> None:
    if not system_printing_available():
        raise PrintError("La impresión directa requiere Windows con pywin32 en el equipo del servidor.")
    import win32print
    name = find_printer(printer)
    try:
        handle = win32print.OpenPrinter(name)
    except Exception as exc:  # noqa: BLE001
        raise PrintError(f"Windows no permitió abrir la impresora «{name}»: {exc}") from exc
    try:
        win32print.StartDocPrinter(handle, 1, (job_name[:60], None, "RAW"))
        try:
            win32print.StartPagePrinter(handle)
            written = win32print.WritePrinter(handle, data)
            win32print.EndPagePrinter(handle)
        finally:
            win32print.EndDocPrinter(handle)
    except PrintError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise PrintError(f"Error al enviar a «{name}»: {exc}. Revise que esté encendida, con papel y conectada.") from exc
    finally:
        win32print.ClosePrinter(handle)
    if written != len(data):
        raise PrintError(f"La impresora «{name}» aceptó solo {written} de {len(data)} bytes.")

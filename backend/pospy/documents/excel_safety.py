"""Comprobaciones de archivos Excel: formato, contenido que openpyxl no conserva y huella."""
from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

from ..core.errors import DomainError


class ExcelError(DomainError):
    title = "Problema con el archivo Excel"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_workbook(path: Path) -> None:
    path = Path(path)
    if not path.exists():
        raise ExcelError(f"No se encontró el archivo: {path.name}")
    if path.suffix.lower() not in (".xlsx", ".xlsm"):
        raise ExcelError(f"Formato no soportado ({path.suffix}). Use .xlsx o .xlsm.")
    if not zipfile.is_zipfile(path):
        raise ExcelError(f"El archivo {path.name} está dañado o no es un libro de Excel válido.")


def unsupported_parts(path: Path) -> list[str]:
    """Partes del libro que openpyxl no conserva al guardar (imágenes, gráficos, macros…)."""
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
    checks = {
        "imágenes o formas": ("xl/drawings/", "xl/media/"),
        "gráficos": ("xl/charts/",),
        "segmentaciones": ("xl/slicers/", "xl/slicerCaches/"),
        "controles de formulario": ("xl/activeX/", "xl/ctrlProps/"),
    }
    found = [label for label, prefixes in checks.items() if any(n.startswith(prefixes) for n in names)]
    if "xl/vbaProject.bin" in names:
        found.append("macros")
    return found

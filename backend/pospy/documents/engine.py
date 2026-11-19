"""Motor de plantillas: aplica las vinculaciones a los datos de una operación y produce el diseño final.

1. La tabla de productos (filas start..end de la plantilla) se repite por cada producto. Si hay más
   productos que filas, se insertan filas con el formato de la fila modelo y TODO lo que está debajo
   (celdas, combinaciones, imágenes, área de impresión, saltos) se desplaza: nunca se sobrescribe el
   subtotal, la firma ni el pie. Las filas sobrantes quedan vacías (sin los datos de ejemplo del archivo).
2. Cada celda vinculada recibe un dato del POS (con valor alternativo si viene vacío) o un cálculo.
3. Los cálculos usan Decimal y el evaluador seguro de layout.py.
   valor de cada producto = cantidad × precio unitario (redondeado a centavos)
   subtotal = suma de los valores · descuento = subtotal × porcentaje (una sola vez) · total = subtotal − descuento
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .layout import (
    CalcError,
    cell_ref,
    col_index,
    compile_expr,
    evaluate,
    format_value,
    money,
    parse_cell,
    parse_range,
    range_ref,
    to_serial,
)

# Campos disponibles, por categoría: clave -> (rótulo, tipo)
FIELDS: dict[str, dict[str, tuple[str, str]]] = {
    "Empresa": {
        "empresa_nombre": ("Nombre comercial", "text"), "empresa_razon_social": ("Razón social", "text"),
        "empresa_nit": ("NIT", "text"), "empresa_direccion": ("Dirección", "text"),
        "empresa_ciudad": ("Ciudad", "text"), "empresa_telefono": ("Teléfono", "text"),
        "empresa_email": ("Correo", "text"), "empresa_pie": ("Texto al pie", "text"),
    },
    "Cliente": {
        "cliente_nombre": ("Nombre", "text"), "cliente_identificacion": ("Identificación", "text"),
        "cliente_tipo_documento": ("Tipo de documento", "text"), "cliente_direccion": ("Dirección", "text"),
        "cliente_telefono": ("Teléfono", "text"), "cliente_email": ("Correo", "text"),
    },
    "Operación": {
        "tipo_documento": ("Tipo de documento", "text"), "numero": ("Número", "text"),
        "fecha": ("Fecha", "date"), "fecha_larga": ("Fecha en texto (MARTES, 18 DE NOVIEMBRE)", "text"),
        "hora_impresion": ("Hora de impresión", "time"), "fecha_hora_impresion": ("Fecha y hora de impresión", "datetime"),
        "valido_hasta": ("Válido hasta", "date"), "vendedor": ("Empleado responsable", "text"),
        "observaciones": ("Observaciones", "text"),
    },
    "Totales": {
        "subtotal": ("Subtotal", "money"), "descuento_pct": ("Porcentaje de descuento", "number"),
        "descuento": ("Descuento", "money"), "total": ("Total a pagar", "money"),
        "iva_incluido": ("IVA incluido", "money"), "cantidad_productos": ("Cantidad de productos", "number"),
        "total_unidades": ("Total de unidades", "number"),
    },
}
LINE_FIELDS: dict[str, tuple[str, str]] = {
    "n": ("N.º de línea", "number"), "cantidad": ("Cantidad", "number"), "codigo": ("Código", "text"),
    "descripcion": ("Descripción", "text"), "unidad": ("Unidad", "text"), "precio": ("Precio unitario", "money"),
    "precio_lista": ("Precio sin descuento", "money"), "descuento_linea": ("Descuento del producto", "money"),
    "valor": ("Valor total del producto", "money"), "iva_pct": ("IVA %", "number"),
}
HEADER_KEYS = {k for group in FIELDS.values() for k in group}
TOTAL_KEYS = set(FIELDS["Totales"])
LINE_NUMERIC = {k for k, (_, t) in LINE_FIELDS.items() if t in ("number", "money")}
DEFAULT_DATE_FMT, DEFAULT_TIME_FMT = "dd/mm/yyyy", "h:mm:ss AM/PM"


@dataclass
class DocData:
    """Datos de una operación (venta, cotización, orden…) ya preparados para la plantilla."""
    header: dict[str, Any] = field(default_factory=dict)
    lines: list[dict[str, Any]] = field(default_factory=list)
    printed_at: datetime = field(default_factory=datetime.now)
    demo: bool = False


class BindingError(ValueError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__(" ".join(problems))


# ------------------------------------------------------------------ validación de la configuración
def validate(layout: dict, bindings: dict) -> list[str]:
    problems: list[str] = []
    nrows, ncols = len(layout.get("rows", [])), len(layout.get("cols", []))
    try:
        pct = Decimal(str(bindings.get("discount_pct") or "0").replace(",", "."))
        if not 0 <= pct <= 100:
            problems.append("El porcentaje de descuento debe estar entre 0 y 100.")
    except ArithmeticError:
        problems.append("El porcentaje de descuento no es un número.")
    products = bindings.get("products")
    block = (0, 0)
    if products:
        try:
            start, end = int(products["start"]), int(products["end"])
            if not 1 <= start <= end <= nrows:
                problems.append(f"La tabla de productos (filas {start} a {end}) está fuera del diseño (1 a {nrows}).")
            block = (start, end)
        except (KeyError, TypeError, ValueError):
            problems.append("La tabla de productos necesita fila inicial y final.")
        cols = products.get("columns") or {}
        if not cols:
            problems.append("La tabla de productos no tiene columnas.")
        for letter, b in cols.items():
            if not re.fullmatch(r"[A-Z]{1,3}", str(letter)) or col_index(letter) > ncols:
                problems.append(f"Columna de productos no válida: {letter}.")
                continue
            problems += _check_binding(f"{letter} (productos)", b, in_line=True)
    for ref, b in (bindings.get("cells") or {}).items():
        try:
            r, c = parse_cell(ref)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        if r > nrows or c > ncols:
            problems.append(f"La celda {ref} está fuera del diseño.")
        if block[0] and block[0] <= r <= block[1]:
            problems.append(f"La celda {ref} está dentro de la tabla de productos: configúrela como columna de la tabla.")
        problems += _check_binding(ref, b, in_line=False)
    return problems


def _check_binding(where: str, b: dict, in_line: bool) -> list[str]:
    if not isinstance(b, dict):
        return [f"{where}: vinculación no válida."]
    if b.get("expr"):
        try:
            compile_expr(b["expr"], TOTAL_KEYS, set(LINE_FIELDS), in_line=in_line)
        except CalcError as exc:
            return [f"{where}: {exc}"]
        return []
    name = b.get("field")
    allowed = set(LINE_FIELDS) if in_line else HEADER_KEYS
    if name not in allowed:
        return [f"{where}: campo desconocido «{name}»."]
    return []


# ------------------------------------------------------------------ cálculo de totales
def compute(data: DocData, discount_pct: Any) -> tuple[list[dict[str, Any]], dict[str, Decimal]]:
    pct = Decimal(str(discount_pct or "0").replace(",", "."))
    lines = []
    for i, ln in enumerate(data.lines, start=1):
        qty = Decimal(str(ln.get("cantidad") or 0))
        price = Decimal(str(ln.get("precio") or 0))
        row = {k: ln.get(k) for k in LINE_FIELDS}
        row.update({"n": Decimal(i), "cantidad": qty, "precio": price, "valor": money(qty * price)})
        for k in ("precio_lista", "descuento_linea", "iva_pct"):
            row[k] = Decimal(str(ln.get(k) or 0))
        lines.append(row)
    subtotal = sum((ln["valor"] for ln in lines), Decimal(0))
    discount = money(subtotal * pct / 100)
    totals = {
        "subtotal": subtotal, "descuento_pct": pct, "descuento": discount, "total": subtotal - discount,
        "iva_incluido": Decimal(str(data.header.get("iva_incluido") or 0)),
        "cantidad_productos": Decimal(len(lines)), "total_unidades": sum((ln["cantidad"] for ln in lines), Decimal(0)),
    }
    return lines, totals


# ------------------------------------------------------------------ aplicación al diseño
def render(layout: dict, bindings: dict, data: DocData) -> tuple[dict, dict[str, Decimal]]:
    """Devuelve (diseño final, totales). El diseño de entrada no se modifica."""
    problems = validate(layout, bindings)
    if problems:
        raise BindingError(problems)
    out = copy.deepcopy(layout)
    lines, totals = compute(data, bindings.get("discount_pct"))
    styles = out["styles"]
    grid: dict[tuple[int, int], dict] = {}
    for ref, cell in out["cells"].items():
        grid[parse_cell(ref)] = cell
    products = bindings.get("products")
    extra = 0
    if products:
        start, end = int(products["start"]), int(products["end"])
        capacity = end - start + 1
        total_rows = max(len(lines), capacity)
        extra = total_rows - capacity
        if extra:
            grid, out = _insert_rows(out, grid, start, end, total_rows)
        out.setdefault("page", {})["repeat_until"] = start + total_rows - 1   # encabezados repetidos solo con productos
        columns = {col_index(k): v for k, v in products["columns"].items()}
        for j in range(total_rows):
            r = start + j
            line = lines[j] if j < len(lines) else None
            for c, b in columns.items():
                cell = grid.setdefault((r, c), {})
                cell.pop("f", None)
                if line is None:
                    cell.pop("v", None)
                    continue
                value = _line_value(b, line, totals)
                _put(cell, value, b, styles)
    for ref, b in (bindings.get("cells") or {}).items():
        r, c = parse_cell(ref)
        if products and r > int(products["end"]):
            r += extra
        cell = grid.setdefault((r, c), {})
        cell.pop("f", None)
        value = _header_value(b, data, totals, lines)
        _put(cell, value, b, styles)
    out["cells"] = {cell_ref(r, c): cell for (r, c), cell in grid.items() if cell}
    out["demo"] = data.demo
    return out, totals


def _line_value(b: dict, line: dict, totals: dict) -> Any:
    if b.get("expr"):
        tree = compile_expr(b["expr"], TOTAL_KEYS, set(LINE_FIELDS), in_line=True)
        scope = {**totals, **{k: v for k, v in line.items() if isinstance(v, Decimal)}}
        return money(evaluate(tree, scope))
    value = line.get(b["field"])
    return value if value not in (None, "") else b.get("fallback", "")


def _header_value(b: dict, data: DocData, totals: dict, lines: list[dict]) -> Any:
    if b.get("expr"):
        tree = compile_expr(b["expr"], TOTAL_KEYS, set(LINE_FIELDS))
        result = evaluate(tree, dict(totals), [{k: v for k, v in ln.items() if isinstance(v, Decimal)} for ln in lines])
        return result
    name = b["field"]
    if name in totals:
        return totals[name]
    if name == "hora_impresion":
        return ("time", data.printed_at)
    if name == "fecha_hora_impresion":
        return ("datetime", data.printed_at)
    if name == "fecha_larga":
        d = data.header.get("fecha") or data.printed_at.date()
        return format_value(to_serial(d), 'dddd, d "de" mmmm').upper()
    value = data.header.get(name)
    if isinstance(value, (date, datetime)):
        return ("date", value)
    if value in (None, ""):
        return b.get("fallback", "") or ""
    return value


def _put(cell: dict, value: Any, b: dict, styles: list[dict]) -> None:
    """Escribe el valor conservando el formato de la celda. Fechas y horas van como número de serie para que
    el formato de la plantilla se aplique; si la celda no tiene formato de fecha se usa uno legible."""
    fmt = b.get("format")
    if isinstance(value, tuple):
        kind, moment = value
        serial = to_serial(moment.time() if kind == "time" else moment)
        cell_fmt = (styles[cell.get("s", 0)] or {}).get("fmt", "") if cell.get("s", 0) < len(styles) else ""
        if fmt:
            cell["v"] = format_value(serial, fmt)
        elif cell_fmt and re.search(r"[hdy]", re.sub(r'"[^"]*"|\[[^\]]*\]', "", cell_fmt), re.IGNORECASE):
            cell["v"] = serial
        else:
            cell["v"] = format_value(serial, {"time": DEFAULT_TIME_FMT, "date": DEFAULT_DATE_FMT}.get(
                kind, f"{DEFAULT_DATE_FMT} {DEFAULT_TIME_FMT}"))
        return
    if isinstance(value, Decimal):
        cell["v"] = format_value(value, fmt) if fmt else value
        return
    cell["v"] = "" if value is None else str(value)


def _insert_rows(out: dict, grid: dict, start: int, end: int, total_rows: int) -> tuple[dict, dict]:
    capacity = end - start + 1
    extra = total_rows - capacity

    def template_row(j: int) -> int:     # fila de la plantilla que da el formato al producto j
        if j == total_rows - 1:
            return end                   # la última conserva el cierre (bordes inferiores) de la tabla
        if j < capacity - 1:
            return start + j
        return start + max(0, capacity - 2)

    new_grid: dict[tuple[int, int], dict] = {}
    for (r, c), cell in grid.items():
        if r < start:
            new_grid[(r, c)] = cell
        elif r > end:
            new_grid[(r + extra, c)] = cell
    for j in range(total_rows):
        src = template_row(j)
        for (r, c), cell in grid.items():
            if r == src:
                new_grid[(start + j, c)] = copy.deepcopy(cell)
    rows = out["rows"]
    out["rows"] = rows[:start - 1] + [rows[template_row(j) - 1] for j in range(total_rows)] + rows[end:]
    merges = []
    for m in out["merges"]:
        a1, b1, a2, b2 = parse_range(m)
        if a2 < start:
            merges.append(m)
        elif a1 > end:
            merges.append(range_ref(a1 + extra, b1, a2 + extra, b2))
        elif a1 == a2 and start <= a1 <= end:
            continue                      # combinaciones de una fila de la tabla: se rehacen por producto
        else:
            merges.append(range_ref(a1, b1, a2 + extra if a2 >= end else a2, b2))
    row_merges = {}
    for m in out["merges"]:
        a1, b1, a2, b2 = parse_range(m)
        if a1 == a2 and start <= a1 <= end:
            row_merges.setdefault(a1, []).append((b1, b2))
    for j in range(total_rows):
        for b1, b2 in row_merges.get(template_row(j), []):
            merges.append(range_ref(start + j, b1, start + j, b2))
    out["merges"] = merges
    for img in out.get("images", []):
        if img["row"] + 1 > end:
            img["row"] += extra
    page = out.get("page") or {}
    if page.get("print_area"):
        r1, c1, r2, c2 = parse_range(page["print_area"])
        page["print_area"] = range_ref(r1, c1, r2 + extra if r2 >= end else r2, c2)
    page["row_breaks"] = [b + extra if b >= end else b for b in page.get("row_breaks") or []]
    return new_grid, out


# ------------------------------------------------------------------ datos de demostración
def demo_data(lines: int = 3, now: datetime | None = None) -> DocData:
    """Datos de demostración, claramente identificados, para probar una plantilla antes de usarla."""
    now = now or datetime.now()
    items = [{"cantidad": Decimal(1 + i % 3), "codigo": f"{i + 1:04d}", "descripcion": f"PRODUCTO DEMO {i + 1}",
              "unidad": "und", "precio": Decimal(5000 * (1 + i % 4)), "precio_lista": Decimal(5000 * (1 + i % 4)),
              "descuento_linea": Decimal(0), "iva_pct": Decimal(19)} for i in range(lines)]
    header = {
        "empresa_nombre": "EMPRESA DE DEMOSTRACIÓN", "empresa_razon_social": "DEMOSTRACIÓN S.A.S.", "empresa_nit": "900.000.000-0",
        "empresa_direccion": "CALLE 0 # 0-00", "empresa_ciudad": "CIUDAD", "empresa_telefono": "300 000 0000",
        "empresa_email": "demo@ejemplo.com", "empresa_pie": "DOCUMENTO DE DEMOSTRACIÓN — NO VÁLIDO",
        "cliente_nombre": "CLIENTE DE DEMOSTRACIÓN", "cliente_identificacion": "", "cliente_tipo_documento": "",
        "cliente_direccion": "", "cliente_telefono": "", "cliente_email": "",
        "tipo_documento": "DEMOSTRACIÓN", "numero": "DEMO-000001", "fecha": now.date(), "valido_hasta": "",
        "vendedor": "USUARIO DE DEMOSTRACIÓN", "observaciones": "Datos de demostración: no corresponden a una operación real.",
    }
    return DocData(header=header, lines=items, printed_at=now, demo=True)

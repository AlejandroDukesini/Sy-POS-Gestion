"""Aritmética decimal y almacenamiento en enteros.

  * dinero      -> INTEGER en centavos        (Decimal("1234.56") <-> 123456)
  * cantidades  -> INTEGER en milésimas       (Decimal("2.5")     <-> 2500)
  * porcentajes -> INTEGER en puntos básicos  (Decimal("19")      <-> 1900)

Todo cálculo se hace con Decimal; la conversión a entero redondea HALF_UP.
"""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from .errors import ValidationError

MONEY_SCALE = 100
QTY_SCALE = 1000
BP_SCALE = 100


def parse_decimal(value: Any) -> Decimal | None:
    """Interpreta números escritos por personas o leídos de Excel: '1.234.567,50', '1,234.5', '$ 12.500', 19."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    text = str(value).strip().replace("$", "").replace("%", "").replace(" ", "").replace(" ", "")
    if not text:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", "") if text.count(",") > 1 else text.replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", text):
        text = text.replace(".", "")
    try:
        result = Decimal(text)
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def _scaled(value: Any, scale: int, label: str) -> int:
    number = parse_decimal(value)
    if number is None:
        raise ValidationError(f"{label}: valor numérico no válido ({value!r}).")
    return int((number * scale).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def to_cents(value: Any, label: str = "Importe") -> int:
    return _scaled(value, MONEY_SCALE, label)


def to_milli(value: Any, label: str = "Cantidad") -> int:
    return _scaled(value, QTY_SCALE, label)


def to_bp(value: Any, label: str = "Porcentaje") -> int:
    return _scaled(value, BP_SCALE, label)


def from_cents(value: int | None) -> Decimal:
    return (Decimal(int(value or 0)) / MONEY_SCALE).quantize(Decimal("0.01"))


def from_milli(value: int | None) -> Decimal:
    return (Decimal(int(value or 0)) / QTY_SCALE).normalize() + Decimal(0)


def round_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def cents_str(value: int | None) -> str:
    """Representación exacta para JSON ('1234.50'); nunca float."""
    return f"{from_cents(value):.2f}"


def milli_str(value: int | None) -> str:
    q = from_milli(value)
    text = format(q, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def bp_str(value: int | None) -> str:
    return milli_str((value or 0) * 10)  # puntos básicos -> porcentaje con hasta dos decimales


def fmt_money(value: int | None, symbol: str = "$") -> str:
    """Formato colombiano: $ 1.234.567,50 (sin decimales si son cero)."""
    amount = from_cents(value)
    negative = amount < 0
    amount = abs(amount)
    integer, _, frac = f"{amount:.2f}".partition(".")
    groups = f"{int(integer):,}".replace(",", ".")
    text = f"{groups},{frac}" if frac != "00" else groups
    return f"{'-' if negative else ''}{symbol} {text}".strip()

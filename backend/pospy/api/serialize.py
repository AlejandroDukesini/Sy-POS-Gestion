"""Convierte la representación interna (enteros) a JSON exacto para la interfaz.

  campo_cents -> campo: "1234.50"   (texto decimal: nunca float)
  campo_milli -> campo: "2.5"
  campo_bp    -> campo: "19"        (porcentaje)
"""
from __future__ import annotations

from typing import Any

from ..core.money import bp_str, cents_str, milli_str

_SUFFIXES = (("_cents", cents_str), ("_milli", milli_str), ("_bp", bp_str))


def out(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            for suffix, fn in _SUFFIXES:
                if isinstance(key, str) and key.endswith(suffix) and (item is None or isinstance(item, int)):
                    result[key[: -len(suffix)]] = None if item is None else fn(item)
                    break
            else:
                result[key] = out(item)
        return result
    if isinstance(value, (list, tuple)):
        return [out(v) for v in value]
    return value

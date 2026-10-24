"""Cálculo de líneas y totales: única implementación, usada por el punto de venta y los documentos.

Por línea (importes en centavos, redondeo HALF_UP por línea):
  precio de lista   = precio sin descuento del producto
  precio unitario   = precio con descuento (si existe) menos el descuento manual (%)
  bruto             = precio de lista × cantidad
  neto              = precio unitario × cantidad (+ IVA si los precios NO incluyen IVA)
  descuento         = bruto − neto (antes de IVA cuando los precios no lo incluyen)
  IVA               = neto − neto / (1 + tarifa)   si los precios incluyen IVA
                    = (precio unitario × cantidad) × tarifa   si no lo incluyen
Invariante: bruto − descuento = neto, y el total del documento es la suma de los netos.
"""
from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from decimal import Decimal

from ..core.actor import Actor
from ..core.errors import ValidationError
from ..core.money import parse_decimal, round_cents, to_bp, to_milli


@dataclass
class PricedLine:
    line_no: int
    product_id: int
    code: str
    description: str
    unit: str
    qty_milli: int
    list_price_cents: int
    unit_price_cents: int
    manual_discount_bp: int
    gross_cents: int
    discount_cents: int
    net_cents: int
    tax_rate_bp: int
    tax_cents: int
    unit_cost_cents: int
    stock_milli: int


@dataclass
class Totals:
    gross_cents: int
    discount_cents: int
    tax_cents: int
    base_cents: int
    total_cents: int
    cost_cents: int
    items_milli: int


def price_line(product: sqlite3.Row | dict, qty_milli: int, manual_bp: int, include_tax: bool, line_no: int) -> PricedLine:
    qty = Decimal(qty_milli) / 1000
    list_price = int(product["price_cents"])
    base_unit = product["discount_price_cents"] if product["discount_price_cents"] is not None else list_price
    unit = round_cents(Decimal(base_unit) * (Decimal(10000 - manual_bp) / 10000))
    rate = Decimal(product["tax_rate_bp"]) / 10000
    gross_pre = round_cents(Decimal(list_price) * qty)
    net_pre = round_cents(Decimal(unit) * qty)
    if include_tax:
        tax = round_cents(Decimal(net_pre) - Decimal(net_pre) / (1 + rate)) if rate else 0
        net = net_pre
        gross = gross_pre
    else:
        tax = round_cents(Decimal(net_pre) * rate)
        net = net_pre + tax
        gross = net + (gross_pre - net_pre)
    return PricedLine(line_no, product["id"], product["code"], product["description"], product["unit"], qty_milli,
                      list_price, unit, manual_bp, gross, gross - net, net, product["tax_rate_bp"], tax,
                      product["cost_cents"], product["stock_milli"])


def totals_of(lines: list[PricedLine]) -> Totals:
    tax = sum(ln.tax_cents for ln in lines)
    total = sum(ln.net_cents for ln in lines)
    cost = sum(round_cents(Decimal(ln.unit_cost_cents) * Decimal(ln.qty_milli) / 1000) for ln in lines)
    return Totals(sum(ln.gross_cents for ln in lines), sum(ln.discount_cents for ln in lines), tax, total - tax, total,
                  cost, sum(ln.qty_milli for ln in lines))


def price_items(conn: sqlite3.Connection, actor: Actor, items: list[dict], ventas: dict,
                require_active: bool = True) -> tuple[list[PricedLine], Totals]:
    """items: [{product_id, qty, discount_pct?}]. Valida productos, cantidades y límite de descuento manual."""
    if not items:
        raise ValidationError("Agregue al menos un producto.")
    if len(items) > 500:
        raise ValidationError("Demasiadas líneas (máximo 500).")
    max_bp = int(ventas["max_manual_discount_pct"]) * 100
    lines: list[PricedLine] = []
    errors: dict[str, str] = {}
    for i, item in enumerate(items, start=1):
        key = f"lines.{i - 1}"
        try:
            product_id = int(item.get("product_id"))
        except (TypeError, ValueError):
            errors[key] = f"Línea {i}: producto no válido."
            continue
        product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if not product:
            errors[key] = f"Línea {i}: el producto no existe."
            continue
        if require_active and not product["active"]:
            errors[key] = f"Línea {i}: {product['code']} está desactivado."
            continue
        qty = parse_decimal(item.get("qty"))
        if qty is None or qty <= 0:
            errors[key] = f"Línea {i}: la cantidad debe ser mayor que cero."
            continue
        qty_milli = to_milli(qty)
        if qty_milli <= 0 or qty_milli > 10**12:
            errors[key] = f"Línea {i}: cantidad fuera de rango."
            continue
        if product["unit"] in ("und", "unidad") and qty_milli % 1000:
            errors[key] = f"Línea {i}: {product['code']} se vende por unidades enteras."
            continue
        raw_discount = item.get("discount_pct") or 0
        discount = parse_decimal(raw_discount)
        if discount is None or discount < 0 or discount > 100:
            errors[key] = f"Línea {i}: descuento no válido (0 a 100 %)."
            continue
        manual_bp = to_bp(discount)
        if manual_bp:
            if not actor.can("ventas.descuento"):
                errors[key] = f"Línea {i}: no tiene permiso para aplicar descuentos manuales."
                continue
            if manual_bp > max_bp:
                errors[key] = f"Línea {i}: el descuento máximo permitido es {max_bp // 100} %."
                continue
        lines.append(price_line(product, qty_milli, manual_bp, bool(ventas["prices_include_tax"]), i))
    if errors:
        first = next(iter(errors.values()))
        raise ValidationError(first if len(errors) == 1 else f"Revise las líneas ({len(errors)} con problemas). {first}", errors)
    return lines, totals_of(lines)


def as_dict(lines: list[PricedLine], totals: Totals) -> dict:
    return {"lines": [asdict(ln) for ln in lines], "totals": asdict(totals)}

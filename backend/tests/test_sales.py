"""5. Ventas con existencias insuficientes · 6. Totales, descuentos y pagos · devoluciones y anulaciones."""
from __future__ import annotations

import pytest

from pospy.core.errors import PermissionDenied, ValidationError

from .conftest import balance, key


def sell(ctx, actor, product, qty, payments, **extra):
    return ctx.sales.checkout(actor, {"lines": [{"product_id": product["id"], "qty": qty, **extra.pop("line", {})}],
                                      "payments": payments, **extra}, key())


def test_totals_with_discount_price_and_vat_included(ctx, admin, product):
    q = ctx.sales.quote(admin, [{"product_id": product["id"], "qty": "3"}])
    t = q["totals"]
    assert t["gross_cents"] == 6000000          # 3 × 20.000 de lista
    assert t["discount_cents"] == 600000        # 3 × 2.000 del precio con descuento
    assert t["total_cents"] == 5400000
    assert t["tax_cents"] == 862185             # 54.000 − 54.000 / 1,19
    assert t["base_cents"] + t["tax_cents"] == t["total_cents"]


def test_manual_discount_requires_permission_and_respects_limit(ctx, admin, employee, product):
    q = ctx.sales.quote(admin, [{"product_id": product["id"], "qty": "1", "discount_pct": "10"}])
    assert q["lines"][0]["unit_price_cents"] == 1620000   # 18.000 − 10 %
    with pytest.raises(ValidationError, match="máximo"):
        ctx.sales.quote(admin, [{"product_id": product["id"], "qty": "1", "discount_pct": "11"}])
    with pytest.raises(ValidationError, match="permiso"):
        ctx.sales.quote(employee, [{"product_id": product["id"], "qty": "1", "discount_pct": "5"}])


def test_prices_without_vat(ctx, admin, product):
    ctx.settings.update("ventas", {"prices_include_tax": False}, admin)
    t = ctx.sales.quote(admin, [{"product_id": product["id"], "qty": "1"}])["totals"]
    assert t["tax_cents"] == 342000 and t["total_cents"] == 2142000   # 18.000 + 19 %
    assert t["gross_cents"] - t["discount_cents"] == t["total_cents"]


def test_insufficient_stock_blocks_sale(ctx, admin, product, cash_id):
    q = ctx.sales.quote(admin, [{"product_id": product["id"], "qty": "11"}])
    assert not q["can_sell"] and q["stock_warnings"]
    with pytest.raises(ValidationError, match="insuficientes"):
        sell(ctx, admin, product, "11", [{"method_id": cash_id, "amount": "198000"}])
    with ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 0
        assert conn.execute("SELECT stock_milli FROM products").fetchone()[0] == 10000


def test_payments_must_match_total_and_change_is_computed(ctx, admin, product, cash_id, bank_id):
    with pytest.raises(ValidationError, match="no coinciden"):
        sell(ctx, admin, product, "1", [{"method_id": cash_id, "amount": "17000"}])
    sale = sell(ctx, admin, product, "2", [{"method_id": cash_id, "amount": "20000", "tendered": "50000"},
                                            {"method_id": bank_id, "amount": "16000", "reference": "TRF-77"}])
    assert sale["total_cents"] == 3600000 and sale["change_cents"] == 3000000 and sale["credit_cents"] == 0
    assert balance(ctx, "1105") == 2000000 and balance(ctx, "1110") == 1600000
    assert balance(ctx, "4135") == -(3600000 - sale["tax_cents"]) and balance(ctx, "2408") == -sale["tax_cents"]
    assert balance(ctx, "6135") == 2000000   # costo 2 × 10.000
    assert ctx.inventory.get(admin, product["id"])["stock_milli"] == 8000


def test_double_submit_is_idempotent(ctx, admin, product, cash_id):
    k = key()
    data = {"lines": [{"product_id": product["id"], "qty": "1"}], "payments": [{"method_id": cash_id, "amount": "18000"}]}
    first = ctx.sales.checkout(admin, data, k)
    again = ctx.sales.checkout(admin, data, k)
    assert again["duplicate"] and again["id"] == first["id"]
    assert ctx.inventory.get(admin, product["id"])["stock_milli"] == 9000


def test_credit_sale_is_receivable_not_cash(ctx, admin, product, credit_id, cash_id):
    with pytest.raises(ValidationError, match="cliente"):
        sell(ctx, admin, product, "1", [{"method_id": credit_id, "amount": "18000"}])
    customer = ctx.catalog.save_party(admin, "clientes", {"name": "Taller Gómez", "identification": "800", "credit_days": 15})
    sale = sell(ctx, admin, product, "2", [{"method_id": credit_id, "amount": "36000"}], customer_id=customer["id"])
    assert sale["credit_cents"] == 3600000 and sale["receivable"]["status"] == "vigente"
    assert balance(ctx, "1105") == 0 and balance(ctx, "1305") == 3600000
    ar_id = sale["receivable"]["id"]
    ctx.receivables.register_payment(admin, ar_id, {"amount": "10000", "method_id": cash_id}, key())
    assert ctx.receivables.detail(admin, ar_id)["balance_cents"] == 2600000
    assert balance(ctx, "1105") == 1000000 and balance(ctx, "1305") == 2600000
    with pytest.raises(ValidationError, match="cobros"):
        ctx.sales.void(admin, sale["id"], "error")


def test_void_restores_stock_and_reverses_entries(ctx, admin, product, cash_id):
    sale = sell(ctx, admin, product, "3", [{"method_id": cash_id, "amount": "54000"}])
    with pytest.raises(ValidationError):
        ctx.sales.void(admin, sale["id"], "  ")
    voided = ctx.sales.void(admin, sale["id"], "Cliente desistió")
    assert voided["status"] == "anulada"
    assert ctx.inventory.get(admin, product["id"])["stock_milli"] == 10000
    for code in ("1105", "4135", "2408", "6135"):
        assert balance(ctx, code) == 0, code
    with pytest.raises(ValidationError, match="ya estaba"):
        ctx.sales.void(admin, sale["id"], "otra vez")


def test_partial_returns_without_rounding_residue(ctx, admin, product, cash_id):
    sale = sell(ctx, admin, product, "3", [{"method_id": cash_id, "amount": "54000"}])
    line = sale["lines"][0]
    with pytest.raises(ValidationError, match="reembolsa"):
        ctx.sales.register_return(admin, sale["id"], {"reason": "Defecto", "lines": [{"sale_line_id": line["id"], "qty": "1"}]},
                                  key())
    r1 = ctx.sales.register_return(admin, sale["id"], {"reason": "Defecto", "refund_method_id": cash_id,
                                                       "lines": [{"sale_line_id": line["id"], "qty": "1"}]}, key())
    r2 = ctx.sales.register_return(admin, sale["id"], {"reason": "Defecto", "refund_method_id": cash_id,
                                                       "lines": [{"sale_line_id": line["id"], "qty": "2"}]}, key())
    total_returned = r1["returns"][0]["total_cents"] + r2["returns"][1]["total_cents"]
    assert total_returned == 5400000
    tax_returned = sum(r["tax_cents"] for r in r2["returns"])
    assert tax_returned == sale["tax_cents"]
    with pytest.raises(ValidationError, match="máximo"):
        ctx.sales.register_return(admin, sale["id"], {"reason": "x", "refund_method_id": cash_id,
                                                      "lines": [{"sale_line_id": line["id"], "qty": "1"}]}, key())
    assert ctx.inventory.get(admin, product["id"])["stock_milli"] == 10000
    assert balance(ctx, "1105") == 0 and balance(ctx, "2408") == 0
    with pytest.raises(ValidationError, match="devoluciones"):
        ctx.sales.void(admin, sale["id"], "x")


def test_return_on_credit_sale_reduces_receivable(ctx, admin, product, credit_id):
    customer = ctx.catalog.save_party(admin, "clientes", {"name": "Cliente crédito"})
    sale = sell(ctx, admin, product, "2", [{"method_id": credit_id, "amount": "36000"}], customer_id=customer["id"])
    ret = ctx.sales.register_return(admin, sale["id"], {"reason": "Sobró", "lines": [
        {"sale_line_id": sale["lines"][0]["id"], "qty": "1"}]}, key())
    assert ret["returns"][0]["credit_applied_cents"] == 1800000 and ret["returns"][0]["refund_cents"] == 0
    assert ctx.receivables.detail(admin, sale["receivable"]["id"])["balance_cents"] == 1800000
    assert balance(ctx, "1305") == 1800000


def test_employee_cannot_void_without_permission(ctx, admin, employee, product, cash_id):
    sale = sell(ctx, employee, product, "1", [{"method_id": cash_id, "amount": "18000"}])
    with pytest.raises(PermissionDenied):
        ctx.sales.void(employee, sale["id"], "x")
    summary = ctx.sales.day_summary(admin)
    assert summary["sales"] == 1 and summary["total_cents"] == 1800000


def test_inactive_product_cannot_be_sold(ctx, admin, product, cash_id):
    ctx.inventory.set_active(admin, product["id"], False)
    with pytest.raises(ValidationError, match="desactivado"):
        sell(ctx, admin, product, "1", [{"method_id": cash_id, "amount": "18000"}])


def test_fractional_quantity_rules(ctx, admin, cash_id):
    rope = ctx.inventory.create(admin, {"code": "CUERDA", "description": "Cuerda", "unit": "m", "price": "1000",
                                        "initial_stock": "10"})
    sale = sell(ctx, admin, rope, "2.5", [{"method_id": cash_id, "amount": "2500"}])
    assert sale["lines"][0]["qty_milli"] == 2500
    nail = ctx.inventory.create(admin, {"code": "CLAVO", "description": "Clavo", "price": "100", "initial_stock": "10"})
    with pytest.raises(ValidationError, match="enteras"):
        sell(ctx, admin, nail, "1.5", [{"method_id": cash_id, "amount": "150"}])


def test_quote_payment_summary_for_interface(ctx, admin, product, cash_id):
    q = ctx.sales.quote(admin, [{"product_id": product["id"], "qty": "2"}],
                        [{"method_id": cash_id, "amount": "36000", "tendered": "50000"}])
    s = q["payment_summary"]
    assert s["complete"] and s["change_cents"] == 1400000 and s["remaining_cents"] == 0

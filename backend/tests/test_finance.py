"""10. Cálculos financieros con datos de prueba controlados."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from pospy.core.clock import local_today
from pospy.core.errors import ValidationError

from .conftest import balance, key


@pytest.fixture()
def books(ctx, admin, product, cash_id, credit_id, bank_id):
    """Escenario controlado:
    capital en banco 1.000.000 · inventario inicial 10 × 10.000 (fixture) · venta contado 2 × 18.000 ·
    venta a crédito 1 × 18.000 · arriendo 300.000 (fijo) · comisión 20.000 (variable).
    """
    ctx.finance.manual_entry(admin, {"description": "Aporte de capital", "lines": [
        {"account_code": "1110", "debit": "1000000"}, {"account_code": "3105", "credit": "1000000"}]}, key())
    ctx.sales.checkout(admin, {"lines": [{"product_id": product["id"], "qty": "2"}],
                               "payments": [{"method_id": cash_id, "amount": "36000"}]}, key())
    customer = ctx.catalog.save_party(admin, "clientes", {"name": "Cliente A"})
    credit = ctx.sales.checkout(admin, {"customer_id": customer["id"], "lines": [{"product_id": product["id"], "qty": "1"}],
                                        "payments": [{"method_id": credit_id, "amount": "18000"}]}, key())
    ctx.finance.register_expense(admin, {"description": "Arriendo", "account_code": "5120", "amount": "300000",
                                         "method_id": bank_id}, key())
    ctx.finance.register_expense(admin, {"description": "Comisión", "account_code": "5205", "amount": "20000",
                                         "method_id": cash_id}, key())
    return {"customer": customer, "credit_sale": credit}


def test_balance_sheet_is_balanced_with_exact_figures(ctx, admin, books):
    bs = ctx.finance.balance_sheet(admin)["current"]
    assert bs["balanced"] and bs["difference_cents"] == 0
    assets = {a["code"]: a["balance_cents"] for a in bs["assets"]}
    assert assets == {"1105": 3600000 - 2000000, "1110": 100000000 - 30000000, "1305": 1800000, "1435": 7 * 1000000}
    liabilities = {a["code"]: a["balance_cents"] for a in bs["liabilities"]}
    tax = round(54000 * 100 - 54000 * 100 / 1.19)
    assert liabilities == {"2408": tax}
    assert bs["total_assets_cents"] == bs["total_liabilities_cents"] + bs["total_equity_cents"]


def test_balance_sheet_comparison_and_missing_data(ctx, admin, books):
    yesterday = str(local_today() - timedelta(days=1))
    bs = ctx.finance.balance_sheet(admin, compare_to=yesterday)
    assert bs["previous"]["total_assets_cents"] == 0
    empty = ctx.finance.balance_sheet(admin, as_of="2000-01-01")
    assert empty["missing"]


def test_income_statement(ctx, admin, books):
    pnl = ctx.finance.income_statement(admin)
    tax = round(54000 * 100 - 54000 * 100 / 1.19)
    assert pnl["net_sales_cents"] == 5400000 - tax
    assert pnl["cogs_cents"] == 3000000
    assert pnl["total_expenses_cents"] == 32000000
    assert pnl["net_income_cents"] == 5400000 - tax - 3000000 - 32000000


def test_break_even(ctx, admin, books):
    manual = ctx.finance.break_even(admin, overrides={"fixed_costs": "1000000", "price": "50000", "variable_cost": "30000"})
    assert manual["source"] == "manual"
    assert manual["break_even_units"] == "50.00" and manual["break_even_sales_cents"] == 250000000
    assert manual["contribution_margin_ratio"] == "40.00"
    real = ctx.finance.break_even(admin)
    assert real["fixed_costs_cents"] == 30000000                 # solo el arriendo es fijo
    assert real["variable_costs_cents"] == 3000000 + 2000000     # costo de ventas + comisión
    assert real["units_sold"] == "3"
    # Con estos datos la comisión vuelve negativo el margen: se informa, no se inventa un punto de equilibrio.
    assert real["contribution_margin_unit_cents"] < 0 and "break_even_units" not in real
    assert any("margen de contribución" in m for m in real["missing"])
    empty = ctx.finance.break_even(admin, date_from="2000-01-01", date_to="2000-01-31")
    assert len(empty["missing"]) == 3 and "break_even_units" not in empty


def test_cash_flow_and_projection(ctx, admin, books):
    cf = ctx.finance.cash_flow(admin)
    cur = cf["current"]
    assert cur["opening_cents"] == 0
    assert cur["total_in_cents"] == 100000000 + 3600000
    assert cur["total_out_cents"] == 30000000 + 2000000
    assert cur["closing_cents"] == balance(ctx, "1105") + balance(ctx, "1110")
    labels = {i["label"] for i in cur["inflows"]}
    assert "Ventas cobradas al contado" in labels
    # la venta a crédito no aparece como entrada de efectivo; sí en la proyección como cobro esperado
    assert sum(w["in_cents"] for w in cf["projection"]["weeks"]) == 1800000


def test_receivables_payments_aging_and_void(ctx, admin, books, cash_id):
    ar = books["credit_sale"]["receivable"]["id"]
    with pytest.raises(ValidationError, match="supera"):
        ctx.receivables.register_payment(admin, ar, {"amount": "18001", "method_id": cash_id}, key())
    k = key()
    ctx.receivables.register_payment(admin, ar, {"amount": "8000", "method_id": cash_id}, k)
    dup = ctx.receivables.register_payment(admin, ar, {"amount": "8000", "method_id": cash_id}, k)
    assert dup["duplicate"] and dup["balance_cents"] == 1000000
    detail = ctx.receivables.detail(admin, ar)
    voided = ctx.receivables.void_payment(admin, detail["payments"][0]["id"], "Cheque devuelto")
    assert voided["balance_cents"] == 1800000 and balance(ctx, "1305") == 1800000
    ctx.receivables.register_payment(admin, ar, {"amount": "18000", "method_id": cash_id}, key())
    assert ctx.receivables.list(admin, "pagadas")[0]["state"] == "pagada"
    # antigüedad: una cuenta manual vencida hace 45 días
    old = (local_today() - timedelta(days=60)).isoformat()
    due = (local_today() - timedelta(days=45)).isoformat()
    ctx.receivables.create(admin, {"customer_id": books["customer"]["id"], "amount": "50000", "issue_date": old,
                                   "due_date": due, "description": "Servicio", "account_code": "4295"})
    aging = ctx.receivables.aging(admin)
    assert aging["totals"]["31_60_cents"] == 5000000 and aging["totals"]["total_cents"] == 5000000
    assert ctx.receivables.alerts(admin)["vencidas"]


def test_payables_flow(ctx, admin, bank_id):
    supplier = ctx.catalog.save_party(admin, "proveedores", {"name": "Proveedor X"})
    item = ctx.payables.create(admin, {"supplier_id": supplier["id"], "number": "F-100", "amount": "200000",
                                       "due_date": str(date.today() + timedelta(days=3)), "account_code": "5135"})
    assert ctx.payables.alerts(admin)["por_vencer"]
    with pytest.raises(Exception, match="ya está registrada"):
        ctx.payables.create(admin, {"supplier_id": supplier["id"], "number": "F-100", "amount": "1"})
    ctx.payables.register_payment(admin, item["id"], {"amount": "50000", "method_id": bank_id}, key())
    assert ctx.payables.detail(admin, item["id"])["balance_cents"] == 15000000
    assert balance(ctx, "2205") == -15000000 and balance(ctx, "1110") == -5000000
    with pytest.raises(ValidationError, match="pagos registrados"):
        ctx.payables.void(admin, item["id"], "error")


def test_manual_entries_must_balance_and_reverse(ctx, admin):
    with pytest.raises(ValidationError, match="no cuadra"):
        ctx.finance.manual_entry(admin, {"description": "Mal", "lines": [
            {"account_code": "1105", "debit": "100"}, {"account_code": "3105", "credit": "90"}]}, key())
    with pytest.raises(ValidationError):
        ctx.finance.manual_entry(admin, {"description": "Ambos", "lines": [
            {"account_code": "1105", "debit": "100", "credit": "100"}, {"account_code": "3105", "credit": "100"}]}, key())
    entry = ctx.finance.manual_entry(admin, {"description": "Préstamo", "lines": [
        {"account_code": "1110", "debit": "500000"}, {"account_code": "2105", "credit": "500000"}]}, key())["entry_id"]
    ctx.finance.reverse_entry(admin, entry, "Registrado por error")
    assert balance(ctx, "1110") == 0
    with pytest.raises(ValidationError, match="ya fue reversado"):
        ctx.finance.reverse_entry(admin, entry, "otra vez")
    assert ctx.finance.trial_balance(admin)["balanced"]


def test_operational_entries_cannot_be_reversed_manually(ctx, admin, books):
    sale_entry = ctx.finance.journal(admin, source="venta")["items"][0]
    with pytest.raises(ValidationError, match="módulo"):
        ctx.finance.reverse_entry(admin, sale_entry["id"], "x")


def test_bank_reconciliation(ctx, admin, books):
    pending = ctx.finance.unreconciled(admin, "1110")
    assert len(pending["lines"]) == 2
    deposit = next(ln for ln in pending["lines"] if ln["debit_cents"])
    rec = ctx.finance.reconcile(admin, {"account_code": "1110", "statement_date": str(local_today()),
                                        "statement_balance": "1000000", "line_ids": [deposit["id"]]})
    assert rec["difference_cents"] == 0 and rec["book_balance_cents"] == 70000000
    assert len(ctx.finance.unreconciled(admin, "1110")["lines"]) == 1
    with pytest.raises(ValidationError, match="ya estaba conciliado"):
        ctx.finance.reconcile(admin, {"account_code": "1110", "statement_date": str(local_today()),
                                      "statement_balance": "0", "line_ids": [deposit["id"]]})


def test_integrity_checks(ctx, admin, books):
    result = ctx.finance.integrity(admin)
    assert result["ok"], result["checks"]


def test_ledger_running_balance(ctx, admin, books):
    led = ctx.finance.ledger_account(admin, "1105")
    assert led["closing_cents"] == balance(ctx, "1105")

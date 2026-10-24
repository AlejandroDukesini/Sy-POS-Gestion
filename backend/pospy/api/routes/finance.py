"""Finanzas: BS, BEP, CF, ACC (libro, mayor, balance de prueba, asientos, gastos, conciliación), AP y AR."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ...context import AppContext
from ...core.actor import Actor
from ...core.errors import NotFoundError
from ..deps import actor, ctx, idempotency_key
from ..models import Account, BreakEvenOverrides, Expense, ManualEntry, OpenItem, OpenItemPayment, Reason, Reconcile
from ..serialize import out

router = APIRouter(prefix="/finance", tags=["finanzas"])


def _book(app: AppContext, kind: str):
    if kind == "ar":
        return app.receivables
    if kind == "ap":
        return app.payables
    raise NotFoundError("Libro desconocido (use ar o ap).")


@router.get("/balance-sheet")
def balance_sheet(as_of: str | None = None, compare_to: str | None = None, current: Actor = Depends(actor),
                  app: AppContext = Depends(ctx)):
    return out(app.finance.balance_sheet(current, as_of, compare_to))


@router.get("/income-statement")
def income_statement(date_from: str | None = None, date_to: str | None = None, current: Actor = Depends(actor),
                     app: AppContext = Depends(ctx)):
    return out(app.finance.income_statement(current, date_from, date_to))


@router.post("/break-even")
def break_even(body: BreakEvenOverrides, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    data = body.data()
    return out(app.finance.break_even(current, data.pop("date_from", None), data.pop("date_to", None), data))


@router.get("/cash-flow")
def cash_flow(date_from: str | None = None, date_to: str | None = None, projection_weeks: int = 8,
              current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.finance.cash_flow(current, date_from, date_to, projection_weeks))


@router.get("/accounts")
def accounts(include_inactive: bool = False, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.finance.accounts(current, include_inactive)


@router.post("/accounts")
def create_account(body: Account, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.finance.save_account(current, body.model_dump())


@router.put("/accounts/{account_id}")
def update_account(account_id: int, body: Account, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.finance.save_account(current, body.model_dump(), account_id)


@router.get("/journal")
def journal(date_from: str | None = None, date_to: str | None = None, source: str = "", page: int = 1, page_size: int = 50,
            current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.finance.journal(current, date_from, date_to, source, page, page_size))


@router.get("/ledger/{account_code}")
def ledger(account_code: str, date_from: str | None = None, date_to: str | None = None, current: Actor = Depends(actor),
           app: AppContext = Depends(ctx)):
    return out(app.finance.ledger_account(current, account_code, date_from, date_to))


@router.get("/trial-balance")
def trial_balance(as_of: str | None = None, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.finance.trial_balance(current, as_of))


@router.post("/entries")
def manual_entry(body: ManualEntry, key: str = Depends(idempotency_key), current: Actor = Depends(actor),
                 app: AppContext = Depends(ctx)):
    return app.finance.manual_entry(current, body.data(), key)


@router.post("/entries/{entry_id}/reverse")
def reverse(entry_id: int, body: Reason, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.finance.reverse_entry(current, entry_id, body.reason)


@router.post("/expenses")
def expense(body: Expense, key: str = Depends(idempotency_key), current: Actor = Depends(actor),
            app: AppContext = Depends(ctx)):
    return app.finance.register_expense(current, body.data(), key)


@router.get("/reconciliation/{account_code}")
def unreconciled(account_code: str, until: str | None = None, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.finance.unreconciled(current, account_code, until))


@router.post("/reconciliation")
def reconcile(body: Reconcile, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.finance.reconcile(current, body.data()))


@router.get("/integrity")
def integrity(current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.finance.integrity(current))


# ------------------------------------------------------------------ AR / AP
@router.get("/{kind}")
def open_items(kind: str, status: str = "pendientes", party_id: int | None = None, q: str = "", as_of: str | None = None,
               current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(_book(app, kind).list(current, status, party_id, q, as_of))


@router.get("/{kind}/aging")
def aging(kind: str, as_of: str | None = None, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(_book(app, kind).aging(current, as_of))


@router.get("/{kind}/alerts")
def alerts(kind: str, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(_book(app, kind).alerts(current))


@router.post("/{kind}")
def create_open_item(kind: str, body: OpenItem, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(_book(app, kind).create(current, body.data()))


@router.get("/{kind}/{item_id}")
def open_item(kind: str, item_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(_book(app, kind).detail(current, item_id))


@router.post("/{kind}/{item_id}/payments")
def pay(kind: str, item_id: int, body: OpenItemPayment, key: str = Depends(idempotency_key),
        current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(_book(app, kind).register_payment(current, item_id, body.data(), key))


@router.post("/{kind}/payments/{payment_id}/void")
def void_payment(kind: str, payment_id: int, body: Reason, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(_book(app, kind).void_payment(current, payment_id, body.reason))


@router.post("/{kind}/{item_id}/void")
def void_item(kind: str, item_id: int, body: Reason, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(_book(app, kind).void(current, item_id, body.reason))

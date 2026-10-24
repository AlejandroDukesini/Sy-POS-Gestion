"""Punto de venta, historial, anulaciones, devoluciones, comprobantes, clientes y métodos de pago."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ...context import AppContext
from ...core.actor import Actor
from ..deps import actor, ctx, idempotency_key
from ..models import BrowserPrintLog, Checkout, Party, PrintRequest, Quote, Reason, SaleReturn
from ..serialize import out

router = APIRouter(tags=["ventas"])


@router.post("/sales/quote")
def quote(body: Quote, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    result = app.sales.quote(current, body.data()["lines"])
    if not current.can("inventario.costos"):
        for ln in result["lines"]:
            ln.pop("unit_cost_cents", None)
        result["totals"].pop("cost_cents", None)
    return out(result)


@router.post("/sales")
def checkout(body: Checkout, key: str = Depends(idempotency_key), current: Actor = Depends(actor),
             app: AppContext = Depends(ctx)):
    sale = app.sales.checkout(current, body.data(), key)
    if app.settings.get("impresion")["auto_print_receipt"] and not sale["duplicate"]:
        try:
            sale["print"] = app.printing.print_receipt(current, sale["id"])
        except Exception as exc:  # noqa: BLE001 - la venta ya quedó registrada; se informa el fallo de impresión
            sale["print"] = {"printed": False, "error": getattr(exc, "detail", "No se pudo imprimir.")}
    return out(sale)


@router.get("/sales")
def list_sales(q: str = "", status: str = "", date_from: str = "", date_to: str = "", page: int = 1, page_size: int = 50,
               current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.sales.list(current, q, status, date_from, date_to, page, page_size))


@router.get("/sales/summary")
def day_summary(day: str | None = None, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.sales.day_summary(current, day))


@router.get("/sales/{sale_id}")
def get_sale(sale_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.sales.get(current, sale_id))


@router.post("/sales/{sale_id}/void")
def void_sale(sale_id: int, body: Reason, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.sales.void(current, sale_id, body.reason))


@router.post("/sales/{sale_id}/returns")
def sale_return(sale_id: int, body: SaleReturn, key: str = Depends(idempotency_key), current: Actor = Depends(actor),
                app: AppContext = Depends(ctx)):
    return out(app.sales.register_return(current, sale_id, body.data(), key))


@router.get("/sales/{sale_id}/receipt")
def receipt(sale_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.printing.receipt_text(current, sale_id))


@router.post("/sales/{sale_id}/print")
def print_receipt(sale_id: int, body: PrintRequest, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.printing.print_receipt(current, sale_id, body.copies)


@router.post("/printing/browser-log")
def browser_log(body: BrowserPrintLog, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    app.printing.log_browser_print(current, body.target_type, body.target_id, body.label)
    return {"ok": True}


@router.get("/printing/printers")
def printers(current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.printing.printers(current)


@router.get("/printing/jobs")
def print_jobs(target_type: str = "", target_id: int | None = None, current: Actor = Depends(actor),
               app: AppContext = Depends(ctx)):
    return app.printing.jobs(current, target_type, target_id)


@router.post("/printing/test")
def test_print(body: PrintRequest, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.printing.test_print(current, body.printer)


@router.get("/payment-methods")
def payment_methods(include_inactive: bool = False, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.catalog.payment_methods(current, include_inactive)


@router.get("/parties/{kind}")
def parties(kind: str, q: str = "", include_inactive: bool = False, page: int = 1, page_size: int = 50,
            sort: str | None = None, direction: str | None = None, current: Actor = Depends(actor),
            app: AppContext = Depends(ctx)):
    return app.catalog.parties(current, kind, q, include_inactive, page, page_size, sort, direction)


@router.get("/parties/{kind}/{party_id}")
def party(kind: str, party_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.catalog.get_party(current, kind, party_id)


@router.post("/parties/{kind}")
def create_party(kind: str, body: Party, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.catalog.save_party(current, kind, body.model_dump(exclude_none=True))


@router.put("/parties/{kind}/{party_id}")
def update_party(kind: str, party_id: int, body: Party, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.catalog.save_party(current, kind, body.model_dump(exclude_none=True), party_id)

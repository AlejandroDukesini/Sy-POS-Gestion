"""Inventario: productos, movimientos, categorías, exportación e importación con vista previa."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response

from ...context import AppContext
from ...core.actor import Actor
from ...core.errors import ValidationError
from ...services.inventory import ENTRY_COUNTERPARTS, EXIT_COUNTERPARTS, UNITS
from ..deps import actor, ctx, idempotency_key, inventory_key
from ..models import Category, ColumnOrder, InventoryColumnIn, InventoryColumnUpdate, Movement, Product
from ..serialize import out

router = APIRouter(tags=["inventario"])
MAX_UPLOAD = 50 * 1024 * 1024


async def _read(file: UploadFile) -> bytes:
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise ValidationError("El archivo supera 50 MB.")
    return data


@router.get("/products")
def list_products(q: str = "", category_id: int | None = None, status: str = "activos", low_stock: bool = False,
                  sort: str | None = None, direction: str | None = None, page: int = 1, page_size: int = 50,
                  inv: str | None = Depends(inventory_key), current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.inventory.list(current, q, category_id, status, low_stock, sort, direction, page, page_size, inv))


@router.get("/products/lookup")
def lookup(q: str, limit: int = 20, inv: str | None = Depends(inventory_key), current: Actor = Depends(actor),
           app: AppContext = Depends(ctx)):
    return out(app.inventory.lookup(current, q, limit, inv))


@router.get("/products/meta")
def products_meta(inv: str | None = Depends(inventory_key), current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return {"units": UNITS, "entry_counterparts": ENTRY_COUNTERPARTS, "exit_counterparts": EXIT_COUNTERPARTS,
            "summary": out(app.inventory.summary(current, inv))}


@router.get("/inventory/dashboard")
def dashboard(date_from: str = "", date_to: str = "", product_id: int | None = None, user_id: int | None = None,
              inv: str | None = Depends(inventory_key), current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.inventory.dashboard(current, inv, date_from, date_to, product_id, user_id))


@router.get("/inventory/returns")
def returns(date_from: str = "", date_to: str = "", product_id: int | None = None, user_id: int | None = None,
            condition: str = "", page: int = 1, page_size: int = 50, inv: str | None = Depends(inventory_key),
            current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.inventory.returns(current, inv, date_from, date_to, product_id, user_id, condition, page, page_size))


@router.get("/products/export")
def export(fmt: str = "xlsx", inv: str | None = Depends(inventory_key), current: Actor = Depends(actor),
           app: AppContext = Depends(ctx)):
    data, name, mime = app.inventory.export(current, "csv" if fmt == "csv" else "xlsx", inv)
    return Response(data, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ------------------------------------------------------------------ columnas del inventario
@router.get("/inventory/columns")
def columns(include_archived: bool = False, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.inventory.columns.list(current, include_archived)


@router.post("/inventory/columns")
def create_column(body: InventoryColumnIn, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.inventory.columns.create(current, body.data())


@router.put("/inventory/columns/order")
def order_columns(body: ColumnOrder, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.inventory.columns.reorder(current, body.ids)


@router.put("/inventory/columns/{column_id}")
def update_column(column_id: int, body: InventoryColumnUpdate, dry_run: bool = False, current: Actor = Depends(actor),
                  app: AppContext = Depends(ctx)):
    return app.inventory.columns.update(current, column_id, body.data(), dry_run)


@router.post("/inventory/columns/{column_id}/archive")
def archive_column(column_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.inventory.columns.set_active(current, column_id, False)


@router.post("/inventory/columns/{column_id}/restore")
def restore_column(column_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.inventory.columns.set_active(current, column_id, True)


@router.delete("/inventory/columns/{column_id}")
def delete_column(column_id: int, dry_run: bool = False, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.inventory.columns.delete(current, column_id, dry_run)


@router.get("/products/{product_id}")
def get_product(product_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.inventory.get(current, product_id))


@router.post("/products")
def create_product(body: Product, inv: str | None = Depends(inventory_key), current: Actor = Depends(actor),
                   app: AppContext = Depends(ctx)):
    return out(app.inventory.create(current, body.data(), inv))


@router.put("/products/{product_id}")
def update_product(product_id: int, body: Product, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    data = body.data()
    data.pop("initial_stock", None)
    return out(app.inventory.update(current, product_id, data))


@router.post("/products/{product_id}/movements")
def movement(product_id: int, body: Movement, key: str = Depends(idempotency_key), current: Actor = Depends(actor),
             app: AppContext = Depends(ctx)):
    return out(app.inventory.register_movement(current, product_id, body.data(), key))


@router.get("/movements")
def movements(product_id: int | None = None, kind: str = "", date_from: str = "", date_to: str = "", page: int = 1,
              page_size: int = 50, category: str = "", user_id: int | None = None, inv: str | None = Depends(inventory_key),
              current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.inventory.history(current, product_id, kind, date_from, date_to, page, page_size, inv, category, user_id))


@router.get("/categories")
def categories(include_inactive: bool = False, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.catalog.categories(current, include_inactive)


@router.post("/categories")
def create_category(body: Category, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.catalog.save_category(current, body.model_dump())


@router.put("/categories/{category_id}")
def update_category(category_id: int, body: Category, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.catalog.save_category(current, body.model_dump(), category_id)


# ------------------------------------------------------------------ importación manual de archivo
@router.post("/imports/inspect")
async def inspect(file: UploadFile = File(...), sheet: str = Form(""), header_row: int = Form(0),
                  current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.sync.inspect_upload(current, file.filename or "archivo.xlsx", await _read(file), sheet, header_row)


@router.post("/imports/preview")
async def preview(file: UploadFile = File(...), options: str = Form("{}"), inv: str | None = Depends(inventory_key),
                  current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    try:
        opts = json.loads(options)
    except json.JSONDecodeError:
        raise ValidationError("Opciones de importación no válidas.") from None
    return app.sync.preview_upload(current, file.filename or "archivo.xlsx", await _read(file), opts, inv)


@router.get("/imports")
def runs(current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.sync.runs(current)


@router.get("/imports/{run_id}")
def run(run_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.sync.run(current, run_id)


@router.post("/imports/{run_id}/apply")
def apply(run_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.sync.apply(current, run_id)


@router.post("/imports/{run_id}/discard")
def discard(run_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.sync.discard(current, run_id)

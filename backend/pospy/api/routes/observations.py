"""Observaciones de inventario: registro, consulta con filtros, seguimiento, adjuntos e indicadores.

Las rutas solo traducen HTTP; los permisos, validaciones e integridad los aplica ObservationService.
Ninguna de estas rutas modifica existencias ni movimientos de inventario.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse

from ...context import AppContext
from ...core.actor import Actor
from ...core.errors import ValidationError
from ..deps import actor, ctx, inventory_key
from ..models import Observation, ObservationComment, ObservationDelete, ObservationStatus
from ..serialize import out

router = APIRouter(tags=["observaciones"])
HARD_LIMIT = 20 * 1024 * 1024     # el límite real (10 MB) lo aplica el servicio; este corta lecturas enormes


@router.get("/observations/meta")
def meta(current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.observations.meta(current)


@router.get("/observations/products")
def products(q: str = "", limit: int = 15, inv: str | None = Depends(inventory_key), current: Actor = Depends(actor),
             app: AppContext = Depends(ctx)):
    return app.observations.product_search(current, q, limit, inv)


@router.get("/observations/products/{product_id}")
def product_context(product_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.observations.product_context(current, product_id))


@router.get("/observations/flags")
def flags(ids: str = "", current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    try:
        product_ids = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise ValidationError("Lista de productos no válida.") from None
    return app.observations.product_flags(current, product_ids)


@router.get("/observations")
def list_observations(q: str = "", product_id: int | None = None, category_id: int | None = None, priority: str = "",
                      status: str = "", responsible_id: int | None = None, supplier_id: int | None = None,
                      date_from: str = "", date_to: str = "", quick: str = "todas", sort: str = "recientes",
                      page: int = 1, page_size: int = 25, inv: str | None = Depends(inventory_key),
                      current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    filters = {"q": q, "product_id": product_id, "category_id": category_id, "priority": priority, "status": status,
               "responsible_id": responsible_id, "supplier_id": supplier_id, "date_from": date_from, "date_to": date_to,
               "quick": quick}
    return out(app.observations.list(current, filters, sort, page, page_size, inv))


@router.post("/observations")
def create(body: Observation, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.observations.create(current, body.data()))


@router.get("/observations/{observation_id}")
def detail(observation_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.observations.get(current, observation_id))


@router.put("/observations/{observation_id}")
def update(observation_id: int, body: Observation, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.observations.update(current, observation_id, body.data()))


@router.post("/observations/{observation_id}/status")
def change_status(observation_id: int, body: ObservationStatus, current: Actor = Depends(actor),
                  app: AppContext = Depends(ctx)):
    return out(app.observations.change_status(current, observation_id, body.status, body.comment or "", body.version))


@router.post("/observations/{observation_id}/comments")
def comment(observation_id: int, body: ObservationComment, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.observations.add_comment(current, observation_id, body.comment)


@router.post("/observations/{observation_id}/delete")
def delete(observation_id: int, body: ObservationDelete, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    app.observations.delete(current, observation_id, body.reason)
    return {"ok": True}


@router.post("/observations/{observation_id}/files")
async def upload(observation_id: int, file: UploadFile = File(...), current: Actor = Depends(actor),
                 app: AppContext = Depends(ctx)):
    data = await file.read(HARD_LIMIT + 1)
    if len(data) > HARD_LIMIT:
        raise ValidationError("Archivo demasiado grande.", {"file": "Máximo 10 MB."})
    return app.observations.upload_file(current, observation_id, file.filename or "", data)


@router.get("/observations/{observation_id}/files/{file_id}/download")
def download(observation_id: int, file_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    path, name, content_type = app.observations.file_for_download(current, observation_id, file_id)
    return FileResponse(path, filename=name, media_type=content_type)


@router.delete("/observations/{observation_id}/files/{file_id}")
def delete_file(observation_id: int, file_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    app.observations.delete_file(current, observation_id, file_id)
    return {"ok": True}

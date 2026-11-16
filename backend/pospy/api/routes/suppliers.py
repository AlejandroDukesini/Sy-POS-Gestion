"""Expediente de proveedores: vista general, resumen, asesor, notas, visitas, cotizaciones y archivos.

Los datos generales y de contacto se siguen guardando con /parties/proveedores (mismo servicio y
validaciones que antes), ampliado con WhatsApp, ciudad e información adicional.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse

from ...context import AppContext
from ...core.actor import Actor
from ...core.errors import ValidationError
from ..deps import actor, ctx
from ..models import SupplierAdvisor, SupplierNote, SupplierQuote, SupplierVisit
from ..serialize import out

router = APIRouter(tags=["proveedores"])
HARD_LIMIT = 50 * 1024 * 1024     # el límite configurable (MB) se aplica en el servicio; este corta lecturas enormes


async def _read(file: UploadFile) -> bytes:
    data = await file.read(HARD_LIMIT + 1)
    if len(data) > HARD_LIMIT:
        raise ValidationError("Archivo demasiado grande.", {"file": "Máximo 50 MB."})
    return data


@router.get("/suppliers")
def overview(q: str = "", status: str = "activos", current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.suppliers.overview(current, q, status)


@router.get("/suppliers/{supplier_id}")
def dashboard(supplier_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.suppliers.dashboard(current, supplier_id))


@router.put("/suppliers/{supplier_id}/advisor")
def advisor(supplier_id: int, body: SupplierAdvisor, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.suppliers.update_advisor(current, supplier_id, body.model_dump())


# ------------------------------------------------------------------ notas
@router.get("/suppliers/{supplier_id}/notes")
def notes(supplier_id: int, status: str = "", category: str = "", current: Actor = Depends(actor),
          app: AppContext = Depends(ctx)):
    return app.suppliers.notes(current, supplier_id, status, category)


@router.post("/suppliers/{supplier_id}/notes")
def create_note(supplier_id: int, body: SupplierNote, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.suppliers.save_note(current, supplier_id, body.data())


@router.put("/suppliers/{supplier_id}/notes/{note_id}")
def update_note(supplier_id: int, note_id: int, body: SupplierNote, current: Actor = Depends(actor),
                app: AppContext = Depends(ctx)):
    return app.suppliers.save_note(current, supplier_id, body.data(), note_id)


@router.delete("/suppliers/{supplier_id}/notes/{note_id}")
def delete_note(supplier_id: int, note_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    app.suppliers.delete_note(current, supplier_id, note_id)
    return {"ok": True}


# ------------------------------------------------------------------ visitas
@router.get("/suppliers/{supplier_id}/visits")
def visits(supplier_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.suppliers.visits(current, supplier_id)


@router.post("/suppliers/{supplier_id}/visits")
def create_visit(supplier_id: int, body: SupplierVisit, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.suppliers.save_visit(current, supplier_id, body.data())


@router.put("/suppliers/{supplier_id}/visits/{visit_id}")
def update_visit(supplier_id: int, visit_id: int, body: SupplierVisit, current: Actor = Depends(actor),
                 app: AppContext = Depends(ctx)):
    return app.suppliers.save_visit(current, supplier_id, body.data(), visit_id)


@router.delete("/suppliers/{supplier_id}/visits/{visit_id}")
def delete_visit(supplier_id: int, visit_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    app.suppliers.delete_visit(current, supplier_id, visit_id)
    return {"ok": True}


# ------------------------------------------------------------------ cotizaciones
@router.get("/suppliers/{supplier_id}/quotes")
def quotes(supplier_id: int, status: str = "", current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.suppliers.quotes(current, supplier_id, status))


@router.post("/suppliers/{supplier_id}/quotes")
def create_quote(supplier_id: int, body: SupplierQuote, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.suppliers.save_quote(current, supplier_id, body.data()))


@router.put("/suppliers/{supplier_id}/quotes/{quote_id}")
def update_quote(supplier_id: int, quote_id: int, body: SupplierQuote, current: Actor = Depends(actor),
                 app: AppContext = Depends(ctx)):
    return out(app.suppliers.save_quote(current, supplier_id, body.data(), quote_id))


@router.delete("/suppliers/{supplier_id}/quotes/{quote_id}")
def delete_quote(supplier_id: int, quote_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    app.suppliers.delete_quote(current, supplier_id, quote_id)
    return {"ok": True}


@router.post("/suppliers/{supplier_id}/quotes/{quote_id}/file")
async def quote_file(supplier_id: int, quote_id: int, file: UploadFile = File(...), current: Actor = Depends(actor),
                     app: AppContext = Depends(ctx)):
    return app.suppliers.upload_quote_file(current, supplier_id, quote_id, file.filename or "", await _read(file))


# ------------------------------------------------------------------ archivos (lista de productos)
@router.get("/suppliers/{supplier_id}/files")
def files(supplier_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.suppliers.product_files(current, supplier_id)


@router.post("/suppliers/{supplier_id}/files")
async def upload_file(supplier_id: int, file: UploadFile = File(...), current: Actor = Depends(actor),
                      app: AppContext = Depends(ctx)):
    return app.suppliers.upload_product_file(current, supplier_id, file.filename or "", await _read(file))


@router.get("/suppliers/{supplier_id}/files/{file_id}/download")
def download_file(supplier_id: int, file_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    path, name, content_type = app.suppliers.file_for_download(current, supplier_id, file_id)
    return FileResponse(path, filename=name, media_type=content_type)


@router.delete("/suppliers/{supplier_id}/files/{file_id}")
def delete_file(supplier_id: int, file_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    app.suppliers.delete_file(current, supplier_id, file_id)
    return {"ok": True}

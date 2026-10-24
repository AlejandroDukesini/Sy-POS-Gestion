"""Tipos de documento, plantillas, cotizaciones y órdenes, vista previa, PDF e impresión."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse, Response

from ...context import AppContext
from ...core.actor import Actor
from ...core.errors import ValidationError
from ..deps import actor, ctx, optional_idempotency_key
from ..models import Capacity, Document, DocumentType, FieldAssignment, PrintRequest, Reason
from ..serialize import out

router = APIRouter(tags=["documentos"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/document-types")
def types(include_inactive: bool = False, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.documents.types(current, include_inactive)


@router.get("/document-types/{type_id}")
def get_type(type_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.documents.get_type(current, type_id)


@router.post("/document-types")
def create_type(body: DocumentType, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.documents.save_type(current, body.model_dump())


@router.put("/document-types/{type_id}")
def update_type(type_id: int, body: DocumentType, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.documents.save_type(current, body.model_dump(exclude={"code"}), type_id)


@router.post("/document-types/{type_id}/template")
async def upload_template(type_id: int, file: UploadFile = File(...), current: Actor = Depends(actor),
                          app: AppContext = Depends(ctx)):
    data = await file.read(10 * 1024 * 1024 + 1)
    return app.documents.upload_template(current, type_id, file.filename or "", data)


@router.get("/document-types/{type_id}/template")
def download_template(type_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    path, name = app.documents.template_file(current, type_id)
    return FileResponse(path, filename=name)


@router.get("/document-types/{type_id}/sample-template")
def sample_template(type_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    data, name = app.documents.sample_template(current, type_id)
    return Response(data, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/document-types/{type_id}/mapping")
def assign(type_id: int, body: FieldAssignment, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.documents.assign_field(current, type_id, body.field, body.cell)


@router.post("/document-types/{type_id}/capacity")
def capacity(type_id: int, body: Capacity, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.documents.set_capacity(current, type_id, body.capacity)


@router.get("/documents")
def list_documents(type_id: int | None = None, q: str = "", status: str = "", page: int = 1, page_size: int = 50,
                   current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.documents.list(current, type_id, q, status, page, page_size))


@router.post("/documents")
def create_document(body: Document, key: str | None = Depends(optional_idempotency_key), current: Actor = Depends(actor),
                    app: AppContext = Depends(ctx)):
    if not body.type_id:
        raise ValidationError("Seleccione el tipo de documento.", {"type_id": "Tipo obligatorio."})
    return out(app.documents.create(current, body.model_dump(), key))


@router.get("/documents/{doc_id}")
def get_document(doc_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.documents.get(current, doc_id))


@router.put("/documents/{doc_id}")
def update_document(doc_id: int, body: Document, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.documents.update(current, doc_id, body.model_dump()))


@router.post("/documents/{doc_id}/void")
def void_document(doc_id: int, body: Reason, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return out(app.documents.void(current, doc_id, body.reason))


@router.get("/documents/{doc_id}/preview")
def preview(doc_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.documents.preview(current, doc_id)


@router.get("/documents/{doc_id}/file")
def file(doc_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    path = app.documents.generate(current, doc_id)
    return FileResponse(path, filename=path.name, media_type=XLSX)


@router.get("/documents/{doc_id}/pdf")
def pdf(doc_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    path = app.documents.pdf(current, doc_id)
    return FileResponse(path, filename=path.name, media_type="application/pdf")


@router.post("/documents/{doc_id}/print")
def print_document(doc_id: int, body: PrintRequest, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.documents.print(current, doc_id, body.printer, body.copies or 1)

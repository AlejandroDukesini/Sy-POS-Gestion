"""Plantillas de impresión: importar Excel, diseñar, vincular, vista previa y PDF de documentos y ventas."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import Field

from ...context import AppContext
from ...core.actor import Actor
from ..deps import actor, ctx, inventory_key
from ..models import Strict

router = APIRouter(tags=["plantillas"])
PDF = "application/pdf"


class TemplateNew(Strict):
    name: str = Field(max_length=80)
    kind: Literal["documento", "venta", "recibo"] = "documento"
    document_type_id: int | None = None
    discount_pct: str | None = None


class TemplateImport(Strict):
    token: str = Field(max_length=60)
    sheet: str = Field(max_length=60)
    name: str = Field(default="", max_length=80)
    kind: Literal["documento", "venta", "recibo"] = "documento"
    document_type_id: int | None = None


class TemplateSave(Strict):
    layout: dict[str, Any]
    bindings: dict[str, Any]
    note: str = Field(default="", max_length=200)
    activate: bool = False
    version: int | None = None


class TemplateMeta(Strict):
    name: str | None = Field(default=None, max_length=80)
    active: bool | None = None
    is_default: bool | None = None


class TemplatePreview(Strict):
    layout: dict[str, Any] | None = None
    bindings: dict[str, Any] | None = None
    lines: int = Field(default=3, ge=0, le=200)


class Duplicate(Strict):
    name: str = Field(default="", max_length=80)


def _pdf(data: bytes, name: str, meta: dict | None = None) -> Response:
    headers = {"Content-Disposition": f'inline; filename="{name}"', "Cache-Control": "no-store"}
    if meta:
        headers["X-Pages"] = str(meta.get("pages", ""))
    return Response(data, media_type=PDF, headers=headers)


@router.get("/print-templates")
def list_templates(kind: str = "", document_type_id: int | None = None, active: bool = False,
                   inv: str | None = Depends(inventory_key), current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.print_templates.list(current, inv, kind, document_type_id, active)


@router.get("/print-templates/catalog")
def catalog(current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.print_templates.catalog()


@router.post("/print-templates/inspect")
async def inspect(file: UploadFile = File(...), current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    data = await file.read(10 * 1024 * 1024 + 1)
    return app.print_templates.inspect_upload(current, file.filename or "", data)


@router.post("/print-templates/import")
def import_excel(body: TemplateImport, inv: str | None = Depends(inventory_key), current: Actor = Depends(actor),
                 app: AppContext = Depends(ctx)):
    return app.print_templates.import_excel(current, body.model_dump(), inv)


@router.post("/print-templates")
def create_blank(body: TemplateNew, inv: str | None = Depends(inventory_key), current: Actor = Depends(actor),
                 app: AppContext = Depends(ctx)):
    return app.print_templates.create_blank(current, body.model_dump(), inv)


@router.get("/print-templates/{public_id}")
def get_template(public_id: str, version: int | None = None, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.print_templates.get(current, public_id, version)


@router.put("/print-templates/{public_id}")
def save_template(public_id: str, body: TemplateSave, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.print_templates.save(current, public_id, body.model_dump(exclude_none=True))


@router.patch("/print-templates/{public_id}")
def update_meta(public_id: str, body: TemplateMeta, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.print_templates.update_meta(current, public_id, body.model_dump(exclude_none=True))


@router.post("/print-templates/{public_id}/duplicate")
def duplicate(public_id: str, body: Duplicate, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.print_templates.duplicate(current, public_id, body.name)


@router.delete("/print-templates/{public_id}")
def delete(public_id: str, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    app.print_templates.delete(current, public_id)
    return {"deleted": True}


@router.get("/print-templates/{public_id}/original")
def original(public_id: str, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    path, name = app.print_templates.original(current, public_id)
    return FileResponse(path, filename=name)


@router.post("/print-templates/{public_id}/images")
async def add_image(public_id: str, file: UploadFile = File(...), current: Actor = Depends(actor),
                    app: AppContext = Depends(ctx)):
    data = await file.read(3 * 1024 * 1024 + 1)
    return app.print_templates.add_image(current, public_id, file.filename or "", data)


@router.get("/print-templates/{public_id}/images/{name}")
def image(public_id: str, name: str, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    data, mime = app.print_templates.image(current, public_id, name)
    return Response(data, media_type=mime, headers={"Cache-Control": "private, max-age=86400"})


@router.post("/print-templates/{public_id}/preview")
def preview(public_id: str, body: TemplatePreview, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    pdf, meta = app.print_templates.preview(current, public_id, body.model_dump())
    return _pdf(pdf, "vista-previa.pdf", meta)


@router.get("/documents/{doc_id}/template-pdf")
def document_pdf(doc_id: int, template: str | None = None, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    result = app.print_templates.render_document(current, doc_id, template)
    return _pdf(result["path"].read_bytes(), result["path"].name, result)


@router.get("/sales/{sale_id}/template-pdf")
def sale_pdf(sale_id: int, template: str | None = None, kind: Literal["venta", "recibo"] = "venta",
             current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    result = app.print_templates.render_sale(current, sale_id, template, kind)
    return _pdf(result["path"].read_bytes(), result["path"].name, result)


@router.get("/print-outputs")
def outputs(target_type: Literal["documento", "venta"], target_id: int, current: Actor = Depends(actor),
            app: AppContext = Depends(ctx)):
    return app.print_templates.outputs(current, target_type, target_id)


@router.get("/print-outputs/{output_id}")
def output_file(output_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    path = app.print_templates.output_file(current, output_id)
    return FileResponse(path, media_type=PDF, filename=path.name)

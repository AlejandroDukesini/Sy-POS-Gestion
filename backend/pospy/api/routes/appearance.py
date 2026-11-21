"""Personalización visual: paleta de la aplicación y pantalla de ingreso (fondo y logotipo)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse

from ...context import AppContext
from ...core.actor import Actor
from ...core.errors import ValidationError
from ..deps import actor, ctx

router = APIRouter(tags=["apariencia"])
KINDS = {"fondo": "background", "logotipo": "logo"}


@router.get("/appearance")
def appearance(app: AppContext = Depends(ctx)):
    """Público: la pantalla de ingreso necesita los colores y la composición antes de iniciar sesión."""
    return app.appearance.public()


@router.put("/appearance/theme")
def save_theme(body: dict[str, Any], current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.appearance.save_theme(current, body)


@router.put("/appearance/login")
def save_login(body: dict[str, Any], current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.appearance.save_login(current, body)


@router.post("/appearance/login/{kind}")
async def upload(kind: str, file: UploadFile = File(...), current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    current.require("gestion.configuracion")
    if kind not in KINDS:
        raise ValidationError("Recurso no válido.")
    data = await file.read(8 * 1024 * 1024 + 1)
    return app.appearance.upload(current, KINDS[kind], data)


@router.delete("/appearance/login/{kind}")
def delete(kind: str, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    if kind not in KINDS:
        raise ValidationError("Recurso no válido.")
    return app.appearance.delete(current, KINDS[kind])


@router.get("/appearance/login/{kind}", include_in_schema=False)
def image(kind: str, app: AppContext = Depends(ctx)):
    """Público (pantalla de ingreso). Solo los dos archivos fijos; el navegador no adivina el tipo (nosniff)."""
    if kind not in KINDS:
        raise ValidationError("Recurso no válido.")
    path, mime = app.appearance.image(KINDS[kind])
    return FileResponse(path, media_type=mime, headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"})

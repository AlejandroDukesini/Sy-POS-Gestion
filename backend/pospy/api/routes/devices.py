"""Equipos autorizados (restricción de acceso por dispositivo)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ...context import AppContext
from ...core.actor import Actor
from ...core.errors import ValidationError
from ..deps import actor, client_key, ctx, is_local, session_token
from ..models import DeviceDecision, DeviceEnforcement, DeviceRename, DeviceRequest

router = APIRouter(tags=["equipos"])


@router.get("/devices/policy")
def policy(request: Request, app: AppContext = Depends(ctx)):
    """Público: la pantalla de ingreso necesita saber si debe identificar el equipo (sin datos de los equipos)."""
    return {"enforced": app.devices.enforced(), "local": is_local(request)}


@router.post("/devices/challenge")
def challenge(request: Request, app: AppContext = Depends(ctx)):
    """Desafío de un solo uso (2 minutos) que el equipo firma con su clave privada."""
    app.auth.limiter.check(f"login:{client_key(request)}")
    return app.devices.challenge()


@router.post("/devices/request")
def request_device(body: DeviceRequest, request: Request, app: AppContext = Depends(ctx)):
    """Sin sesión: solicita autorizar ESTE equipo con usuario y contraseña. Queda pendiente de un administrador."""
    if not body.username or not body.password:
        raise ValidationError("Escriba su usuario y contraseña para solicitar la autorización.")
    return app.auth.request_device(body.username, body.password, body.device.model_dump(), body.name,
                                   request.headers.get("user-agent", ""), client_key(request))


@router.post("/devices/register")
def register(body: DeviceRequest, request: Request, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    """Con sesión: registra ESTE equipo (un administrador lo autoriza de inmediato; un empleado queda pendiente)."""
    return app.auth.register_device(current, session_token(request), body.device.model_dump(), body.name,
                                    request.headers.get("user-agent", ""))


@router.get("/devices/current")
def current_device(request: Request, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return {**app.auth.device_status(session_token(request)), "local": is_local(request)}


@router.get("/devices")
def list_devices(current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.devices.list(current)


@router.put("/devices/policy")
def set_policy(body: DeviceEnforcement, request: Request, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    status = app.auth.device_status(session_token(request))
    device_id = None
    if status["device"] and status["device"]["status"] == "autorizado":
        with app.db.read() as conn:
            row = conn.execute("SELECT id FROM devices WHERE public_id = ?", (status["device"]["public_id"],)).fetchone()
            device_id = row[0] if row else None
    return app.devices.set_enforced(current, body.enforced, device_id, is_local(request))


@router.put("/devices/{device_id}/status")
def decide(device_id: int, body: DeviceDecision, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.devices.decide(current, device_id, body.status, body.note)


@router.put("/devices/{device_id}/name")
def rename(device_id: int, body: DeviceRename, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.devices.rename(current, device_id, body.name)

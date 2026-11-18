"""Grupos de trabajo, invitaciones por enlace y canal de tiempo real (SSE)."""
from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from ...context import AppContext
from ...core.actor import Actor
from ...core.errors import AuthError, DomainError
from ..deps import actor, client_key, ctx, session_token
from ..models import GroupIn, GroupUpdate, InvitationIn

router = APIRouter(tags=["grupos de trabajo"])
log = logging.getLogger("pospy.realtime")

HEARTBEAT_S = 15.0        # mantiene viva la conexión a través de proxies y túneles (cierran conexiones mudas)
SESSION_CHECK_S = 30.0    # si la sesión se cierra o vence, el canal se corta en menos de este tiempo


def _request_base(request: Request) -> str:
    return str(request.base_url).rstrip("/")


# ------------------------------------------------------------------ grupos
@router.get("/groups")
def list_groups(current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.groups.list(current)


@router.post("/groups")
def create_group(body: GroupIn, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.groups.create(current, body.data())


@router.get("/groups/{public_id}")
def get_group(public_id: str, request: Request, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    data = app.groups.get(current, public_id)
    if data["view"] == "admin":
        data["invite_base"] = app.groups.invite_base_info(_request_base(request))
    return data


@router.put("/groups/{public_id}")
def update_group(public_id: str, body: GroupUpdate, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.groups.update(current, public_id, body.data())


@router.post("/groups/{public_id}/close")
def close_group(public_id: str, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.groups.set_open(current, public_id, False)


@router.post("/groups/{public_id}/reopen")
def reopen_group(public_id: str, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.groups.set_open(current, public_id, True)


@router.post("/groups/{public_id}/invitations")
def create_invitation(public_id: str, body: InvitationIn, request: Request, current: Actor = Depends(actor),
                      app: AppContext = Depends(ctx)):
    return app.groups.create_invitation(current, public_id, body.data(), _request_base(request))


@router.post("/groups/{public_id}/invitations/{invitation_id}/revoke")
def revoke_invitation(public_id: str, invitation_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.groups.revoke_invitation(current, public_id, invitation_id)


@router.post("/groups/{public_id}/members/{user_id}/{action}")
def member_action(public_id: str, user_id: int, action: str, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.groups.member_action(current, public_id, user_id, action)


@router.post("/groups/{public_id}/leave")
def leave_group(public_id: str, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.groups.leave(current, public_id)


# ------------------------------------------------------------------ enlace de invitación
# El token viaja en la ruta (es lo que contiene el enlace). Nunca se registra: el servidor no guarda
# registros de acceso y la auditoría solo anota el id interno de la invitación.
@router.get("/invitations/{token}")
def preview_invitation(token: str, request: Request, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.groups.preview(current, token, client_key(request))


@router.post("/invitations/{token}/accept")
def accept_invitation(token: str, request: Request, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.groups.accept(current, token, client_key(request))


# ------------------------------------------------------------------ tiempo real
def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/realtime/stream")
async def realtime_stream(request: Request, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    """Canal de eventos del servidor (text/event-stream). Requiere sesión; el navegador reconecta solo."""
    token = session_token(request)
    loop = asyncio.get_running_loop()
    sub, first = app.realtime.subscribe(current.id, loop)
    if first:
        await run_in_threadpool(app.groups.presence_changed, current.id, True)

    async def events():
        last_check = time.monotonic()
        try:
            yield "retry: 3000\n" + _sse("hola", {"user": current.id, "connection": "conectado"})
            while True:
                try:
                    event = await asyncio.wait_for(sub.queue.get(), timeout=HEARTBEAT_S)
                    yield _sse(event.get("type", "evento"), event)
                except TimeoutError:
                    yield ": latido\n\n"
                if app.realtime.is_stale(sub):
                    return   # conexión medio abierta tras un proxy: el cliente ya no está
                if sub.overflow:
                    sub.overflow = False
                    yield _sse("resync", {})
                if time.monotonic() - last_check >= SESSION_CHECK_S:
                    last_check = time.monotonic()
                    try:
                        await run_in_threadpool(app.auth.resolve, token, False)
                    except (AuthError, DomainError):
                        yield _sse("sesion", {"reason": "terminada"})
                        return
        finally:
            if app.realtime.unsubscribe(sub):
                # Sin esperar: el generador puede estar cancelándose porque el cliente se fue.
                loop.run_in_executor(None, _safe_presence, app, current.id)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


@router.post("/realtime/ping")
def realtime_ping(current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    """Latido del navegador: permite detectar canales que un proxy mantiene abiertos sin cliente."""
    app.realtime.ping(current.id)
    return {"connection": app.realtime.status(current.id)}


def _safe_presence(app: AppContext, user_id: int) -> None:
    try:
        app.groups.presence_changed(user_id, False)
    except Exception:  # noqa: BLE001 - la presencia nunca debe tumbar el servidor
        log.exception("No se pudo registrar la desconexión de %s", user_id)

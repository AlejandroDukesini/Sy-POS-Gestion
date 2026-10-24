"""Dependencias HTTP: sesión, identidad, CSRF e idempotencia."""
from __future__ import annotations

from fastapi import Depends, Header, Request

from ..context import AppContext
from ..core.actor import Actor
from ..core.errors import PermissionDenied, ValidationError

COOKIE = "pospy_session"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "pos-py"


def ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def session_token(request: Request) -> str | None:
    return request.cookies.get(COOKIE)


def actor_any(request: Request, app: AppContext = Depends(ctx)) -> Actor:
    """Actor autenticado, aunque deba cambiar su contraseña (solo para /auth y /me)."""
    actor, must_change = app.auth.resolve(session_token(request))
    request.state.must_change = must_change
    return actor


def actor(request: Request, current: Actor = Depends(actor_any)) -> Actor:
    if request.state.must_change:
        raise PermissionDenied("Debe cambiar su contraseña temporal antes de continuar.", {"password": "cambio_obligatorio"})
    return current


def idempotency_key(idempotency_key: str | None = Header(default=None)) -> str:
    if not idempotency_key or not 8 <= len(idempotency_key) <= 80:
        raise ValidationError("Falta la cabecera Idempotency-Key de la operación.")
    return idempotency_key


def optional_idempotency_key(idempotency_key: str | None = Header(default=None)) -> str | None:
    return idempotency_key if idempotency_key and 8 <= len(idempotency_key) <= 80 else None


"""Dependencias HTTP: sesión, identidad, CSRF e idempotencia."""
from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

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


# Cabeceras que añade un proxy inverso o un túnel (Caddy, nginx, cloudflared…). Si aparecen, la
# petición llegó desde otra máquina aunque la conexión TCP venga del propio equipo.
FORWARD_HEADERS = ("forwarded", "x-forwarded-for", "x-real-ip", "cf-connecting-ip", "true-client-ip", "x-forwarded-host")


def _loopback(request: Request) -> bool:
    host = request.client.host if request.client else ""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host in ("localhost", "testclient")


LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "::1"}


def _host_name(request: Request) -> str:
    """Nombre del encabezado Host, sin puerto ni corchetes IPv6."""
    host = request.headers.get("host", "").strip().lower()
    if host.startswith("["):
        return host[1:].split("]", 1)[0]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def is_local(request: Request) -> bool:
    """True solo si la petición se hizo en este mismo equipo, sin pasar por un proxy ni un túnel.

    Detrás de un túnel o proxy local TODAS las conexiones parecen venir de 127.0.0.1; sin esta
    comprobación, cualquiera en Internet obtendría el acceso directo o el asistente de instalación.
    Dos señales, ambas obligatorias:
    - Sin cabeceras de reenvío: un atacante remoto no puede quitar las que agrega el proxy, y
      agregarlas solo le resta acceso.
    - Host de bucle local: hay túneles (ssh -R, localhost.run) que no agregan ninguna cabecera, pero
      enrutan por nombre de dominio, así que desde Internet el Host es siempre el dominio público.
    """
    if not _loopback(request) or any(h in request.headers for h in FORWARD_HEADERS):
        return False
    if request.client and request.client.host == "testclient":   # TestClient de Starlette (sin socket real)
        return True
    return _host_name(request) in LOCAL_HOSTNAMES


def client_key(request: Request) -> str:
    """Dirección del cliente para límites de intentos (la real, si la entrega un proxy del propio equipo)."""
    if _loopback(request):
        forwarded = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "").split(",")[0]
        if forwarded.strip():
            return forwarded.strip()[:64]
    return request.client.host if request.client else ""


def is_https(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    if not _loopback(request):
        return False
    if request.headers.get("x-forwarded-proto", "").lower() == "https":
        return True
    # Túnel HTTPS sin cabeceras de reenvío: la petición llegó con el Host de la dirección pública https.
    public = urlsplit(ctx(request).groups.configured_base())
    return public.scheme == "https" and bool(public.hostname) and _host_name(request) == public.hostname


def actor_any(request: Request, app: AppContext = Depends(ctx)) -> Actor:
    """Actor autenticado, aunque deba cambiar su contraseña (solo para /auth y /me)."""
    actor, must_change = app.auth.resolve(session_token(request))
    request.state.must_change = must_change
    return actor


def actor(request: Request, current: Actor = Depends(actor_any), app: AppContext = Depends(ctx)) -> Actor:
    """Actor de la petición con los permisos de inventario del inventario elegido (cabecera X-Inventory) o del
    predeterminado. Así cada operación usa los permisos que la persona tiene en ESE inventario."""
    if request.state.must_change:
        raise PermissionDenied("Debe cambiar su contraseña temporal antes de continuar.", {"password": "cambio_obligatorio"})
    key = (request.headers.get("x-inventory") or "").strip()[:20] or None
    with app.db.read() as conn:
        return app.scopes.scope_actor(conn, current, key)


def inventory_key(x_inventory: str | None = Header(default=None)) -> str | None:
    """Inventario elegido en la interfaz (id público «I-…»). El servicio valida el acceso."""
    return (x_inventory or "").strip()[:20] or None


def idempotency_key(idempotency_key: str | None = Header(default=None)) -> str:
    if not idempotency_key or not 8 <= len(idempotency_key) <= 80:
        raise ValidationError("Falta la cabecera Idempotency-Key de la operación.")
    return idempotency_key


def optional_idempotency_key(idempotency_key: str | None = Header(default=None)) -> str | None:
    return idempotency_key if idempotency_key and 8 <= len(idempotency_key) <= 80 else None


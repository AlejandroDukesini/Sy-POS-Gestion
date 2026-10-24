"""Instalación, sesión, identidad, permisos visibles y preferencias personales."""
from __future__ import annotations

import ipaddress

from fastapi import APIRouter, Depends, Request, Response

from ...context import AppContext
from ...core import permissions as perms
from ...core.actor import Actor
from ...core.errors import PermissionDenied
from ...core.settings import PUBLIC_READ
from ..deps import COOKIE, actor, actor_any, ctx, session_token
from ..models import ChangePassword, Login, Setup
from ..serialize import out

router = APIRouter(tags=["sesión"])


def _is_local(request: Request) -> bool:
    host = request.client.host if request.client else ""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host in ("localhost", "testclient")


@router.get("/setup/status")
def setup_status(request: Request, app: AppContext = Depends(ctx)):
    needs = app.auth.needs_setup()
    return {"needs_setup": needs, "local": _is_local(request),
            "code_file": str(app.auth.setup_file) if needs and _is_local(request) and not app.config.setup_code else None,
            "code_injected": bool(app.config.setup_code) and needs}


@router.post("/setup")
def setup(body: Setup, request: Request, app: AppContext = Depends(ctx)):
    if not _is_local(request):
        raise PermissionDenied("La instalación inicial solo se puede hacer desde el propio equipo del servidor.")
    app.auth.setup_admin(body.code, body.username, body.full_name, body.password)
    return {"ok": True}


@router.post("/auth/login")
def login(body: Login, request: Request, response: Response, app: AppContext = Depends(ctx)):
    result = app.auth.login(body.username, body.password, request.headers.get("user-agent", ""))
    max_age = app.settings.get("seguridad")["session_max_hours"] * 3600
    response.set_cookie(COOKIE, result.token, httponly=True, samesite="strict", secure=app.config.secure_cookies,
                        max_age=max_age, path="/")
    return {"user": _me(app, result.actor), "must_change_password": result.must_change_password}


@router.post("/auth/logout")
def logout(request: Request, response: Response, app: AppContext = Depends(ctx)):
    app.auth.logout(session_token(request))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.post("/auth/password")
def change_password(body: ChangePassword, request: Request, current: Actor = Depends(actor_any),
                    app: AppContext = Depends(ctx)):
    app.auth.change_password(current, body.current, body.password, session_token(request))
    return {"ok": True}


def _me(app: AppContext, a: Actor) -> dict:
    return {"id": a.id, "username": a.username, "full_name": a.full_name, "role": a.role,
            "permissions": sorted(a.permissions)}


@router.get("/me")
def me(request: Request, current: Actor = Depends(actor_any), app: AppContext = Depends(ctx)):
    company = app.settings.get("empresa")
    return {"user": _me(app, current), "must_change_password": request.state.must_change,
            "company": {"name": company["name"], "primary_color": company["primary_color"],
                        "currency_symbol": company["currency_symbol"], "timezone": company["timezone"]},
            "desktop": app.config.desktop}


@router.get("/permissions/catalog")
def permission_catalog(current: Actor = Depends(actor)):
    return [{"code": p.code, "label": p.label, "group": p.group, "admin_only": p.admin_only} for p in perms.CATALOG]


@router.get("/prefs")
def get_prefs(current: Actor = Depends(actor_any), app: AppContext = Depends(ctx)):
    return app.prefs.get(current)


@router.put("/prefs")
def save_prefs(body: dict, current: Actor = Depends(actor_any), app: AppContext = Depends(ctx)):
    return app.prefs.save(current, body)


@router.get("/settings/public")
def public_settings(current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    """Configuración que la interfaz necesita para operar (sin datos sensibles)."""
    return out({section: app.settings.get(section) for section in PUBLIC_READ})

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
from ..models import ChangePassword, Login, OpenSession, Setup, SetupStart, SetupStep
from ..serialize import out

router = APIRouter(tags=["sesión"])


def _is_local(request: Request) -> bool:
    host = request.client.host if request.client else ""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host in ("localhost", "testclient")


def _set_session(app: AppContext, response: Response, token: str) -> None:
    max_age = app.settings.get("seguridad")["session_max_hours"] * 3600
    response.set_cookie(COOKIE, token, httponly=True, samesite="strict", secure=app.config.secure_cookies,
                        max_age=max_age, path="/")


def _require_local(request: Request, what: str) -> None:
    if not _is_local(request):
        raise PermissionDenied(f"{what} solo se permite desde el propio equipo donde está instalado POS-PY.")


@router.get("/setup/status")
def setup_status(request: Request, app: AppContext = Depends(ctx)):
    """Público: indica a la interfaz qué pantalla mostrar (asistente, acceso directo o inicio de sesión)."""
    state = app.access.state()
    needs = not state["setup_completed"]
    local = _is_local(request)
    return {"needs_setup": needs, "setup_step": state["setup_step"], "login_enabled": state["login_enabled"],
            "direct_access": local and state["setup_completed"] and not state["login_enabled"],
            "local": local,
            "code_file": str(app.auth.setup_file) if needs and local and not app.config.setup_code else None,
            "code_injected": bool(app.config.setup_code) and needs}


@router.post("/setup")
def setup(body: Setup, request: Request, app: AppContext = Depends(ctx)):
    """Instalación clásica: crea el administrador con contraseña e inicio de sesión activo."""
    _require_local(request, "La instalación inicial")
    app.auth.setup_admin(body.code, body.username, body.full_name, body.password)
    return {"ok": True}


@router.post("/setup/start")
def setup_start(body: SetupStart, request: Request, response: Response, app: AppContext = Depends(ctx)):
    """Abre o retoma el asistente de configuración inicial sin exigir cuenta (local + código de instalación)."""
    _require_local(request, "La configuración inicial")
    result = app.auth.start_setup(body.code, request.headers.get("user-agent", ""))
    _set_session(app, response, result.token)
    return {"user": _me(app, result.actor), "access": app.access.state()}


@router.put("/setup/step")
def setup_step(body: SetupStep, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.access.set_step(current, body.step)


@router.post("/setup/complete")
def setup_complete(current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    state = app.access.complete_setup(current)
    app.auth.discard_setup_code()
    return state


@router.get("/auth/profiles")
def profiles(request: Request, app: AppContext = Depends(ctx)):
    """Acceso directo (inicio de sesión desactivado): perfiles activos para elegir, solo desde el propio equipo."""
    _require_local(request, "El acceso directo")
    return app.auth.profiles()


@router.post("/auth/open")
def open_session(body: OpenSession, request: Request, response: Response, app: AppContext = Depends(ctx)):
    _require_local(request, "El acceso directo")
    result = app.auth.open_session(body.user_id, request.headers.get("user-agent", ""))
    _set_session(app, response, result.token)
    return {"user": _me(app, result.actor), "must_change_password": False}


@router.post("/auth/login")
def login(body: Login, request: Request, response: Response, app: AppContext = Depends(ctx)):
    result = app.auth.login(body.username, body.password, request.headers.get("user-agent", ""))
    _set_session(app, response, result.token)
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
    return {"user": {**_me(app, current), "has_password": app.auth.has_password(current.id)},
            "must_change_password": request.state.must_change,
            "company": {"name": company["name"], "primary_color": company["primary_color"],
                        "currency_symbol": company["currency_symbol"], "timezone": company["timezone"]},
            "desktop": app.config.desktop, "access": app.access.state(),
            "direct_session": app.auth.is_direct(session_token(request))}


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

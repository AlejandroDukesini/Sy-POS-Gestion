"""Gestión: usuarios, configuración, logotipo, métodos de pago, actividad, reportes, integraciones y respaldos."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response

from ...context import AppContext
from ...core.actor import Actor
from ...core.audit import record
from ...core.errors import DomainError, NotFoundError, ValidationError
from ...core.settings import Settings
from ..deps import actor, ctx
from ..models import Connection, GoogleSecret, PasswordReset, PaymentMethod, Restore, UserCreate, UserUpdate
from ..serialize import out

router = APIRouter(tags=["gestión"])
LOGO_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


# ------------------------------------------------------------------ usuarios
@router.get("/users")
def users(current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.users.list(current)


@router.post("/users")
def create_user(body: UserCreate, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.users.create(current, body.data())


@router.put("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.users.update(current, user_id, body.data())


@router.post("/users/{user_id}/password")
def reset_password(user_id: int, body: PasswordReset, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    app.users.reset_password(current, user_id, body.password)
    return {"ok": True}


@router.post("/users/{user_id}/unlock")
def unlock(user_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    app.users.unlock(current, user_id)
    return {"ok": True}


# ------------------------------------------------------------------ configuración
@router.get("/settings")
def settings(current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    current.require("gestion.configuracion")
    return {"schema": Settings.describe(), "values": {s: app.settings.get(s) for s in Settings.describe()}}


@router.put("/settings/{section}")
def update_settings(section: str, body: dict, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.settings.update(section, body, current)


@router.get("/company/logo", include_in_schema=False)
def logo(app: AppContext = Depends(ctx)):
    """Público: la pantalla de ingreso lo muestra antes de iniciar sesión."""
    for suffix in LOGO_TYPES.values():
        path = app.config.data_dir / f"logo{suffix}"
        if path.exists():
            return FileResponse(path, headers={"Cache-Control": "no-cache"})
    raise NotFoundError("Sin logotipo.")


@router.get("/company/public", include_in_schema=False)
def company_public(app: AppContext = Depends(ctx)):
    company = app.settings.get("empresa")
    has_logo = any((app.config.data_dir / f"logo{s}").exists() for s in LOGO_TYPES.values())
    return {"name": company["name"], "primary_color": company["primary_color"], "has_logo": has_logo}


@router.post("/company/logo")
async def upload_logo(file: UploadFile = File(...), current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    current.require("gestion.configuracion")
    suffix = LOGO_TYPES.get(file.content_type or "")
    if not suffix:
        raise ValidationError("Formato no admitido.", {"file": "Use PNG, JPG o WEBP."})
    data = await file.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise ValidationError("Imagen demasiado grande.", {"file": "Máximo 2 MB."})
    signatures = {".png": b"\x89PNG", ".jpg": b"\xff\xd8", ".webp": b"RIFF"}
    if not data.startswith(signatures[suffix]):
        raise ValidationError("El archivo no es una imagen válida.", {"file": "Imagen dañada o con otra extensión."})
    for s in LOGO_TYPES.values():
        (app.config.data_dir / f"logo{s}").unlink(missing_ok=True)
    (app.config.data_dir / f"logo{suffix}").write_bytes(data)
    with app.db.tx() as conn:
        record(conn, current, "configuracion.logotipo", "settings", "empresa", {"bytes": len(data)})
    return {"ok": True}


@router.delete("/company/logo")
def delete_logo(current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    current.require("gestion.configuracion")
    for s in LOGO_TYPES.values():
        (app.config.data_dir / f"logo{s}").unlink(missing_ok=True)
    with app.db.tx() as conn:
        record(conn, current, "configuracion.logotipo_eliminado", "settings", "empresa")
    return {"ok": True}


@router.post("/payment-methods")
def create_method(body: PaymentMethod, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.catalog.save_payment_method(current, body.model_dump())


@router.put("/payment-methods/{method_id}")
def update_method(method_id: int, body: PaymentMethod, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.catalog.save_payment_method(current, body.model_dump(), method_id)


# ------------------------------------------------------------------ actividad y reportes
@router.get("/activity")
def activity(q: str = "", user_id: int | None = None, entity: str = "", date_from: str = "", date_to: str = "",
             page: int = 1, page_size: int = 50, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.catalog.activity(current, q, user_id, entity, date_from, date_to, page, page_size)


@router.get("/reports/sales")
def sales_report(date_from: str | None = None, date_to: str | None = None, current: Actor = Depends(actor),
                 app: AppContext = Depends(ctx)):
    return out(app.reports.sales(current, date_from, date_to))


@router.get("/reports/movements")
def movements_report(date_from: str | None = None, date_to: str | None = None, current: Actor = Depends(actor),
                     app: AppContext = Depends(ctx)):
    return out(app.reports.movements(current, date_from, date_to))


# ------------------------------------------------------------------ integraciones
@router.get("/integrations")
def connections(current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.sync.connections(current)


@router.get("/integrations/credentials")
def credentials(current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.sync.oauth_credentials_status(current)


@router.put("/integrations/credentials/google-secret")
def google_secret(body: GoogleSecret, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    app.sync.set_google_secret(current, body.client_secret)
    return {"ok": True}


@router.get("/integrations/oauth/callback", include_in_schema=False)
def oauth_callback(state: str = "", code: str | None = None, error: str | None = None, app: AppContext = Depends(ctx)):
    try:
        connection_id = app.sync.oauth_callback(state, code, error)
        message, ok = "Autorización completada. Ya puede cerrar esta pestaña y volver a POS-PY.", True
    except DomainError as exc:
        connection_id, message, ok = None, exc.detail, False
    target = f"/gestion/integraciones?conexion={connection_id}" if connection_id else "/gestion/integraciones"
    color = "#166534" if ok else "#991b1b"
    return HTMLResponse(f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><title>POS-PY</title>
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:Arial,sans-serif;font-size:18px;padding:32px;max-width:640px;margin:auto">
<h1 style="color:{color};font-size:24px">{'Conexión autorizada' if ok else 'No se completó la autorización'}</h1>
<p>{message}</p><p><a href="{target}">Volver a Integraciones</a></p></body></html>""",
                        status_code=200 if ok else 400)


@router.get("/integrations/{connection_id}")
def connection(connection_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.sync.get(current, connection_id)


@router.post("/integrations")
def create_connection(body: Connection, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.sync.save(current, body.model_dump())


@router.put("/integrations/{connection_id}")
def update_connection(connection_id: int, body: Connection, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.sync.save(current, body.model_dump(), connection_id)


@router.post("/integrations/{connection_id}/deactivate")
def deactivate(connection_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.sync.deactivate(current, connection_id)


@router.post("/integrations/{connection_id}/test")
def test_connection(connection_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.sync.test(current, connection_id)


@router.post("/integrations/{connection_id}/authorize")
def authorize(connection_id: int, request: Request, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.sync.oauth_start(current, connection_id, str(request.base_url))


@router.post("/integrations/{connection_id}/preview")
def preview_connection(connection_id: int, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.sync.preview_connection(current, connection_id)


# ------------------------------------------------------------------ respaldos
@router.get("/backups")
def backups(current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.backups.list(current)


@router.post("/backups")
def create_backup(current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.backups.create(current)


@router.post("/backups/upload")
async def upload_backup(file: UploadFile = File(...), current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    current.require("gestion.respaldos")
    return {"file": app.backups.store_upload(current, await file.read())}


@router.get("/backups/{name}/verify")
def verify_backup(name: str, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    return app.backups.verify(current, name)


@router.get("/backups/{name}/download")
def download_backup(name: str, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    path = app.backups.file(current, name)
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@router.post("/backups/restore")
def restore(body: Restore, response: Response, current: Actor = Depends(actor), app: AppContext = Depends(ctx)):
    result = app.backups.restore(current, body.file)
    response.delete_cookie("pospy_session", path="/")
    return result

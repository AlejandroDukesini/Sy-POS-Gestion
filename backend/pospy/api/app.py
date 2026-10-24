"""Aplicación FastAPI: API en /api y la interfaz React compilada en el mismo origen."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from .. import __version__
from ..context import AppContext
from ..core.errors import DomainError
from .deps import CSRF_HEADER, CSRF_VALUE
from .routes import admin, auth, documents, finance, inventory, sales

log = logging.getLogger("pospy.api")
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


def create_app(ctx: AppContext, run_scheduler: bool = False) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if run_scheduler:
            ctx.start_scheduler()
        yield
        ctx.stop()

    app = FastAPI(title="POS-PY API", version=__version__, docs_url="/api/docs", redoc_url=None,
                  openapi_url="/api/openapi.json", lifespan=lifespan,
                  description="API del punto de venta POS-PY. Los importes viajan como texto decimal. Las operaciones que "
                              "modifican datos exigen la cabecera `X-Requested-With: pos-py`; ventas, pagos y movimientos "
                              "exigen `Idempotency-Key`.")
    app.state.ctx = ctx
    if ctx.config.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(ctx.config.cors_origins), allow_credentials=True,
                           allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and request.method in UNSAFE and path != "/api/integrations/oauth/callback":
            if request.headers.get(CSRF_HEADER, "").lower() != CSRF_VALUE:
                return JSONResponse({"error": "Solicitud rechazada", "detail": "Falta la cabecera de protección CSRF.",
                                     "fields": {}}, status_code=403)
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if not path.startswith("/api/docs"):
            response.headers.setdefault("Content-Security-Policy", CSP)
        if path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(DomainError)
    async def domain_error(_request: Request, exc: DomainError):
        return JSONResponse({"error": exc.title, "detail": exc.detail, "fields": exc.fields}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        fields = {}
        for err in exc.errors():
            loc = [str(p) for p in err.get("loc", []) if p not in ("body", "query", "path")]
            fields[".".join(loc) or "body"] = _spanish(err)
        return JSONResponse({"error": "Revise los datos", "detail": "Algunos datos no tienen el formato esperado.",
                             "fields": fields}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected(_request: Request, exc: Exception):
        log.exception("Error no controlado", exc_info=exc)
        return JSONResponse({"error": "Error interno", "detail": "Ocurrió un error inesperado. Quedó registrado en el "
                             "registro del servidor.", "fields": {}}, status_code=500)

    @app.get("/api/health", tags=["sistema"])
    def health():
        return {"status": "ok", "version": __version__, "schema": ctx.db.schema_version(), "desktop": ctx.config.desktop}

    for module in (auth, inventory, sales, documents, finance, admin):
        app.include_router(module.router, prefix="/api")

    _mount_frontend(app, ctx.config.web_dist)
    return app


def _spanish(err: dict) -> str:
    kind = err.get("type", "")
    if kind == "missing":
        return "Dato obligatorio."
    if kind == "extra_forbidden":
        return "Campo no permitido."
    if kind.startswith(("int", "float")):
        return "Debe ser un número."
    if kind.startswith("string_too_long"):
        return "Texto demasiado largo."
    if kind == "literal_error":
        return "Opción no válida."
    return "Valor no válido."


def _mount_frontend(app: FastAPI, dist: Path | None) -> None:
    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"error": "No encontrado", "detail": "Ruta de API inexistente.", "fields": {}}, status_code=404)
        if not dist or not (dist / "index.html").exists():
            return JSONResponse({"error": "Interfaz no compilada", "detail": "Ejecute «npm run build» en frontend/.",
                                 "fields": {}}, status_code=503)
        target = (dist / path).resolve()
        if path and target.is_file() and dist.resolve() in target.parents:
            headers = {"Cache-Control": "no-cache"} if target.name in ("sw.js", "manifest.webmanifest", "registerSW.js") \
                else ({"Cache-Control": "public, max-age=31536000, immutable"} if "/assets/" in target.as_posix() else {})
            return FileResponse(target, headers=headers)
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})

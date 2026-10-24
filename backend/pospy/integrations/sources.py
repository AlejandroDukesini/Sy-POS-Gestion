"""Adaptadores de fuentes de inventario. Cada uno sabe obtener el archivo; el resto del proceso
(lectura, mapeo, vista previa, conciliación y aplicación) es común y no depende del proveedor.

  excel     archivo .xlsx/.xlsm/.csv en el equipo del servidor
  carpeta   carpeta local o de red (UNC \\\\servidor\\recurso): toma el archivo más reciente que coincida
  onedrive  Microsoft Graph (OAuth 2.0 con PKCE, permiso Files.Read + offline_access)
  gdrive    Google Drive API v3 (OAuth 2.0 con PKCE, permiso drive.readonly)

Para añadir un proveedor: implemente Adapter.fetch() y regístrelo en ADAPTERS.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import httpx

from ..core.errors import ExternalServiceError, ValidationError

ALLOWED_SUFFIXES = (".xlsx", ".xlsm", ".csv")
MAX_BYTES = 50 * 1024 * 1024
TIMEOUT = httpx.Timeout(30.0, connect=10.0)


@dataclass
class SourceFile:
    name: str
    content: bytes
    modified: str = ""

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


class Adapter:
    provider = ""
    needs_oauth = False

    def __init__(self, connection: dict, secrets, settings, db=None):
        self.db = db
        self.connection = connection
        self.config = connection["config"]
        self.secrets = secrets
        self.settings = settings

    def validate_config(self) -> None:
        raise NotImplementedError

    def fetch(self) -> SourceFile:
        raise NotImplementedError

    def describe(self) -> str:
        return ""


def _check_file(path: Path) -> None:
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValidationError("Formato no soportado. Use .xlsx, .xlsm o .csv.", {"path": "Extensión no admitida."})
    if not path.exists():
        raise ValidationError(f"No se encuentra el archivo {path}. Verifique la ruta y que el servidor tenga acceso.",
                              {"path": "Archivo no encontrado."})
    if path.stat().st_size > MAX_BYTES:
        raise ValidationError("El archivo supera 50 MB.")


class ExcelAdapter(Adapter):
    provider = "excel"

    def validate_config(self) -> None:
        if not str(self.config.get("path") or "").strip():
            raise ValidationError("Indique la ruta del archivo.", {"path": "Ruta obligatoria."})

    def fetch(self) -> SourceFile:
        path = Path(str(self.config["path"]).strip().strip('"'))
        _check_file(path)
        try:
            data = path.read_bytes()
        except PermissionError:
            raise ValidationError(f"{path.name} está abierto en otro programa o sin permisos de lectura.") from None
        return SourceFile(path.name, data, time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(path.stat().st_mtime)))

    def describe(self) -> str:
        return str(self.config.get("path") or "")


class FolderAdapter(Adapter):
    provider = "carpeta"

    def validate_config(self) -> None:
        if not str(self.config.get("folder") or "").strip():
            raise ValidationError("Indique la carpeta.", {"folder": "Carpeta obligatoria."})

    def fetch(self) -> SourceFile:
        folder = Path(str(self.config["folder"]).strip().strip('"'))
        pattern = (self.config.get("pattern") or "*.xlsx").strip()
        if not folder.is_dir():
            raise ValidationError(f"No se puede acceder a la carpeta {folder}. Si es una carpeta de red, verifique la "
                                  "conexión y que la cuenta que ejecuta POS-PY tenga permiso.", {"folder": "Sin acceso."})
        candidates = [p for p in folder.iterdir() if p.is_file() and fnmatch.fnmatch(p.name.lower(), pattern.lower())
                      and p.suffix.lower() in ALLOWED_SUFFIXES and not p.name.startswith("~$")]
        if not candidates:
            raise ValidationError(f"No hay archivos que coincidan con «{pattern}» en {folder}.")
        latest = max(candidates, key=lambda p: p.stat().st_mtime)
        _check_file(latest)
        return ExcelAdapter({"config": {"path": str(latest)}}, None, None).fetch()

    def describe(self) -> str:
        return f"{self.config.get('folder', '')} ({self.config.get('pattern') or '*.xlsx'})"


# --------------------------------------------------------------------------- OAuth
class OAuthAdapter(Adapter):
    needs_oauth = True
    scopes: str = ""

    @property
    def secret_name(self) -> str:
        return f"integration.{self.connection['id']}.oauth"

    def client(self) -> dict:
        raise NotImplementedError

    def authorize_endpoint(self) -> str:
        raise NotImplementedError

    def token_endpoint(self) -> str:
        raise NotImplementedError

    def extra_authorize_params(self) -> dict:
        return {}

    def tokens(self) -> dict:
        raw = self.secrets.get(self.secret_name)
        if not raw:
            raise ValidationError("La conexión no está autorizada. Pulse «Autorizar» para iniciar sesión con la cuenta.")
        return json.loads(raw)

    def exchange(self, code: str, verifier: str, redirect_uri: str) -> dict:
        data = {"grant_type": "authorization_code", "code": code, "code_verifier": verifier,
                "redirect_uri": redirect_uri, **self.client(), "scope": self.scopes}
        return self._token_request(data)

    def _token_request(self, data: dict) -> dict:
        try:
            resp = httpx.post(self.token_endpoint(), data=data, timeout=TIMEOUT)
        except httpx.HTTPError as exc:
            raise ExternalServiceError(f"No se pudo contactar el servicio de autorización: {exc}") from None
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if resp.status_code != 200 or "access_token" not in body:
            raise ExternalServiceError("El proveedor rechazó la autorización: "
                                       f"{body.get('error_description') or body.get('error') or resp.status_code}")
        body["obtained_at"] = int(time.time())
        return body

    def access_token(self) -> str:
        tok = self.tokens()
        if tok.get("obtained_at", 0) + int(tok.get("expires_in", 0)) - 120 > time.time():
            return tok["access_token"]
        if not tok.get("refresh_token"):
            raise ValidationError("La autorización expiró. Pulse «Autorizar» de nuevo.")
        fresh = self._token_request({"grant_type": "refresh_token", "refresh_token": tok["refresh_token"], **self.client(),
                                     "scope": self.scopes})
        fresh.setdefault("refresh_token", tok["refresh_token"])
        with self.db.tx() as conn:
            self.secrets.set(conn, self.secret_name, json.dumps(fresh))
        return fresh["access_token"]

    def _download(self, url: str, token: str) -> httpx.Response:
        try:
            resp = httpx.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT, follow_redirects=True)
        except httpx.HTTPError as exc:
            raise ExternalServiceError(f"Sin conexión con el proveedor: {exc}. Las operaciones locales siguen disponibles.") from None
        if resp.status_code == 401:
            raise ValidationError("La autorización ya no es válida. Pulse «Autorizar» de nuevo.")
        if resp.status_code == 404:
            raise ValidationError("El archivo no existe o la cuenta no tiene acceso a él.")
        if resp.status_code >= 400:
            raise ExternalServiceError(f"El proveedor respondió {resp.status_code}: {resp.text[:200]}")
        if len(resp.content) > MAX_BYTES:
            raise ValidationError("El archivo supera 50 MB.")
        return resp


class OneDriveAdapter(OAuthAdapter):
    provider = "onedrive"
    scopes = "offline_access Files.Read"
    redirect_host = "localhost"

    def validate_config(self) -> None:
        if not str(self.config.get("item_path") or "").strip():
            raise ValidationError("Indique la ruta del archivo en OneDrive (ej.: /Inventario/existencias.xlsx).",
                                  {"item_path": "Ruta obligatoria."})

    def client(self) -> dict:
        client_id = self.settings.get("oauth")["microsoft_client_id"]
        if not client_id:
            raise ValidationError("Falta el Id. de aplicación de Microsoft. Regístrelo en Gestión › Integraciones › "
                                  "Credenciales (ver README: registro en Microsoft Entra).")
        return {"client_id": client_id}

    def _tenant(self) -> str:
        return self.settings.get("oauth")["microsoft_tenant"] or "common"

    def authorize_endpoint(self) -> str:
        return f"https://login.microsoftonline.com/{self._tenant()}/oauth2/v2.0/authorize"

    def token_endpoint(self) -> str:
        return f"https://login.microsoftonline.com/{self._tenant()}/oauth2/v2.0/token"

    def fetch(self) -> SourceFile:
        token = self.access_token()
        path = "/" + str(self.config["item_path"]).strip().lstrip("/")
        resp = self._download(f"https://graph.microsoft.com/v1.0/me/drive/root:{quote(path)}:/content", token)
        return SourceFile(Path(path).name, resp.content, resp.headers.get("last-modified", ""))

    def describe(self) -> str:
        return f"OneDrive: {self.config.get('item_path', '')}"


class GoogleDriveAdapter(OAuthAdapter):
    provider = "gdrive"
    scopes = "https://www.googleapis.com/auth/drive.readonly"
    redirect_host = "127.0.0.1"
    SHEET = "application/vnd.google-apps.spreadsheet"
    XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def validate_config(self) -> None:
        if not str(self.config.get("file_id") or "").strip():
            raise ValidationError("Indique el Id. del archivo de Google Drive (está en su enlace: /d/<Id>/).",
                                  {"file_id": "Id. obligatorio."})

    def client(self) -> dict:
        client_id = self.settings.get("oauth")["google_client_id"]
        secret = self.secrets.get("oauth.google_client_secret")
        if not client_id or not secret:
            raise ValidationError("Faltan el Id. y el secreto del cliente OAuth de Google. Regístrelos en Gestión › "
                                  "Integraciones › Credenciales (ver README: Google Cloud Console).")
        return {"client_id": client_id, "client_secret": secret}

    def authorize_endpoint(self) -> str:
        return "https://accounts.google.com/o/oauth2/v2/auth"

    def token_endpoint(self) -> str:
        return "https://oauth2.googleapis.com/token"

    def extra_authorize_params(self) -> dict:
        return {"access_type": "offline", "prompt": "consent"}

    def fetch(self) -> SourceFile:
        token = self.access_token()
        file_id = quote(str(self.config["file_id"]).strip(), safe="")
        meta = self._download(f"https://www.googleapis.com/drive/v3/files/{file_id}?fields=name,mimeType,modifiedTime"
                              "&supportsAllDrives=true", token).json()
        if meta.get("mimeType") == self.SHEET:
            resp = self._download(f"https://www.googleapis.com/drive/v3/files/{file_id}/export?mimeType={quote(self.XLSX)}",
                                  token)
            name = f"{meta.get('name', 'inventario')}.xlsx"
        else:
            resp = self._download(f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&supportsAllDrives=true", token)
            name = meta.get("name", "inventario.xlsx")
        return SourceFile(name, resp.content, meta.get("modifiedTime", ""))

    def describe(self) -> str:
        return f"Google Drive: {self.config.get('file_id', '')}"


ADAPTERS: dict[str, type[Adapter]] = {a.provider: a for a in (ExcelAdapter, FolderAdapter, OneDriveAdapter, GoogleDriveAdapter)}
PROVIDER_LABELS = {"excel": "Archivo Excel o CSV", "carpeta": "Carpeta local o de red", "onedrive": "Microsoft OneDrive",
                   "gdrive": "Google Drive"}

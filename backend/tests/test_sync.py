"""Conexión del inventario: adaptadores, vista previa, conciliación, autoridad de existencias y OAuth."""
from __future__ import annotations

import json
import os
import time
from urllib.parse import parse_qs, urlparse

import httpx
import openpyxl
import pytest

from pospy.core.errors import ValidationError
from pospy.integrations import sources


def workbook(path, rows, header=("Código", "Descripción", "Precio", "Cantidad", "Costo")):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Inventario de la empresa"])   # título: el encabezado real está en la fila 2
    ws.append(list(header))
    for r in rows:
        ws.append(list(r))
    wb.save(path)
    return path


def test_manual_import_preview_and_apply(ctx, admin, tmp_path):
    path = workbook(tmp_path / "inv.xlsx", [("A1", "Llave 10 mm", 15000, 4, 8000), ("A2", "Destornillador", "12.500", 2, 6000),
                                            ("A3", "", 1, 1, 1), ("A1", "Duplicado", 1, 1, 1), ("A4", "Sin precio", "abc", 1, 1)])
    info = ctx.sync.inspect_upload(admin, "inv.xlsx", path.read_bytes())
    assert info["header_row"] == 2 and info["suggested_columns"]["code"] == "Código"
    run = ctx.sync.preview_upload(admin, "inv.xlsx", path.read_bytes(), {"columns": info["suggested_columns"]})
    counts = run["summary"]["counts"]
    assert counts["new"] == 1 and counts["invalid"] == 2 and counts["duplicates"] == 2
    with ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0   # la vista previa no cambia nada
    applied = ctx.sync.apply(admin, run["id"])["summary"]["applied"]
    assert applied["created"] == 1
    p = ctx.inventory.lookup(admin, "A2")[0]
    assert p["price_cents"] == 1250000 and p["stock_milli"] == 2000
    with pytest.raises(ValidationError, match="ya fue aplicada"):
        ctx.sync.apply(admin, run["id"])
    assert ctx.finance.integrity(admin)["ok"]


def test_external_stock_never_overwrites_local_without_master_policy(ctx, admin, product, tmp_path):
    path = workbook(tmp_path / "inv.xlsx", [("MART-01", "Martillo nuevo nombre", 21000, 3, 1)])
    run = ctx.sync.preview_upload(admin, "inv.xlsx", path.read_bytes(), {})
    s = run["summary"]
    assert s["counts"]["stock_differences"] == 1 and s["counts"]["cost_differences"] == 1
    ctx.sync.apply(admin, run["id"])
    p = ctx.inventory.get(admin, product["id"])
    assert p["stock_milli"] == 10000 and p["price_cents"] == 2100000 and p["cost_cents"] == 1000000


def test_master_connection_reconciles_with_movements(ctx, admin, product, tmp_path):
    path = workbook(tmp_path / "maestro.xlsx", [("MART-01", "Martillo de uña", 20000, 7, 10000)])
    with pytest.raises(ValidationError, match="fuente maestra"):
        ctx.sync.save(admin, {"name": "Excel", "provider": "excel", "config": {"path": str(path)}, "stock_policy": "ajustar"})
    conn = ctx.sync.save(admin, {"name": "Excel maestro", "provider": "excel", "config": {"path": str(path)},
                                 "is_master": True, "stock_policy": "ajustar"})
    test = ctx.sync.test(admin, conn["id"])
    assert test["ok"] and test["header_row"] == 2
    run = ctx.sync.preview_connection(admin, conn["id"])
    ctx.sync.apply(admin, run["id"])
    assert ctx.inventory.get(admin, product["id"])["stock_milli"] == 7000
    kinds = [m["kind"] for m in ctx.inventory.history(admin, product["id"])["items"]]
    assert kinds == ["conciliacion", "inicial"]          # el historial local se conserva
    assert ctx.sync.get(admin, conn["id"])["last_status"] == "ok"
    second = ctx.sync.save(admin, {"name": "Otro", "provider": "excel", "config": {"path": str(path)}, "is_master": True})
    assert second["is_master"] and not ctx.sync.get(admin, conn["id"])["is_master"]   # una sola fuente maestra


def test_source_change_after_preview_requires_new_preview(ctx, admin, tmp_path):
    path = workbook(tmp_path / "inv.xlsx", [("N1", "Nuevo", 100, 1, 50)])
    conn = ctx.sync.save(admin, {"name": "Excel", "provider": "excel", "config": {"path": str(path)}})
    run = ctx.sync.preview_connection(admin, conn["id"])
    time.sleep(0.05)
    workbook(path, [("N1", "Nuevo", 999, 1, 50)])
    with pytest.raises(ValidationError, match="cambió"):
        ctx.sync.apply(admin, run["id"])


def test_folder_adapter_takes_latest_file(ctx, admin, tmp_path):
    folder = tmp_path / "red"
    folder.mkdir()
    old = workbook(folder / "inventario-1.xlsx", [("F1", "Viejo", 1, 1, 1)])
    new = workbook(folder / "inventario-2.xlsx", [("F2", "Nuevo", 1, 1, 1)])
    os.utime(old, (time.time() - 100, time.time() - 100))
    (folder / "~$inventario-2.xlsx").write_bytes(b"lock")
    conn = ctx.sync.save(admin, {"name": "Carpeta", "provider": "carpeta", "config": {"folder": str(folder), "pattern": "inventario-*.xlsx"}})
    assert ctx.sync.test(admin, conn["id"])["file"] == new.name
    missing = ctx.sync.save(admin, {"name": "Carpeta mala", "provider": "carpeta", "config": {"folder": str(tmp_path / "no")}})
    assert not ctx.sync.test(admin, missing["id"])["ok"]


def test_scheduled_sync(ctx, admin, tmp_path):
    path = workbook(tmp_path / "inv.xlsx", [("S1", "Programado", 100, 2, 50)])
    ctx.sync.save(admin, {"name": "Auto", "provider": "excel", "config": {"path": str(path)}, "sync_mode": "intervalo",
                          "sync_interval_min": 5})
    assert ctx.sync.tick() and ctx.inventory.lookup(admin, "S1")
    assert ctx.sync.tick() == []      # no vuelve a sincronizar antes del intervalo


class FakeResponse:
    def __init__(self, status=200, body=None, content=b"", headers=None):
        self.status_code = status
        self._body = body
        self.content = content
        self.text = json.dumps(body) if body is not None else ""
        self.headers = {"content-type": "application/json"} if body is not None else (headers or {})

    def json(self):
        return self._body


def test_onedrive_oauth_pkce_refresh_and_download(ctx, admin, tmp_path, monkeypatch):
    ctx.settings.update("oauth", {"microsoft_client_id": "app-123", "microsoft_tenant": "consumers"}, admin)
    conn = ctx.sync.save(admin, {"name": "OneDrive", "provider": "onedrive", "config": {"item_path": "/Inventario/stock.xlsx"}})
    assert conn["needs_oauth"] and not conn["authorized"]
    start = ctx.sync.oauth_start(admin, conn["id"], "http://127.0.0.1:8123/")
    q = parse_qs(urlparse(start["authorize_url"]).query)
    assert q["code_challenge_method"] == ["S256"] and q["client_id"] == ["app-123"]
    assert start["redirect_uri"] == "http://localhost:8123/api/integrations/oauth/callback"
    content = workbook(tmp_path / "od.xlsx", [("OD1", "Desde OneDrive", 100, 3, 40)]).read_bytes()
    posts, gets = [], []

    def fake_post(url, data, timeout):
        posts.append((url, data))
        return FakeResponse(body={"access_token": f"tok{len(posts)}", "refresh_token": "ref", "expires_in": 1})

    def fake_get(url, headers, timeout, follow_redirects):
        gets.append((url, headers["Authorization"]))
        return FakeResponse(content=content, headers={"last-modified": "ayer"})
    monkeypatch.setattr(sources.httpx, "post", fake_post)
    monkeypatch.setattr(sources.httpx, "get", fake_get)
    with pytest.raises(ValidationError):
        ctx.sync.oauth_callback("estado-falso", "code", None)
    ctx.sync.oauth_callback(q["state"][0], "auth-code", None)
    assert posts[0][1]["code_verifier"] and posts[0][1]["grant_type"] == "authorization_code"
    assert ctx.sync.get(admin, conn["id"])["authorized"]
    run = ctx.sync.preview_connection(admin, conn["id"])     # token expirado -> se renueva con refresh_token
    assert posts[1][1]["grant_type"] == "refresh_token"
    assert gets[0][0].endswith("/me/drive/root:/Inventario/stock.xlsx:/content") and gets[0][1] == "Bearer tok2"
    assert run["summary"]["counts"]["new"] == 1
    with ctx.db.read() as c:
        raw = c.execute("SELECT ciphertext FROM secrets WHERE name LIKE 'integration.%'").fetchone()[0]
    assert b"ref" not in bytes(raw)                           # tokens cifrados en reposo


def test_google_drive_requires_credentials_and_exports_sheets(ctx, admin, tmp_path, monkeypatch):
    conn = ctx.sync.save(admin, {"name": "Drive", "provider": "gdrive", "config": {"file_id": "abc123"}})
    with pytest.raises(ValidationError, match="Google"):
        ctx.sync.oauth_start(admin, conn["id"], "http://127.0.0.1:8000/")
    ctx.settings.update("oauth", {"google_client_id": "gid.apps.googleusercontent.com"}, admin)
    ctx.sync.set_google_secret(admin, "gsecret")
    start = ctx.sync.oauth_start(admin, conn["id"], "http://127.0.0.1:8000/")
    q = parse_qs(urlparse(start["authorize_url"]).query)
    assert q["access_type"] == ["offline"] and "drive.readonly" in q["scope"][0]
    content = workbook(tmp_path / "g.xlsx", [("G1", "Desde Drive", 100, 1, 1)]).read_bytes()
    monkeypatch.setattr(sources.httpx, "post", lambda url, data, timeout: FakeResponse(
        body={"access_token": "g", "refresh_token": "r", "expires_in": 3600}))
    urls = []

    def fake_get(url, headers, timeout, follow_redirects):
        urls.append(url)
        if "fields=" in url:
            return FakeResponse(body={"name": "Inventario", "mimeType": sources.GoogleDriveAdapter.SHEET})
        return FakeResponse(content=content)
    monkeypatch.setattr(sources.httpx, "get", fake_get)
    ctx.sync.oauth_callback(q["state"][0], "code", None)
    run = ctx.sync.preview_connection(admin, conn["id"])
    assert "/export?mimeType=" in urls[1] and run["summary"]["file"] == "Inventario.xlsx"


def test_provider_network_failure_is_reported(ctx, admin, monkeypatch):
    ctx.settings.update("oauth", {"microsoft_client_id": "app"}, admin)
    conn = ctx.sync.save(admin, {"name": "OD", "provider": "onedrive", "config": {"item_path": "/x.xlsx"}})
    with ctx.db.tx() as c:
        ctx.secrets.set(c, f"integration.{conn['id']}.oauth", json.dumps({"access_token": "t", "expires_in": 3600,
                                                                            "obtained_at": int(time.time())}))

    def offline(*a, **k):
        raise httpx.ConnectError("sin red")
    monkeypatch.setattr(sources.httpx, "get", offline)
    result = ctx.sync.test(admin, conn["id"])
    assert not result["ok"] and "Sin conexión" in result["message"]

"""Personalización visual: tema (paleta claro/oscuro), pantalla de ingreso (fondo y logotipo independientes),
validación de imágenes, permisos, persistencia y endpoints públicos."""
from __future__ import annotations

import struct

import pytest
from fastapi.testclient import TestClient

from pospy.api.app import create_app
from pospy.core.errors import PermissionDenied, ValidationError
from pospy.services.appearance import COLOR_KEYS, DEFAULT_DARK, DEFAULT_LIGHT, inspect_image

from .conftest import EMPLOYEE_PASSWORD, login
from .test_canvas import _png


def _rgba_png(w: int, h: int) -> bytes:
    """PNG con transparencia (RGBA)."""
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b"".join(bytes(1) + bytes(4 * w) for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _jpeg(w: int, h: int) -> bytes:
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, h, w, 1) + b"\x01\x11\x00"
    return b"\xff\xd8\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + sof + b"\xff\xd9"


def _webp(w: int, h: int) -> bytes:
    body = b"VP8X" + struct.pack("<I", 10) + b"\x10\x00\x00\x00" + (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little")
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WEBP" + body


def test_inspect_image_by_content_only():
    assert inspect_image(_png(30, 20)) == (".png", 30, 20)
    assert inspect_image(_rgba_png(8, 4)) == (".png", 8, 4)
    assert inspect_image(_jpeg(640, 480)) == (".jpg", 640, 480)
    assert inspect_image(_webp(1200, 800)) == (".webp", 1200, 800)
    for bad in (b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", b"MZ\x90\x00",
                b"GIF89a....", _png(4, 4)[:30]):
        with pytest.raises(ValidationError):
            inspect_image(bad)


def test_defaults_are_public_and_match_factory(ctx):
    pub = ctx.appearance.public()
    assert pub["theme"]["enabled"] is False and pub["theme"]["light"] == DEFAULT_LIGHT and pub["theme"]["dark"] == DEFAULT_DARK
    assert pub["login"]["has_background"] is False and pub["login"]["logo"]["use_company"] is True


def test_save_theme_validates_and_persists(ctx, admin):
    light = {**DEFAULT_LIGHT, "primary": "#7C3AED", "nav": "#1E1B4B"}
    saved = ctx.appearance.save_theme(admin, {"enabled": True, "palette": "violet", "light": light, "dark": DEFAULT_DARK})
    assert saved["theme"]["enabled"] and saved["theme"]["light"]["primary"] == "#7c3aed"
    assert ctx.appearance.public()["theme"]["light"]["nav"] == "#1e1b4b"          # se recupera (base de datos)
    for bad in ({**light, "primary": "red"}, {**light, "text": "#12345"}, {k: v for k, v in light.items() if k != "danger"},
                {**light, "surface": "javascript:alert(1)"}):
        with pytest.raises(ValidationError):
            ctx.appearance.save_theme(admin, {"enabled": True, "palette": "violet", "light": bad, "dark": DEFAULT_DARK})
    with pytest.raises(ValidationError):
        ctx.appearance.save_theme(admin, {"enabled": True, "palette": "otra", "light": light, "dark": DEFAULT_DARK})
    assert ctx.appearance.public()["theme"]["light"]["primary"] == "#7c3aed"     # lo inválido no se guardó
    assert set(COLOR_KEYS) == set(DEFAULT_LIGHT)


def test_login_composition_and_independent_images(ctx, admin):
    v0 = ctx.appearance.public()["login"]["version"]
    out = ctx.appearance.save_login(admin, {"background": {"fit": "cover", "pos_x": 30, "pos_y": 70, "zoom": 140, "darken": 20,
                                                           "overlay_color": "#0F172A", "overlay_opacity": 35},
                                            "logo": {"size": 180, "position": "bottom-right", "offset": 24, "use_company": False}})
    login_cfg = out["login"]
    assert login_cfg["background"]["zoom"] == 140 and login_cfg["logo"]["position"] == "bottom-right" and login_cfg["version"] > v0
    with pytest.raises(ValidationError):
        ctx.appearance.save_login(admin, {"background": {"zoom": 900}, "logo": {}})
    with pytest.raises(ValidationError):
        ctx.appearance.save_login(admin, {"background": {}, "logo": {"position": "../../etc"}})
    ctx.appearance.upload(admin, "background", _jpeg(1920, 1080))
    ctx.appearance.upload(admin, "logo", _rgba_png(300, 120))                     # transparente
    pub = ctx.appearance.public()["login"]
    assert pub["has_background"] and pub["has_logo"]
    assert ctx.appearance.image("logo")[1] == "image/png" and ctx.appearance.image("background")[1] == "image/jpeg"
    ctx.appearance.delete(admin, "background")                                   # eliminar el fondo no toca el logotipo
    pub = ctx.appearance.public()["login"]
    assert not pub["has_background"] and pub["has_logo"]
    ctx.appearance.delete(admin, "logo")
    assert not ctx.appearance.public()["login"]["has_logo"]


def test_image_limits(ctx, admin):
    with pytest.raises(ValidationError, match="4000"):
        ctx.appearance.upload(admin, "logo", _webp(5000, 100))
    with pytest.raises(ValidationError, match="grande"):
        ctx.appearance.upload(admin, "logo", _png(10, 10) + b"\x00" * (2 * 1024 * 1024))
    with pytest.raises(ValidationError):
        ctx.appearance.upload(admin, "background", b"<svg onload=alert(1)>")
    assert not ctx.appearance.public()["login"]["has_background"]


def test_permissions_employee_cannot_change_appearance(ctx, employee):
    for call in (lambda: ctx.appearance.save_theme(employee, {"enabled": True, "palette": "corporate", "light": DEFAULT_LIGHT,
                                                              "dark": DEFAULT_DARK}),
                 lambda: ctx.appearance.save_login(employee, {}),
                 lambda: ctx.appearance.upload(employee, "logo", _png(4, 4)),
                 lambda: ctx.appearance.delete(employee, "background")):
        with pytest.raises(PermissionDenied):
            call()


def test_http_public_reads_admin_writes(client, ctx, admin, employee):
    assert client.get("/api/appearance").status_code == 200                      # público (antes de iniciar sesión)
    assert client.get("/api/appearance/login/fondo").status_code == 404
    assert client.put("/api/appearance/theme", json={}).status_code == 401        # sin sesión
    login(client)
    r = client.post("/api/appearance/login/fondo", files={"file": ("f.png", _png(64, 32), "image/png")})
    assert r.status_code == 200 and r.json()["login"]["has_background"]
    r = client.post("/api/appearance/login/logotipo", files={"file": ("x.svg", b"<svg/>", "image/svg+xml")})
    assert r.status_code == 422
    assert client.post("/api/appearance/login/..%2F..%2Fsecreto", files={"file": ("a.png", _png(2, 2), "image/png")}).status_code >= 400
    img = client.get("/api/appearance/login/fondo")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png" and img.headers["x-content-type-options"] == "nosniff"
    r = client.put("/api/appearance/theme", json={"enabled": True, "palette": "emerald", "light": DEFAULT_LIGHT, "dark": DEFAULT_DARK})
    assert r.status_code == 200
    other = TestClient(create_app(ctx))                                            # otro dispositivo, otra sesión
    other.headers.update({"X-Requested-With": "pos-py"})
    login(other, "empleado", EMPLOYEE_PASSWORD)
    assert other.put("/api/appearance/theme", json={"enabled": False}).status_code == 403
    assert other.delete("/api/appearance/login/fondo").status_code == 403
    assert other.get("/api/appearance").json()["theme"]["palette"] == "emerald"    # todos ven el tema del negocio

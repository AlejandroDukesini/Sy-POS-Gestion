"""Personalización visual del negocio: paleta de colores de toda la aplicación y composición de la pantalla de
ingreso (imagen de fondo y logotipo independientes).

Persistencia (misma tabla «settings» que el resto de la configuración, una clave por módulo):
- «apariencia»: tema (activo sí/no, paleta de partida, colores del modo claro y del modo oscuro).
- «login»: composición del panel visual del ingreso (ajuste/posición/zoom/oscurecimiento/superposición del
  fondo; tamaño/posición del logotipo) y versión para invalidar la caché del navegador.
Las imágenes se guardan como archivos en la carpeta de datos (branding/), nunca como Base64 en la base.

Alcance: una instalación = un negocio. Inventarios y grupos comparten la apariencia (no hay apariencia por
inventario, así que uno no puede sobrescribir la de otro negocio).

La paleta solo define 12 colores base por modo; la interfaz deriva el resto (hover, suaves, texto sobre color)
y advierte los contrastes insuficientes. El servidor valida formato y rangos.
"""
from __future__ import annotations

import json
import re
import sqlite3
import struct
from pathlib import Path
from typing import Any

from ..core.actor import Actor
from ..core.audit import record
from ..core.clock import iso
from ..core.errors import NotFoundError, ValidationError

THEME_KEY, LOGIN_KEY = "apariencia", "login"
COLOR_KEYS = ("primary", "secondary", "accent", "background", "surface", "nav", "text", "text_muted", "border",
              "success", "warning", "danger")
PALETTES = ("corporate", "emerald", "violet", "warm", "neutral", "dark_pro", "personalizada")
LOGO_POSITIONS = ("top-left", "top-center", "top-right", "center-left", "center", "center-right",
                  "bottom-left", "bottom-center", "bottom-right")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

# Colores de fábrica (coinciden con styles/tokens.css): «Corporate Blue».
DEFAULT_LIGHT = {"primary": "#1d4ed8", "secondary": "#475569", "accent": "#0e7490", "background": "#f4f6fa",
                 "surface": "#ffffff", "nav": "#ffffff", "text": "#111827", "text_muted": "#4b5563", "border": "#c9d0dc",
                 "success": "#15803d", "warning": "#b45309", "danger": "#b91c1c"}
DEFAULT_DARK = {"primary": "#8fb0ff", "secondary": "#a5b4c8", "accent": "#5fd3e6", "background": "#0f141c",
                "surface": "#171e29", "nav": "#171e29", "text": "#f1f4f9", "text_muted": "#b6c0cf", "border": "#364256",
                "success": "#6ee7a0", "warning": "#fbbf5b", "danger": "#ff9b9b"}
DEFAULT_THEME = {"enabled": False, "palette": "corporate", "light": DEFAULT_LIGHT, "dark": DEFAULT_DARK}
DEFAULT_LOGIN = {
    "background": {"fit": "cover", "pos_x": 50, "pos_y": 50, "zoom": 100, "darken": 0,
                   "overlay_color": "#000000", "overlay_opacity": 0},
    "logo": {"size": 240, "position": "center", "offset": 32, "use_company": True},
    "version": 0,
}

IMAGE_LIMITS = {"background": (6 * 1024 * 1024, 8000), "logo": (2 * 1024 * 1024, 4000)}   # bytes, lado máximo (px)
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}


# ------------------------------------------------------------------ imágenes
def inspect_image(data: bytes) -> tuple[str, int, int]:
    """(extensión, ancho, alto) según el CONTENIDO real. Solo PNG, JPEG y WEBP; SVG y demás se rechazan."""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
            w, h = struct.unpack(">II", data[16:24])
            if b"IEND" not in data[-16:]:
                raise ValueError("PNG incompleto")
            return ".png", w, h
        if data[:3] == b"\xff\xd8\xff":
            i = 2
            while i < len(data) - 9:
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                    i += 2
                    continue
                length = struct.unpack(">H", data[i + 2:i + 4])[0]
                if marker in (0xC0, 0xC1, 0xC2):
                    h, w = struct.unpack(">HH", data[i + 5:i + 9])
                    return ".jpg", w, h
                i += 2 + length
            raise ValueError("JPEG sin dimensiones")
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            kind = data[12:16]
            if kind == b"VP8 ":
                w, h = struct.unpack("<HH", data[26:30])
                return ".webp", w & 0x3FFF, h & 0x3FFF
            if kind == b"VP8L":
                b = data[21:25]
                w = 1 + (((b[1] & 0x3F) << 8) | b[0])
                h = 1 + (((b[3] & 0x0F) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
                return ".webp", w, h
            if kind == b"VP8X":
                w = 1 + int.from_bytes(data[24:27], "little")
                h = 1 + int.from_bytes(data[27:30], "little")
                return ".webp", w, h
    except (struct.error, IndexError, ValueError):
        pass
    raise ValidationError("El archivo no es una imagen válida.", {"file": "Use PNG, JPG o WEBP (no se admite SVG)."})


class AppearanceService:
    def __init__(self, db, data_dir: Path):
        self.db = db
        self.dir = data_dir / "branding"
        self.dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ lectura (pública: la usa la pantalla de ingreso)
    def _load(self, conn: sqlite3.Connection, key: str, default: dict) -> dict:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        stored = json.loads(row[0]) if row else {}
        return _merge(default, stored)

    def public(self) -> dict:
        with self.db.read() as conn:
            theme = self._load(conn, THEME_KEY, DEFAULT_THEME)
            login = self._load(conn, LOGIN_KEY, DEFAULT_LOGIN)
        login["has_background"] = self._file("background") is not None
        login["has_logo"] = self._file("logo") is not None
        return {"theme": theme, "login": login, "defaults": {"light": DEFAULT_LIGHT, "dark": DEFAULT_DARK}}

    # ------------------------------------------------------------------ escritura (administrador)
    def save_theme(self, actor: Actor, data: dict) -> dict:
        actor.require("gestion.configuracion")
        errors: dict[str, str] = {}
        palette = data.get("palette", "personalizada")
        if palette not in PALETTES:
            errors["palette"] = "Paleta desconocida."
        theme = {"enabled": bool(data.get("enabled")), "palette": palette}
        for mode in ("light", "dark"):
            colors = data.get(mode) if isinstance(data.get(mode), dict) else {}
            theme[mode] = {}
            for k in COLOR_KEYS:
                v = colors.get(k)
                if not isinstance(v, str) or not _HEX.match(v):
                    errors[f"{mode}.{k}"] = "Color no válido: use el formato #RRGGBB."
                    continue
                theme[mode][k] = v.lower()
        if errors:
            raise ValidationError("Revise los colores. " + next(iter(errors.values())), errors)
        self._store(actor, THEME_KEY, theme, "apariencia.tema", {"activo": theme["enabled"], "paleta": palette})
        return self.public()

    def save_login(self, actor: Actor, data: dict) -> dict:
        actor.require("gestion.configuracion")
        errors: dict[str, str] = {}
        bg_in = data.get("background") if isinstance(data.get("background"), dict) else {}
        logo_in = data.get("logo") if isinstance(data.get("logo"), dict) else {}

        def num(src: dict, key: str, lo: int, hi: int, default: int) -> int:
            try:
                v = int(round(float(src.get(key, default))))
            except (TypeError, ValueError):
                errors[key] = "Número no válido."
                return default
            if not lo <= v <= hi:
                errors[key] = f"Debe estar entre {lo} y {hi}."
            return max(lo, min(hi, v))

        d_bg, d_logo = DEFAULT_LOGIN["background"], DEFAULT_LOGIN["logo"]
        fit = bg_in.get("fit", d_bg["fit"])
        if fit not in ("cover", "contain"):
            errors["fit"] = "Ajuste no válido."
        color = bg_in.get("overlay_color", d_bg["overlay_color"])
        if not isinstance(color, str) or not _HEX.match(color):
            errors["overlay_color"] = "Color no válido: use el formato #RRGGBB."
        position = logo_in.get("position", d_logo["position"])
        if position not in LOGO_POSITIONS:
            errors["position"] = "Posición no válida."
        background = {"fit": fit, "pos_x": num(bg_in, "pos_x", 0, 100, 50), "pos_y": num(bg_in, "pos_y", 0, 100, 50),
                      "zoom": num(bg_in, "zoom", 100, 300, 100), "darken": num(bg_in, "darken", 0, 80, 0),
                      "overlay_color": str(color).lower(), "overlay_opacity": num(bg_in, "overlay_opacity", 0, 90, 0)}
        logo = {"size": num(logo_in, "size", 40, 520, 240), "position": position, "offset": num(logo_in, "offset", 0, 160, 32),
                "use_company": bool(logo_in.get("use_company", True))}
        if errors:
            raise ValidationError("Revise la pantalla de ingreso. " + next(iter(errors.values())), errors)
        with self.db.read() as conn:
            version = self._load(conn, LOGIN_KEY, DEFAULT_LOGIN)["version"]
        self._store(actor, LOGIN_KEY, {"background": background, "logo": logo, "version": version + 1}, "apariencia.ingreso",
                    {"ajuste": fit, "logo": position})
        return self.public()

    def upload(self, actor: Actor, kind: str, data: bytes) -> dict:
        actor.require("gestion.configuracion")
        if kind not in IMAGE_LIMITS:
            raise NotFoundError("Recurso no encontrado.")
        max_bytes, max_side = IMAGE_LIMITS[kind]
        if len(data) > max_bytes:
            raise ValidationError("Imagen demasiado grande.", {"file": f"Máximo {max_bytes // (1024 * 1024)} MB."})
        ext, w, h = inspect_image(data)
        if not (1 <= w <= max_side and 1 <= h <= max_side):
            raise ValidationError(f"La imagen debe medir como máximo {max_side} × {max_side} píxeles.",
                                  {"file": f"Mide {w} × {h} px."})
        self._remove_files(kind)
        (self.dir / f"login-{kind}{ext}").write_bytes(data)
        self._bump(actor, f"apariencia.ingreso.{'fondo' if kind == 'background' else 'logotipo'}",
                   {"accion": "subir", "ancho": w, "alto": h, "bytes": len(data)})
        return self.public()

    def delete(self, actor: Actor, kind: str) -> dict:
        actor.require("gestion.configuracion")
        if kind not in IMAGE_LIMITS:
            raise NotFoundError("Recurso no encontrado.")
        self._remove_files(kind)
        self._bump(actor, f"apariencia.ingreso.{'fondo' if kind == 'background' else 'logotipo'}", {"accion": "eliminar"})
        return self.public()

    def image(self, kind: str) -> tuple[Path, str]:
        """Archivo público de la pantalla de ingreso (solo los dos nombres fijos: sin rutas arbitrarias)."""
        path = self._file(kind) if kind in IMAGE_LIMITS else None
        if path is None:
            raise NotFoundError("Sin imagen.")
        return path, MIME[path.suffix]

    # ------------------------------------------------------------------ utilidades
    def _file(self, kind: str) -> Path | None:
        for ext in MIME:
            p = self.dir / f"login-{kind}{ext}"
            if p.is_file():
                return p
        return None

    def _remove_files(self, kind: str) -> None:
        for ext in MIME:
            (self.dir / f"login-{kind}{ext}").unlink(missing_ok=True)

    def _bump(self, actor: Actor, action: str, detail: dict) -> None:
        with self.db.read() as conn:
            login = self._load(conn, LOGIN_KEY, DEFAULT_LOGIN)
        login["version"] += 1
        self._store(actor, LOGIN_KEY, login, action, detail)

    def _store(self, actor: Actor, key: str, value: dict, action: str, detail: dict) -> None:
        with self.db.tx() as conn:
            conn.execute("INSERT INTO settings(key, value, updated_at, updated_by) VALUES (?,?,?,?) ON CONFLICT(key) DO UPDATE"
                         " SET value = excluded.value, updated_at = excluded.updated_at, updated_by = excluded.updated_by",
                         (key, json.dumps(value, ensure_ascii=False), iso(), actor.id))
            record(conn, actor, action, "settings", key, detail)


def _merge(default: Any, stored: Any) -> Any:
    """Valores guardados sobre los de fábrica (claves nuevas toman su valor de fábrica)."""
    if isinstance(default, dict):
        src = stored if isinstance(stored, dict) else {}
        return {k: _merge(v, src.get(k)) for k, v in default.items()}
    return default if stored is None else stored

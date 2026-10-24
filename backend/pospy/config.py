"""Configuración de proceso leída del entorno (no la de negocio: esa vive en la tabla settings)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "si", "sí", "on")


def _default_data_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "data"


@dataclass(frozen=True)
class Config:
    data_dir: Path
    host: str = "127.0.0.1"
    port: int = 8000
    web_dist: Path | None = None
    secure_cookies: bool = False
    cors_origins: tuple[str, ...] = ()
    setup_code: str = ""          # código de instalación inyectado por el escritorio (Tauri)
    master_key: str = ""          # alternativa a DPAPI para cifrar secretos fuera de Windows
    desktop: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "pospy.db"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def templates_dir(self) -> Path:
        return self.data_dir / "templates"

    @property
    def output_dir(self) -> Path:
        return self.data_dir / "documents"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def imports_dir(self) -> Path:
        return self.data_dir / "imports"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.backups_dir, self.templates_dir, self.output_dir, self.logs_dir, self.imports_dir):
            d.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls, **overrides) -> Config:
        env = os.environ
        dist = env.get("POS_WEB_DIST")
        default_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
        values = dict(
            data_dir=Path(env.get("POS_DATA_DIR") or _default_data_dir()),
            host=env.get("POS_HOST", "127.0.0.1"),
            port=int(env.get("POS_PORT", "8000")),
            web_dist=Path(dist) if dist else default_dist,
            secure_cookies=_bool(env.get("POS_SECURE_COOKIES"), False),
            cors_origins=tuple(o.strip() for o in env.get("POS_CORS_ORIGINS", "").split(",") if o.strip()),
            setup_code=env.get("POS_SETUP_CODE", ""),
            master_key=env.get("POS_MASTER_KEY", ""),
            desktop=_bool(env.get("POS_DESKTOP"), False),
        )
        values.update(overrides)
        if isinstance(values["data_dir"], str):
            values["data_dir"] = Path(values["data_dir"])
        return cls(**values)

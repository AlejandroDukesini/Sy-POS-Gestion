"""Servidor POS-PY: python -m pospy [--host H] [--port P] [--data-dir D] [--web-dist W] [--desktop]

La aplicación de escritorio (Tauri) lo ejecuta empaquetado como pospy-server.exe con --desktop,
un puerto libre y la carpeta de datos del usuario.
"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
from pathlib import Path


def setup_logging(logs_dir: Path) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(logs_dir / "pospy.log", maxBytes=5 * 1024 * 1024, backupCount=5,
                                                   encoding="utf-8")
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(fmt)
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [handler, console]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pospy", description="Servidor POS-PY (API + interfaz)")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--data-dir")
    parser.add_argument("--web-dist")
    parser.add_argument("--desktop", action="store_true", help="Modo escritorio (lo usa la aplicación Tauri)")
    args = parser.parse_args(argv)
    for flag, env in ((args.host, "POS_HOST"), (args.port, "POS_PORT"), (args.data_dir, "POS_DATA_DIR"),
                      (args.web_dist, "POS_WEB_DIST")):
        if flag is not None:
            os.environ[env] = str(flag)
    if args.desktop:
        os.environ["POS_DESKTOP"] = "1"

    import uvicorn

    from .api.app import create_app
    from .config import Config
    from .context import AppContext

    config = Config.from_env()
    if getattr(sys, "frozen", False) and not os.environ.get("POS_WEB_DIST"):
        # Ejecutable PyInstaller: la interfaz compilada viaja dentro del paquete.
        config = Config.from_env(web_dist=Path(getattr(sys, "_MEIPASS", ".")) / "web")
    setup_logging(config.logs_dir)
    if config.host not in ("127.0.0.1", "localhost", "::1") and not config.secure_cookies:
        logging.getLogger("pospy").warning("Escuchando en %s sin POS_SECURE_COOKIES=1: publíquelo solo detrás de HTTPS.",
                                           config.host)
    ctx = AppContext(config)
    app = create_app(ctx, run_scheduler=True)
    uvicorn.run(app, host=config.host, port=config.port, log_config=None, workers=1, access_log=False)


if __name__ == "__main__":
    main()

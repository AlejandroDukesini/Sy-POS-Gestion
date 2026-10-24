"""Empaqueta el backend Python (con la interfaz compilada) como ejecutable para la aplicación de escritorio.

  backend\\.venv\\Scripts\\python.exe scripts\\build_backend.py

Requisitos: haber ejecutado `npm run build` en frontend/ y tener requirements-dev.txt instalado (PyInstaller).
Resultado: desktop/src-tauri/binaries/pospy-server-<triple>.exe, el nombre que Tauri espera para un
"externalBin" (sidecar). Incluye Python, las dependencias y frontend/dist: el equipo final no necesita
instalar Python.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
DIST = ROOT / "frontend" / "dist"
OUT = ROOT / "desktop" / "src-tauri" / "binaries"


def target_triple() -> str:
    try:
        out = subprocess.run(["rustc", "-vV"], capture_output=True, text=True, check=True).stdout
        return next(line.split(": ", 1)[1] for line in out.splitlines() if line.startswith("host: "))
    except (OSError, subprocess.CalledProcessError, StopIteration):
        return "x86_64-pc-windows-msvc"


def main() -> int:
    if not (DIST / "index.html").exists():
        print("Falta frontend/dist: ejecute `npm run build` en frontend/ primero.", file=sys.stderr)
        return 1
    triple = target_triple()
    name = f"pospy-server-{triple}"
    work = BACKEND / "build"
    sep = ";" if sys.platform == "win32" else ":"
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--name", name,
        "--distpath", str(OUT), "--workpath", str(work), "--specpath", str(work),
        "--add-data", f"{DIST}{sep}web",
        "--collect-submodules", "pospy", "--collect-submodules", "uvicorn", "--collect-data", "tzdata",
        "--hidden-import", "win32print", "--hidden-import", "win32com.client", "--hidden-import", "pythoncom",
        "--noconsole",
        str(BACKEND / "pospy_server.py"),
    ]
    print(" ".join(cmd))
    result = subprocess.run(cmd, cwd=BACKEND, check=False)
    if result.returncode:
        return result.returncode
    shutil.rmtree(work, ignore_errors=True)
    print(f"Listo: {OUT / (name + ('.exe' if sys.platform == 'win32' else ''))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

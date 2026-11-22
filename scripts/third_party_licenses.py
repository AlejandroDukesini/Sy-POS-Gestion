"""Genera docs/developer/licencias-terceros.md con las licencias de las dependencias de EJECUCIÓN.

Fuentes: metadatos de los paquetes Python instalados (requirements.txt y sus dependencias) y package.json de
cada paquete npm de producción de frontend/ (npm ls --omit=dev). Marca licencias copyleft o desconocidas para
revisión. Uso:  backend\\.venv\\Scripts\\python.exe scripts\\third_party_licenses.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "developer" / "licencias-terceros.md"
REVIEW = re.compile(r"GPL|AGPL|SSPL|BUSL|Commons Clause|CC-BY-NC|UNKNOWN|Desconocida", re.IGNORECASE)


def python_packages() -> list[tuple[str, str, str]]:
    wanted = []
    for line in (ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line and not line.startswith("-"):
            name = re.split(r"[=<>;\[ ]", line)[0]
            if ";" in line and "win32" in line and sys.platform != "win32":
                continue
            wanted.append(name)
    seen: dict[str, tuple[str, str, str]] = {}
    while wanted:
        name = wanted.pop()
        key = name.lower().replace("_", "-")
        if key in seen:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        meta = dist.metadata
        lic = meta.get("License-Expression") or ""
        if not lic or len(lic) > 60:
            classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
            lic = ", ".join(classifiers) or (meta.get("License") or "").splitlines()[0][:60] or "Desconocida"
        seen[key] = (dist.metadata["Name"], dist.version, lic)
        for req in dist.requires or []:
            if "extra ==" in req:
                continue
            if "sys_platform" in req and "win32" in req and sys.platform != "win32":
                continue
            wanted.append(re.split(r"[=<>!~;\[ (]", req)[0])
    return sorted(seen.values(), key=lambda x: x[0].lower())


def npm_packages() -> list[tuple[str, str, str]]:
    front = ROOT / "frontend"
    out = subprocess.run("npm ls --omit=dev --all --json", cwd=front, capture_output=True, text=True, shell=True).stdout
    tree = json.loads(out or "{}")
    found: dict[str, tuple[str, str, str]] = {}

    def walk(deps: dict):
        for name, info in (deps or {}).items():
            version = info.get("version", "")
            if f"{name}@{version}" not in found:
                pkg = front / "node_modules" / name / "package.json"
                lic = "Desconocida"
                if pkg.exists():
                    data = json.loads(pkg.read_text(encoding="utf-8"))
                    lic = data.get("license") or (data.get("licenses") or [{}])[0].get("type", "Desconocida")
                    if isinstance(lic, dict):
                        lic = lic.get("type", "Desconocida")
                found[f"{name}@{version}"] = (name, version, str(lic))
            walk(info.get("dependencies"))
    walk(tree.get("dependencies"))
    return sorted(found.values(), key=lambda x: x[0].lower())


def table(rows: list[tuple[str, str, str]]) -> str:
    lines = ["| Paquete | Versión | Licencia |", "|---|---|---|"]
    lines += [f"| {n} | {v} | {lic}{' ⚠️ revisar' if REVIEW.search(lic) else ''} |" for n, v, lic in rows]
    return "\n".join(lines)


def main() -> None:
    py, js = python_packages(), npm_packages()
    flagged = [r for r in py + js if REVIEW.search(r[2])]
    text = f"""# Licencias de terceros

Generado con `scripts/third_party_licenses.py` a partir de las dependencias instaladas (no editar a mano).
Incluye solo dependencias de **ejecución** (servidor Python y paquetes npm que llegan al navegador); las
herramientas de desarrollo y compilación (pytest, ruff, vite, eslint, PyInstaller…) no se distribuyen.

Licencia del proyecto: CC BY-NC 4.0 (ver `LICENSE`). Las dependencias usan licencias permisivas compatibles con
su uso y redistribución (MIT, BSD, Apache-2.0, ISC, PSF…), que exigen conservar sus avisos de copyright: este
documento y los propios paquetes los conservan.

Paquetes marcados para revisión: {len(flagged)}{" — " + ", ".join(f"{n} ({lic})" for n, _, lic in flagged) if flagged else ""}.

La aplicación de escritorio (desktop/src-tauri) usa crates de Rust de Tauri (mayoritariamente MIT o Apache-2.0);
su lista exacta está en `desktop/src-tauri/Cargo.lock` y puede generarse con `cargo license` si se distribuye el
instalador. Los iconos de la interfaz son de lucide-react (ISC). No se usan fuentes ni imágenes externas.

## Servidor (Python)

{table(py)}

## Interfaz (npm, producción)

{table(js)}
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: {len(py)} paquetes Python, {len(js)} npm, {len(flagged)} para revisar")


if __name__ == "__main__":
    main()

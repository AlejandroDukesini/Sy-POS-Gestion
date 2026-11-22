# Licencias de terceros

Generado con `scripts/third_party_licenses.py` a partir de las dependencias instaladas (no editar a mano).
Incluye solo dependencias de **ejecución** (servidor Python y paquetes npm que llegan al navegador); las
herramientas de desarrollo y compilación (pytest, ruff, vite, eslint, PyInstaller…) no se distribuyen.

Licencia del proyecto: CC BY-NC 4.0 (ver `LICENSE`). Las dependencias usan licencias permisivas compatibles con
su uso y redistribución (MIT, BSD, Apache-2.0, ISC, PSF…), que exigen conservar sus avisos de copyright: este
documento y los propios paquetes los conservan.

Paquetes marcados para revisión: 0.

La aplicación de escritorio (desktop/src-tauri) usa crates de Rust de Tauri (mayoritariamente MIT o Apache-2.0);
su lista exacta está en `desktop/src-tauri/Cargo.lock` y puede generarse con `cargo license` si se distribuye el
instalador. Los iconos de la interfaz son de lucide-react (ISC). No se usan fuentes ni imágenes externas.

## Servidor (Python)

| Paquete | Versión | Licencia |
|---|---|---|
| annotated-doc | 0.0.5 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.15.1 | MIT |
| certifi | 2026.10.23 | Mozilla Public License 2.0 (MPL 2.0) |
| cffi | 2.1.1 | MIT-0 |
| click | 8.5.0 | BSD-3-Clause |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause |
| et_xmlfile | 2.0.0 | MIT License |
| fastapi | 0.162.0 | MIT |
| h11 | 0.16.0 | MIT License |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpx | 0.28.1 | BSD License |
| idna | 3.20 | BSD-3-Clause |
| openpyxl | 3.1.5 | MIT License |
| opentelemetry-api | 1.45.1 | Apache-2.0 |
| pycparser | 3.12 | BSD-3-Clause |
| pydantic | 2.14.1 | MIT |
| pydantic_core | 2.50.1 | MIT |
| python-multipart | 0.0.32 | Apache-2.0 |
| pywin32 | 312 | Python Software Foundation License |
| starlette | 1.10.0 | BSD-3-Clause |
| typing-inspection | 0.4.4 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| tzdata | 2025.2 | Apache Software License |
| uvicorn | 0.37.0 | BSD-3-Clause |

## Interfaz (npm, producción)

| Paquete | Versión | Licencia |
|---|---|---|
| cookie | 1.1.1 | MIT |
| js-tokens | 4.0.0 | MIT |
| loose-envify | 1.4.0 | MIT |
| lucide-react | 0.460.0 | ISC |
| react | 18.3.1 | MIT |
| react-dom | 18.3.1 | MIT |
| react-router | 7.18.4 | MIT |
| react-router-dom | 7.18.4 | MIT |
| scheduler | 0.23.2 | MIT |
| set-cookie-parser | 2.7.3 | MIT |

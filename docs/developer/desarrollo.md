# Desarrollo, configuración, pruebas y despliegue

## Requisitos

- Python 3.12 o superior (verificado con 3.13) y Node.js 20 o superior (verificado con 22 y 24).
- Windows 10/11 para la impresión directa (pywin32). El servidor web también funciona en Linux/macOS, sin impresión directa.
- Solo para compilar el escritorio: Rust estable y Visual Studio Build Tools (MSVC).

## Instalación

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

cd ..\frontend
npm ci
```

## Ejecución

- Forma simple: `iniciar.cmd` en la raíz (usa siempre `backend\.venv` y lo crea si no existe). Ejecutar
  `python -m pospy` con el Python global falla con `ModuleNotFoundError: No module named 'uvicorn'`.
- Desarrollo con recarga (dos terminales):

```powershell
cd backend;  .venv\Scripts\python.exe -m pospy   # API en http://127.0.0.1:8000 (documentación: /api/docs, solo en este equipo)
cd frontend; npm run dev                          # interfaz en http://localhost:5173 (reenvía /api al backend)
```

- Producción web (un proceso sirve la API y la interfaz): `npm run build` en `frontend/` y luego `python -m pospy`.
  Acepta `--host`, `--port`, `--data-dir` y `--web-dist`.

### Instalación inicial

No hay usuarios por defecto ni registro público. Mientras la configuración inicial no termine, el servidor guarda un
código de un solo uso en `<datos>\setup-code.txt`; el asistente solo se abre **desde el propio equipo** con ese código
(en el escritorio se inyecta solo). Herramientas de consola desde `backend/`:

```powershell
.venv\Scripts\python.exe -m pospy.cli create-admin
.venv\Scripts\python.exe -m pospy.cli reset-password <usuario>   # contraseña temporal
.venv\Scripts\python.exe -m pospy.cli status
.venv\Scripts\python.exe -m pospy.cli backup
```

## Configuración

| Variable | Uso | Predeterminado |
|---|---|---|
| `POS_DATA_DIR` | Carpeta de datos (base, copias, plantillas, documentos, imágenes, registros) | `backend/data` |
| `POS_HOST` / `POS_PORT` | Dirección y puerto | `127.0.0.1` / `8000` |
| `POS_WEB_DIST` | Interfaz compilada | `frontend/dist` |
| `POS_SECURE_COOKIES` | `1` = cookie de sesión solo por HTTPS | `0` |
| `POS_CORS_ORIGINS` | Orígenes permitidos si la interfaz se sirve desde otro origen | vacío |
| `POS_MASTER_KEY` | Clave para cifrar credenciales fuera de Windows (en Windows: DPAPI) | vacío |
| `POS_SETUP_CODE` | Código de instalación inyectado (escritorio) | vacío |
| `POS_PUBLIC_URL` | Dirección pública HTTPS para los enlaces de invitación | vacío |

La configuración del negocio se hace en **Gestión** y se guarda en la tabla `settings` (una clave por sección; los
módulos propios usan `acceso`, `apariencia`, `login` y `dispositivos`).

### Red local e Internet

Por defecto solo escucha en el propio equipo. Para otros equipos: proxy inverso con **HTTPS**, `POS_HOST=0.0.0.0`
solo en una red de confianza y `POS_SECURE_COOKIES=1`. Un único proceso; la base SQLite nunca en una carpeta de red.
El tiempo real usa Server-Sent Events: el proxy no debe almacenar `text/event-stream` (nginx: `proxy_buffering off`).
La restricción por equipo (Gestión › Equipos autorizados) exige HTTPS en los demás equipos (WebCrypto).

## Pruebas

```powershell
cd backend
.venv\Scripts\python.exe -m pytest                       # incluye tests/test_security.py (autorización y equipos)
.venv\Scripts\python.exe -m ruff check pospy tests
.venv\Scripts\python.exe -m bandit -r pospy -q --severity-level high
.venv\Scripts\python.exe -m pip_audit -r requirements.txt

cd ..\frontend
npm run lint; npm run typecheck; npm test
npm audit --omit=dev --registry=https://registry.npmjs.org
npm run build
node e2e/smoke.mjs            # y los demás e2e/*.mjs: navegador real (Edge) contra el servidor real
```

Pruebas de extremo a extremo (`frontend/e2e/`): `smoke`, `inventories`, `group-inventory`, `groups`, `notes-tasks`,
`columns-group-tasks`, `print-templates`, `canvas-editor`, `printers-documents`, `appearance`, `devices`,
`upgrade-regression`. Variables: `PYTHON`, `BROWSER` (`msedge` o `chrome`), `SHOTS`. `devices.mjs` entra por la IP de
red del equipo para simular otros computadores. `scripts/groups_e2e.py [--public https://…]` prueba grupos a través de
un túnel.

Si el registro npm configurado es un espejo sin auditoría, use `--registry=https://registry.npmjs.org` en `npm audit`.

## CI/CD (GitHub Actions)

`.github/workflows/ci.yml` en cada push y PR a `Beta` y `Principal`: Ruff, pytest, Bandit (falla con severidad
alta), pip-audit, ESLint, Vitest, build, `npm audit` y gitleaks sobre todo el historial. `.github/dependabot.yml`
propone actualizaciones (se revisan y prueban antes de fusionar). Flujo de ramas: los cambios entran a `Beta` y se
pasan a `Principal` tras revisarlos.

## Escritorio (Tauri)

```powershell
cd frontend; npm ci; npm run build
cd ..; backend\.venv\Scripts\python.exe scripts\build_backend.py   # desktop\src-tauri\binaries\pospy-server-<triple>.exe
cd desktop; npm ci; npm run build                                 # instaladores en desktop\src-tauri\target\release\bundle\
```

La ventana arranca el backend empaquetado en un puerto libre de `127.0.0.1` y lo detiene al cerrarse. Icono:
`desktop/src-tauri/app-icon.png` y `npm run icons` en `desktop/`, o `scripts/make_icons.py "#color"`.
Licencias de terceros: `scripts/third_party_licenses.py` → `docs/developer/licencias-terceros.md`.

## Integraciones de inventario

Gestión › Integraciones. POS-PY es la autoridad sobre las existencias salvo que una conexión se marque como fuente
maestra («ajustar» registra movimientos de conciliación; «informar» solo reporta). Toda sincronización manual pasa por
vista previa y exige que el archivo no haya cambiado (SHA-256).

- **OneDrive (Entra ID)**: aplicación de «escritorio» con redirección `http://localhost`, permisos delegados
  `Files.Read` y `offline_access`; el Id. de cliente va en Gestión › Integraciones › Credenciales (sin secreto).
- **Google Drive**: «Google Drive API», pantalla de consentimiento y cliente OAuth «App de escritorio»; `drive.readonly`
  es restringido (fuera de usuarios de prueba, Google exige verificar la aplicación).
- **Carpeta de red**: rutas UNC con permiso de lectura para la cuenta que ejecuta POS-PY.

## Plantillas de documentos

Dos sistemas conviven: **Plantillas de impresión** (recomendado: importar el Excel o diseñar en cuadrícula o en el
editor visual; PDF, Excel e impresión directa) y la plantilla Excel de **Tipos de documento** con marcadores
`{{numero}}`, `{{cliente_nombre}}`, `{{linea.descripcion}}`… Ninguno necesita Microsoft Excel ni exige campos: los datos
que falten quedan en blanco. Detalle en [modulos/plantillas-e-impresion.md](modulos/plantillas-e-impresion.md).

## Solución de problemas

| Síntoma | Causa y solución |
|---|---|
| `No module named 'uvicorn'` | Se usó el Python global: use `iniciar.cmd` o `backend\.venv\Scripts\python.exe`. |
| La interfaz avisa «servidor desactualizado» | El servidor en marcha es anterior: ciérrelo y vuelva a iniciarlo (aplica las migraciones). |
| «Equipo no autorizado» al ingresar | Restricción por equipo activa: solicite la autorización desde esa pantalla y apruébela en Gestión › Equipos autorizados. |
| «Este navegador no puede identificar el equipo» | Se abrió por `http://` desde otro equipo: use la dirección HTTPS. |
| Los colores quedaron ilegibles | Abra el POS con `?tema=original` y corrija en Gestión › Apariencia. |
| Imprimir con «Microsoft Print to PDF» abre una ventana en el servidor | Es el comportamiento de esa impresora virtual; elija una impresora real. |
| `npm audit` falla con `NOT_IMPLEMENTED` | El registro configurado es un espejo: agregue `--registry=https://registry.npmjs.org`. |

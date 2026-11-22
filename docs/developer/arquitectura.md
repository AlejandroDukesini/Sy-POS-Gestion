# Arquitectura

POS-PY es una aplicación de una sola instalación por negocio: un servidor Python (FastAPI + SQLite) que concentra
toda la lógica y una interfaz React (web/PWA) que también se empaqueta como aplicación de escritorio (Tauri).

```
navegador / ventana Tauri ──HTTPS o 127.0.0.1──▶ FastAPI (pospy/api) ──▶ servicios (pospy/services) ──▶ SQLite (WAL)
        ▲                                             │                        │
        └──────────── Server-Sent Events ◀────────────┘                        └─▶ archivos en <datos>/ (plantillas,
                                                                                    imágenes, documentos, copias)
```

## Estructura del código

| Carpeta | Contenido |
|---|---|
| `backend/pospy/api` | Aplicación FastAPI (`app.py`: CSRF, cabeceras de seguridad, errores), dependencias de identidad (`deps.py`), modelos de entrada estrictos (`models.py`, rechazan campos desconocidos) y rutas por módulo (`routes/`). |
| `backend/pospy/services` | Reglas de negocio. Cada operación recibe el `Actor` y valida permisos, inventario y propiedad del recurso. |
| `backend/pospy/core` | Identidad y permisos (`actor.py`, `permissions.py`), contraseñas y tokens (`security.py`), auditoría (`audit.py`), configuración (`settings.py`), límites de intentos (`ratelimit.py`), secretos cifrados (`secrets_store.py`), dinero y fechas. |
| `backend/pospy/documents` | Motor de plantillas: modelo de cuadrícula y lienzo (`layout.py`, `canvas.py`), cálculo (`engine.py`), PDF propio (`layout_pdf.py`), Excel (`layout_xlsx.py`), importación segura de Excel (`xlsx_import.py`), plantillas de «Tipos de documento» (`templates.py`). |
| `backend/pospy/printing` | Impresoras de Windows (`printers.py`), comprobante ESC/POS (`escpos.py`) e impresión directa de plantillas por GDI (`gdi.py`). |
| `backend/pospy/integrations` | OneDrive, Google Drive y carpeta de red para el inventario. |
| `backend/pospy/migrations` | Migraciones versionadas (ver abajo). |
| `frontend/src` | `api/` (cliente HTTP), `context/` (sesión, inventario, preferencias, tema), `pages/` por módulo, `components/ui/`, `lib/` (modelos puros probados con Vitest), `styles/` (tokens CSS). |
| `frontend/e2e` | Pruebas de extremo a extremo con navegador real contra el servidor real. |
| `desktop/` | Envoltura Tauri v2 (Rust) que arranca el servidor empaquetado con PyInstaller. |
| `scripts/` | Empaquetado del backend, iconos, licencias de terceros y prueba de grupos por túnel. |

## Decisiones

| Tema | Decisión |
|---|---|
| Reglas de negocio | Solo en el backend; la interfaz no calcula totales ni decide permisos. |
| Persistencia | SQLite en modo WAL, `BEGIN IMMEDIATE`, claves foráneas, un único proceso. |
| Dinero | Enteros en centavos y cantidades en milésimas con `Decimal` (HALF_UP); la API envía importes como texto. |
| Inventario | La existencia es la suma de movimientos; un trigger impide modificarla de otra forma. |
| Contabilidad | Asiento de partida doble por operación; asientos inmutables con reversos enlazados. |
| Idempotencia | `Idempotency-Key` en ventas, devoluciones, cobros, pagos, movimientos y asientos. |
| Multinventario | Cada inventario tiene dueño (administrador) y grupo; productos, ventas, documentos y plantillas llevan `inventory_id`; la cabecera `X-Inventory` elige el inventario y los permisos efectivos son los del usuario **y** los del inventario. |
| Tiempo real | SSE (`/api/realtime/stream`) con revalidación periódica de la sesión. |
| Documentos | Motor propio sin Microsoft Excel: PDF, Excel e impresión directa con la misma geometría. |
| Apariencia | Tokens CSS semánticos (`styles/tokens.css`) + tema del negocio derivado de 12 colores (`lib/theme.ts`). |

## Base de datos (migraciones)

Se aplican al arrancar, una sola vez y en orden (`schema_migrations`). Las que reconstruyen tablas referenciadas se
ejecutan con las claves foráneas desactivadas y se verifican después.

| Versión | Cambio |
|---|---|
| 1–2 | Esquema inicial y datos base (plan de cuentas, métodos de pago, numeración, tipos de documento). |
| 3 | Acceso configurable y sesiones de acceso directo. |
| 4–6 | Proveedores, informes financieros guardados, observaciones de inventario. |
| 7–10 | Grupos de trabajo, notas y tareas personales, columnas del inventario, tareas por grupo. |
| 11, 13 | Inventario por grupo (11) reemplazado por inventarios por administrador asociados a grupos (13). |
| 12, 14 | Plantillas de impresión; impresora por plantilla, modo de impresión «directa», descuento máximo 20 %. |
| 15 | Equipos autorizados (`devices`, `sessions.device_id`). |

Tablas protegidas por triggers: `audit_log` (sin UPDATE/DELETE), versiones de plantillas y documentos emitidos
(inmutables), existencias (solo por movimientos).

## API

- Base `/api`; documentación interactiva en `/api/docs` **solo desde el equipo servidor**.
- Toda operación que modifica datos exige la cabecera `X-Requested-With: pos-py` (CSRF) y una sesión válida.
- Errores con forma `{error, detail, fields}`; los importes viajan como texto decimal.
- Rutas públicas (sin sesión): salud, estado de instalación, instalación (solo local), ingreso y salida, apariencia de
  la pantalla de ingreso, política y desafío de equipos y solicitud de autorización de equipo. Todo lo demás exige
  sesión (lo verifica `tests/test_security.py` recorriendo el OpenAPI).

## Módulos

Documentación técnica por módulo en [modulos/](modulos/): inventarios, grupos de trabajo, columnas y tareas de grupo,
notas y tareas, observaciones de inventario, proveedores, informes financieros, plantillas e impresión, apariencia.
Seguridad, roles y equipos autorizados en [seguridad.md](seguridad.md).

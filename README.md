# POS-PY

Punto de venta y control de inventario para pequeñas empresas: ventas, inventario por administrador y grupo de
trabajo, cotizaciones y órdenes con plantillas propias, impresión en cualquier impresora de Windows, finanzas de
gestión, tareas y permisos por usuario.

Funciona como **aplicación web / PWA** o como **aplicación de escritorio para Windows**. Ambas comparten la misma
interfaz (React) y el mismo servidor (Python), que concentra toda la lógica de negocio. Los datos se guardan en el
propio equipo (SQLite); no requiere servidor de base de datos.

## Funcionalidades

- **Ventas (POS)**: lectura de código, carrito, descuentos con permiso y máximo configurable, pagos combinados, crédito,
  anulaciones y devoluciones parciales con reingreso al inventario.
- **Inventario**: varios inventarios por administrador, cada uno asociado a un grupo de trabajo, con permisos por
  integrante; entradas, salidas y ajustes con historial inmutable, costo promedio, alertas, importación y exportación
  Excel/CSV, columnas personalizables, observaciones con seguimiento y sincronización en tiempo real entre equipos.
- **Documentos e impresión**: cotizaciones y órdenes; plantillas importadas de Excel o diseñadas en cuadrícula o en un
  editor visual (arrastrar y soltar, en milímetros); PDF, Excel e **impresión directa en cualquier impresora de
  Windows**, sin Microsoft Excel.
- **Finanzas**: partida doble automática, libros, balances, flujo de caja, cartera, conciliación e informes de ingresos.
- **Gestión**: usuarios y permisos, grupos de trabajo con invitación por enlace, tareas y notas, clientes, proveedores
  (expediente completo), copias de seguridad, historial de actividad, apariencia (paleta de colores y pantalla de
  ingreso) y **equipos autorizados**.
- **Integraciones**: inventario desde OneDrive, Google Drive o carpeta de red.

## Tecnologías

| Parte | Tecnología |
|---|---|
| `backend/` | Python 3.12+, FastAPI, Uvicorn, SQLite, openpyxl, cryptography, pywin32 (Windows) |
| `frontend/` | React 18, TypeScript, Vite, vite-plugin-pwa, React Router, Vitest, Playwright (E2E) |
| `desktop/` | Tauri v2 (Rust); el servidor se empaqueta con PyInstaller |

Arquitectura resumida: la interfaz llama a la API (`/api`), el servidor valida identidad, equipo, permisos e
inventario en cada operación y guarda en SQLite (WAL, transacciones, auditoría inmutable). Detalle en
[docs/developer/arquitectura.md](docs/developer/arquitectura.md).

## Requisitos

- Usuarios: Windows 10/11 (el instalador incluye todo; WebView2 se descarga si falta).
- Desarrollo: Python 3.12+ y Node.js 20+ (Rust y MSVC solo para compilar el escritorio).

## Instalación y ejecución

```powershell
cd backend;  python -m venv .venv; .venv\Scripts\python.exe -m pip install -r requirements-dev.txt
cd ..\frontend; npm ci; npm run build
cd ..; .\iniciar.cmd            # servidor + interfaz en http://127.0.0.1:8000
```

La primera vez se abre el **asistente de configuración** (solo desde el propio equipo, con un código de un solo uso
guardado en `<datos>\setup-code.txt`; en el escritorio se completa solo). No hay usuarios por defecto.

Configuración (variables `POS_*`, red local con HTTPS, integraciones), desarrollo con recarga, pruebas y compilación
del escritorio: [docs/developer/desarrollo.md](docs/developer/desarrollo.md).

## Pruebas

```powershell
cd backend;  .venv\Scripts\python.exe -m pytest; .venv\Scripts\python.exe -m ruff check pospy tests
cd ..\frontend; npm run lint; npm test; npm run build; node e2e/smoke.mjs
```

El CI (GitHub Actions) ejecuta además Bandit, pip-audit, `npm audit` y gitleaks.

## Seguridad

Contraseñas con scrypt, sesiones con cookie `HttpOnly`/`SameSite=Strict`, protección CSRF, límites de intentos,
autorización en el servidor por permiso, inventario y propiedad, **restricción opcional por equipo** (clave
criptográfica del equipo aprobada por un administrador), auditoría inmutable y cabeceras de seguridad. Política y
reporte de vulnerabilidades: [SECURITY.md](SECURITY.md). Detalle técnico y última auditoría interna:
[docs/developer/seguridad.md](docs/developer/seguridad.md).

## Documentación técnica

[docs/developer/](docs/developer/README.md): arquitectura, desarrollo, seguridad, informe de auditoría, licencias de
terceros y documentación por módulo.

## Estado y limitaciones

Proyecto en uso y desarrollo activo (ramas `Beta` → `Principal`).

- **No emite facturación electrónica DIAN**: el comprobante de venta es un documento interno.
- Contabilidad de gestión con un plan de cuentas de ejemplo (PUC); no sustituye la contabilidad oficial.
- Sin lotes ni seriales. Vender y guardar requieren conexión con el servidor (sin conexión solo se consulta el catálogo).
- Sin autenticación de dos factores. El instalador no está firmado y no hay actualización automática.
- Las integraciones con OneDrive y Google Drive se probaron con respuestas simuladas, no con cuentas reales.

## Licencia

© 2026 Café Con Alejo ([AlejandroDukesini](https://github.com/AlejandroDukesini)). Distribuido bajo
[Creative Commons Atribución-NoComercial 4.0 Internacional (CC BY-NC 4.0)](https://creativecommons.org/licenses/by-nc/4.0/deed.es);
ver [`LICENSE`](LICENSE). Toda copia o adaptación debe dar crédito al autor, enlazar la licencia e indicar los cambios;
no se permite el uso comercial (para usos comerciales, contacte al autor). Licencias de terceros:
[docs/developer/licencias-terceros.md](docs/developer/licencias-terceros.md).

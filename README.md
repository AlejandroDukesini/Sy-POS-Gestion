# POS-PY

Punto de venta y control de inventario para pequeñas empresas: ventas, entradas y salidas,
cotizaciones y órdenes generadas desde plantillas de Excel, impresión en impresoras térmicas,
finanzas de gestión y permisos por usuario.

Se usa como **aplicación web / PWA** o como **aplicación de escritorio para Windows**. Ambas
comparten la misma interfaz (React) y el mismo backend (Python), que concentra toda la lógica de
negocio. Los datos se guardan localmente en SQLite; no requiere internet ni servidor de base de datos.

## Funcionalidades

- **Inventario**: productos con precio, costo, IVA y existencia mínima; entradas (contado, crédito,
  inventario inicial), salidas, ajustes por conteo, costo promedio ponderado, historial por
  movimiento, alertas de existencias bajas, importación con vista previa y exportación Excel/CSV.
- **Ventas (POS)**: lectura de código, carrito, descuentos con permiso y límite, pagos combinados,
  venta a crédito, anulaciones y devoluciones parciales con reingreso al inventario.
- **Documentos**: tipos configurables (cotizaciones, órdenes, etc.) generados sobre la plantilla de
  Excel original, con vista previa, descarga, reimpresión y paso a venta.
- **Finanzas**: partida doble automática, libro diario y mayor, balance de prueba, balance general,
  flujo de caja, punto de equilibrio, cuentas por cobrar y por pagar, conciliación bancaria.
- **Gestión**: usuarios (administrador o empleado con permisos asignables), clientes, proveedores,
  categorías, métodos de pago, empresa, copias de seguridad con verificación y restauración,
  historial de actividad.
- **Integraciones**: sincronización de inventario desde OneDrive, Google Drive o una carpeta de red.
- **Preferencias por usuario**: tema, tamaño de texto, densidad, alto contraste, animaciones reducidas.

### Limitaciones

- **No emite facturación electrónica DIAN.** El comprobante de venta es un documento interno.
- Es contabilidad de gestión con un plan de cuentas de ejemplo basado en el PUC; no sustituye la
  contabilidad oficial (sin retenciones automáticas, cierres de periodo ni información exógena).
- Una sola sede y bodega; sin lotes ni seriales.
- Vender y guardar requieren conexión con el backend (la PWA solo permite consultar el catálogo sin conexión).
- La impresión ESC/POS (DIGITALPOS) y las integraciones con OneDrive y Google Drive se probaron con
  impresoras y respuestas simuladas, no con equipos o cuentas reales.
- El instalador no está firmado y no hay actualización automática.

## Tecnologías

| Parte | Tecnología |
|---|---|
| `backend/` | Python ≥ 3.12, FastAPI, Uvicorn, SQLite, openpyxl, cryptography, pywin32 (Windows) |
| `frontend/` | React 18, TypeScript, Vite, vite-plugin-pwa, React Router, Vitest |
| `desktop/` | Tauri v2 (Rust); el backend se empaqueta con PyInstaller |
| `scripts/` | Empaquetado del backend y generación de iconos |

---

## Para usuarios finales (aplicación de escritorio)

**Requisitos**: Windows 10/11. Opcional: Microsoft Excel (impresión directa de plantillas y
plantillas con imágenes o gráficos) y el controlador de la impresora térmica.

1. Ejecute el instalador:
   - `POS-PY_<versión>_x64-setup.exe` (NSIS): instalación por usuario, sin permisos de administrador.
   - `POS-PY_<versión>_x64_es-ES.msi`: para despliegue corporativo.

   Si falta WebView2, el instalador lo descarga. No hace falta instalar Python.
2. Abra POS-PY y cree el usuario administrador. En el escritorio el código de instalación se
   completa automáticamente.
3. Configure la empresa, el IVA, la impresión y los usuarios en **Gestión**.

**Datos**: `%APPDATA%\com.pospy.app\data`. Desinstalar no los borra.

**Actualizar**: cree una copia en *Gestión › Copias de seguridad* e instale la versión nueva encima
de la anterior. Las migraciones se aplican al arrancar.

**Impresora térmica**: instale su controlador en Windows, escriba el nombre exacto en
*Gestión › Impresión* y use «Imprimir página de prueba».

---

## Para desarrolladores

### Requisitos

- Python 3.12 o superior
- Node.js 20 o superior
- Solo para compilar el escritorio: Rust estable y Visual Studio Build Tools (MSVC)

La versión web también funciona en Linux/macOS, sin impresión directa ni Excel COM.

### Instalación

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

cd ..\frontend
npm ci
```

### Ejecución

Desarrollo con recarga en caliente (dos terminales):

```powershell
cd backend;  .venv\Scripts\python.exe -m pospy   # API en http://127.0.0.1:8000 (documentación: /api/docs)
cd frontend; npm run dev                          # interfaz en http://localhost:5173 (reenvía /api al backend)
```

Producción web (un solo proceso sirve la API y la interfaz compilada):

```powershell
cd frontend; npm run build
cd ..\backend; .venv\Scripts\python.exe -m pospy  # http://127.0.0.1:8000
```

`python -m pospy` acepta `--host`, `--port`, `--data-dir` y `--web-dist`, equivalentes a las variables de entorno.

### Primer administrador

No hay usuarios por defecto ni registro público.

1. Al arrancar sin usuarios, el backend crea un código de un solo uso en
   `<carpeta de datos>\setup-code.txt`.
2. Abra la aplicación **desde el mismo equipo**, escriba el código y cree el administrador.

Herramientas de consola (desde `backend/`):

```powershell
.venv\Scripts\python.exe -m pospy.cli create-admin
.venv\Scripts\python.exe -m pospy.cli reset-password <usuario>   # genera una contraseña temporal
.venv\Scripts\python.exe -m pospy.cli status
.venv\Scripts\python.exe -m pospy.cli backup
```

### Configuración

Variables de entorno del backend:

| Variable | Uso | Predeterminado |
|---|---|---|
| `POS_DATA_DIR` | Carpeta de datos (base, copias, plantillas, documentos, registros) | `backend/data` |
| `POS_HOST` / `POS_PORT` | Dirección y puerto de escucha | `127.0.0.1` / `8000` |
| `POS_WEB_DIST` | Carpeta de la interfaz compilada | `frontend/dist` |
| `POS_SECURE_COOKIES` | `1` = cookie de sesión solo por HTTPS | `0` |
| `POS_CORS_ORIGINS` | Orígenes permitidos, separados por comas, si la interfaz se sirve desde otro origen | vacío |
| `POS_MASTER_KEY` | Clave para cifrar credenciales fuera de Windows (en Windows se usa DPAPI) | vacío |
| `POS_SETUP_CODE` | Código de instalación inyectado (lo usa el escritorio) | vacío |

La configuración del negocio (empresa, IVA, impresión, sesiones, copias, integraciones) se hace
desde **Gestión** y se guarda en la base de datos. Los secretos se guardan cifrados y nunca se
envían a la interfaz.

**Red local**: por defecto solo escucha en el propio equipo. Para usarlo desde otros equipos,
publíquelo detrás de un proxy inverso con HTTPS, con `POS_HOST=0.0.0.0` solo en una red de
confianza y `POS_SECURE_COOKIES=1`. Use un único proceso y no ponga la base SQLite en una carpeta de red.

### Pruebas

```powershell
cd backend
.venv\Scripts\python.exe -m pytest
.venv\Scripts\ruff.exe check pospy tests

cd ..\frontend
npm run lint
npm run typecheck
npm test
npm run build; npm run e2e   # navegador real contra el servidor real
```

`npm run e2e` arranca un servidor con datos temporales. Variables: `PYTHON` (intérprete con las
dependencias del backend), `BROWSER` (`msedge` o `chrome`, predeterminado `msedge`), `SHOTS`
(carpeta de capturas).

### Compilar la aplicación de escritorio

```powershell
cd frontend; npm ci; npm run build
cd ..; backend\.venv\Scripts\python.exe scripts\build_backend.py   # genera desktop\src-tauri\binaries\pospy-server-<triple>.exe
cd desktop; npm ci; npm run build                                 # instaladores en desktop\src-tauri\target\release\bundle\
```

La ventana de Tauri arranca el backend empaquetado en un puerto libre de `127.0.0.1` y lo detiene
al cerrarse; una segunda apertura enfoca la ventana existente.

Nombre e identificador: `productName` e `identifier` en `desktop/src-tauri/tauri.conf.json`.
Icono: reemplace `desktop/src-tauri/app-icon.png` (1024×1024) y ejecute `npm run icons` en `desktop/`,
o `python scripts/make_icons.py "#color"` para regenerar los iconos de la PWA y del escritorio.

### Arquitectura

| Tema | Decisión |
|---|---|
| Reglas de negocio | Solo en el backend (`backend/pospy/services`); la interfaz no calcula totales ni decide permisos. |
| Persistencia | SQLite en modo WAL, transacciones `BEGIN IMMEDIATE`, claves foráneas. |
| Dinero | Enteros en centavos y cantidades en milésimas, con `Decimal` (HALF_UP). La API envía importes como texto (`"1234.50"`). |
| Inventario | La existencia es la suma de movimientos; un trigger impide modificarla de otra forma. |
| Contabilidad | Asiento de partida doble por cada operación; asientos inmutables con reversos enlazados. |
| Idempotencia | Cabecera `Idempotency-Key` en ventas, devoluciones, cobros, pagos, movimientos y asientos. |
| Sesión | Cookie `HttpOnly; SameSite=Strict`, token guardado como hash, protección CSRF por cabecera. |

Detalle de las reglas contables y de autoridad sobre existencias: cabeceras de
`backend/pospy/services/ledger.py` y `backend/pospy/services/sync.py`.

---

## Integraciones de inventario

*Gestión › Integraciones*. Por defecto POS-PY es la autoridad sobre las existencias y ninguna fuente
las sobrescribe. Una conexión puede marcarse como **fuente maestra**: con la política «ajustar» las
diferencias se registran como movimientos de conciliación; con «informar» solo se reportan. Toda
sincronización manual pasa por vista previa, y aplicarla exige que el archivo no haya cambiado (SHA-256).

**OneDrive (Microsoft Entra ID)**: registre una aplicación › Autenticación › plataforma
«Aplicaciones móviles y de escritorio» con URI de redirección `http://localhost` › permisos delegados
de Microsoft Graph `Files.Read` y `offline_access`. Copie el *Id. de aplicación (cliente)* en
*Gestión › Integraciones › Credenciales*. No necesita secreto.

**Google Drive (Google Cloud Console)**: habilite «Google Drive API», configure la pantalla de
consentimiento OAuth (con usuarios de prueba mientras no esté verificada) y cree un ID de cliente
OAuth de tipo «App de escritorio». Copie el Id. y el secreto en *Gestión › Integraciones*. El
permiso `drive.readonly` es restringido: fuera de los usuarios de prueba, Google exige verificar la aplicación.

**Carpeta de red**: rutas UNC; la cuenta de Windows que ejecuta POS-PY necesita permiso de lectura.

## Plantillas de documentos

*Gestión › Tipos de documento › (tipo) › Plantilla*. Use su propio Excel y escriba marcadores:

- Encabezado: `{{numero}}`, `{{fecha}}`, `{{fecha_validez}}`, `{{cliente_nombre}}`, `{{cliente_identificacion}}`,
  `{{subtotal}}`, `{{descuento}}`, `{{iva}}`, `{{total}}`, `{{vendedor}}`, `{{empresa_nombre}}`, `{{empresa_nit}}`,
  y los campos adicionales del tipo como `{{extra.clave}}`. Pueden ir dentro de un texto: `Cotización N° {{numero}}`.
- Primera fila de productos: `{{linea.n}}`, `{{linea.codigo}}`, `{{linea.descripcion}}`, `{{linea.cantidad}}`,
  `{{linea.precio}}`, `{{linea.descuento}}`, `{{linea.iva_pct}}`, `{{linea.total}}`.

«Descargar plantilla base» entrega un ejemplo con todos los marcadores disponibles. La plantilla
original nunca se modifica; si deja de coincidir con el mapeo, la generación se detiene y lista los
problemas. Las plantillas con imágenes, gráficos o formas requieren Microsoft Excel (COM), porque
openpyxl no las conserva.

## Seguridad

- Los permisos se validan en el backend en cada operación; la interfaz solo oculta lo no autorizado.
- La instalación inicial exige el código de un solo uso y solo se acepta desde el propio equipo.
  Detrás de un proxy inverso local todas las peticiones parecen locales: cree el administrador antes de publicar.
- Auditoría inmutable que excluye contraseñas, tokens y secretos.
- Las copias de seguridad contienen datos del negocio: guárdelas en un medio con acceso restringido.
- Los permisos no protegen contra quien tenga acceso directo al archivo de la base: proteja la cuenta
  de Windows y use cifrado de disco (BitLocker).

## Licencia

© 2026 Café Con Alejo ([AlejandroDukesini](https://github.com/AlejandroDukesini)). Distribuido bajo
[Creative Commons Atribución-NoComercial 4.0 Internacional (CC BY-NC 4.0)](https://creativecommons.org/licenses/by-nc/4.0/deed.es).
Ver [`LICENSE`](LICENSE).

- **Atribución**: toda copia, redistribución o adaptación debe dar crédito al autor, enlazar la
  licencia e indicar si se hicieron cambios.
- **No comercial**: no se permite su uso con fines comerciales.

Para usos comerciales, contacte al autor.

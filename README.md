# POS-PY

Punto de venta y control de entradas y salidas para empresas: inventario, ventas, cotizaciones y
órdenes con plantillas de Excel, impresión (DIGITALPOS), finanzas de gestión y administración, con
permisos reales por usuario.

Funciona como **aplicación web / PWA** (React) y como **aplicación de escritorio para Windows**
(Tauri). Ambas usan la misma interfaz y el mismo backend Python, que concentra toda la lógica de
negocio.

```
frontend/  React 18 + Vite + TypeScript (PWA). Solo presentación: los totales, permisos y reglas los decide el backend.
backend/   Python 3.13 + FastAPI + SQLite. Lógica de negocio, transacciones, permisos, auditoría, integraciones e impresión.
desktop/   Tauri v2 (Rust). Ventana de Windows que arranca el backend empaquetado (pospy-server.exe) y lo detiene al salir.
scripts/   Empaquetado del backend (PyInstaller) y generación de iconos.
```

## Arquitectura y decisiones

| Tema | Decisión | Por qué |
|---|---|---|
| Backend | FastAPI + servicios Python (`backend/pospy/services`) | API documentada (`/api/docs`) y validada (Pydantic), sin duplicar reglas en React. |
| Persistencia | SQLite local (modo WAL, `BEGIN IMMEDIATE`, claves foráneas) | Funciona sin internet ni servidor de base de datos; las copias son un único archivo verificable. |
| Dinero | Enteros en centavos, cantidades en milésimas, cálculo con `Decimal` (HALF_UP) | Sin errores de punto flotante. La API envía importes como texto decimal (`"1234.50"`). |
| Inventario | Existencia = suma de movimientos; un trigger impide cambiarla de otra forma | Trazabilidad completa: ninguna edición borra historial. |
| Contabilidad | Partida doble automática por cada operación; asientos inmutables con reversos enlazados | Los informes se derivan de registros reales. |
| Idempotencia | `Idempotency-Key` en ventas, devoluciones, cobros, pagos, movimientos y asientos | Un doble clic o un reintento de red no duplica operaciones. |
| Sesión | Cookie `HttpOnly; SameSite=Strict`, token aleatorio guardado como hash, CSRF por cabecera | JavaScript nunca ve el token. |
| Escritorio | Tauri abre `http://127.0.0.1:<puerto>` servido por el backend empaquetado | La misma interfaz y API que la web; sin IPC ni lógica en Rust. |

Reglas contables y de inventario detalladas: `backend/pospy/services/ledger.py` (cabecera) y
`backend/pospy/services/sync.py` (autoridad sobre existencias).

## Requisitos

* Windows 10/11 (la web también funciona en Linux/macOS sin impresión directa ni Excel COM).
* Python 3.12 o superior (verificado con 3.13).
* Node.js 20 o superior (verificado con 24).
* Solo para compilar el escritorio: Rust estable (verificado con 1.99; Tauri 2.12) y las Build Tools de Visual Studio (MSVC).
* Opcional: Microsoft Excel (para imprimir directamente y exportar a PDF las plantillas, y para plantillas con imágenes o gráficos).

## Instalación para desarrollo

```powershell
# Backend
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

# Frontend
cd ..\frontend
npm ci
```

Desarrollo con recarga en caliente (dos terminales):

```powershell
cd backend;  .venv\Scripts\python.exe -m pospy            # API en http://127.0.0.1:8000 (docs: /api/docs)
cd frontend; npm run dev                                   # interfaz en http://localhost:5173 (reenvía /api)
```

Producción web (un solo proceso sirve API + interfaz):

```powershell
cd frontend; npm run build
cd ..\backend; .venv\Scripts\python.exe -m pospy            # http://127.0.0.1:8000
```

## Primer uso: administrador inicial

No hay usuarios ni contraseñas por defecto en el repositorio, ni registro público.

1. Al arrancar sin usuarios, el backend crea un **código de instalación de un solo uso** en
   `<carpeta de datos>\setup-code.txt` (también lo indica el registro).
2. Abra la aplicación **desde el mismo equipo** (la instalación inicial se rechaza desde otros
   equipos), escriba el código y cree el administrador. El archivo se elimina al terminar.
3. Alternativa por consola: `.venv\Scripts\python.exe -m pospy.cli create-admin`.

En la aplicación de escritorio el código lo genera Tauri y se completa solo.

Recuperación de acceso desde el equipo: `python -m pospy.cli reset-password <usuario>` (contraseña
temporal), `python -m pospy.cli status`, `python -m pospy.cli backup`.

## Variables de entorno (backend)

| Variable | Uso | Predeterminado |
|---|---|---|
| `POS_DATA_DIR` | Carpeta de datos: base, copias, plantillas, documentos, registros | `backend/data` |
| `POS_HOST` / `POS_PORT` | Dirección de escucha | `127.0.0.1` / `8000` |
| `POS_WEB_DIST` | Interfaz compilada | `frontend/dist` |
| `POS_SECURE_COOKIES` | `1` = cookie solo por HTTPS (obligatorio detrás de un proxy TLS) | `0` |
| `POS_CORS_ORIGINS` | Orígenes permitidos si la interfaz se sirve desde otro origen | vacío |
| `POS_MASTER_KEY` | Clave para cifrar credenciales fuera de Windows (en Windows se usa DPAPI) | vacío |
| `POS_SETUP_CODE` | Código de instalación inyectado (lo usa el escritorio) | vacío |

Toda la configuración de negocio (empresa, IVA, impresión, sesiones, copias, integraciones) se hace
desde la aplicación, en **Gestión**, y se guarda en la base de datos. Los secretos (tokens OAuth,
secreto del cliente de Google) se guardan **cifrados** (DPAPI de Windows / Fernet) y nunca se envían
a la interfaz.

### Red local

Por defecto solo escucha en el propio equipo. Para usarlo desde otros equipos publíquelo detrás de
un proxy inverso con HTTPS (IIS, Caddy, nginx), con `POS_HOST=0.0.0.0` solo en una red de confianza
y `POS_SECURE_COOKIES=1`. Un único proceso (`workers=1`); SQLite no debe ponerse en una carpeta de red.

## Módulos

### Funcionan completamente (con pruebas automatizadas)

| Módulo | Qué hace |
|---|---|
| Autenticación y permisos | Usuarios ilimitados con rol administrador o empleado; 16 permisos asignables a empleados; los de administración (usuarios, configuración, integraciones, respaldos, auditoría) nunca se asignan a empleados. Contraseñas scrypt, bloqueo tras intentos fallidos, sesiones con inactividad y duración máxima, revocación al cambiar permisos. Validación en el backend de cada operación. |
| Inventario | Productos (código, descripción, precio con y sin descuento, costo, IVA, mínimo), búsqueda, filtros, orden, paginación, alertas de existencias bajas, entradas (de contado, a crédito con cuenta por pagar, inventario inicial, sobrante), salidas (merma, consumo), ajustes por conteo, costo promedio ponderado, historial con fecha, usuario y motivo, exportación Excel/CSV, importación con vista previa. |
| Ventas (POS) | Búsqueda o lectura de código, carrito, descuentos (con permiso y límite), IVA incluido o no, pagos combinados, cambio, venta a crédito (cuenta por cobrar, no ingreso de caja), validación de existencias, confirmación, idempotencia, historial, anulación y devoluciones parciales con reingreso al inventario y reversos contables. |
| Cotizaciones, órdenes y otros documentos | Tipos ilimitados configurables (nombre, plantilla, campos adicionales, numeración, vigencia, impresora, página, estado) con estadísticas de uso. Generación respetando la plantilla de Excel original (formato, bordes, celdas combinadas, fórmulas, encabezados y pies). Vista previa, descarga, reimpresión y paso a venta. |
| Finanzas | BS (con comparación), BEP (contable y calculadora), CF (por concepto, comparación con el periodo anterior y proyección por CxC/CxP), ACC (libro diario, mayor, balance de prueba, asientos manuales, gastos, reversos, conciliación bancaria, plan de cuentas, verificaciones cruzadas), AP y AR (abonos parciales, anulaciones, antigüedad, alertas). Si faltan datos, el informe lo dice; no inventa cifras. |
| Gestión | Usuarios, clientes, proveedores, categorías, tipos de documento, métodos de pago, parámetros, empresa y logotipo, sesiones, copias de seguridad (crear, verificar, descargar, cargar, restaurar con copia previa automática), historial de actividad y reportes operativos. |
| Preferencias personales | Tema claro/oscuro/sistema, tamaño de texto (16 a 22 px), densidad, animaciones reducidas, alto contraste, enlaces subrayados, menú compacto, impresora preferida. Se guardan por usuario en el servidor. |
| PWA | Manifiesto, iconos, service worker, actualización a elección del usuario, catálogo consultable sin conexión; vender y guardar exigen conexión (no hay cola fuera de línea, para evitar conflictos). |
| Escritorio Windows | Instalador NSIS y MSI, backend empaquetado sin Python instalado, datos en `%APPDATA%\com.pospy.app\data`, una sola instancia, cierre coordinado. |

### Requieren configuración externa

| Módulo | Estado | Qué hace falta |
|---|---|---|
| Impresión directa en DIGITALPOS | Implementada (ESC/POS RAW por `win32print`, ancho 58/76/80 mm, corte, cajón). Probada con impresoras simuladas; **no se probó con una DIGITALPOS física**, porque no hay una instalada en el equipo de desarrollo. | Instalar el controlador de la impresora en Windows y escribir su nombre en Gestión › Impresión. Usar «Imprimir página de prueba». |
| Impresión de plantillas sin diálogos | Implementada mediante Microsoft Excel (COM), con impresora, papel, orientación, márgenes y escala del tipo de documento. | Microsoft Excel instalado en el equipo del backend. Sin Excel se usa el diálogo de impresión del navegador. |
| OneDrive | Implementado con Microsoft Graph, OAuth 2.0 + PKCE y permisos `Files.Read offline_access`. Probado con respuestas simuladas, **no contra una cuenta real**. | Registrar una aplicación en Microsoft Entra (ver abajo). |
| Google Drive | Implementado con Drive API v3, OAuth 2.0 + PKCE y permiso `drive.readonly`; exporta hojas de Google a Excel. Probado con respuestas simuladas. | Crear un cliente OAuth «Aplicación de escritorio» en Google Cloud (ver abajo). |
| Carpeta de red | Implementada (rutas UNC). | La cuenta de Windows que ejecuta POS-PY debe tener permiso de lectura en la carpeta. |

### Pendiente o fuera de alcance

* **Facturación electrónica DIAN**: no implementada. El comprobante de venta es un documento
  interno y lo indica así. Si la empresa está obligada a facturar electrónicamente, debe hacerlo
  con un proveedor tecnológico autorizado.
* **Contabilidad oficial**: es contabilidad de gestión con un plan de cuentas de ejemplo basado en
  el PUC. No se afirma cumplimiento de normas contables o tributarias colombianas; revísela con su
  contador. Sin retenciones automáticas, cierres de periodo ni información exógena.
* Varias sucursales o bodegas, lotes y seriales.
* Ventas sin conexión con sincronización posterior (deliberadamente excluidas: se pueden duplicar o entrar en conflicto con las existencias).
* Revisión manual con lectores de pantalla (NVDA o Narrador): no se ha hecho; las pruebas cubren etiquetas, roles y contraste.
* Firma de código del instalador y actualización automática del escritorio. Actualizar se hace instalando la versión nueva encima de la anterior.

## Integraciones de inventario

Gestión › Integraciones. La **autoridad sobre las existencias** es explícita:

* Por defecto manda POS-PY: la existencia es la suma de movimientos y ninguna fuente la sobrescribe.
* Una conexión puede ser la única **fuente maestra**. Solo si su política es «ajustar», las
  diferencias se registran como movimientos de *conciliación* (con historial y asiento).
* Con «informar», las diferencias solo se reportan.
* El costo de productos existentes siempre lo calcula POS-PY.
* Toda sincronización manual pasa por vista previa; aplicar exige que el archivo no haya cambiado
  desde la vista previa (SHA-256). La sincronización automática por intervalo aplica la política
  configurada y deja cada proceso en el historial.
* Importar un archivo desde Inventario es una operación única, no una sincronización.

**OneDrive (Microsoft Entra)**: portal de Azure › Microsoft Entra ID › Registros de aplicaciones ›
Nuevo registro → tipo de cuenta según su caso (personal: `consumers`; empresarial: su inquilino) →
Autenticación › Agregar plataforma «Aplicaciones móviles y de escritorio» con URI de redirección
`http://localhost` → Permisos de API: Microsoft Graph delegados `Files.Read` y `offline_access`.
Copie el *Id. de aplicación (cliente)* en Gestión › Integraciones › Credenciales. No necesita secreto.

**Google Drive (Google Cloud Console)**: cree un proyecto → habilite «Google Drive API» → Pantalla
de consentimiento OAuth (agregue los usuarios de prueba mientras no esté verificada) → Credenciales ›
Crear ID de cliente OAuth › «App de escritorio». Copie el Id. y el secreto en Gestión › Integraciones.
El permiso `drive.readonly` es restringido: para uso fuera de los usuarios de prueba, Google exige
verificación de la aplicación.

La autorización usa el navegador y vuelve a `http://localhost:<puerto>/api/integrations/oauth/callback`
(Microsoft) o `http://127.0.0.1:<puerto>/…` (Google), atendida por el propio backend local.

## Plantillas de documentos

Gestión › Tipos de documento › (tipo) › Plantilla. Use su Excel tal como está y escriba marcadores:

* Encabezado: `{{numero}}`, `{{fecha}}`, `{{fecha_validez}}`, `{{cliente_nombre}}`, `{{cliente_identificacion}}`,
  `{{cliente_telefono}}`, `{{cliente_email}}`, `{{cliente_direccion}}`, `{{observaciones}}`, `{{subtotal}}`,
  `{{descuento}}`, `{{base}}`, `{{iva}}`, `{{total}}`, `{{vendedor}}`, `{{empresa_nombre}}`, `{{empresa_nit}}`, … y
  los campos adicionales del tipo como `{{extra.clave}}`. Pueden ir dentro de un texto: `Cotización N° {{numero}}`.
* Primera fila de productos: `{{linea.n}}`, `{{linea.codigo}}`, `{{linea.descripcion}}`, `{{linea.cantidad}}`,
  `{{linea.precio}}`, `{{linea.precio_lista}}`, `{{linea.descuento}}`, `{{linea.iva_pct}}`, `{{linea.total}}`.
* También se puede asignar un campo a una celda concreta sin marcador (mapeo manual).

La plantilla original nunca se modifica. Si deja de coincidir con el mapeo (se borró un marcador o
cambió una celda), la generación se detiene con la lista de problemas en lugar de imprimir algo
incorrecto. «Descargar plantilla base» entrega un punto de partida con todos los marcadores.
Limitación de openpyxl: no conserva imágenes, gráficos ni formas; con esas plantillas se usa
Microsoft Excel (COM) automáticamente.

## Pruebas

```powershell
cd backend;  .venv\Scripts\python.exe -m pytest           # 91 pruebas: dominio, API, permisos, contabilidad, plantillas, integraciones, respaldos, ciclo de vida
             .venv\Scripts\ruff.exe check pospy tests
cd frontend; npm run lint; npm test                        # 52 pruebas: contraste AA, preferencias, cliente HTTP, ingreso, navegación por rol
             npm run build; npm run e2e                    # navegador real (Edge) contra el servidor real
```

`npm run e2e` arranca un servidor con datos temporales y recorre: instalación con código, ingreso
(dos columnas), creación de producto, entrada, estabilidad de la barra lateral, venta con cambio,
balance cuadrado, preferencias persistentes, vistas móviles sin desborde y manifiesto PWA. Variables:
`PYTHON`, `BROWSER` (`msedge` o `chrome`), `SHOTS` (carpeta de capturas).

## Compilar la aplicación de escritorio (Windows)

```powershell
cd frontend; npm ci; npm run build
cd ..; backend\.venv\Scripts\python.exe scripts\build_backend.py   # desktop\src-tauri\binaries\pospy-server-<triple>.exe
cd desktop; npm ci; npm run build                                 # instaladores en desktop\src-tauri\target\release\bundle\
```

* `nsis\POS-PY_1.0.0_x64-setup.exe`: instalación por usuario, sin permisos de administrador.
* `msi\POS-PY_1.0.0_x64_es-ES.msi`: para despliegue corporativo.
* Si falta WebView2, el instalador lo descarga.
* Verificado en Windows 11: el ejecutable arranca `pospy-server.exe` en un puerto libre de 127.0.0.1 con la carpeta de
  datos del usuario; cerrar la ventana detiene el backend; si la aplicación termina a la fuerza, el backend lo detecta
  (`--parent-pid`) y se cierra; una segunda apertura enfoca la ventana existente en lugar de iniciar otro backend.
* **Datos**: `%APPDATA%\com.pospy.app\data`. Desinstalar no los borra; elimínelos a mano solo
  después de guardar una copia.
* **Actualizar**: instale la versión nueva encima. Las migraciones se aplican solas al arrancar.
  Antes, cree una copia en Gestión › Copias de seguridad.
* **Nombre e icono**: `productName` e `identifier` en `desktop/src-tauri/tauri.conf.json`. Para el
  icono, reemplace `desktop/src-tauri/app-icon.png` (1024×1024) y ejecute `npm run icons`, o
  `python scripts/make_icons.py "#color"` para regenerar los de la PWA y el escritorio.

## Seguridad

* Permisos verificados en cada servicio del backend; la interfaz solo oculta lo no autorizado.
* Auditoría inmutable sin contraseñas, tokens ni secretos (se filtran por nombre de campo).
* CSP estricta, `X-Frame-Options: DENY`, `nosniff`, sin caché en respuestas de la API.
* Las copias contienen datos del negocio. Guárdelas cifradas o en un medio con acceso restringido.
* Instalación inicial: además de exigir el código de un solo uso que solo existe en el disco del servidor, se
  acepta únicamente desde el propio equipo. Detrás de un proxy inverso local todas las peticiones parecen
  locales, así que en ese caso la protección efectiva es el código: cree el administrador antes de publicar.
* El retorno de OAuth está fuera de la protección CSRF por ser una redirección del proveedor; lo protege un
  `state` aleatorio de un solo uso que caduca en 10 minutos, más PKCE.
* Los permisos no protegen contra alguien con acceso directo al archivo de la base: proteja la cuenta
  de Windows y use BitLocker.

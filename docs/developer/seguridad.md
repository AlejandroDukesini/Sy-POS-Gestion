# Seguridad: autenticación, roles, equipos autorizados y DevSecOps

Política de reporte de vulnerabilidades: [SECURITY.md](../../SECURITY.md). Resultado de la última auditoría:
[auditoria-seguridad-2026-11.md](auditoria-seguridad-2026-11.md).

## Autenticación y sesiones

- Contraseñas con **scrypt** (N=2¹⁴, r=8, p=1, sal aleatoria de 16 bytes por contraseña). Nunca en texto plano ni en
  el navegador. Política: 10 caracteres, letras y números, sin el nombre de usuario.
- Comparaciones en tiempo constante; si el usuario no existe se calcula un hash de igual coste y el mensaje es el mismo
  («Usuario o contraseña incorrectos»): no se pueden enumerar cuentas.
- **Bloqueo por cuenta** (5 intentos, 15 min; configurable) y **límite por origen** (20 fallos en 15 min por
  dirección → 429), registrados en la auditoría.
- Sesión: token aleatorio de 256 bits en cookie `HttpOnly; SameSite=Strict` (y `Secure` por HTTPS); en la base solo
  se guarda su SHA-256. Caduca por inactividad y por duración máxima; se revoca al cerrar sesión, al cambiar la
  contraseña (las demás sesiones), al desactivar la cuenta o al cambiar sus permisos (`session_version`).
- CSRF: toda petición que modifica datos exige `X-Requested-With: pos-py` (los formularios de otros sitios no pueden
  enviarla) además de `SameSite=Strict`.
- Instalación inicial y acceso directo (inicio de sesión desactivado): solo desde el propio equipo, sin proxy ni túnel
  (`deps.is_local`), con código de un solo uso.
- No hay MFA: se evaluó y no se implementó en esta versión (ver riesgos residuales).

## Autorización (RBAC + inventario + propiedad)

Cada operación del backend valida, en este orden: sesión válida → equipo autorizado (si la restricción está activa)
→ cambio de contraseña pendiente → permiso específico (`Actor.require`) → inventario (`scopes.check/resolve`, cabecera
`X-Inventory`) → propiedad del recurso (notas, tareas personales, ventas propias) → estado del recurso. La interfaz
solo oculta lo no permitido; **nunca** decide.

- Roles: `admin` (todos los permisos) y `employee` (solo los asignados). Los permisos marcados como exclusivos de
  administración **no pueden asignarse** a un empleado (el servidor rechaza la asignación).
- Permisos por inventario: en cada inventario el dueño decide qué puede hacer cada integrante; el efectivo es
  permiso del usuario **y** del inventario (nunca da más).
- Un administrador solo ve y administra **sus** inventarios y grupos.
- Denegación: 403 con «No tiene permiso para esta operación. Si la necesita para su trabajo, solicítela a un
  administrador.» Se registra `seguridad.acceso_denegado` (usuario, ruta, permiso). No hay autoelevación.
- Denegación por defecto verificada: `tests/test_security.py` recorre **toda** la API (OpenAPI): sin sesión todo da 401
  salvo la lista pública; un empleado con permisos por defecto solo completa la lista revisada `EMPLOYEE_OK`.

### Matriz de permisos (generada del catálogo `core/permissions.py`)

| Permiso | Qué permite | Empleado | Administrador |
|---|---|---|---|
| `inventario.ver` | Consultar inventario · por inventario | Sí, por defecto | Sí |
| `inventario.costos` | Ver costos de productos · por inventario | Si se le asigna | Sí |
| `inventario.editar` | Crear, editar y desactivar productos · por inventario | Si se le asigna | Sí |
| `inventario.movimientos` | Registrar entradas, salidas y ajustes · por inventario | Si se le asigna | Sí |
| `inventario.importar` | Importar y exportar inventario · por inventario | Si se le asigna | Sí |
| `inventario.columnas` | Administrar las columnas del inventario · por inventario | No (exclusivo de administración) | Sí |
| `observaciones.ver` | Consultar observaciones de inventario · por inventario | Sí, por defecto | Sí |
| `observaciones.crear` | Registrar observaciones y adjuntar archivos · por inventario | Sí, por defecto | Sí |
| `observaciones.editar` | Editar observaciones (datos y prioridad) · por inventario | Si se le asigna | Sí |
| `observaciones.estado` | Cambiar el estado de las observaciones · por inventario | Si se le asigna | Sí |
| `observaciones.comentar` | Comentar observaciones · por inventario | Sí, por defecto | Sí |
| `observaciones.eliminar` | Eliminar observaciones (se conserva el historial) · por inventario | Si se le asigna | Sí |
| `ventas.vender` | Registrar ventas · por inventario | Sí, por defecto | Sí |
| `ventas.descuento` | Aplicar descuentos manuales (máximo configurable, 20 % de fábrica) · por inventario | Si se le asigna | Sí |
| `ventas.historial` | Consultar historial de ventas · por inventario | Sí, por defecto | Sí |
| `ventas.anular` | Anular ventas y registrar devoluciones · por inventario | Si se le asigna | Sí |
| `documentos.ver` | Consultar cotizaciones y órdenes · por inventario | Sí, por defecto | Sí |
| `documentos.crear` | Crear cotizaciones y órdenes · por inventario | Sí, por defecto | Sí |
| `documentos.anular` | Anular cotizaciones y órdenes · por inventario | Si se le asigna | Sí |
| `documentos.imprimir` | Imprimir y reimprimir documentos · por inventario | Sí, por defecto | Sí |
| `finanzas.ver` | Consultar informes financieros | Si se le asigna | Sí |
| `finanzas.registrar` | Registrar cobros, pagos, gastos y asientos | Si se le asigna | Sí |
| `finanzas.cierres` | Guardar y revisar informes de ingresos | Si se le asigna | Sí |
| `terceros.gestionar` | Gestionar clientes y proveedores | Si se le asigna | Sí |
| `tareas.gestionar` | Crear y asignar tareas a cualquier persona | Si se le asigna | Sí |
| `gestion.usuarios` | Administrar usuarios y permisos | No (exclusivo de administración) | Sí |
| `gestion.configuracion` | Configuración, plantillas, impresión, apariencia y **equipos autorizados** | No (exclusivo de administración) | Sí |
| `gestion.integraciones` | Conexiones y sincronización de inventario | No (exclusivo de administración) | Sí |
| `gestion.respaldos` | Copias de seguridad y restauración | No (exclusivo de administración) | Sí |
| `gestion.auditoria` | Historial de actividad y reportes operativos | No (exclusivo de administración) | Sí |
| `grupos.gestionar` | Crear grupos de trabajo, inventarios e invitar empleados | No (exclusivo de administración) | Sí |

Sin permiso de auditoría, «Historial de actividad» muestra solo las operaciones propias. Cada persona gestiona sus
notas y tareas personales y ve sus propias impresiones. No existe un rol técnico o de desarrollador dentro del POS ni
cuentas por defecto: el mantenimiento se hace con las herramientas de consola en el equipo servidor.

## Equipos autorizados (restricción por dispositivo)

Objetivo: que copiar la dirección del POS y usar las credenciales desde otro computador no baste.

1. Cada equipo crea con **WebCrypto** un par de claves **ECDSA P-256**; la clave privada es **no exportable** y queda
   en IndexedDB (`frontend/src/lib/device.ts`). El servidor solo guarda la clave pública (SPKI) y su huella SHA-256.
2. Para ingresar, el equipo firma un **desafío de un solo uso** (2 minutos) emitido por el servidor
   (`POST /api/devices/challenge`); el servidor verifica la firma (`services/devices.py`, librería `cryptography`).
   Un desafío reutilizado o una firma de otra clave se rechazan.
3. Equipos nuevos: la persona solicita la autorización con sus credenciales (`POST /api/devices/request`) y queda
   **pendiente**; solo un administrador la aprueba. Un administrador puede autorizar el equipo desde el que trabaja.
4. Con la restricción activa (Gestión › Equipos autorizados), el ingreso desde un equipo no autorizado se rechaza aunque
   la contraseña sea correcta, y **cada petición** comprueba que la sesión fue abierta por un equipo que **sigue**
   autorizado: revocar un equipo cierra de inmediato sus sesiones (también el canal en tiempo real).
5. El **equipo servidor** (peticiones locales sin proxy) queda exento para que el negocio nunca quede bloqueado; para
   activar la restricción desde otro equipo, ese equipo debe estar autorizado.
6. Eventos auditados: solicitud, autorización, rechazo, revocación, renombre, activación/desactivación e ingresos
   rechazados por equipo.

No se usa IP, User-Agent ni huellas del navegador para autenticar (solo como información).

**Limitaciones (honestas):** un navegador no identifica de forma infalible un computador físico. La clave no es
exportable por la página, pero quien controle el perfil del sistema operativo podría copiar el perfil completo del
navegador; borrar los datos del navegador elimina la clave (hay que autorizar de nuevo). Requiere HTTPS en los equipos
que no son el servidor. La cookie de sesión es un portador: si se robara junto con acceso al equipo, valdría hasta que
caduque o se revoque el equipo. Para máxima garantía se recomienda, además, BitLocker y cuentas de Windows por persona.

## Entradas, archivos y salida

- Modelos de entrada estrictos (Pydantic `extra=forbid`): precios, totales o roles enviados por el cliente se rechazan;
  el servidor calcula precios, descuentos (con permiso y máximo), totales y existencias.
- SQL siempre parametrizado; nombres de columnas y órdenes de listas blancas (`core/query.py`).
- Excel importados: solo .xlsx/.xlsm, límite de tamaño descomprimido, sin rutas internas `..`, XML sin DOCTYPE ni
  entidades (anti XXE/expansión); las macros nunca se ejecutan. Textos que empiezan por `= + - @` se escriben como texto.
- Imágenes (plantillas, logotipo, pantalla de ingreso): PNG/JPEG/WEBP validados por **contenido**, tamaño y dimensiones
  máximos; SVG rechazado; nombres generados por el servidor (sin rutas del usuario).
- Cabeceras: CSP (`script-src 'self'`, `frame-ancestors 'none'`), `X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`, `Permissions-Policy`, `Cross-Origin-Opener-Policy`, HSTS bajo HTTPS, `Cache-Control: no-store` en la API.
- Secretos de integraciones cifrados (DPAPI en Windows o `POS_MASTER_KEY`); nunca se envían a la interfaz.
- Auditoría append-only (triggers) y depurada de contraseñas, tokens y secretos.

## DevSecOps

`.github/workflows/ci.yml`: Ruff, pytest (incluye autorización y equipos), Bandit (severidad alta), pip-audit, ESLint,
Vitest, build, `npm audit` y gitleaks sobre todo el historial; Dependabot semanal. Herramientas y resultados de la
auditoría en [auditoria-seguridad-2026-11.md](auditoria-seguridad-2026-11.md).

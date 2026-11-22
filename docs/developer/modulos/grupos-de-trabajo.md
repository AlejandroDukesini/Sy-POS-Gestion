> Documento técnico del módulo (estado vigente). La historia de cambios está en git; la visión general en [../README.md](../README.md).

DOCUMENTACIÓN — MÓDULO DE GRUPOS DE TRABAJO (INVITACIÓN POR ENLACE Y CONEXIÓN POR INTERNET)
POS-PY · 17-11-2026
==========================================================================================

1. DIAGNÓSTICO DE LA ARQUITECTURA EXISTENTE
------------------------------------------------------------------------------------------
- Backend: Python con FastAPI y uvicorn, en un solo proceso. La interfaz compilada se sirve en el
  mismo origen que la API (/api).
- Base de datos: SQLite (modo WAL) con migraciones versionadas (backend/pospy/migrations). Antes
  de este módulo el esquema iba en la versión 6.
- Autenticación: cuentas propias (tabla users) y contraseñas con hash. La sesión va en una cookie
  HttpOnly con SameSite=Strict, y el servidor guarda solo el hash del token (tabla sessions).
  Hay cierre por inactividad y una cabecera anti-CSRF (X-Requested-With: pos-py) en toda
  operación que modifica datos.
- Roles: admin y employee, más permisos por usuario (core/permissions.py). Ya existía un registro
  de actividad (audit_log).
- Comunicación: solo API REST. No había WebSocket, sistema de eventos ni sincronización en vivo.
- Despliegue: aplicación de escritorio (Tauri, que inicia el servidor en 127.0.0.1) o servidor
  detrás de un proxy inverso con HTTPS. Variables de entorno POS_* para la configuración.
- Sin servicios externos de pago. Sin Render, Vercel ni Netlify en el proyecto.


2. ARQUITECTURA DE CONEXIÓN IMPLEMENTADA
------------------------------------------------------------------------------------------
    Administrador (PC)      Empleado (teléfono, datos móviles)      Empleado (otro PC, otra red)
           |                              |                                     |
           +----------------- HTTPS por Internet (mismo origen) ----------------+
                                          |
                    Proxy inverso / servidor en la nube / túnel HTTPS
                                          |
                          Servidor POS-PY (FastAPI, un proceso)
                           |                                  |
                 API REST (acciones,                 Canal SSE /api/realtime/stream
                 permisos, CSRF)                     (solo avisos de cambios)
                           |                                  |
                 SQLite: grupos, integrantes,        Hub de eventos y presencia
                 invitaciones, bitácora              en memoria
- No hay conexión directa entre dispositivos, ni descubrimiento por red local, ni IP local.
- El enlace de invitación usa la dirección pública (POS_PUBLIC_URL o la configuración del
  negocio). Si no se define ninguna, usa la dirección con que el administrador abrió la
  aplicación, y la pantalla avisa cuando esa dirección no es accesible desde Internet.


3. TECNOLOGÍA DE COMUNICACIÓN
------------------------------------------------------------------------------------------
- API REST para todas las acciones. Es la única fuente de datos autorizada.
- Server-Sent Events (SSE) para el tiempo real, en lugar de WebSocket, por estas razones:
  - Las notificaciones solo van del servidor al navegador.
  - El navegador reconecta solo.
  - Usa la misma cookie y el mismo origen.
  - No requiere dependencias nuevas.
- Los eventos solo avisan que algo cambió ({"type": "grupo", "group": "G…"}). La pantalla vuelve
  a pedir los datos a la API, así que un evento nunca entrega información a quien no puede verla.
- Tipos de evento: hola, grupo, presencia, cuenta, sesion, resync.
- Latido del servidor cada 15 s, que mantiene viva la conexión a través de proxies.
- Ping del navegador cada 10 s (POST /api/realtime/ping). Si un proxy o túnel deja la conexión
  medio abierta después de que el cliente se fue, el servidor la cierra tras 30 s sin ping.
- Respaldo: si el saludo «hola» no llega en 8 s (un intermediario retiene el stream), la interfaz
  recarga los datos cada 10 s. La presencia sigue funcionando.
- Estados de conexión: Conectado, Reconectando (hasta 60 s después de perder el canal),
  Desconectado y Sin datos de conexión (desconocido). Desconectarse NUNCA saca a nadie del grupo.


4. MODELO DE DATOS (migración 7, v007_work_groups.py; solo agrega tablas)
------------------------------------------------------------------------------------------
    users ──< work_group_members >── work_groups ──< work_group_invitations
                                          └──< work_group_events
    users ── user_presence
- work_groups: public_id aleatorio y único (nunca se expone el id interno), nombre, descripción,
  owner_id (administrador dueño), estado activo/cerrado, política de ingreso
  (automatica/aprobacion), visibilidad de integrantes, versión y fechas.
- work_group_invitations: token_hash (SHA-256, UNIQUE; el token en claro se muestra una sola vez),
  expires_at, max_uses, used_count, revoked_at, quién la creó.
- work_group_members: UNIQUE(group_id, user_id), lo que impide duplicados. Estado: activo,
  pendiente, retirado, rechazado o salió. Se conserva la fila para no perder el historial.
- work_group_events: bitácora inmutable del grupo (ingresos, retiros, invitaciones, cambios).
- user_presence: última conexión y desconexión conocidas.
- Las operaciones administrativas también quedan en audit_log.


5. ENDPOINTS
------------------------------------------------------------------------------------------
Nuevos (backend/pospy/api/routes/groups.py; todos exigen sesión):
  GET  /api/groups                                   grupos propios y grupos donde participa
  POST /api/groups                                   crear grupo (solo administrador)
  GET  /api/groups/{public_id}                       detalle (vista de administrador o de integrante)
  PUT  /api/groups/{public_id}                       editar nombre, descripción y políticas
  POST /api/groups/{public_id}/close | /reopen       cerrar o reabrir el grupo
  POST /api/groups/{public_id}/invitations           generar enlace (vigencia 1–720 h, cupo 1–500)
  POST /api/groups/{public_id}/invitations/{id}/revoke
  POST /api/groups/{public_id}/members/{user_id}/{aprobar|rechazar|retirar}
  POST /api/groups/{public_id}/leave                 el empleado sale del grupo
  GET  /api/invitations/{token}                      validar enlace y ver a qué grupo se une
  POST /api/invitations/{token}/accept               confirmar el ingreso
  GET  /api/realtime/stream                          canal SSE
  POST /api/realtime/ping                            latido del navegador
Modificados:
  POST /api/auth/login, /api/setup y cambio de contraseña: la cookie lleva Secure cuando la
  petición llega por HTTPS, ya sea directo, por proxy (X-Forwarded-Proto) o por un túnel que usa
  la dirección pública https configurada.
  GET /api/setup/status y el acceso directo: una petición solo es «local» si viene de 127.0.0.1,
  sin cabeceras de proxy y con Host localhost, 127.0.0.1 o [::1].


6. SISTEMA DE INVITACIONES
------------------------------------------------------------------------------------------
- Token aleatorio de 256 bits (secrets.token_urlsafe). Solo se guarda su SHA-256.
- Enlace: https://<dirección pública>/unirse/<token>. Sin QR.
- Validez: no vencido, no revocado, con cupo y con el grupo activo. El cupo se descuenta dentro
  de la misma transacción, sin carreras entre ingresos simultáneos.
- Varias personas pueden usar el mismo enlace. Abrirlo de nuevo siendo integrante no consume cupo.
- Quien fue retirado o rechazado solo puede volver con un enlace generado después de esa decisión.
- Errores claros: enlace inválido (404); vencido, revocado, sin cupo o grupo cerrado (410).
- Al abrir el enlace sin sesión, se pide iniciar sesión y luego se muestra la invitación. El
  token sale de la barra de direcciones después de unirse.
- Interfaz: generar, copiar, compartir (Web Share API del dispositivo, si existe), ver vigencia y
  cupo, revocar y generar uno nuevo.
- Fuerza bruta: 10 intentos fallidos cada 15 minutos, por usuario y por dirección IP (HTTP 429).


7. SISTEMA DE PERMISOS (todo se valida en el servidor)
------------------------------------------------------------------------------------------
- Permiso nuevo «grupos.gestionar», exclusivo de administradores. Se integra con el sistema de
  permisos existente, sin duplicarlo.
- Solo el administrador dueño gestiona su grupo. Para cualquier otra persona, un grupo ajeno no
  existe (404).
- El empleado no puede crear grupos, generar ni revocar enlaces, expulsar a otros ni cambiar su
  rol. El enlace nunca otorga permisos, y el servidor rechaza los campos extra que envíe el
  frontend (owner_id, role…), porque los modelos son estrictos.
- La interfaz oculta los controles administrativos al empleado, pero la seguridad no depende de eso.


8. ARCHIVOS CREADOS Y MODIFICADOS
------------------------------------------------------------------------------------------
Creados:
  backend/pospy/migrations/v007_work_groups.py
  backend/pospy/services/groups.py, services/realtime.py, core/ratelimit.py
  backend/pospy/api/routes/groups.py
  backend/tests/test_groups.py
  frontend/src/lib/realtime.ts
  frontend/src/pages/groups/GroupsPage.tsx, JoinPage.tsx, labels.tsx
  frontend/src/test/groups.test.tsx, realtime.test.ts
  frontend/e2e/groups.mjs, scripts/groups_e2e.py
  grupos-de-trabajo.md
Modificados:
  backend/pospy/__main__.py (cierre rápido con canales abiertos), api/app.py (rutas),
  api/deps.py (detección de local/HTTPS detrás de proxy, IP real para límites),
  api/models.py, api/routes/auth.py, api/routes/admin.py, config.py (POS_PUBLIC_URL),
  context.py, core/permissions.py, core/settings.py (sección «grupos»),
  migrations/__init__.py, services/auth.py (validar la sesión sin renovar la inactividad)
  frontend/src/App.tsx (rutas /grupos y /unirse), components/layout/AppShell.tsx (menú y canal),
  styles/layout.css (barra inferior móvil con 6 secciones), README.md


9. VARIABLES DE ENTORNO
------------------------------------------------------------------------------------------
  POS_PUBLIC_URL      https://pos.miempresa.com. Base de los enlaces. Alternativa sin variable:
                      Gestión › Configuración › Grupos de trabajo.
  POS_SECURE_COOKIES  1 en producción.
  POS_HOST            0.0.0.0 solo si el proxy está en otra máquina. Si el proxy o túnel está en el
                      mismo equipo, deje 127.0.0.1.
  POS_CORS_ORIGINS    Vacío. La interfaz se sirve en el mismo origen; si se separa, ponga solo ese
                      dominio.
  POS_DATA_DIR, POS_MASTER_KEY: igual que antes. Los secretos no van en el código.


10. INSTRUCCIONES DE DESPLIEGUE
------------------------------------------------------------------------------------------
La aplicación de escritorio, tal como viene, solo escucha en el propio equipo. Para que los
empleados entren desde otras redes, el servidor tiene que estar publicado con HTTPS:
  a) Servidor en la nube o equipo con dominio propio, con Caddy o nginx delante (HTTPS automático).
     En nginx, para /api/realtime/: proxy_buffering off; proxy_read_timeout 1h;
  b) Túnel con nombre (por ejemplo, Cloudflare Tunnel con dominio propio). Es gratuito y no
     requiere abrir puertos.
  c) Servicios tipo Render: sirven, siempre que tengan disco persistente para SQLite y una sola
     instancia.
Pasos:
  1. cd frontend && npm run build
  2. Defina POS_PUBLIC_URL=https://su-dominio, POS_SECURE_COOKIES=1 y POS_DATA_DIR con disco
     persistente.
  3. python -m pospy --port 8000 detrás del proxy o túnel. Un solo proceso.
  4. Health check: GET /api/health devuelve {"status":"ok","schema":7}.
  5. Haga la instalación inicial desde el propio servidor (http://127.0.0.1:8000). Por Internet se
     rechaza a propósito.
  6. Registros: carpeta logs dentro de POS_DATA_DIR. Errores con mensajes claros y sin datos
     internos.
Qué requiere Internet y qué no:
  - Grupos, invitaciones y tiempo real necesitan conexión con el servidor.
  - El resto de la aplicación funciona igual que antes (en el propio equipo, sin Internet).


11. RESULTADOS DE LAS PRUEBAS
------------------------------------------------------------------------------------------
Automáticas (simuladas, en proceso):
  - Backend: toda la suite de pytest pasa (incluye test_groups.py: servicio, HTTP con sesiones
    independientes, seguridad, presencia, túnel sin cabeceras de proxy y canal medio abierto).
  - Frontend: 66/66 pruebas de vitest (pantallas de invitación y empleado, respaldo del tiempo
    real, ping). TypeScript y ESLint sin errores.
Extremo a extremo con servidor REAL y sesiones independientes (scripts/groups_e2e.py):
  - Local: 45/45.
  - Por Internet (túnel HTTPS público de localhost.run): 48/48. Cubre los escenarios A–F:
    creación, ingreso, varios empleados sin duplicados, aviso en vivo al administrador
    (223 ms), seguridad, desconexión detectada («Reconectando») y recuperación con la misma
    sesión.
Navegador real (Microsoft Edge con Playwright, frontend/e2e/groups.mjs), administrador y
empleada en contextos con cookies distintas:
  - Local: todo correcto.
  - Por Internet (túnel de Cloudflare): todo correcto. Ana aparece en la pantalla del
    administrador sin recargar (466 ms), con estado «Conectado», luego «Reconectando…» al cortar y
    otra vez «Conectado» al volver. Sin desbordamiento en un teléfono de 360 px y sin errores de
    JavaScript.
Distinción: todas las sesiones corrieron en este mismo equipo, con el tráfico saliendo y
volviendo por Internet a través de los túneles públicos. NO se probó con dispositivos físicos
distintos (por ejemplo, un teléfono Android con datos móviles).


12. LIMITACIONES Y PENDIENTES
------------------------------------------------------------------------------------------
- Falta una prueba con dispositivos físicos reales en redes distintas.
- El despliegue público no está hecho: hay que elegir el alojamiento (sección 10).
- Un solo proceso. Los eventos y la presencia en vivo están en memoria: tras reiniciar el
  servidor, la presencia vuelve a «desconocido» hasta que cada persona reconecta. Para varias
  instancias haría falta un bus de eventos compartido (por ejemplo, Redis) y otra base de datos.
- Los límites de intentos están en memoria y se reinician con el servidor.
- Los túneles rápidos de Cloudflare (trycloudflare.com) retienen el stream SSE. La interfaz lo
  compensa recargando cada 10 s, pero no son aptos para producción. localhost.run limita el
  ancho de banda en su plan gratuito.
- Detrás de un proxy o túnel que no propaga el corte, la desconexión se detecta en 30–45 s.
- No hay notificaciones push cuando la aplicación está cerrada o en segundo plano.
- Los empleados necesitan una cuenta creada por el administrador; el enlace no crea cuentas.
- La detección de «local» no cubre un reenvío que reescriba el Host a localhost y no agregue
  cabeceras de proxy. No configure el proxy o túnel de esa forma.


13. TAREAS DEL GRUPO (18-11-2026)
--------------------------------------------------------------------------------
- La página de cada grupo incluye un tablero de tareas:
  - el administrador lo ve como «Tareas del grupo»;
  - cada integrante lo ve como «Mis tareas en este grupo».
- El administrador dueño del grupo asigna tareas a uno o varios integrantes activos.
- El administrador sigue el estado individual de cada responsable en vivo, por el mismo canal SSE.
- Quien sale del grupo, o es retirado, deja de ver las tareas del grupo.
- Detalle, permisos y pruebas: columnas-inventario-y-tareas-de-grupo.md.

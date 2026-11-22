# Informe interno de evaluación de seguridad — noviembre de 2026

| | |
|---|---|
| Fecha | 2026-11-21/22 |
| Versión evaluada | Rama `Beta` sobre el commit `ab7d775` + correcciones de esta auditoría (esquema 15) |
| Tipo | Revisión de código, análisis estático, análisis de dependencias y secretos, pruebas automatizadas de autorización y pentest controlado **solo contra instalaciones locales de prueba** |
| Estado | **APROBADO CON OBSERVACIONES** (ver §8) |

> Evaluación interna del proyecto. No es una certificación de ISO, OWASP ni de ningún organismo externo. Se usó
> OWASP ASVS 4 como referencia de controles y OWASP Top 10 como guía de riesgos; no se evaluaron todos los controles de
> ASVS, por lo que no se declara cumplimiento.

## 1. Alcance y arquitectura evaluada

Servidor FastAPI + SQLite (`backend/pospy`), interfaz React/PWA (`frontend/src`), envoltura Tauri (`desktop/`),
scripts y configuración (`.gitignore`, CI). 246 operaciones de API publicadas (OpenAPI) más 4 rutas públicas ocultas
(logotipo, datos públicos de empresa, imágenes de la pantalla de ingreso, retorno de OAuth). Fuera de alcance: equipos
y redes de los negocios, proxies HTTPS de terceros, servicios de Microsoft/Google y producción (no se probó contra
ningún servicio real ni externo).

## 2. Metodología

1. Inventario del repositorio, Git, archivos sensibles, documentación y comandos reales.
2. Revisión manual de autenticación, sesiones, autorización (servicios, dependencias y rutas), carga de archivos, XML,
   SQL dinámico, cabeceras y configuración.
3. Análisis estático y de dependencias; escaneo de secretos de todo el historial.
4. Pruebas automatizadas de **denegación por defecto** recorriendo toda la API como anónimo y como empleado.
5. Pentest controlado (autenticación, autorización, manipulación de datos, sesiones, dispositivos) contra servidores
   locales con datos temporales.
6. Corrección por prioridad, prueba de regresión por hallazgo, reejecución completa de pruebas y E2E.

## 3. Herramientas

| Herramienta | Versión | Alcance | Resultado |
|---|---|---|---|
| Bandit | 1.9.4 | `backend/pospy` | 0 altos. 69 medios (B608 «SQL por texto»): **falsos positivos** verificados uno a uno — solo se interpolan nombres de tabla/columna de listas blancas del código y marcadores `?`; valores siempre parametrizados. 1 B314 (XML): mitigado (sin DOCTYPE/ENTITY; endurecido). 9 bajos (try/except en limpieza de recursos; textos que Bandit confunde con contraseñas). |
| pip-audit | 2.10.1 | `backend/requirements.txt` | Sin vulnerabilidades conocidas. |
| npm audit (registro oficial) | npm 12.2.1 | `frontend/`, `desktop/` | Producción: 0. Desarrollo: 9 moderadas (`glob`, `minimatch` vía workbox-build y typescript-eslint) → **corregidas** (typescript-eslint 8.73.0 y `overrides` de `glob` 14.0.6 / `minimatch` 11.0.9, build y PWA verificados) → 0. Escritorio: 0. |
| gitleaks | 8.21.2 | Historial completo (24 commits) y árbol de trabajo | Historial: sin secretos. Árbol: 215 coincidencias, **todas** en paquetes de terceros no versionados (`.venv`, `node_modules`); 0 en archivos del repositorio. |
| Ruff / ESLint / TypeScript | 0.17.1 / 9.38.0 / 5.9.3 | Todo el código | Sin errores. |
| Pruebas propias | pytest 9.1.1, Vitest, Playwright + Edge | Ver §6 | Todas correctas. |

No se usaron OWASP ZAP, Nuclei, Semgrep ni Trivy: no están disponibles en el entorno y las comprobaciones que aportan
(rutas expuestas, cabeceras, inyección, dependencias) se cubrieron con las pruebas automatizadas de §6 y las
herramientas anteriores. Es una limitación documentada (§9).

## 4. Controles evaluados (resumen)

| Área | Estado |
|---|---|
| Contraseñas | scrypt con sal por contraseña, política mínima, sin texto plano ni reversibles. ✔ |
| Fuerza bruta / enumeración | Bloqueo por cuenta + **nuevo límite por origen**; mismo mensaje y coste para usuario inexistente. ✔ |
| Sesiones | Token aleatorio (hash en BD), `HttpOnly`/`SameSite=Strict`/`Secure` en HTTPS, inactividad, duración máxima, revocación por versión. **Logout corregido** (§5). ✔ |
| CSRF / CORS | Cabecera obligatoria en escrituras; CORS solo si se configura. ✔ |
| Autorización | Validada en el backend en cada operación (permiso + inventario + propiedad); denegación por defecto verificada en toda la API. **Reportes corregidos** (§5). ✔ |
| Escalada de privilegios | El empleado no cambia roles ni permisos; los permisos de administración no se pueden asignar a empleados. ✔ |
| Manipulación de datos | Modelos estrictos; precio, total, descuento (permiso + máximo), cantidad y existencias decididos por el servidor; idempotencia. ✔ |
| Cargas de archivos | Validación por contenido, tamaño y dimensiones; sin SVG; nombres del servidor; Excel sin XXE ni rutas `..`; macros nunca ejecutadas. ✔ |
| Cabeceras | CSP, nosniff, X-Frame-Options, Referrer-Policy, **Permissions-Policy, COOP, HSTS (HTTPS)**. ✔ |
| Exposición de información | `/api/docs` y OpenAPI **solo en el equipo servidor**; errores sin detalles internos. ✔ |
| Auditoría | Append-only (triggers), sin secretos; **nuevo registro de accesos denegados** y eventos de equipos. ✔ |
| Dispositivos | **Nuevo**: restricción por equipo con clave ECDSA no exportable y prueba de posesión. ✔ (con limitaciones §9) |
| Secretos | Ninguno versionado; credenciales de integraciones cifradas (DPAPI / `POS_MASTER_KEY`). ✔ |
| MFA | No implementado. ✖ (riesgo residual) |

## 5. Hallazgos y correcciones

| # | Riesgo | Hallazgo | Corrección | Prueba de regresión |
|---|---|---|---|---|
| 1 | **ALTO** | **El cierre de sesión no revocaba la sesión en el servidor.** La consulta unía `sessions` y `users` y ambas columnas se llamaban `id`; la auditoría recibía el id de la *sesión* como usuario, fallaba la clave foránea y se revertía la transacción: el navegador borraba su cookie, pero una copia del token seguía válida hasta caducar (hasta 12 h). | Alias explícitos (`services/auth.py`). | `test_sessions_logout_tampering_revocation_and_deactivation` (reutilizar el token tras el cierre → 401). |
| 2 | **ALTO** | **Fuga de datos entre inventarios en los reportes operativos** (`/api/reports/sales`, `/movements`): sumaban ventas, productos más vendidos, ventas por vendedor y movimientos de **todos** los inventarios (incluso de otros administradores) y solo exigían «ver historial», que todo empleado tiene por defecto (BOLA). | Exigen `gestion.auditoria` (como la pantalla) y filtran por el inventario de la petición (`services/reports.py`). | `test_reports_only_for_audit_permission_and_current_inventory`, `test_employee_cannot_use_administrative_endpoints`. |
| 3 | MEDIO | Sin límite de intentos por origen: solo bloqueo por cuenta (permitía probar muchas cuentas). | 20 fallos / 15 min por dirección → 429 (`core/ratelimit.py`, `services/auth.py`). | `test_login_rate_limit_by_origin_and_account_lockout`. |
| 4 | MEDIO | No existía control por dispositivo (requisito): con la URL y una contraseña se ingresaba desde cualquier computador. | Equipos autorizados (`services/devices.py`, migración 15, `lib/device.ts`, Gestión › Equipos autorizados). | `test_device_restriction_full_flow`, `test_device_registered_by_employee_session_stays_pending`, `e2e/devices.mjs`. |
| 5 | MEDIO | El ejecutable de escritorio (PyInstaller) no incluía `win32ui`/`win32gui`/`win32con`/`pywintypes` que usa la impresión directa: habría fallado en la aplicación empaquetada. | Imports ocultos corregidos (`scripts/build_backend.py`). | Revisión; **no se compiló el instalador en esta auditoría** (§9). |
| 6 | MEDIO | 9 vulnerabilidades moderadas en herramientas de compilación (cadena de suministro de desarrollo). | Actualización y `overrides` sin `--force`. | `npm audit` = 0; build y PWA verificados. |
| 7 | BAJO | `GET /api/printing/jobs` mostraba a cualquier empleado los trabajos de impresión de todos los inventarios (documentos y usuarios). | Cada persona ve los suyos; la administración, todos (`services/printing.py`). | Barrido de empleado (`test_employee_reaches_only_reviewed_operations`). |
| 8 | BAJO | Documentación interactiva de la API accesible desde la red (reconocimiento). | Solo desde el equipo servidor (`api/app.py`). | `test_security_headers_and_api_docs_only_on_the_server`. |
| 9 | BAJO | Faltaban Permissions-Policy, COOP y HSTS. | Agregadas (`api/app.py`). | Misma prueba. |
| 10 | BAJO | La detección de `DOCTYPE` en XML de Excel solo miraba los primeros 4 KB (mitigado porque `ENTITY` se buscaba en todo el archivo). | Todo el documento (`documents/xlsx_import.py`). | Pruebas de importación existentes. |
| 11 | INFORMATIVO | Los accesos denegados no quedaban registrados; el mensaje no indicaba cómo pedir el permiso. | `seguridad.acceso_denegado` en la auditoría; mensaje «solicítela a un administrador». | `test_denied_access_is_audited`. |
| 12 | INFORMATIVO | Código muerto: automatización de Excel por COM (`documents/com_excel.py`) sin uso tras el motor propio. | Eliminado (y su prueba). | Suite completa. |

No se encontraron vulnerabilidades críticas. Comprobado sin hallazgos: inyección SQL, XSS (React escapa; CSP sin
`unsafe-inline` en scripts; los colores del tema solo aceptan `#RRGGBB`), inyección de comandos (no se ejecutan
comandos con datos del usuario), path traversal (nombres de archivo del servidor y validación de rutas), SSRF (las
integraciones solo llaman a endpoints fijos de Microsoft/Google), manipulación de precios/totales/existencias,
repetición de operaciones (idempotencia), IDOR en notas, tareas, grupos e inventarios (pruebas existentes y barrido).

## 6. Pentest controlado y pruebas ejecutadas

Todo contra servidores **locales** con datos temporales; nada destructivo ni contra servicios externos.

- **Autenticación**: credenciales inválidas, 20 intentos desde un origen (→ 429), token alterado, reutilización tras
  el cierre, cuenta desactivada, CSRF ausente, cookie copiada a otro «equipo» tras revocar el equipo.
- **Autorización**: barrido de las 246 operaciones como anónimo (solo responden las públicas) y como empleado (solo
  completa la lista revisada); 16 operaciones administrativas como empleado (usuarios, configuración, seguridad,
  copias, integraciones, apariencia, equipos, grupos, plantillas, tipos de documento, reportes) → 403/404; cambio de
  rol y de permisos propios → rechazado.
- **Manipulación de datos**: precio unitario, total, cantidad negativa, descuento sobre el máximo, descuento sin
  permiso, campos desconocidos, edición directa de existencias → rechazados; venta repetida con la misma clave → una
  sola venta.
- **Dispositivos**: ingreso sin prueba, con equipo no registrado, pendiente, revocado o rechazado; desafío reutilizado;
  firma falsificada; empleado intentando autorizar; revocación con sesión abierta (→ 401 inmediato); exención del
  equipo servidor.

Resultados:

| Suite | Resultado |
|---|---|
| pytest (backend) | **265 pruebas en 25 archivos: todas correctas** (28 de seguridad, 7 de apariencia, 11 de impresión directa) |
| Vitest (frontend) | 113 pruebas: todas correctas |
| ESLint, TypeScript, Ruff, build | Sin errores |
| E2E con navegador real | ver tabla siguiente |

| E2E (Edge real, servidor real) | Resultado |
|---|---|
| smoke, inventories, group-inventory, groups, notes-tasks, columns-group-tasks, upgrade-regression | Todo correcto (regresión de funciones comerciales: el empleado conserva vender, inventario de su grupo, tareas y notas) |
| print-templates, canvas-editor, printers-documents, appearance | Todo correcto |
| **devices** (otros computadores por la IP de red + equipo servidor) | Todo correcto: rechazo con contraseña correcta, solicitud pendiente, aprobación, empleado conserva Vender, credenciales en otro equipo rechazadas, revocación → 401 inmediato, equipo servidor exento, historial |

## 7. Riesgo residual y pendientes

| Riesgo | Nivel | Tratamiento |
|---|---|---|
| Sin autenticación de dos factores. | MEDIO | Pendiente. Mitigado con límites de intentos y restricción por equipo. |
| El token de sesión es un portador: robado junto con acceso al equipo, vale hasta caducar o hasta revocar el equipo. | MEDIO | Aceptado (HttpOnly, SameSite, HTTPS, caducidad, revocación inmediata por equipo). |
| La restricción por equipo depende del navegador (clave no exportable, pero el perfil completo del sistema podría copiarse; requiere HTTPS). | MEDIO | Documentado; se recomienda BitLocker y cuentas de Windows por persona. |
| El historial de actividad de un administrador incluye eventos de otros administradores de la misma instalación. | BAJO | Pendiente: la auditoría no guarda el inventario de cada evento; los administradores son de la misma empresa. |
| El bloqueo por cuenta permite que un tercero bloquee temporalmente una cuenta conocida (15 min). | BAJO | Aceptado; mitigado por el límite por origen. |
| Los límites de intentos están en memoria (se reinician al reiniciar el servidor). | BAJO | Aceptado (un solo proceso). |
| No se ejecutó DAST (OWASP ZAP) ni se compiló el instalador de escritorio. | INFORMATIVO | Pendiente para la próxima versión. |
| El acceso al archivo de la base en el equipo servidor equivale a acceso a los datos. | INFORMATIVO | Responsabilidad de operación (SECURITY.md). |

## 8. Estado de evaluación

**APROBADO CON OBSERVACIONES.** Criterios: no quedan hallazgos críticos ni altos sin corregir (los 2 altos se
corrigieron con pruebas de regresión que pasan); los medios corregibles se corrigieron; los riesgos residuales medios
(MFA, token portador, límites del navegador) están documentados y aceptados con mitigaciones. No es «Aprobado
internamente» porque falta MFA, DAST y la compilación verificada del instalador.

## 9. Limitaciones de la evaluación

Evaluación interna y en un solo equipo (Windows 11). No se probó contra producción, proxies reales ni cuentas de
Microsoft/Google. Sin ZAP/Nuclei/Semgrep/Trivy. La revisión de ASVS fue selectiva (autenticación, sesiones, control de
acceso, validación, archivos, configuración y registros). El instalador de escritorio no se compiló.

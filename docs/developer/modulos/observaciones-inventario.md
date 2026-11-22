> Documento técnico del módulo (estado vigente). La historia de cambios está en git; la visión general en [../README.md](../README.md).

================================================================================
POS-PY — MÓDULO DE OBSERVACIONES DE INVENTARIO
Documentación técnica y de pruebas · 15/11/2026
================================================================================

Ruta raíz del proyecto: C:\Users\USUARIO LENOVO\Desktop\Codigo\WSP\PROGRAMAS\CRM-P-COMPANY
(En adelante, las rutas son relativas a esa carpeta.)

--------------------------------------------------------------------------------
1. DIAGNÓSTICO INICIAL
--------------------------------------------------------------------------------
- El POS ya tenía un módulo de Inventario con tres pestañas: Productos, Movimientos e
  Importar y exportar (frontend/src/pages/inventory/InventoryPage.tsx). No existía ningún
  registro de novedades por producto.
- La existencia de un producto está protegida por la base de datos: solo cambia insertando
  movimientos en inventory_movements (triggers moves_apply_stock y products_stock_guard), y los
  movimientos son inmutables. Esto permite garantizar que las observaciones no alteren existencias.
- Los productos no tienen un proveedor asignado. El único vínculo real producto-proveedor son las
  compras a crédito (payables con source_type = 'entrada_inventario' enlazadas a un movimiento).
- El código del producto (products.code) es el SKU / código de barras; existe además
  products.external_ref (referencia externa de sincronización).
- Permisos: catálogo plano (backend/pospy/core/permissions.py). El administrador tiene todos;
  el empleado solo los asignados. No hay roles intermedios.
- Adjuntos: el módulo de proveedores ya resolvía la carga segura de archivos (verificación de la
  firma del contenido, nombre interno aleatorio, carpeta dentro de los datos). Se reutilizó.

--------------------------------------------------------------------------------
2. ARQUITECTURA ENCONTRADA
--------------------------------------------------------------------------------
- Backend: Python 3.12+/3.13, FastAPI, SQLite (WAL, claves foráneas activas, transacciones
  BEGIN IMMEDIATE). Capas:
    api/routes/*.py   -> traducen HTTP (sin lógica de negocio)
    api/models.py     -> validación estructural (Pydantic, extra="forbid")
    services/*.py     -> reglas de negocio; reciben un Actor y validan permisos
    migrations/vNNN   -> migraciones versionadas, aplicadas una vez al arrancar
    core/audit.py     -> bitácora audit_log
- Frontend: React 18 + TypeScript + Vite; componentes propios (DataTable, Dialog, ConfirmDialog,
  Metric, Tabs, Badge, TextField, SelectField…), hooks useApi/useOnline, tokens CSS con modo
  claro/oscuro y alto contraste.

--------------------------------------------------------------------------------
3. MODELO DE DATOS
--------------------------------------------------------------------------------
observation_categories (categorías ampliables sin tocar la estructura)
  id, code UNIQUE, name, sort_order, active, created_at
  Sembradas: Diferencia de inventario, Producto defectuoso, Producto vencido o próximo a vencer,
  Faltante de mercancía, Reposición pendiente, Problema con proveedor, Error de información,
  Problema de precio, Producto reservado, Otro.
  No se borran (trigger); se desactivan con active = 0.

inventory_observations (observación principal)
  id                 identificador (se muestra como OBS-00012)
  product_id         FK products(id)  NOT NULL  — no se copian datos del producto
  category_id        FK observation_categories(id) NOT NULL
  priority           'baja' | 'media' | 'alta' | 'critica'
  status             'pendiente' | 'en_proceso' | 'resuelta' | 'cerrada'
  description        NOT NULL (5 a 2000 caracteres)
  qty_milli          cantidad afectada en milésimas (opcional, >= 0) — solo informativa
  supplier_id        FK suppliers(id) (opcional)
  reference_doc      factura o documento de referencia (≤ 80)
  detected_on        fecha de la novedad (AAAA-MM-DD; no futura)
  follow_up_date     fecha límite de seguimiento (≥ detected_on)
  notes              comentarios adicionales (≤ 2000)
  assigned_to        FK users(id) responsable (por defecto quien registra)
  created_by / updated_by  FK users(id)
  created_at / updated_at / resolved_at / closed_at   instantes UTC ISO-8601
  deleted_at / deleted_by / delete_reason             eliminación lógica (motivo obligatorio)
  version            control de concurrencia optimista
  Trigger observations_no_delete: impide el borrado físico.

inventory_observation_events (historial de seguimiento, INMUTABLE)
  id, observation_id FK, kind ('creada','comentario','estado','prioridad','edicion','adjunto',
  'adjunto_eliminado','eliminada'), from_value, to_value, comment, details (JSON con antes/después),
  user_id FK, created_at.
  Triggers observation_events_no_update / observation_events_no_delete.

inventory_observation_files (metadatos de adjuntos)
  id, observation_id FK, original_name, stored_name UNIQUE (aleatorio), content_type, size_bytes,
  sha256, uploaded_by FK, uploaded_at.
  El archivo se guarda en <datos>\observaciones\<id de la observación>\.

--------------------------------------------------------------------------------
4. MIGRACIONES
--------------------------------------------------------------------------------
- backend/pospy/migrations/v006_inventory_observations.py (VERSION = 6).
- Solo CREA tablas, índices, triggers y la semilla de categorías. No elimina ni modifica tablas
  existentes, no toca registros históricos y conserva todos los identificadores.
- Se aplica automáticamente al arrancar (Database.migrate) y una sola vez (schema_migrations).
- Incluye DOWN_SQL documentado para reversión manual (restaurar antes una copia de seguridad).
- Integridad referencial: todas las relaciones son FOREIGN KEY con PRAGMA foreign_keys = ON;
  los productos y usuarios ya tenían triggers que impiden borrarlos, por lo que una observación
  nunca queda huérfana.

--------------------------------------------------------------------------------
5. ARCHIVOS CREADOS
--------------------------------------------------------------------------------
backend\pospy\migrations\v006_inventory_observations.py
backend\pospy\services\observations.py
backend\pospy\api\routes\observations.py
backend\tests\test_observations.py
frontend\src\pages\inventory\observations\labels.tsx
frontend\src\pages\inventory\observations\ObservationForm.tsx
frontend\src\pages\inventory\observations\ObservationsPage.tsx
frontend\src\pages\inventory\observations\ObservationDetail.tsx
observaciones-inventario.md

--------------------------------------------------------------------------------
6. ARCHIVOS MODIFICADOS
--------------------------------------------------------------------------------
backend\pospy\migrations\__init__.py       registra la migración v006
backend\pospy\core\permissions.py          6 permisos nuevos; 3 en el perfil por defecto del empleado
backend\pospy\context.py                   instancia ObservationService
backend\pospy\api\app.py                   registra el router de observaciones
backend\pospy\api\models.py                modelos Observation, ObservationStatus, ObservationComment,
                                           ObservationDelete
frontend\src\pages\inventory\InventoryPage.tsx
                                           pestaña «Observaciones»; ruta /inventario/observaciones/*;
                                           indicador discreto en el listado; sección «Observaciones»
                                           en la ficha del producto; ?producto=ID abre la ficha
frontend\src\pages\manage\Users.tsx        permisos por defecto de un empleado nuevo (igual al backend)
frontend\src\styles\components.css         estilos semánticos de prioridad/estado, línea de tiempo,
                                           filtros y diseño de la ficha (responsive)
frontend\src\test\screens.test.tsx         2 pruebas de pantalla nuevas
README.md                                  funcionalidad y carpeta de adjuntos «observaciones\»

--------------------------------------------------------------------------------
7. FUNCIONALIDADES IMPLEMENTADAS
--------------------------------------------------------------------------------
Navegación: Inventario › Productos · Movimientos · Observaciones · Importar y exportar.
La pestaña solo aparece con el permiso observaciones.ver.

Panel (/inventario/observaciones)
- Indicadores calculados en el servidor sobre registros reales (no eliminados): total, pendientes,
  en proceso, resueltas (y cerradas), críticas abiertas, recientes (7 días) y seguimientos vencidos.
- Filtros rápidos: Todas, Pendientes, Críticas, En proceso, Resueltas, Recientes.
- Búsqueda: nombre del producto, código/SKU, código de barras (parcial), referencia externa,
  descripción, documento de referencia e identificador («OBS-00012» o «#12» buscan solo por id;
  un número suelto busca id y códigos).
- Filtros combinables: categoría, prioridad, estado, responsable, proveedor, fecha inicial y final
  (fecha de la novedad), producto (?producto=ID).
- Orden: más recientes, más antiguas, mayor prioridad, producto, estado.
- Tabla: ID, Fecha (registro), Producto, Código, Categoría, Prioridad, Descripción (2 líneas),
  Responsable, Estado (+ «Vencida» si pasó la fecha límite), Acciones (consultar, editar, eliminar
  según permisos). Paginación de 25. Estados de carga, vacío y error.

Formulario (crear / editar)
- Obligatorios: producto, categoría, descripción, prioridad (validados en frontend y backend).
- Adicionales: fecha de la novedad, cantidad afectada, responsable, proveedor, documento de
  referencia, fecha límite de seguimiento, comentarios, fotografías/documentos (al crear).
- Selección de producto por nombre, SKU, código de barras o referencia; muestra nombre, código,
  categoría, existencia actual, precio de compra (costo promedio, solo con inventario.costos),
  proveedor asociado (última compra a crédito real) y observaciones abiertas.
- La observación guarda solo product_id: no se crean productos ni se duplican sus datos.
- El producto de una observación no se puede cambiar al editar (trazabilidad).
- Control de versiones: si otra persona la modificó, se responde 409 y se pide recargar.

Ficha (/inventario/observaciones/:id)
- Identificador, categoría, prioridad, estado, descripción completa, cantidad, responsable,
  quién registró, fecha de la novedad, de registro, última actualización, fecha límite,
  proveedor, documento, resuelta/cerrada.
- Historial cronológico inmutable: registro, comentarios, cambios de estado (anterior → nuevo +
  comentario), cambios de prioridad, ediciones (cada campo antes → después), adjuntos y
  eliminaciones, cada uno con fecha, hora y usuario.
- Cambiar estado (diálogo con comentario; cerrar o reabrir exige motivo).
- Agregar comentarios de seguimiento.
- Documentos adjuntos: listar, descargar, adjuntar, eliminar (con confirmación).
- Producto relacionado con enlace a su ficha y a todas sus observaciones.

--------------------------------------------------------------------------------
8. PERMISOS
--------------------------------------------------------------------------------
Se integraron en el catálogo existente (grupo «Inventario»), sin roles nuevos:
  observaciones.ver       Consultar observaciones                     (empleado por defecto)
  observaciones.crear     Registrar observaciones y adjuntar archivos (empleado por defecto)
  observaciones.editar    Editar datos y prioridad; eliminar adjuntos
  observaciones.estado    Cambiar el estado
  observaciones.comentar  Agregar comentarios de seguimiento           (empleado por defecto)
  observaciones.eliminar  Eliminar (lógico, con motivo y confirmación)
- El administrador los tiene todos. Los empleados EXISTENTES no reciben permisos nuevos de forma
  automática (la migración no modifica user_permissions): el administrador los asigna en
  Gestión › Usuarios. Los empleados creados desde ahora reciben ver, crear y comentar.
- Todos los permisos se verifican en el backend (ObservationService); la interfaz solo oculta
  botones. Los indicadores en el listado de productos se devuelven vacíos sin observaciones.ver.

--------------------------------------------------------------------------------
9. INTEGRACIÓN CON PRODUCTOS E INVENTARIO
--------------------------------------------------------------------------------
- Ficha del producto (panel lateral en Inventario › Productos): sección «Observaciones» con
  «Sin observaciones pendientes» / «N observaciones abiertas» / «N críticas», las 5 más recientes
  (enlazadas a su ficha), «Ver todas» y «Registrar observación» (con el producto preseleccionado).
- Listado de productos: un distintivo pequeño junto a la descripción SOLO cuando hay observaciones
  abiertas (amarillo = pendientes, rojo sólido = alguna crítica), con texto accesible.
- Desde una observación: «Ficha del producto» abre /inventario?producto=ID.
- REGLA DE INTEGRIDAD: ObservationService no importa ni llama a InventoryService y no escribe en
  products, inventory_movements, payables, sales, journal_entries ni costos. Registrar, editar,
  resolver, cerrar o eliminar una observación no altera existencias, entradas, salidas, ventas,
  compras, costos ni movimientos. Verificado por prueba automática y en navegador real.
  Los ajustes se hacen con el procedimiento existente (botón «Ajuste» de la ficha del producto).

--------------------------------------------------------------------------------
10. VALIDACIONES Y SEGURIDAD
--------------------------------------------------------------------------------
- Obligatorios y longitudes: descripción 5–2000, comentarios 2000, documento 80, motivo 300.
- Sanitización: se eliminan caracteres de control (se conservan saltos de línea); la interfaz
  muestra texto plano (React escapa todo; no se usa HTML crudo).
- Pydantic con extra="forbid" rechaza campos desconocidos; prioridades y estados por lista blanca.
- Fechas en formato AAAA-MM-DD; la novedad no puede ser futura; la fecha límite no puede ser
  anterior a la novedad; rango de filtro coherente.
- Referencias verificadas: producto, categoría activa, proveedor existente, responsable activo.
- Adjuntos: extensiones .pdf .png .jpg .jpeg .xlsx; se comprueba la firma real del contenido;
  máximo 10 MB y 10 archivos por observación; nombre original saneado (sin rutas ni caracteres
  reservados de Windows); nombre interno aleatorio; la ruta resuelta nunca sale de la carpeta de
  la observación; un archivo de otra observación responde 404.
- Consultas parametrizadas; el orden usa una lista blanca de columnas; comodines LIKE escapados.
- Errores de dominio traducidos a 403/404/409/422 sin detalles internos.
- Auditoría: observacion.crear / actualizar / estado / adjunto / adjunto_eliminar / eliminar en
  audit_log (además del historial propio de cada observación).
- Protección CSRF y sesión existentes del POS (cabecera X-Requested-With, cookie HttpOnly).

--------------------------------------------------------------------------------
11. PRUEBAS REALIZADAS
--------------------------------------------------------------------------------
A) Backend — backend\tests\test_observations.py (14 pruebas, todas correctas)
   1  Crear asociada a un producto (sin copiar columnas del producto)   test_create_links_existing_product...
   -  Obligatorios, longitudes, fechas, referencias y sanitización      test_required_fields_and_validation
   2  Buscar por nombre                                                 test_search_by_name_code_and_id
   3  Buscar por código / código de barras / id / documento            test_search_by_name_code_and_id
   4  Cambiar prioridad (con comentario y control de versión)           test_follow_up_lifecycle
   5  Cambiar estado (cerrar y reabrir exigen motivo)                   test_follow_up_lifecycle
   6  Agregar comentarios                                               test_follow_up_lifecycle
   7  Consultar historial cronológico                                   test_follow_up_lifecycle
   8  Editar descripción (antes/después en el historial)                test_follow_up_lifecycle
   -  Historial inmutable y producto no modificable                     test_history_is_immutable...
   9  Adjuntar archivo (tipos, firma, tamaño, rutas, aislamiento)       test_attachments
   10 Observaciones desde la ficha del producto + indicadores            test_product_integration
   -  Proveedor asociado desde compras reales                           test_last_supplier_comes_from_real_purchases
   11 Indicadores del panel                                             test_dashboard_metrics_and_combined_filters
   12 Filtros combinados y ordenamientos                                test_dashboard_metrics_and_combined_filters
   13 Acciones sin permiso (403) y permisos por acción                  test_permissions, test_default_employee_permissions
   14 Eliminar (lógico, motivo, auditoría)                              test_logical_delete_keeps_traceability
   15 Existencias, costos, movimientos, ventas, compras intactos        test_observations_never_touch_inventory
   16 Reinicio: datos y archivos persisten; la migración no se reaplica test_persistence_after_restart
   Suite completa del backend: 144 pruebas correctas (sin regresiones). Ruff: sin errores.

B) Frontend — frontend\src\test\screens.test.tsx
   - Panel con indicadores, prioridad crítica destacada, sin acciones no permitidas, filtro rápido
     combinado con búsqueda.
   - Ficha con historial, proveedor del producto, enlace a la ficha del producto y acciones.
   Suite completa: 60 pruebas correctas. tsc -b y eslint: sin errores. npm run build: correcto.

C) Prueba de extremo a extremo en navegador real (Microsoft Edge, servidor real, datos reales
   en una carpeta temporal) — 20 verificaciones correctas:
   pestaña dentro de Inventario y estado vacío; validación de obligatorios; búsqueda del producto
   por código de barras con existencia actual; registro con adjunto; cambio de estado con
   comentario; comentario; edición de prioridad y descripción; historial con 6 eventos en orden;
   indicadores reales; filtro rápido + búsqueda por nombre; sin coincidencias; búsqueda por
   código; indicador discreto solo en el producto afectado; navegación producto ↔ observación;
   eliminar exige motivo; eliminación lógica; existencias, costos y movimientos sin cambios;
   empleado solo-consulta sin botones de acción; backend responde 403; persistencia tras
   reiniciar el servidor (incluido el adjunto); ficha sin desplazamiento horizontal en móvil
   (390 px); sin errores de consola ni del backend.

--------------------------------------------------------------------------------
12. PROBLEMAS ENCONTRADOS Y SOLUCIÓN
--------------------------------------------------------------------------------
- Un número buscado (p. ej. «1») coincidía con el id y también con códigos de barras que
  contienen ese dígito. Se mantuvo ese comportamiento para números sueltos (un código puede ser
  numérico) y se añadió la forma explícita «OBS-00001» / «#1», que busca solo por id.
- Los productos no tienen proveedor propio: el «proveedor asociado» se deduce de la compra a
  crédito más reciente del producto; si no hay, se indica que no hay compras registradas.

--------------------------------------------------------------------------------
13. LIMITACIONES PENDIENTES
--------------------------------------------------------------------------------
- Las categorías se amplían insertando filas en observation_categories (no hay pantalla de
  administración de categorías todavía).
- Las copias de seguridad de Gestión solo incluyen la base de datos; los adjuntos están en
  <datos>\observaciones\ y deben copiarse aparte (igual que la carpeta de proveedores).
- Las observaciones eliminadas no tienen pantalla de consulta; se conservan en la base de datos
  (deleted_at, delete_reason) y en la auditoría (Gestión › Historial de actividad).
- El filtro de fechas usa la fecha de la novedad (detected_on); la columna «Fecha» de la tabla
  muestra la fecha y hora de registro.
- Los empleados existentes deben recibir los nuevos permisos manualmente.
- No hay notificaciones automáticas cuando vence la fecha límite (solo indicador «Vencida»).

--------------------------------------------------------------------------------
14. INSTRUCCIONES DE EJECUCIÓN
--------------------------------------------------------------------------------
Backend (desarrollo):
  cd backend
  .venv\Scripts\python.exe -m pospy --port 8000
  (la migración v006 se aplica sola al arrancar)

Frontend (desarrollo):
  cd frontend
  npm run dev

Pruebas:
  cd backend  &&  .venv\Scripts\python.exe -m pytest tests\test_observations.py
  cd backend  &&  .venv\Scripts\python.exe -m pytest            (suite completa)
  cd frontend &&  npm run typecheck && npm run lint && npm test
  cd frontend &&  npm run build

Uso:
  Inventario › Observaciones › «Nueva observación», o desde la ficha de un producto
  › «Registrar observación». Asignar permisos en Gestión › Usuarios (grupo Inventario).
================================================================================

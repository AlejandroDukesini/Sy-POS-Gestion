> Documento técnico del módulo (estado vigente). La historia de cambios está en git; la visión general en [../README.md](../README.md).

CAMBIOS — MÓDULO DE NOTAS Y TAREAS
POS-PY · 17-11-2026
==========================================================================================

ACTUALIZACIÓN 18-11-2026 (tareas de grupos de trabajo). Lo siguiente reemplaza lo que dice más abajo:
- Una tarea asignada puede tener VARIOS responsables, cada uno con su estado individual. También
  puede pertenecer a un grupo de trabajo, y entonces solo se asigna a integrantes de ese grupo.
- Estado general: Pendiente, En progreso, En revisión, Completada o Cancelada. Pasa a «Completada»
  solo cuando terminan todos los responsables.
- Tiene prioridad (Baja, Media, Alta o Urgente), observaciones, comentarios, solicitudes de cambio
  e historial.
- Una tarea asignada solo se elimina si nadie registró avance ni comentarios; si no, se cancela.
- Las notas y las tareas personales no cambian.
Detalle: columnas-inventario-y-tareas-de-grupo.md.

1. PUNTO DE PARTIDA (inspección)
------------------------------------------------------------------------------------------
- Backend FastAPI + SQLite con migraciones versionadas. Sesión por cookie HttpOnly, roles admin y
  employee, permisos por usuario.
- Ya existía una sección «Tareas» (/tareas):
  - Tabla tasks y permiso «tareas.gestionar» (los administradores lo tienen).
  - El administrador asignaba tareas y el empleado solo cambiaba su estado.
  - Cuatro estados: pendiente, en_curso, completada y cancelada.
  - Un trigger impedía borrar tareas.
- No había notas ni tareas personales.
- Decisión: EXTENDER ese módulo en vez de crear otro.
  - Una sola tabla de tareas, con una columna que distingue su origen.
  - Una tabla nueva solo para las notas.
  - Sin roles nuevos ni cambios a los roles actuales.


2. FUNCIONALIDADES
------------------------------------------------------------------------------------------
Sección «Notas y tareas» en el menú (en el teléfono, el rótulo corto «Tareas»). Tres pestañas:

Mis notas (/tareas/notas) — administrador y empleados
  - Crear, editar y eliminar (con confirmación).
  - Buscar por título o contenido.
  - Tarjetas tipo bloc de notas con título, contenido y fechas de creación y de modificación.
  - Cada nota es privada: nadie más la ve, ni siquiera el administrador.

Mis tareas (/tareas/mias) — administrador y empleados
  - Tareas personales para organizar la jornada: crear, editar, eliminar y cambiar el estado.
  - Botón «Marcar como completada».
  - Filtros: Pendientes / Completadas / Todas.
  - Son privadas: las del administrador no aparecen a los empleados y viceversa.

Tareas asignadas (/tareas/asignadas)
  - Administrador:
    - Crea la tarea: título, descripción opcional, responsable y fecha límite opcional.
    - Consulta todas las tareas asignadas y su estado, con filtro por responsable.
    - Edita, reasigna o elimina (con confirmación).
    - Ve los cambios de estado de los empleados EN VIVO, sin recargar.
  - Empleado:
    - Ve las tareas que le asignaron, con su descripción y quién las asignó.
    - Cambia el estado o pulsa «Marcar como completada».
    - No ve botones de editar, eliminar ni asignar, y el servidor también se lo impide.

Estados: Pendiente (amarillo), En progreso (azul) y Completada (verde). Las tareas completadas
aparecen tachadas. Una fecha límite vencida se resalta en rojo.
Estados vacíos claros, por ejemplo: «Todavía no tiene tareas. Cree una para organizar su
trabajo.» (Se usa «usted», como en el resto del sistema.)


3. PERMISOS Y SEGURIDAD (comprobados en el backend)
------------------------------------------------------------------------------------------
- Notas: toda consulta filtra por la persona que inició sesión. La nota de otra persona responde
  404 («no encontrada») para cualquiera, incluido el administrador.
- Tareas personales: solo su dueño las ve, edita o elimina; para los demás no existen (404).
  Se crean siempre a nombre de quien las crea: el servidor ignora cualquier responsable enviado.
  Si alguien intenta asignarla a otra persona, recibe 403.
- Tareas asignadas:
  - Crear, editar, reasignar y eliminar requiere «tareas.gestionar».
  - El responsable solo puede cambiar el estado (403 para cualquier otro cambio, incluso
    eliminar o cambiar el responsable).
  - Otro empleado no la ve: lista vacía, 403 si pide las tareas de otra persona y 404 si intenta
    modificarla.
- Los modelos de entrada rechazan campos extra (owner_id, etc.) con 422.
- Las notas y las tareas personales NO se copian al historial de actividad, porque los
  administradores pueden leerlo. Las tareas asignadas sí: crear, actualizar y eliminar.
- Sin sesión: 401.


4. PERSISTENCIA (migración 8: v008_notes_personal_tasks.py)
------------------------------------------------------------------------------------------
- tasks.personal: 0 = asignada, 1 = personal. Las tareas existentes quedan como asignadas; no se
  modifica ningún dato.
- Tabla notes: owner_id, title, content, created_at, updated_at, version. Exige título o contenido.
- Se reemplazó el trigger que impedía borrar tareas: ahora se pueden eliminar las personales y,
  por un administrador, las asignadas. La eliminación de una asignada queda en el historial de
  actividad con su título, responsable y estado.
  CAMBIO DE COMPORTAMIENTO: antes ninguna tarea se podía borrar (solo cancelar).
- «Cancelada» ya no se puede elegir. Las tareas antiguas canceladas se conservan, se muestran como
  «Cancelada» y se pueden pasar a otro estado.
- Todo se guarda en SQLite: sobrevive a cerrar sesión y a reiniciar el servidor (comprobado).
- Reversión manual documentada en DOWN_SQL de la migración (restaurar antes una copia).


5. ARCHIVOS
------------------------------------------------------------------------------------------
Creados:
  backend/pospy/migrations/v008_notes_personal_tasks.py   Columna personal, tabla notes
  backend/pospy/services/notes.py                          Notas privadas por persona
  backend/pospy/api/routes/notes.py                        GET/POST /api/notes, PUT/DELETE /api/notes/{id}
  backend/tests/test_notes_tasks.py                        Los 12 escenarios + contrato HTTP
  frontend/src/pages/tasks/NotesTab.tsx                    Pestaña «Mis notas»
  frontend/src/test/notes-tasks.test.tsx                   Pantallas de ambos roles
  frontend/e2e/notes-tasks.mjs                             Navegador real + reinicio del servidor
  notas-y-tareas.md
Modificados:
  backend/pospy/services/tasks.py      Tareas personales, eliminar, tres estados, aviso en vivo
  backend/pospy/api/routes/admin.py    GET /api/tasks?scope=personales, DELETE /api/tasks/{id}
  backend/pospy/api/models.py          TaskIn.personal; NoteIn / NoteUpdate
  backend/pospy/api/app.py             Rutas de notas
  backend/pospy/context.py             NoteService; TaskService recibe el canal de tiempo real
  backend/pospy/migrations/__init__.py Registro de la migración 8
  backend/tests/test_access.py         La prueba de «las tareas no se borran» ahora comprueba la
                                       regla nueva (el empleado no puede borrar una tarea asignada)
  frontend/src/pages/tasks/TasksPage.tsx  Sección con pestañas, tarjetas de tareas
  frontend/src/App.tsx                 Ruta /tareas/*
  frontend/src/components/layout/AppShell.tsx  Menú «Notas y tareas» (rótulo corto en el teléfono)
  frontend/src/lib/realtime.ts         Evento «tarea»
  frontend/src/styles/components.css   Tarjetas de notas y tareas
  frontend/src/styles/layout.css       Rótulo corto en el menú móvil. Corrección: la barra inferior
                                       se salía de la pantalla con 6 secciones (el último ítem
                                       quedaba cortado). Pestañas más compactas en el teléfono.
  frontend/src/test/screens.test.tsx   El menú se llama «Notas y tareas»
  README.md                            Funcionalidad y comando de prueba


6. PRUEBAS
------------------------------------------------------------------------------------------
Automáticas:
  - Backend: 165 pruebas, todas pasan; ruff sin errores.
    test_notes_tasks.py cubre los 12 escenarios, más el contrato HTTP con tres sesiones
    independientes y el aviso en vivo.
  - Frontend: 70 pruebas de vitest, todas pasan; TypeScript y ESLint sin errores.
Navegador real (Microsoft Edge), servidor real, administrador y dos empleados con sesiones
separadas (frontend/e2e/notes-tasks.mjs): todo correcto.
   1  El administrador crea una nota y la vuelve a ver ............................. OK
   2  La nota de Ana es privada (ni el administrador ni Beto la ven) ................. OK
   3  Ana crea una tarea personal ...................................................... OK
   4  El administrador crea una tarea personal (Ana no la ve) .......................... OK
   5  El administrador asigna una tarea a Ana ........................................... OK
   6  Ana ve la tarea asignada y su descripción ......................................... OK
   7  Ana la pasa a «En progreso» ....................................................... OK
   8  Ana la marca «Completada» ......................................................... OK
   9  El administrador ve ambos cambios sin recargar (≈230 ms y ≈350 ms) ................ OK
  10  Beto no ve ni modifica las tareas de Ana (lista vacía, 403, 404) .................. OK
  11  Ana no puede eliminar ni cambiar la responsable (403) y no ve esos botones ........ OK
  12  Tras detener y volver a arrancar el servidor, todo sigue guardado ................. OK
  Además: teléfono de 360 px sin desplazamiento horizontal y sin errores de JavaScript.
También se repitieron, sin fallos, la prueba con navegador de Grupos de trabajo y la prueba
general de extremo a extremo (npm run e2e).


7. INSTRUCCIONES DE USO
------------------------------------------------------------------------------------------
- Abra «Notas y tareas» en el menú.
- Notas: «Mis notas» › «Nueva nota» › escriba título y contenido › Guardar. Para buscar, escriba
  en «Buscar notas». En cada tarjeta: Editar o Eliminar (pide confirmación).
- Tareas personales: «Mis tareas» › «Nueva tarea». Cambie el estado en la tarjeta o pulse
  «Marcar como completada». Use Pendientes / Completadas / Todas para filtrar.
- Asignar (administrador): «Tareas asignadas» › «Nueva tarea» › elija el responsable (y, si
  quiere, una fecha límite). El estado se actualiza solo cuando el empleado lo cambia.
- Empleado: «Tareas asignadas» muestra lo que le asignaron. Cambie el estado o marque la tarea
  como completada.
Pruebas:
  cd backend;  .venv\Scripts\python.exe -m pytest tests\test_notes_tasks.py
  cd frontend; npm test;  npm run build;  node e2e/notes-tasks.mjs


8. LIMITACIONES
------------------------------------------------------------------------------------------
- Las notas son texto plano: sin formato, adjuntos ni compartir.
- Sin recordatorios ni notificaciones fuera de la aplicación.
- Cualquier persona con «tareas.gestionar» ve y gestiona todas las tareas asignadas (no solo las
  que creó), igual que antes. Las tareas personales de otros nunca las ve.
- En un teléfono de 360 px, la pestaña «Tareas asignadas» queda parcialmente visible y se llega a
  ella deslizando las pestañas (como en el resto del sistema). Desde 390 px caben las tres.

VERSION = 10
NAME = "tareas por grupo de trabajo: varios responsables, prioridad, estado individual e historial"

# Compatibilidad: no se pierde ninguna tarea ni nota.
# - tasks se reconstruye (SQLite no permite quitar NOT NULL de assignee_id): se copian todas las filas
#   con el mismo id. Las tareas existentes quedan sin grupo (group_id NULL), prioridad «media» y su
#   mismo estado. El responsable único pasa a task_assignees con un estado individual equivalente.
# - task_assignees: una fila por responsable (clave primaria compuesta: sin duplicados). Guarda el
#   estado individual (pendiente / en_curso / completada) y cuándo empezó y terminó cada persona.
# - tasks.status es el estado general: pendiente, en_curso, en_revision, completada o cancelada.
# - task_events: historial de la tarea (creación, ediciones, cambios de responsables y de estado,
#   avances individuales, comentarios y solicitudes de cambio). No se modifica (trigger); se borra
#   solo junto con su tarea (CASCADE), que únicamente se elimina si no tiene avance registrado.
# - Una tarea personal no tiene grupo (CHECK).
SQL = r"""
ALTER TABLE tasks RENAME TO tasks_v9;

CREATE TABLE tasks(
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL CHECK(length(trim(title)) > 0),
  description TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  group_id INTEGER REFERENCES work_groups(id),
  priority TEXT NOT NULL DEFAULT 'media' CHECK(priority IN ('baja','media','alta','urgente')),
  status TEXT NOT NULL DEFAULT 'pendiente'
    CHECK(status IN ('pendiente','en_curso','en_revision','completada','cancelada')),
  due_date TEXT,
  personal INTEGER NOT NULL DEFAULT 0 CHECK(personal IN (0,1)),
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  completed_at TEXT,
  version INTEGER NOT NULL DEFAULT 1,
  CHECK(personal = 0 OR group_id IS NULL)
);
INSERT INTO tasks(id, title, description, status, due_date, personal, created_by, created_at, updated_at, completed_at, version)
  SELECT id, title, description, status, due_date, personal, created_by, created_at, updated_at, completed_at, version
  FROM tasks_v9;

CREATE TABLE task_assignees(
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id),
  status TEXT NOT NULL DEFAULT 'pendiente' CHECK(status IN ('pendiente','en_curso','completada')),
  assigned_at TEXT NOT NULL,
  started_at TEXT,
  completed_at TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(task_id, user_id)
) WITHOUT ROWID;
INSERT INTO task_assignees(task_id, user_id, status, assigned_at, completed_at, updated_at)
  SELECT id, assignee_id, CASE status WHEN 'en_curso' THEN 'en_curso' WHEN 'completada' THEN 'completada' ELSE 'pendiente' END,
         created_at, CASE status WHEN 'completada' THEN completed_at END, updated_at
  FROM tasks_v9;

DROP TABLE tasks_v9;
CREATE INDEX ix_tasks_group ON tasks(group_id, status);
CREATE INDEX ix_tasks_personal ON tasks(personal, status);
CREATE INDEX ix_task_assignees_user ON task_assignees(user_id, status);

CREATE TABLE task_events(
  id INTEGER PRIMARY KEY,
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  user_id INTEGER REFERENCES users(id),
  kind TEXT NOT NULL CHECK(kind IN ('creada','edicion','responsables','estado','avance','comentario','solicitud')),
  details TEXT,
  comment TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX ix_task_events_task ON task_events(task_id, id);
CREATE TRIGGER task_events_no_update BEFORE UPDATE ON task_events
BEGIN SELECT RAISE(ABORT, 'El historial de la tarea no se modifica'); END;
"""

# Reversión manual (restaure antes una copia de seguridad: es la forma segura de volver atrás,
# porque las tareas con varios responsables no caben en el esquema anterior).
DOWN_SQL = r"""
-- Restaure la copia de seguridad anterior a la migración 10.
"""

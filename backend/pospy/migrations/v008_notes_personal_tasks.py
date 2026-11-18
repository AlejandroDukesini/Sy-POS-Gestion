VERSION = 8
NAME = "notas personales y tareas personales"

# Compatibilidad: no modifica ni borra datos existentes.
# - tasks.personal: 0 = asignada (todas las tareas que ya existían), 1 = tarea personal de su responsable.
#   Una sola tabla para ambos tipos; el servicio decide quién ve y modifica cada una.
# - El trigger tasks_no_delete se reemplaza: antes ninguna tarea se podía borrar. Ahora se borran las
#   tareas personales (las borra su dueño) y las asignadas solo las borra quien las gestiona (la
#   eliminación queda en el historial de actividad). El servicio aplica esas reglas.
# - notes: cada nota pertenece a una sola persona (owner_id). Nadie más la consulta.
SQL = r"""
ALTER TABLE tasks ADD COLUMN personal INTEGER NOT NULL DEFAULT 0 CHECK(personal IN (0, 1));
CREATE INDEX ix_tasks_personal ON tasks(personal, assignee_id, status);
DROP TRIGGER IF EXISTS tasks_no_delete;

CREATE TABLE notes(
  id INTEGER PRIMARY KEY,
  owner_id INTEGER NOT NULL REFERENCES users(id),
  title TEXT NOT NULL DEFAULT '',
  content TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  CHECK(length(trim(title)) > 0 OR length(trim(content)) > 0)
);
CREATE INDEX ix_notes_owner ON notes(owner_id, updated_at);
"""

# Reversión manual (restaure antes una copia de seguridad; requiere SQLite >= 3.35 para DROP COLUMN):
DOWN_SQL = r"""
DROP TABLE IF EXISTS notes;
DELETE FROM tasks WHERE personal = 1;
DROP INDEX IF EXISTS ix_tasks_personal;
ALTER TABLE tasks DROP COLUMN personal;
CREATE TRIGGER tasks_no_delete BEFORE DELETE ON tasks
BEGIN SELECT RAISE(ABORT, 'Las tareas no se eliminan: cancélelas'); END;
DELETE FROM schema_migrations WHERE version = 8;
"""

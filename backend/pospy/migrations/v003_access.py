VERSION = 3
NAME = "acceso configurable, sesiones de acceso directo y tareas de empleados"

# Compatibilidad: solo agrega columnas, una tabla y una fila de configuración. No modifica ni borra
# usuarios, contraseñas, permisos ni sesiones existentes.
#
# - Las instalaciones que ya tienen usuarios conservan el inicio de sesión obligatorio y la
#   instalación se considera terminada (mismo comportamiento que antes de esta versión).
# - Una base nueva queda sin fila «acceso»: el asistente de configuración inicial la crea.
# - Un empleado sin cuenta se guarda con password_hash = '' (nunca coincide con ninguna contraseña).
SQL = r"""
ALTER TABLE sessions ADD COLUMN open_mode INTEGER NOT NULL DEFAULT 0 CHECK(open_mode IN (0,1));

INSERT INTO settings(key, value, updated_at)
  SELECT 'acceso', '{"login_enabled": true, "setup_completed": true, "setup_step": "listo"}',
         strftime('%Y-%m-%dT%H:%M:%SZ','now')
  WHERE EXISTS (SELECT 1 FROM users) AND NOT EXISTS (SELECT 1 FROM settings WHERE key = 'acceso');

CREATE TABLE tasks(
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL CHECK(length(trim(title)) > 0),
  description TEXT NOT NULL DEFAULT '',
  assignee_id INTEGER NOT NULL REFERENCES users(id),
  status TEXT NOT NULL DEFAULT 'pendiente' CHECK(status IN ('pendiente','en_curso','completada','cancelada')),
  due_date TEXT,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  completed_at TEXT,
  version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX ix_tasks_assignee ON tasks(assignee_id, status);
CREATE TRIGGER tasks_no_delete BEFORE DELETE ON tasks
BEGIN SELECT RAISE(ABORT, 'Las tareas no se eliminan: cancélelas'); END;
"""

# Reversión manual (restaure antes una copia de seguridad; requiere SQLite >= 3.35 para DROP COLUMN):
DOWN_SQL = r"""
DROP TRIGGER IF EXISTS tasks_no_delete;
DROP TABLE IF EXISTS tasks;
DELETE FROM settings WHERE key = 'acceso';
ALTER TABLE sessions DROP COLUMN open_mode;
DELETE FROM schema_migrations WHERE version = 3;
"""

VERSION = 9
NAME = "columnas personalizables del inventario y columna Observaciones"

# Compatibilidad: solo crea tablas nuevas. La tabla products y sus campos principales (código,
# descripción, precios, costo, IVA, existencias…) no cambian, así que ventas, compras, movimientos y
# contabilidad siguen leyendo exactamente lo mismo.
#
# - inventory_columns: definición de cada columna adicional (nombre, tipo, si es obligatoria, valor
#   predeterminado, opciones de lista, posición, si es del sistema y si está activa o archivada).
#   «Observaciones» viene creada como columna del sistema: no se puede eliminar ni archivar.
# - inventory_custom_values: un valor por producto y columna (clave primaria compuesta: sin
#   duplicados). Un valor vacío no se guarda. Al eliminar una columna se eliminan sus valores (CASCADE);
#   archivarla los conserva.
# Los valores se guardan como texto normalizado según el tipo (entero «12», decimal «12.5», fecha
# «2026-11-18», sí/no «1»/«0», lista: la opción exacta). El servicio valida el tipo antes de guardar.
SQL = r"""
CREATE TABLE inventory_columns(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK(length(trim(name)) BETWEEN 1 AND 60),
  data_type TEXT NOT NULL CHECK(data_type IN ('texto','texto_largo','entero','decimal','fecha','si_no','lista')),
  description TEXT NOT NULL DEFAULT '' CHECK(length(description) <= 300),
  required INTEGER NOT NULL DEFAULT 0 CHECK(required IN (0,1)),
  default_value TEXT,
  options TEXT NOT NULL DEFAULT '[]',
  position INTEGER NOT NULL,
  is_system INTEGER NOT NULL DEFAULT 0 CHECK(is_system IN (0,1)),
  active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  created_by INTEGER REFERENCES users(id),
  updated_by INTEGER REFERENCES users(id),
  version INTEGER NOT NULL DEFAULT 1,
  CHECK(required = 0 OR default_value IS NOT NULL)
);
CREATE INDEX ix_inventory_columns_position ON inventory_columns(active, position);
CREATE TRIGGER inventory_columns_system_no_delete BEFORE DELETE ON inventory_columns WHEN OLD.is_system = 1
BEGIN SELECT RAISE(ABORT, 'Las columnas del sistema no se eliminan'); END;

CREATE TABLE inventory_custom_values(
  product_id INTEGER NOT NULL REFERENCES products(id),
  column_id INTEGER NOT NULL REFERENCES inventory_columns(id) ON DELETE CASCADE,
  value TEXT NOT NULL CHECK(length(value) BETWEEN 1 AND 5000),
  updated_at TEXT NOT NULL,
  updated_by INTEGER REFERENCES users(id),
  PRIMARY KEY(product_id, column_id)
) WITHOUT ROWID;
CREATE INDEX ix_inventory_custom_values_column ON inventory_custom_values(column_id);

INSERT INTO inventory_columns(name, data_type, description, position, is_system, created_at, updated_at)
VALUES ('Observaciones', 'texto_largo', 'Información adicional sobre el producto (texto libre).', 10, 1,
        strftime('%Y-%m-%dT%H:%M:%SZ','now'), strftime('%Y-%m-%dT%H:%M:%SZ','now'));
"""

# Reversión manual (restaure antes una copia de seguridad):
DOWN_SQL = r"""
DROP TABLE IF EXISTS inventory_custom_values;
DROP TABLE IF EXISTS inventory_columns;
DELETE FROM schema_migrations WHERE version = 9;
"""

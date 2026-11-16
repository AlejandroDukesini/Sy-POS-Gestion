VERSION = 6
NAME = "observaciones de inventario: novedades por producto, seguimiento inmutable y adjuntos"

# Compatibilidad: solo crea tablas nuevas que referencian products, suppliers y users por su id.
# No modifica productos, existencias, movimientos, compras, ventas ni costos. Una observación
# DOCUMENTA una situación; ningún trigger ni servicio la convierte en una operación de inventario.
#
# Trazabilidad:
# - Las observaciones no se borran físicamente (trigger): se marcan como eliminadas (deleted_at).
# - El historial de seguimiento (inventory_observation_events) es inmutable: no admite UPDATE ni DELETE.
# - Las categorías viven en su propia tabla para poder agregar más sin cambiar la estructura.
# Los archivos adjuntos se guardan en <datos>/observaciones/<id de la observación>/; aquí solo sus metadatos.
SQL = r"""
CREATE TABLE observation_categories(
  id INTEGER PRIMARY KEY,
  code TEXT NOT NULL UNIQUE CHECK(length(trim(code)) > 0),
  name TEXT NOT NULL CHECK(length(trim(name)) > 0),
  sort_order INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TRIGGER observation_categories_no_delete BEFORE DELETE ON observation_categories
BEGIN SELECT RAISE(ABORT, 'Las categorías de observaciones no se eliminan: desactívelas'); END;

INSERT INTO observation_categories(code, name, sort_order) VALUES
  ('diferencia_inventario', 'Diferencia de inventario', 10),
  ('producto_defectuoso', 'Producto defectuoso', 20),
  ('vencimiento', 'Producto vencido o próximo a vencer', 30),
  ('faltante', 'Faltante de mercancía', 40),
  ('reposicion_pendiente', 'Reposición pendiente', 50),
  ('problema_proveedor', 'Problema con proveedor', 60),
  ('error_informacion', 'Error de información', 70),
  ('problema_precio', 'Problema de precio', 80),
  ('producto_reservado', 'Producto reservado', 90),
  ('otro', 'Otro', 1000);

CREATE TABLE inventory_observations(
  id INTEGER PRIMARY KEY,
  product_id INTEGER NOT NULL REFERENCES products(id),
  category_id INTEGER NOT NULL REFERENCES observation_categories(id),
  priority TEXT NOT NULL CHECK(priority IN ('baja','media','alta','critica')),
  status TEXT NOT NULL DEFAULT 'pendiente' CHECK(status IN ('pendiente','en_proceso','resuelta','cerrada')),
  description TEXT NOT NULL CHECK(length(trim(description)) > 0),
  qty_milli INTEGER CHECK(qty_milli IS NULL OR qty_milli >= 0),
  supplier_id INTEGER REFERENCES suppliers(id),
  reference_doc TEXT NOT NULL DEFAULT '',
  detected_on TEXT NOT NULL,
  follow_up_date TEXT,
  notes TEXT NOT NULL DEFAULT '',
  assigned_to INTEGER REFERENCES users(id),
  created_by INTEGER REFERENCES users(id),
  updated_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  resolved_at TEXT,
  closed_at TEXT,
  deleted_at TEXT,
  deleted_by INTEGER REFERENCES users(id),
  delete_reason TEXT,
  version INTEGER NOT NULL DEFAULT 1,
  CHECK(deleted_at IS NULL OR length(trim(COALESCE(delete_reason, ''))) > 0)
);
CREATE INDEX ix_observations_product ON inventory_observations(product_id, status);
CREATE INDEX ix_observations_status ON inventory_observations(status, priority);
CREATE INDEX ix_observations_created ON inventory_observations(created_at);
CREATE TRIGGER observations_no_delete BEFORE DELETE ON inventory_observations
BEGIN SELECT RAISE(ABORT, 'Las observaciones no se borran: se marcan como eliminadas'); END;

-- Historial de seguimiento: cada acontecimiento es un registro propio que nunca se modifica.
CREATE TABLE inventory_observation_events(
  id INTEGER PRIMARY KEY,
  observation_id INTEGER NOT NULL REFERENCES inventory_observations(id),
  kind TEXT NOT NULL CHECK(kind IN ('creada','comentario','estado','prioridad','edicion','adjunto',
                                    'adjunto_eliminado','eliminada')),
  from_value TEXT,
  to_value TEXT,
  comment TEXT NOT NULL DEFAULT '',
  details TEXT,
  user_id INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL
);
CREATE INDEX ix_observation_events ON inventory_observation_events(observation_id, id);
CREATE TRIGGER observation_events_no_update BEFORE UPDATE ON inventory_observation_events
BEGIN SELECT RAISE(ABORT, 'El historial de seguimiento es inmutable'); END;
CREATE TRIGGER observation_events_no_delete BEFORE DELETE ON inventory_observation_events
BEGIN SELECT RAISE(ABORT, 'El historial de seguimiento es inmutable'); END;

CREATE TABLE inventory_observation_files(
  id INTEGER PRIMARY KEY,
  observation_id INTEGER NOT NULL REFERENCES inventory_observations(id),
  original_name TEXT NOT NULL,
  stored_name TEXT NOT NULL UNIQUE,
  content_type TEXT NOT NULL,
  size_bytes INTEGER NOT NULL CHECK(size_bytes > 0),
  sha256 TEXT NOT NULL,
  uploaded_by INTEGER REFERENCES users(id),
  uploaded_at TEXT NOT NULL
);
CREATE INDEX ix_observation_files ON inventory_observation_files(observation_id);
"""

# Reversión manual (restaure antes una copia de seguridad):
DOWN_SQL = r"""
DROP TABLE IF EXISTS inventory_observation_files;
DROP TABLE IF EXISTS inventory_observation_events;
DROP TABLE IF EXISTS inventory_observations;
DROP TABLE IF EXISTS observation_categories;
DELETE FROM schema_migrations WHERE version = 6;
"""

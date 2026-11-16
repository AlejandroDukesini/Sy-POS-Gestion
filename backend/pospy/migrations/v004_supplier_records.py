VERSION = 4
NAME = "expediente de proveedores: contacto, asesor, notas, visitas, cotizaciones y archivos"

# Compatibilidad: solo agrega columnas (con valor por defecto) a suppliers y tablas nuevas que la
# referencian. No modifica proveedores, compras, cuentas por pagar ni inventario. Las notas, visitas
# y cotizaciones son registros informativos: ningún trigger ni servicio las enlaza con transacciones.
# Los archivos se guardan en <datos>/proveedores/<id del proveedor>/; aquí solo sus metadatos.
SQL = r"""
ALTER TABLE suppliers ADD COLUMN whatsapp TEXT NOT NULL DEFAULT '';
ALTER TABLE suppliers ADD COLUMN city TEXT NOT NULL DEFAULT '';
ALTER TABLE suppliers ADD COLUMN contact_notes TEXT NOT NULL DEFAULT '';
ALTER TABLE suppliers ADD COLUMN advisor_name TEXT NOT NULL DEFAULT '';
ALTER TABLE suppliers ADD COLUMN advisor_phone TEXT NOT NULL DEFAULT '';
ALTER TABLE suppliers ADD COLUMN advisor_email TEXT NOT NULL DEFAULT '';
ALTER TABLE suppliers ADD COLUMN advisor_notes TEXT NOT NULL DEFAULT '';

CREATE TABLE supplier_notes(
  id INTEGER PRIMARY KEY,
  supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
  category TEXT NOT NULL DEFAULT 'general'
    CHECK(category IN ('deuda','pago','entrega','acuerdo','reclamacion','seguimiento','general')),
  title TEXT NOT NULL CHECK(length(trim(title)) > 0),
  body TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pendiente' CHECK(status IN ('pendiente','resuelta')),
  important INTEGER NOT NULL DEFAULT 0 CHECK(important IN (0,1)),
  due_date TEXT,
  created_by INTEGER REFERENCES users(id),
  updated_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  resolved_at TEXT,
  version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX ix_supplier_notes ON supplier_notes(supplier_id, status);

CREATE TABLE supplier_visits(
  id INTEGER PRIMARY KEY,
  supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
  visit_date TEXT NOT NULL,
  advisor_name TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL CHECK(length(trim(reason)) > 0),
  summary TEXT NOT NULL DEFAULT '',
  agreements TEXT NOT NULL DEFAULT '',
  next_visit_date TEXT,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX ix_supplier_visits ON supplier_visits(supplier_id, visit_date);

CREATE TABLE supplier_quotes(
  id INTEGER PRIMARY KEY,
  supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
  number TEXT NOT NULL CHECK(length(trim(number)) > 0),
  issue_date TEXT NOT NULL,
  due_date TEXT,
  advisor_name TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  total_cents INTEGER CHECK(total_cents IS NULL OR total_cents >= 0),
  status TEXT NOT NULL DEFAULT 'pendiente' CHECK(status IN ('pendiente','aceptada','rechazada','vencida')),
  notes TEXT NOT NULL DEFAULT '',
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  UNIQUE(supplier_id, number COLLATE NOCASE)
);
CREATE INDEX ix_supplier_quotes ON supplier_quotes(supplier_id, issue_date);

-- Archivos: listas de productos (con versiones) y adjuntos de cotizaciones.
CREATE TABLE supplier_files(
  id INTEGER PRIMARY KEY,
  supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
  kind TEXT NOT NULL CHECK(kind IN ('productos','cotizacion')),
  quote_id INTEGER REFERENCES supplier_quotes(id),
  original_name TEXT NOT NULL,
  stored_name TEXT NOT NULL UNIQUE,
  content_type TEXT NOT NULL,
  size_bytes INTEGER NOT NULL CHECK(size_bytes > 0),
  sha256 TEXT NOT NULL,
  uploaded_by INTEGER REFERENCES users(id),
  uploaded_at TEXT NOT NULL,
  CHECK((kind = 'cotizacion') = (quote_id IS NOT NULL))
);
CREATE INDEX ix_supplier_files ON supplier_files(supplier_id, kind, uploaded_at);
CREATE UNIQUE INDEX ux_supplier_quote_file ON supplier_files(quote_id) WHERE quote_id IS NOT NULL;
"""

# Reversión manual (restaure antes una copia de seguridad; DROP COLUMN requiere SQLite >= 3.35):
DOWN_SQL = r"""
DROP TABLE IF EXISTS supplier_files;
DROP TABLE IF EXISTS supplier_quotes;
DROP TABLE IF EXISTS supplier_visits;
DROP TABLE IF EXISTS supplier_notes;
ALTER TABLE suppliers DROP COLUMN advisor_notes;
ALTER TABLE suppliers DROP COLUMN advisor_email;
ALTER TABLE suppliers DROP COLUMN advisor_phone;
ALTER TABLE suppliers DROP COLUMN advisor_name;
ALTER TABLE suppliers DROP COLUMN contact_notes;
ALTER TABLE suppliers DROP COLUMN city;
ALTER TABLE suppliers DROP COLUMN whatsapp;
DELETE FROM schema_migrations WHERE version = 4;
"""

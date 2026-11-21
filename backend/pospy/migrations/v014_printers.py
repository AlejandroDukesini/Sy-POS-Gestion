VERSION = 14
NAME = "impresora por plantilla y descuento manual máximo de 20 %"

# Compatibilidad: no borra datos.
# - print_templates.printer: impresora de Windows de la plantilla ('' = la predeterminada de Configuración › Impresión).
# - print_jobs admite el modo «directa» (se reconstruye la tabla conservando todos los registros).
# - Descuento manual máximo: el valor de fábrica pasa de 10 % a 20 %. Solo se cambia si seguía en 10 %
#   (si el administrador había elegido otro valor, se respeta).
DISCOUNT_SQL = r"""
UPDATE settings SET value = json_set(value, '$.max_manual_discount_pct', 20)
 WHERE key = 'ventas' AND json_extract(value, '$.max_manual_discount_pct') = 10;
"""

SQL = r"""
ALTER TABLE print_templates ADD COLUMN printer TEXT NOT NULL DEFAULT '';
-- Trabajos de impresión: nuevo modo «directa» (plantilla dibujada en la impresora de Windows, sin Excel).
CREATE TABLE print_jobs_new(
  id INTEGER PRIMARY KEY,
  created_at TEXT NOT NULL,
  user_id INTEGER REFERENCES users(id),
  target_type TEXT NOT NULL CHECK(target_type IN ('venta','documento','devolucion','prueba')),
  target_id INTEGER,
  target_label TEXT NOT NULL DEFAULT '',
  printer TEXT NOT NULL DEFAULT '',
  mode TEXT NOT NULL CHECK(mode IN ('escpos','excel','navegador','directa')),
  copies INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL CHECK(status IN ('ok','error')),
  error TEXT
);
INSERT INTO print_jobs_new SELECT id, created_at, user_id, target_type, target_id, target_label, printer, mode, copies, status, error
  FROM print_jobs;
DROP TABLE print_jobs;
ALTER TABLE print_jobs_new RENAME TO print_jobs;
CREATE INDEX ix_print_jobs_target ON print_jobs(target_type, target_id);
""" + DISCOUNT_SQL

# Reversión manual (restaure antes una copia de seguridad; requiere SQLite >= 3.35 para DROP COLUMN):
DOWN_SQL = r"""
ALTER TABLE print_templates DROP COLUMN printer;
DELETE FROM schema_migrations WHERE version = 14;
"""

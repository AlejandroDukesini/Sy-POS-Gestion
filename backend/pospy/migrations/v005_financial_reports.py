VERSION = 5
NAME = "informes financieros guardados: instantáneas, revisiones y observaciones"

# Compatibilidad: solo crea tablas nuevas y una secuencia. No toca ventas, pagos, devoluciones, caja,
# cartera, asientos ni inventario. Un informe guardado es una instantánea (JSON) de cifras calculadas
# a partir de esos registros: no es una venta ni un ingreso, y nada en el POS lo lee como tal.
#
# Trazabilidad: las cifras de un informe no se pueden modificar (trigger). Si las operaciones del
# periodo cambian después, se genera una REVISIÓN nueva (revision + 1, mismo root_id) y la anterior
# pasa a estado 'reemplazado' conservando sus cifras originales. Los informes no se eliminan.
SQL = r"""
CREATE TABLE financial_reports(
  id INTEGER PRIMARY KEY,
  number TEXT NOT NULL UNIQUE,
  idempotency_key TEXT UNIQUE,
  name TEXT NOT NULL CHECK(length(trim(name)) > 0),
  kind TEXT NOT NULL CHECK(kind IN ('diario','semanal','mensual','anual','personalizado')),
  closure TEXT NOT NULL CHECK(closure IN ('habitual','anticipado','personalizado')),
  date_from TEXT NOT NULL,
  date_to TEXT NOT NULL,
  days INTEGER NOT NULL CHECK(days > 0),
  period_days INTEGER NOT NULL CHECK(period_days > 0),
  in_progress INTEGER NOT NULL DEFAULT 0 CHECK(in_progress IN (0,1)),
  week_start TEXT NOT NULL,
  data TEXT NOT NULL,
  data_sha256 TEXT NOT NULL,
  net_sales_cents INTEGER NOT NULL,
  total_received_cents INTEGER NOT NULL,
  sales_count INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'vigente' CHECK(status IN ('vigente','reemplazado')),
  revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
  root_id INTEGER REFERENCES financial_reports(id),
  previous_id INTEGER REFERENCES financial_reports(id),
  replaced_by_id INTEGER REFERENCES financial_reports(id),
  generated_by INTEGER REFERENCES users(id),
  generated_at TEXT NOT NULL,
  CHECK(date_to >= date_from)
);
CREATE INDEX ix_financial_reports_period ON financial_reports(date_from, date_to);
CREATE INDEX ix_financial_reports_root ON financial_reports(root_id);

CREATE TRIGGER financial_reports_no_delete BEFORE DELETE ON financial_reports
BEGIN SELECT RAISE(ABORT, 'Los informes guardados no se eliminan'); END;
CREATE TRIGGER financial_reports_frozen BEFORE UPDATE ON financial_reports
  WHEN NEW.data IS NOT OLD.data OR NEW.data_sha256 IS NOT OLD.data_sha256 OR NEW.date_from IS NOT OLD.date_from
    OR NEW.date_to IS NOT OLD.date_to OR NEW.kind IS NOT OLD.kind OR NEW.closure IS NOT OLD.closure
    OR NEW.net_sales_cents IS NOT OLD.net_sales_cents OR NEW.total_received_cents IS NOT OLD.total_received_cents
    OR NEW.generated_at IS NOT OLD.generated_at OR NEW.generated_by IS NOT OLD.generated_by
    OR NEW.number IS NOT OLD.number OR NEW.revision IS NOT OLD.revision
BEGIN SELECT RAISE(ABORT, 'Las cifras de un informe guardado no se modifican: genere una revisión'); END;

CREATE TABLE financial_report_notes(
  id INTEGER PRIMARY KEY,
  report_id INTEGER NOT NULL REFERENCES financial_reports(id),
  category TEXT NOT NULL DEFAULT 'general'
    CHECK(category IN ('general','incidencia','diferencia_caja','aclaracion','extraordinaria')),
  body TEXT NOT NULL CHECK(length(trim(body)) > 0),
  amount_cents INTEGER,
  copied_from_id INTEGER REFERENCES financial_report_notes(id),
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  updated_by INTEGER REFERENCES users(id),
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX ix_financial_report_notes ON financial_report_notes(report_id);

INSERT OR IGNORE INTO sequences(name, prefix, next_value, padding) VALUES ('informe', 'INF-', 1, 5);
"""

DOWN_SQL = r"""
DROP TABLE IF EXISTS financial_report_notes;
DROP TRIGGER IF EXISTS financial_reports_frozen;
DROP TRIGGER IF EXISTS financial_reports_no_delete;
DROP TABLE IF EXISTS financial_reports;
DELETE FROM sequences WHERE name = 'informe';
"""

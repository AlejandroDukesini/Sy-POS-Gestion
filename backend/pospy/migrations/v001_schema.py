VERSION = 1
NAME = "esquema inicial"

# Convenciones: dinero en centavos (INTEGER), cantidades en milésimas, porcentajes en puntos básicos,
# instantes en UTC ISO-8601 y fechas de negocio AAAA-MM-DD. Los registros contables, los movimientos
# de inventario y la auditoría son inmutables: las correcciones se hacen con reversos enlazados.
SQL = r"""
-- ------------------------------------------------------------------ usuarios y sesiones
CREATE TABLE users(
  id INTEGER PRIMARY KEY,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK(length(username) BETWEEN 3 AND 40),
  full_name TEXT NOT NULL CHECK(length(trim(full_name)) > 0),
  role TEXT NOT NULL CHECK(role IN ('admin','employee')),
  password_hash TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
  must_change_password INTEGER NOT NULL DEFAULT 0 CHECK(must_change_password IN (0,1)),
  failed_attempts INTEGER NOT NULL DEFAULT 0,
  locked_until TEXT,
  session_version INTEGER NOT NULL DEFAULT 1,
  last_login_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1
);
CREATE TRIGGER users_no_delete BEFORE DELETE ON users
BEGIN SELECT RAISE(ABORT, 'Los usuarios no se eliminan: desactívelos'); END;

CREATE TABLE user_permissions(
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  permission TEXT NOT NULL,
  PRIMARY KEY(user_id, permission)
);

CREATE TABLE sessions(
  id INTEGER PRIMARY KEY,
  token_hash TEXT NOT NULL UNIQUE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  session_version INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  revoked_at TEXT,
  client TEXT
);
CREATE INDEX ix_sessions_user ON sessions(user_id);

CREATE TABLE user_prefs(
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  data TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- ------------------------------------------------------------------ configuración, secretos, auditoría
CREATE TABLE settings(
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  updated_by INTEGER REFERENCES users(id)
);

CREATE TABLE secrets(
  name TEXT PRIMARY KEY,
  ciphertext BLOB NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE sequences(
  name TEXT PRIMARY KEY,
  prefix TEXT NOT NULL,
  next_value INTEGER NOT NULL CHECK(next_value > 0),
  padding INTEGER NOT NULL DEFAULT 6
);

CREATE TABLE audit_log(
  id INTEGER PRIMARY KEY,
  created_at TEXT NOT NULL,
  user_id INTEGER REFERENCES users(id),
  username TEXT,
  action TEXT NOT NULL,
  entity TEXT,
  entity_id TEXT,
  details TEXT
);
CREATE INDEX ix_audit_created ON audit_log(created_at);
CREATE INDEX ix_audit_entity ON audit_log(entity, entity_id);
CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'La auditoría es inmutable'); END;
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'La auditoría es inmutable'); END;

-- ------------------------------------------------------------------ terceros y catálogos
CREATE TABLE categories(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK(length(trim(name)) > 0),
  active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE customers(
  id INTEGER PRIMARY KEY,
  identification TEXT UNIQUE COLLATE NOCASE,
  name TEXT NOT NULL CHECK(length(trim(name)) > 0),
  phone TEXT NOT NULL DEFAULT '',
  email TEXT NOT NULL DEFAULT '',
  address TEXT NOT NULL DEFAULT '',
  credit_days INTEGER NOT NULL DEFAULT 30 CHECK(credit_days BETWEEN 0 AND 365),
  active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE suppliers(
  id INTEGER PRIMARY KEY,
  identification TEXT UNIQUE COLLATE NOCASE,
  name TEXT NOT NULL CHECK(length(trim(name)) > 0),
  phone TEXT NOT NULL DEFAULT '',
  email TEXT NOT NULL DEFAULT '',
  address TEXT NOT NULL DEFAULT '',
  payment_days INTEGER NOT NULL DEFAULT 30 CHECK(payment_days BETWEEN 0 AND 365),
  active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1
);

-- ------------------------------------------------------------------ contabilidad (plan de cuentas)
CREATE TABLE accounts(
  id INTEGER PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  type TEXT NOT NULL CHECK(type IN ('activo','pasivo','patrimonio','ingreso','costo','gasto')),
  is_cash INTEGER NOT NULL DEFAULT 0 CHECK(is_cash IN (0,1)),
  cost_behavior TEXT CHECK(cost_behavior IN ('fijo','variable')),
  system INTEGER NOT NULL DEFAULT 0 CHECK(system IN (0,1)),
  active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
  created_at TEXT NOT NULL
);

CREATE TABLE payment_methods(
  id INTEGER PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('efectivo','tarjeta','transferencia','credito','otro')),
  account_id INTEGER REFERENCES accounts(id),
  active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
  sort_order INTEGER NOT NULL DEFAULT 0,
  CHECK((kind = 'credito') = (account_id IS NULL))
);

-- ------------------------------------------------------------------ inventario
CREATE TABLE products(
  id INTEGER PRIMARY KEY,
  code TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK(length(trim(code)) > 0),
  description TEXT NOT NULL CHECK(length(trim(description)) > 0),
  category_id INTEGER REFERENCES categories(id),
  unit TEXT NOT NULL DEFAULT 'und',
  price_cents INTEGER NOT NULL CHECK(price_cents >= 0),
  discount_price_cents INTEGER CHECK(discount_price_cents IS NULL OR (discount_price_cents >= 0 AND discount_price_cents <= price_cents)),
  cost_cents INTEGER NOT NULL DEFAULT 0 CHECK(cost_cents >= 0),
  tax_rate_bp INTEGER NOT NULL DEFAULT 0 CHECK(tax_rate_bp BETWEEN 0 AND 10000),
  stock_milli INTEGER NOT NULL DEFAULT 0,
  min_stock_milli INTEGER NOT NULL DEFAULT 0 CHECK(min_stock_milli >= 0),
  active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
  external_ref TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  created_by INTEGER REFERENCES users(id),
  updated_by INTEGER REFERENCES users(id),
  version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX ix_products_description ON products(description COLLATE NOCASE);
CREATE INDEX ix_products_active ON products(active);

CREATE TABLE inventory_movements(
  id INTEGER PRIMARY KEY,
  product_id INTEGER NOT NULL REFERENCES products(id),
  kind TEXT NOT NULL CHECK(kind IN ('inicial','entrada','salida','ajuste','venta','devolucion','anulacion_venta','conciliacion')),
  qty_milli INTEGER NOT NULL CHECK(qty_milli <> 0),
  stock_after_milli INTEGER NOT NULL,
  unit_cost_cents INTEGER NOT NULL DEFAULT 0 CHECK(unit_cost_cents >= 0),
  reason TEXT NOT NULL CHECK(length(trim(reason)) > 0),
  reference_type TEXT,
  reference_id INTEGER,
  user_id INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  idempotency_key TEXT UNIQUE
);
CREATE INDEX ix_moves_product ON inventory_movements(product_id, id);
CREATE INDEX ix_moves_created ON inventory_movements(created_at);
CREATE INDEX ix_moves_reference ON inventory_movements(reference_type, reference_id);

-- La existencia en products es una caché de SUM(qty_milli): solo la cambia este trigger, y otro
-- trigger rechaza cualquier escritura directa que no coincida con el libro de movimientos.
CREATE TRIGGER moves_apply_stock AFTER INSERT ON inventory_movements
BEGIN
  UPDATE products SET stock_milli = stock_milli + NEW.qty_milli WHERE id = NEW.product_id;
END;
CREATE TRIGGER products_stock_guard BEFORE UPDATE OF stock_milli ON products
  WHEN NEW.stock_milli <> (SELECT COALESCE(SUM(qty_milli), 0) FROM inventory_movements WHERE product_id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'La existencia solo cambia mediante movimientos de inventario'); END;
CREATE TRIGGER moves_no_update BEFORE UPDATE ON inventory_movements
BEGIN SELECT RAISE(ABORT, 'Los movimientos de inventario son inmutables'); END;
CREATE TRIGGER moves_no_delete BEFORE DELETE ON inventory_movements
BEGIN SELECT RAISE(ABORT, 'Los movimientos de inventario son inmutables'); END;
CREATE TRIGGER products_no_delete BEFORE DELETE ON products
BEGIN SELECT RAISE(ABORT, 'Los productos no se eliminan: desactívelos'); END;

-- ------------------------------------------------------------------ ventas
CREATE TABLE sales(
  id INTEGER PRIMARY KEY,
  number TEXT NOT NULL UNIQUE,
  idempotency_key TEXT NOT NULL UNIQUE,
  customer_id INTEGER REFERENCES customers(id),
  customer_name TEXT NOT NULL DEFAULT '',
  customer_identification TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'completada' CHECK(status IN ('completada','anulada')),
  gross_cents INTEGER NOT NULL,
  discount_cents INTEGER NOT NULL,
  total_cents INTEGER NOT NULL CHECK(total_cents >= 0),
  tax_cents INTEGER NOT NULL,
  cost_cents INTEGER NOT NULL,
  paid_cents INTEGER NOT NULL,
  credit_cents INTEGER NOT NULL DEFAULT 0,
  change_cents INTEGER NOT NULL DEFAULT 0,
  notes TEXT NOT NULL DEFAULT '',
  sale_date TEXT NOT NULL,
  user_id INTEGER NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL,
  voided_at TEXT,
  voided_by INTEGER REFERENCES users(id),
  void_reason TEXT,
  source_document_id INTEGER
);
CREATE INDEX ix_sales_date ON sales(sale_date);
CREATE INDEX ix_sales_customer ON sales(customer_id);

CREATE TABLE sale_lines(
  id INTEGER PRIMARY KEY,
  sale_id INTEGER NOT NULL REFERENCES sales(id),
  line_no INTEGER NOT NULL,
  product_id INTEGER NOT NULL REFERENCES products(id),
  code TEXT NOT NULL,
  description TEXT NOT NULL,
  qty_milli INTEGER NOT NULL CHECK(qty_milli > 0),
  list_price_cents INTEGER NOT NULL,
  unit_price_cents INTEGER NOT NULL,
  manual_discount_bp INTEGER NOT NULL DEFAULT 0,
  gross_cents INTEGER NOT NULL,
  discount_cents INTEGER NOT NULL,
  net_cents INTEGER NOT NULL,
  tax_rate_bp INTEGER NOT NULL,
  tax_cents INTEGER NOT NULL,
  unit_cost_cents INTEGER NOT NULL,
  returned_milli INTEGER NOT NULL DEFAULT 0,
  CHECK(returned_milli BETWEEN 0 AND qty_milli),
  UNIQUE(sale_id, line_no)
);

CREATE TABLE sale_payments(
  id INTEGER PRIMARY KEY,
  sale_id INTEGER NOT NULL REFERENCES sales(id),
  method_id INTEGER NOT NULL REFERENCES payment_methods(id),
  amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
  tendered_cents INTEGER,
  reference TEXT NOT NULL DEFAULT ''
);

CREATE TABLE sale_returns(
  id INTEGER PRIMARY KEY,
  number TEXT NOT NULL UNIQUE,
  idempotency_key TEXT NOT NULL UNIQUE,
  sale_id INTEGER NOT NULL REFERENCES sales(id),
  reason TEXT NOT NULL CHECK(length(trim(reason)) > 0),
  refund_method_id INTEGER REFERENCES payment_methods(id),
  total_cents INTEGER NOT NULL CHECK(total_cents >= 0),
  tax_cents INTEGER NOT NULL,
  cost_cents INTEGER NOT NULL,
  credit_applied_cents INTEGER NOT NULL DEFAULT 0,
  refund_cents INTEGER NOT NULL DEFAULT 0,
  return_date TEXT NOT NULL,
  user_id INTEGER NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL
);

CREATE TABLE sale_return_lines(
  id INTEGER PRIMARY KEY,
  return_id INTEGER NOT NULL REFERENCES sale_returns(id),
  sale_line_id INTEGER NOT NULL REFERENCES sale_lines(id),
  qty_milli INTEGER NOT NULL CHECK(qty_milli > 0),
  net_cents INTEGER NOT NULL,
  tax_cents INTEGER NOT NULL,
  cost_cents INTEGER NOT NULL
);

-- ------------------------------------------------------------------ documentos comerciales
CREATE TABLE document_types(
  id INTEGER PRIMARY KEY,
  code TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK(code GLOB '[a-z0-9_-]*' AND length(code) BETWEEN 2 AND 30),
  name TEXT NOT NULL CHECK(length(trim(name)) > 0),
  template_file TEXT,
  template_sha256 TEXT,
  mapping TEXT NOT NULL DEFAULT '{}',
  fields TEXT NOT NULL DEFAULT '[]',          -- campos adicionales [{key, label, required}]
  prefix TEXT NOT NULL DEFAULT '',
  next_number INTEGER NOT NULL DEFAULT 1 CHECK(next_number > 0),
  numbering INTEGER NOT NULL DEFAULT 1 CHECK(numbering IN (0,1)),
  validity_days INTEGER NOT NULL DEFAULT 0 CHECK(validity_days BETWEEN 0 AND 365),
  printer TEXT NOT NULL DEFAULT '',
  page_setup TEXT NOT NULL DEFAULT '{}',
  active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE commercial_documents(
  id INTEGER PRIMARY KEY,
  type_id INTEGER NOT NULL REFERENCES document_types(id),
  number TEXT NOT NULL,
  idempotency_key TEXT UNIQUE,
  status TEXT NOT NULL DEFAULT 'vigente' CHECK(status IN ('vigente','anulado')),
  customer_id INTEGER REFERENCES customers(id),
  customer_name TEXT NOT NULL DEFAULT '',
  customer_identification TEXT NOT NULL DEFAULT '',
  customer_phone TEXT NOT NULL DEFAULT '',
  customer_email TEXT NOT NULL DEFAULT '',
  customer_address TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  extra TEXT NOT NULL DEFAULT '{}',
  doc_date TEXT NOT NULL,
  valid_until TEXT,
  gross_cents INTEGER NOT NULL,
  discount_cents INTEGER NOT NULL,
  tax_cents INTEGER NOT NULL,
  total_cents INTEGER NOT NULL,
  user_id INTEGER NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  UNIQUE(type_id, number)
);

CREATE TABLE commercial_document_lines(
  id INTEGER PRIMARY KEY,
  document_id INTEGER NOT NULL REFERENCES commercial_documents(id) ON DELETE CASCADE,
  line_no INTEGER NOT NULL,
  product_id INTEGER REFERENCES products(id),
  code TEXT NOT NULL,
  description TEXT NOT NULL,
  qty_milli INTEGER NOT NULL CHECK(qty_milli > 0),
  list_price_cents INTEGER NOT NULL,
  unit_price_cents INTEGER NOT NULL,
  manual_discount_bp INTEGER NOT NULL DEFAULT 0,
  gross_cents INTEGER NOT NULL,
  discount_cents INTEGER NOT NULL,
  net_cents INTEGER NOT NULL,
  tax_rate_bp INTEGER NOT NULL,
  tax_cents INTEGER NOT NULL,
  UNIQUE(document_id, line_no)
);

CREATE TABLE document_outputs(
  id INTEGER PRIMARY KEY,
  document_id INTEGER NOT NULL REFERENCES commercial_documents(id),
  file_name TEXT NOT NULL,
  template_sha256 TEXT,
  user_id INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL
);

CREATE TABLE print_jobs(
  id INTEGER PRIMARY KEY,
  created_at TEXT NOT NULL,
  user_id INTEGER REFERENCES users(id),
  target_type TEXT NOT NULL CHECK(target_type IN ('venta','documento','devolucion','prueba')),
  target_id INTEGER,
  target_label TEXT NOT NULL DEFAULT '',
  printer TEXT NOT NULL DEFAULT '',
  mode TEXT NOT NULL CHECK(mode IN ('escpos','excel','navegador')),
  copies INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL CHECK(status IN ('ok','error')),
  error TEXT
);
CREATE INDEX ix_print_jobs_target ON print_jobs(target_type, target_id);

-- ------------------------------------------------------------------ libro diario
CREATE TABLE journal_entries(
  id INTEGER PRIMARY KEY,
  entry_date TEXT NOT NULL,
  description TEXT NOT NULL CHECK(length(trim(description)) > 0),
  source_type TEXT NOT NULL,
  source_id INTEGER,
  purpose TEXT NOT NULL DEFAULT 'principal',
  reverses_id INTEGER REFERENCES journal_entries(id),
  reversed_by_id INTEGER REFERENCES journal_entries(id),
  user_id INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  UNIQUE(source_type, source_id, purpose)
);
CREATE INDEX ix_entries_date ON journal_entries(entry_date);

CREATE TABLE journal_lines(
  id INTEGER PRIMARY KEY,
  entry_id INTEGER NOT NULL REFERENCES journal_entries(id),
  account_id INTEGER NOT NULL REFERENCES accounts(id),
  debit_cents INTEGER NOT NULL DEFAULT 0 CHECK(debit_cents >= 0),
  credit_cents INTEGER NOT NULL DEFAULT 0 CHECK(credit_cents >= 0),
  party_type TEXT CHECK(party_type IN ('cliente','proveedor')),
  party_id INTEGER,
  memo TEXT NOT NULL DEFAULT '',
  CHECK((debit_cents = 0) <> (credit_cents = 0))
);
CREATE INDEX ix_lines_entry ON journal_lines(entry_id);
CREATE INDEX ix_lines_account ON journal_lines(account_id);

CREATE TRIGGER entries_no_delete BEFORE DELETE ON journal_entries
BEGIN SELECT RAISE(ABORT, 'Los asientos no se eliminan: se reversan'); END;
CREATE TRIGGER entries_only_link_reversal BEFORE UPDATE ON journal_entries
  WHEN OLD.reversed_by_id IS NOT NULL OR NEW.reversed_by_id IS NULL
    OR NEW.entry_date <> OLD.entry_date OR NEW.description <> OLD.description
    OR NEW.source_type <> OLD.source_type OR NEW.source_id IS NOT OLD.source_id OR NEW.purpose <> OLD.purpose
BEGIN SELECT RAISE(ABORT, 'Los asientos son inmutables'); END;
CREATE TRIGGER lines_no_update BEFORE UPDATE ON journal_lines
BEGIN SELECT RAISE(ABORT, 'Los asientos son inmutables'); END;
CREATE TRIGGER lines_no_delete BEFORE DELETE ON journal_lines
BEGIN SELECT RAISE(ABORT, 'Los asientos son inmutables'); END;

-- ------------------------------------------------------------------ cuentas por cobrar y por pagar
CREATE TABLE receivables(
  id INTEGER PRIMARY KEY,
  number TEXT NOT NULL UNIQUE,
  customer_id INTEGER NOT NULL REFERENCES customers(id),
  source_type TEXT NOT NULL CHECK(source_type IN ('venta','manual')),
  source_id INTEGER,
  issue_date TEXT NOT NULL,
  due_date TEXT NOT NULL,
  amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
  description TEXT NOT NULL DEFAULT '',
  income_account_id INTEGER REFERENCES accounts(id),
  status TEXT NOT NULL DEFAULT 'vigente' CHECK(status IN ('vigente','anulada')),
  user_id INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  CHECK(due_date >= issue_date)
);
CREATE INDEX ix_receivables_customer ON receivables(customer_id);

-- Ajustes que reducen el saldo sin ser cobros: devoluciones sobre ventas a crédito.
CREATE TABLE receivable_credits(
  id INTEGER PRIMARY KEY,
  receivable_id INTEGER NOT NULL REFERENCES receivables(id),
  amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
  source_type TEXT NOT NULL,
  source_id INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(source_type, source_id, receivable_id)
);

CREATE TABLE receivable_payments(
  id INTEGER PRIMARY KEY,
  receivable_id INTEGER NOT NULL REFERENCES receivables(id),
  idempotency_key TEXT NOT NULL UNIQUE,
  payment_date TEXT NOT NULL,
  amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
  method_id INTEGER NOT NULL REFERENCES payment_methods(id),
  reference TEXT NOT NULL DEFAULT '',
  user_id INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  voided_at TEXT,
  voided_by INTEGER REFERENCES users(id),
  void_reason TEXT
);

CREATE TABLE payables(
  id INTEGER PRIMARY KEY,
  supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
  number TEXT NOT NULL,
  issue_date TEXT NOT NULL,
  due_date TEXT NOT NULL,
  amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
  description TEXT NOT NULL DEFAULT '',
  debit_account_id INTEGER NOT NULL REFERENCES accounts(id),
  source_type TEXT NOT NULL DEFAULT 'manual' CHECK(source_type IN ('manual','entrada_inventario')),
  source_id INTEGER,
  status TEXT NOT NULL DEFAULT 'vigente' CHECK(status IN ('vigente','anulada')),
  user_id INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  UNIQUE(supplier_id, number),
  CHECK(due_date >= issue_date)
);

CREATE TABLE payable_payments(
  id INTEGER PRIMARY KEY,
  payable_id INTEGER NOT NULL REFERENCES payables(id),
  idempotency_key TEXT NOT NULL UNIQUE,
  payment_date TEXT NOT NULL,
  amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
  method_id INTEGER NOT NULL REFERENCES payment_methods(id),
  reference TEXT NOT NULL DEFAULT '',
  user_id INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  voided_at TEXT,
  voided_by INTEGER REFERENCES users(id),
  void_reason TEXT
);

-- ------------------------------------------------------------------ conciliación bancaria
CREATE TABLE reconciliations(
  id INTEGER PRIMARY KEY,
  account_id INTEGER NOT NULL REFERENCES accounts(id),
  statement_date TEXT NOT NULL,
  statement_balance_cents INTEGER NOT NULL,
  book_balance_cents INTEGER NOT NULL,
  reconciled_balance_cents INTEGER NOT NULL,
  difference_cents INTEGER NOT NULL,
  notes TEXT NOT NULL DEFAULT '',
  user_id INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL
);
CREATE TABLE reconciliation_items(
  reconciliation_id INTEGER NOT NULL REFERENCES reconciliations(id),
  journal_line_id INTEGER NOT NULL UNIQUE REFERENCES journal_lines(id),
  PRIMARY KEY(reconciliation_id, journal_line_id)
);

-- ------------------------------------------------------------------ integraciones de inventario
CREATE TABLE integration_connections(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  provider TEXT NOT NULL CHECK(provider IN ('excel','carpeta','onedrive','gdrive')),
  config TEXT NOT NULL DEFAULT '{}',
  is_master INTEGER NOT NULL DEFAULT 0 CHECK(is_master IN (0,1)),
  sync_mode TEXT NOT NULL DEFAULT 'manual' CHECK(sync_mode IN ('manual','intervalo')),
  sync_interval_min INTEGER NOT NULL DEFAULT 60 CHECK(sync_interval_min BETWEEN 5 AND 1440),
  stock_policy TEXT NOT NULL DEFAULT 'informar' CHECK(stock_policy IN ('informar','ajustar')),
  update_catalog INTEGER NOT NULL DEFAULT 1 CHECK(update_catalog IN (0,1)),
  create_missing INTEGER NOT NULL DEFAULT 1 CHECK(create_missing IN (0,1)),
  active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
  last_sync_at TEXT,
  last_status TEXT,
  last_message TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX ux_single_master ON integration_connections(is_master) WHERE is_master = 1;

CREATE TABLE sync_runs(
  id INTEGER PRIMARY KEY,
  connection_id INTEGER REFERENCES integration_connections(id),   -- NULL: importación manual de un archivo
  source_label TEXT NOT NULL DEFAULT '',
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL CHECK(status IN ('vista_previa','aplicada','error','descartada')),
  trigger TEXT NOT NULL CHECK(trigger IN ('manual','automatica','archivo')),
  source_sha256 TEXT,
  summary TEXT NOT NULL DEFAULT '{}',
  user_id INTEGER REFERENCES users(id)
);
"""

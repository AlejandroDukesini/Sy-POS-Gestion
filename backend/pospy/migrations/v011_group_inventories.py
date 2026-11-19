VERSION = 11
NAME = "inventario por grupo: productos del grupo, ventas y documentos del grupo, estado de las devoluciones"
FOREIGN_KEYS_OFF = True   # reconstruye products, que otras tablas referencian (procedimiento oficial de SQLite)

# Compatibilidad: no se pierde ni cambia ningún dato.
# - products se reconstruye con los mismos id y la columna group_id:
#     NULL  = «Inventario general» del negocio (todos los productos que ya existían quedan aquí).
#     G     = inventario del grupo de trabajo G. Cada grupo tiene su propio inventario.
#   El código deja de ser único en todo el sistema y pasa a ser único DENTRO de cada inventario
#   (dos sucursales pueden usar el mismo código). Un producto no cambia de inventario (trigger).
#   Se vuelven a crear los mismos índices y triggers (la existencia sigue siendo la suma de movimientos).
# - sales.group_id y commercial_documents.group_id: inventario al que pertenece la venta o el documento.
#   Las existentes quedan en el inventario general.
# - sale_return_lines.condition: apto (vuelve al inventario), revision (pendiente de revisar, aún no
#   vuelve) o no_apto (no vuelve). Las devoluciones anteriores reingresaron todas: quedan como «apto».
SQL = r"""
DROP TRIGGER IF EXISTS moves_apply_stock;
DROP TRIGGER IF EXISTS products_stock_guard;
DROP TRIGGER IF EXISTS products_no_delete;

CREATE TABLE products_v11(
  id INTEGER PRIMARY KEY,
  group_id INTEGER REFERENCES work_groups(id),
  code TEXT NOT NULL COLLATE NOCASE CHECK(length(trim(code)) > 0),
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
INSERT INTO products_v11(id, group_id, code, description, category_id, unit, price_cents, discount_price_cents, cost_cents,
                         tax_rate_bp, stock_milli, min_stock_milli, active, external_ref, created_at, updated_at, created_by,
                         updated_by, version)
  SELECT id, NULL, code, description, category_id, unit, price_cents, discount_price_cents, cost_cents, tax_rate_bp,
         stock_milli, min_stock_milli, active, external_ref, created_at, updated_at, created_by, updated_by, version
  FROM products;
DROP TABLE products;
ALTER TABLE products_v11 RENAME TO products;

CREATE UNIQUE INDEX ux_products_inventory_code ON products(COALESCE(group_id, 0), code);
CREATE INDEX ix_products_description ON products(description COLLATE NOCASE);
CREATE INDEX ix_products_active ON products(active);
CREATE INDEX ix_products_group ON products(group_id, active);

CREATE TRIGGER moves_apply_stock AFTER INSERT ON inventory_movements
BEGIN
  UPDATE products SET stock_milli = stock_milli + NEW.qty_milli WHERE id = NEW.product_id;
END;
CREATE TRIGGER products_stock_guard BEFORE UPDATE OF stock_milli ON products
  WHEN NEW.stock_milli <> (SELECT COALESCE(SUM(qty_milli), 0) FROM inventory_movements WHERE product_id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'La existencia solo cambia mediante movimientos de inventario'); END;
CREATE TRIGGER products_no_delete BEFORE DELETE ON products
BEGIN SELECT RAISE(ABORT, 'Los productos no se eliminan: desactívelos'); END;
CREATE TRIGGER products_inventory_fixed BEFORE UPDATE OF group_id ON products WHEN OLD.group_id IS NOT NEW.group_id
BEGIN SELECT RAISE(ABORT, 'Un producto no cambia de inventario'); END;

ALTER TABLE sales ADD COLUMN group_id INTEGER REFERENCES work_groups(id);
CREATE INDEX ix_sales_group ON sales(group_id, sale_date);
ALTER TABLE commercial_documents ADD COLUMN group_id INTEGER REFERENCES work_groups(id);
CREATE INDEX ix_documents_group ON commercial_documents(group_id);

ALTER TABLE sale_return_lines ADD COLUMN condition TEXT NOT NULL DEFAULT 'apto' CHECK(condition IN ('apto','revision','no_apto'));
ALTER TABLE sale_return_lines ADD COLUMN resolved_at TEXT;
ALTER TABLE sale_return_lines ADD COLUMN resolved_by INTEGER REFERENCES users(id);
CREATE INDEX ix_return_lines_condition ON sale_return_lines(condition);
"""

# Reversión: restaure la copia de seguridad anterior a la migración 11.
DOWN_SQL = r"""
-- Restaure la copia de seguridad anterior a la migración 11.
"""

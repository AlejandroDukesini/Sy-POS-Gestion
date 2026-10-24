VERSION = 2
NAME = "configuración inicial (plan de cuentas, métodos de pago, numeración, tipos de documento)"

# Plan de cuentas mínimo inspirado en el PUC colombiano. Es un punto de partida para la contabilidad
# de gestión: debe revisarlo un contador antes de usarlo como base de reportes oficiales.
SQL = r"""
INSERT INTO accounts(code, name, type, is_cash, cost_behavior, system, created_at) VALUES
 ('1105', 'Caja', 'activo', 1, NULL, 1, strftime('%Y-%m-%dT%H:%M:%SZ','now')),
 ('1110', 'Bancos', 'activo', 1, NULL, 1, strftime('%Y-%m-%dT%H:%M:%SZ','now')),
 ('1305', 'Clientes (cuentas por cobrar)', 'activo', 0, NULL, 1, strftime('%Y-%m-%dT%H:%M:%SZ','now')),
 ('1435', 'Inventario de mercancías', 'activo', 0, NULL, 1, strftime('%Y-%m-%dT%H:%M:%SZ','now')),
 ('1520', 'Maquinaria y equipo', 'activo', 0, NULL, 0, strftime('%Y-%m-%dT%H:%M:%SZ','now')),
 ('2205', 'Proveedores (cuentas por pagar)', 'pasivo', 0, NULL, 1, strftime('%Y-%m-%dT%H:%M:%SZ','now')),
 ('2335', 'Costos y gastos por pagar', 'pasivo', 0, NULL, 0, strftime('%Y-%m-%dT%H:%M:%SZ','now')),
 ('2408', 'IVA por pagar', 'pasivo', 0, NULL, 1, strftime('%Y-%m-%dT%H:%M:%SZ','now')),
 ('2105', 'Obligaciones financieras', 'pasivo', 0, NULL, 0, strftime('%Y-%m-%dT%H:%M:%SZ','now')),
 ('3105', 'Capital', 'patrimonio', 0, NULL, 1, strftime('%Y-%m-%dT%H:%M:%SZ','now')),
 ('3605', 'Resultados de ejercicios anteriores', 'patrimonio', 0, NULL, 0, strftime('%Y-%m-%dT%H:%M:%SZ','now')),
 ('4135', 'Ingresos por ventas', 'ingreso', 0, NULL, 1, strftime('%Y-%m-%dT%H:%M:%SZ','now')),
 ('4175', 'Devoluciones en ventas', 'ingreso', 0, NULL, 1, strftime('%Y-%m-%dT%H:%M:%SZ','now')),
 ('4295', 'Otros ingresos (sobrantes de inventario)', 'ingreso', 0, NULL, 1, strftime('%Y-%m-%dT%H:%M:%SZ','now')),
 ('6135', 'Costo de ventas', 'costo', 0, 'variable', 1, strftime('%Y-%m-%dT%H:%M:%SZ','now')),
 ('5105', 'Gastos de personal', 'gasto', 0, 'fijo', 0, strftime('%Y-%m-%dT%H:%M:%SZ','now')),
 ('5120', 'Arrendamientos', 'gasto', 0, 'fijo', 0, strftime('%Y-%m-%dT%H:%M:%SZ','now')),
 ('5135', 'Servicios públicos', 'gasto', 0, 'fijo', 0, strftime('%Y-%m-%dT%H:%M:%SZ','now')),
 ('5145', 'Mantenimiento', 'gasto', 0, 'fijo', 0, strftime('%Y-%m-%dT%H:%M:%SZ','now')),
 ('5195', 'Gastos diversos', 'gasto', 0, 'variable', 0, strftime('%Y-%m-%dT%H:%M:%SZ','now')),
 ('5205', 'Comisiones de venta', 'gasto', 0, 'variable', 0, strftime('%Y-%m-%dT%H:%M:%SZ','now')),
 ('5305', 'Gastos financieros', 'gasto', 0, 'fijo', 0, strftime('%Y-%m-%dT%H:%M:%SZ','now')),
 ('5315', 'Pérdidas por ajustes de inventario', 'gasto', 0, 'variable', 1, strftime('%Y-%m-%dT%H:%M:%SZ','now'));

INSERT INTO payment_methods(code, name, kind, account_id, sort_order) VALUES
 ('efectivo', 'Efectivo', 'efectivo', (SELECT id FROM accounts WHERE code = '1105'), 1),
 ('tarjeta', 'Tarjeta débito o crédito', 'tarjeta', (SELECT id FROM accounts WHERE code = '1110'), 2),
 ('transferencia', 'Transferencia', 'transferencia', (SELECT id FROM accounts WHERE code = '1110'), 3),
 ('credito', 'Crédito (cuenta por cobrar)', 'credito', NULL, 4);

INSERT INTO sequences(name, prefix, next_value, padding) VALUES
 ('venta', 'V-', 1, 6),
 ('devolucion', 'D-', 1, 6),
 ('cxc', 'CXC-', 1, 6);

INSERT INTO document_types(code, name, prefix, validity_days, page_setup, created_at, updated_at) VALUES
 ('cotizacion', 'Cotización', 'COT-', 15,
  '{"paper":"letter","orientation":"portrait","margins_cm":1.5,"fit_width":true,"scale":100}',
  strftime('%Y-%m-%dT%H:%M:%SZ','now'), strftime('%Y-%m-%dT%H:%M:%SZ','now')),
 ('orden', 'Orden', 'ORD-', 0,
  '{"paper":"letter","orientation":"portrait","margins_cm":1.5,"fit_width":true,"scale":100}',
  strftime('%Y-%m-%dT%H:%M:%SZ','now'), strftime('%Y-%m-%dT%H:%M:%SZ','now'));
"""

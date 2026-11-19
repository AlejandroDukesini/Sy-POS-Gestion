/** Estado del producto devuelto por un cliente (sale_return_lines.condition). */
export const CONDITION_LABELS: Record<string, string> = {
  apto: 'Apto: volvió al inventario', revision: 'Pendiente de revisión', no_apto: 'No apto para la venta',
};
export const CONDITION_KIND: Record<string, 'success' | 'warning' | 'danger'> = { apto: 'success', revision: 'warning', no_apto: 'danger' };

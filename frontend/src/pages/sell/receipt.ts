import { get, post } from '../../api/client';
import { escapeHtml, printInBrowser } from './Cart';

/**
 * Imprime el comprobante de una venta con una sola acción:
 *  - modo ESC/POS: el backend lo envía directamente a la impresora configurada (DIGITALPOS);
 *  - modo navegador: se abre la vista del comprobante y el diálogo de impresión del navegador.
 */
export async function printReceipt(saleId: number): Promise<void> {
  const result = await post(`/sales/${saleId}/print`, {});
  if (result.mode === 'navegador') {
    const receipt = await get(`/sales/${saleId}/receipt`);
    printInBrowser(`Comprobante ${receipt.sale.number}`, `<pre>${escapeHtml(receipt.text)}</pre>`, '@page{margin:4mm}');
  }
}

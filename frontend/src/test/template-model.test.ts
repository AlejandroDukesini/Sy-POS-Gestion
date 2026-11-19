import { describe, expect, it } from 'vitest';
import {
  applyBorders, blankDoc, clearValues, deleteCols, deleteRows, displayValue, expandToMerges, insertCols, insertRows, merge,
  parseRange, setBinding, setValue, unmerge, updateStyle,
} from '../lib/templateModel';

function sample() {
  let doc = blankDoc();
  doc = setValue(doc, 'A1', 'COTIZACIÓN');
  doc = merge(doc, parseRange('A1:F1')!);
  doc = setValue(doc, 'A3', 'Cliente');
  doc = setBinding(doc, 'B3', { field: 'cliente_identificacion', fallback: '222222222222' });
  doc = setBinding(doc, 'F12', { expr: 'subtotal' });
  doc.bindings.products = { start: 6, end: 10, header_row: 5, columns: { A: { field: 'cantidad' }, F: { expr: 'cantidad*precio' } } };
  doc.layout.page.print_area = 'A1:F20';
  doc.layout.page.repeat_rows = '5:5';
  doc.layout.images.push({ id: 'img1', file: 'img-1.png', col: 0, col_off: 0, row: 14, row_off: 0, w: 50, h: 20 });
  return doc;
}

describe('modelo de plantillas del editor', () => {
  it('escribe valores con su tipo y los borra sin perder el formato', () => {
    let doc = setValue(blankDoc(), 'B2', '12500');
    expect(doc.layout.cells.B2.v).toBe(12500);
    doc = setValue(doc, 'B2', '0257');
    expect(doc.layout.cells.B2.v).toBe('0257');                    // los códigos con cero inicial siguen siendo texto
    doc = updateStyle(doc, parseRange('B2')!, (st) => ({ ...st, font: { ...st.font, b: true } }));
    doc = clearValues(doc, parseRange('B2')!);
    expect(doc.layout.cells.B2.v).toBeUndefined();
    expect(doc.layout.styles[doc.layout.cells.B2.s!].font?.b).toBe(true);
  });

  it('reutiliza estilos iguales y aplica bordes exteriores', () => {
    let doc = updateStyle(blankDoc(), parseRange('A1:C3')!, (st) => ({ ...st, fill: '#EEF2F7' }));
    expect(doc.layout.styles.length).toBe(2);
    doc = applyBorders(doc, parseRange('A1:C3')!, 'outer', 'medium', '#000000');
    const b = (r: string) => doc.layout.styles[doc.layout.cells[r].s!].border ?? {};
    expect(b('A1')).toEqual({ l: ['medium', '#000000'], t: ['medium', '#000000'] });
    expect(b('B2')).toEqual({});
    expect(b('C3')).toEqual({ r: ['medium', '#000000'], b: ['medium', '#000000'] });
  });

  it('combina como Excel (solo conserva la celda superior izquierda) y separa', () => {
    let doc = setValue(setValue(blankDoc(), 'A1', 'uno'), 'B1', 'dos');
    doc = merge(doc, parseRange('A1:B2')!);
    expect(doc.layout.merges).toEqual(['A1:B2']);
    expect(doc.layout.cells.B1?.v).toBeUndefined();
    expect(expandToMerges(doc.layout, parseRange('B2:C2')!)).toEqual(parseRange('A1:C2'));
    doc = unmerge(doc, parseRange('B2')!);
    expect(doc.layout.merges).toEqual([]);
  });

  it('insertar filas mueve vinculaciones, tabla de productos, combinaciones, imágenes y área de impresión', () => {
    const doc = insertRows(sample(), 4, 2);
    expect(doc.bindings.cells.B3).toBeDefined();
    expect(doc.bindings.cells.F14).toEqual({ expr: 'subtotal' });
    expect(doc.bindings.products).toMatchObject({ start: 8, end: 12, header_row: 7 });
    expect(doc.layout.page).toMatchObject({ print_area: 'A1:F22', repeat_rows: '7:7' });
    expect(doc.layout.images[0].row).toBe(16);
    expect(doc.layout.merges).toEqual(['A1:F1']);
    expect(doc.layout.rows.length).toBe(32);
  });

  it('eliminar filas quita lo que estaba en ellas y acorta la tabla de productos', () => {
    const doc = deleteRows(sample(), 7, 2);
    expect(doc.bindings.products).toMatchObject({ start: 6, end: 8 });
    expect(doc.bindings.cells.F10).toEqual({ expr: 'subtotal' });
    const gone = deleteRows(sample(), 3, 1);
    expect(gone.bindings.cells.B3).toBeUndefined();
  });

  it('insertar y eliminar columnas mueve las columnas de la tabla de productos', () => {
    let doc = insertCols(sample(), 2, 1);
    expect(Object.keys(doc.bindings.products!.columns)).toEqual(['A', 'G']);
    expect(doc.bindings.cells.C3).toBeDefined();
    expect(doc.layout.merges).toEqual(['A1:G1']);
    doc = deleteCols(doc, 1, 1);
    expect(Object.keys(doc.bindings.products!.columns)).toEqual(['F']);
  });

  it('muestra valores con formatos comunes', () => {
    expect(displayValue(56000, '"$"#,##0.00')).toBe('$ 56.000,00');
    expect(displayValue(0.2, '0%')).toBe('20%');
    expect(displayValue(0.5, 'h:mm:ss AM/PM')).toBe('12:00:00 p. m.');
    expect(displayValue('texto')).toBe('texto');
  });
});

import { describe, expect, it } from 'vitest';
import {
  addElement, align, changePaper, distribute, duplicate, makeElement, move, outOfBounds, paperSize, printableArea, remove, reorder,
  resize, setLocked, snapBox, type CanvasDoc,
} from '../lib/canvasModel';

function blank(): CanvasDoc {
  return {
    kind: 'canvas', v: 1, discount_pct: '0', grid: { size_mm: 1, snap: true, show: true },
    page: { paper: 'roll80', width_mm: 80, height_mm: 120, orientation: 'portrait', unit: 'mm', auto_height: true,
      printable_width_mm: 72, margins: { t: 2, r: 4, b: 2, l: 4 } },
    elements: [],
  };
}

describe('modelo del editor visual (lienzo)', () => {
  it('papel térmico: área imprimible real y alto que crece con el contenido', () => {
    let d = blank();
    expect(printableArea(d)).toMatchObject({ x: 4, w: 72 });
    d = addElement(d, makeElement(d, 'text', 4, 200));
    expect(paperSize(d).h).toBeGreaterThan(200);
  });

  it('insertar, mover, redimensionar, duplicar, bloquear y eliminar', () => {
    let d = blank();
    const t = makeElement(d, 'text', 10, 10);
    d = addElement(d, t);
    d = move(d, [t.id], 5, 3);
    expect(d.elements[0]).toMatchObject({ x: 15, y: 13 });
    d = resize(d, t.id, 'se', 10, 4);
    expect(d.elements[0]).toMatchObject({ w: t.w + 10, h: 10 });
    d = resize(d, t.id, 'w', 500, 0);                        // no se invierte: ancho mínimo y borde derecho fijo
    expect(d.elements[0].w).toBe(1);
    expect(d.elements[0].x + d.elements[0].w).toBeCloseTo(15 + t.w + 10, 1);
    const dup = duplicate(d, [t.id]);
    expect(dup.doc.elements).toHaveLength(2);
    d = setLocked(dup.doc, [t.id], true);
    expect(move(d, [t.id], 9, 9).elements[0].x).toBe(d.elements[0].x);   // bloqueado: no se mueve
    expect(remove(d, [t.id]).elements).toHaveLength(2);                    // ni se elimina
    expect(remove(d, dup.ids).elements).toHaveLength(1);
  });

  it('imagen: redimensionar conserva la proporción', () => {
    let d = blank();
    const img = makeElement(d, 'image', 10, 10, { w: 20, h: 10 });
    d = addElement(d, img);
    d = resize(d, img.id, 'se', 10, 0, true);
    expect(d.elements[0]).toMatchObject({ w: 30, h: 15 });
  });

  it('una sola tabla de productos y sus columnas se adaptan al ancho', () => {
    let d = blank();
    const tb = makeElement(d, 'table', 4, 30);
    d = addElement(addElement(d, tb), makeElement(d, 'table', 4, 60));
    expect(d.elements.filter((e) => e.type === 'table')).toHaveLength(1);
    d = resize(d, tb.id, 'e', -36, 0);
    const sum = d.elements[0].table!.columns.reduce((s, c) => s + c.width_mm, 0);
    expect(sum).toBeCloseTo(36, 0);
  });

  it('cambiar el papel convierte posiciones y avisa lo que queda fuera', () => {
    let d = blank();
    d = addElement(d, makeElement(d, 'text', 4, 10, { w: 72 }));
    d = changePaper(d, 'roll58');
    expect(d.page.printable_width_mm).toBe(48);
    expect(d.elements[0]).toMatchObject({ x: 5, w: 48 });
    expect(outOfBounds(d)).toEqual([]);
    d = changePaper(d, 'a4');
    expect(d.page.auto_height).toBe(false);
    expect(paperSize(d)).toEqual({ w: 210, h: 297 });
    d = move(d, [d.elements[0].id], -50, 0);
    expect(outOfBounds(d)).toHaveLength(1);
  });

  it('alinear, distribuir, capas e imán a guías', () => {
    let d = blank();
    const a = makeElement(d, 'rect', 10, 10, { w: 10, h: 5 });
    d = addElement(d, a);
    const b = makeElement(d, 'rect', 30, 20, { w: 10, h: 5 });
    d = addElement(d, b);
    const c = makeElement(d, 'rect', 60, 40, { w: 10, h: 5 });
    d = addElement(d, c);
    expect(align(d, [a.id, b.id], 'left').elements.find((e) => e.id === b.id)!.x).toBe(10);
    const dist = distribute(d, [a.id, b.id, c.id], 'h');
    expect(dist.elements.find((e) => e.id === b.id)!.x).toBe(35);
    expect(reorder(d, a.id, 'front').elements.find((e) => e.id === a.id)!.z).toBe(3);
    const snapped = snapBox(d, { x: 30.6, y: 50, w: 10, h: 5 }, []);
    expect(snapped.box.x).toBe(30);                          // borde de otro elemento
    expect(snapped.guides.some((g) => g.axis === 'x' && g.at === 30)).toBe(true);
  });
});

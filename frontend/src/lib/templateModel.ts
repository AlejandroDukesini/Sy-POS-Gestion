/**
 * Modelo de plantillas de impresión (el mismo JSON que guarda el servidor) y operaciones puras del editor.
 * Cada operación devuelve un documento nuevo: así deshacer/rehacer es guardar copias.
 * Insertar o eliminar filas y columnas mueve también vinculaciones, combinaciones, imágenes, la tabla de
 * productos y el área de impresión, para que nada quede apuntando a la celda equivocada.
 */

export type Side = 'l' | 'r' | 't' | 'b';
export interface StyleDef {
  font?: { name?: string; size?: number; b?: boolean; i?: boolean; u?: boolean; color?: string };
  fill?: string;
  h?: 'left' | 'center' | 'right';
  v?: 'top' | 'center' | 'bottom';
  wrap?: boolean;
  fmt?: string;
  border?: Partial<Record<Side, [string, string]>>;
}
export interface CellDef { v?: string | number; s?: number; f?: string }
export interface ImageDef {
  id: string; file: string; mime?: string; col: number; col_off: number; row: number; row_off: number; w: number; h: number;
  crop?: Partial<Record<Side, number>>;
}
export interface PageDef {
  paper: string; orientation: 'portrait' | 'landscape'; width_mm?: number; height_mm?: number;
  margins: Record<Side, number>; scale: number; fit_width: boolean; print_area: string; repeat_rows: string;
  header: string; footer: string; row_breaks: number[];
}
export interface Layout {
  v: 1; cols: number[]; rows: number[]; cells: Record<string, CellDef>; styles: StyleDef[]; merges: string[];
  images: ImageDef[]; page: PageDef;
}
export interface Binding { field?: string; expr?: string; fallback?: string; format?: string }
export interface ProductBlock { start: number; end: number; header_row: number; columns: Record<string, Binding> }
export interface Bindings { cells: Record<string, Binding>; products: ProductBlock | null; discount_pct: string }
export interface TemplateDoc { layout: Layout; bindings: Bindings }
export interface Range { r1: number; c1: number; r2: number; c2: number }

// ------------------------------------------------------------------ coordenadas
export function colLetter(n: number): string {
  let out = '';
  while (n > 0) {
    const r = (n - 1) % 26;
    out = String.fromCharCode(65 + r) + out;
    n = Math.floor((n - 1) / 26);
  }
  return out;
}

export function colIndex(letters: string): number {
  return [...letters.toUpperCase()].reduce((n, ch) => n * 26 + (ch.charCodeAt(0) - 64), 0);
}

export function ref(r: number, c: number): string {
  return `${colLetter(c)}${r}`;
}

export function parseRef(text: string): [number, number] | null {
  const m = /^\$?([A-Z]{1,3})\$?(\d{1,7})$/.exec(String(text).trim().toUpperCase());
  return m ? [Number(m[2]), colIndex(m[1])] : null;
}

export function parseRange(text: string): Range | null {
  const [a, b] = String(text).replace(/\$/g, '').split(':');
  const p1 = parseRef(a ?? '');
  const p2 = parseRef(b ?? a ?? '');
  if (!p1 || !p2) return null;
  return { r1: Math.min(p1[0], p2[0]), c1: Math.min(p1[1], p2[1]), r2: Math.max(p1[0], p2[0]), c2: Math.max(p1[1], p2[1]) };
}

export function rangeRef(g: Range): string {
  const a = ref(g.r1, g.c1);
  const b = ref(g.r2, g.c2);
  return a === b ? a : `${a}:${b}`;
}

export function normalize(g: Range): Range {
  return { r1: Math.min(g.r1, g.r2), c1: Math.min(g.c1, g.c2), r2: Math.max(g.r1, g.r2), c2: Math.max(g.c1, g.c2) };
}

export function intersects(a: Range, b: Range): boolean {
  return a.r1 <= b.r2 && b.r1 <= a.r2 && a.c1 <= b.c2 && b.c1 <= a.c2;
}

/** Ancho de columna de Excel (caracteres) a píxeles, y alto de fila (puntos) a píxeles. */
export const colPx = (w: number) => (w > 0 ? Math.trunc(w * 7 + 5) : 0);
export const rowPx = (h: number) => Math.round((h * 4) / 3);

/** Amplía la selección para que incluya completas las combinaciones que toca. */
export function expandToMerges(layout: Layout, g: Range): Range {
  let out = normalize(g);
  let changed = true;
  while (changed) {
    changed = false;
    for (const m of layout.merges) {
      const mr = parseRange(m);
      if (mr && intersects(out, mr)) {
        const next = { r1: Math.min(out.r1, mr.r1), c1: Math.min(out.c1, mr.c1), r2: Math.max(out.r2, mr.r2), c2: Math.max(out.c2, mr.c2) };
        if (JSON.stringify(next) !== JSON.stringify(out)) {
          out = next;
          changed = true;
        }
      }
    }
  }
  return out;
}

export function mergeAt(layout: Layout, r: number, c: number): Range | null {
  for (const m of layout.merges) {
    const g = parseRange(m);
    if (g && r >= g.r1 && r <= g.r2 && c >= g.c1 && c <= g.c2) return g;
  }
  return null;
}

// ------------------------------------------------------------------ utilidades
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));

export function styleOf(layout: Layout, cellRef: string): StyleDef {
  const s = layout.cells[cellRef]?.s ?? 0;
  return layout.styles[s] ?? {};
}

function styleIndex(styles: StyleDef[], style: StyleDef): number {
  const key = JSON.stringify(style);
  const found = styles.findIndex((s) => JSON.stringify(s) === key);
  if (found >= 0) return found;
  styles.push(style);
  return styles.length - 1;
}

function cleanStyle(st: StyleDef): StyleDef {
  const out: StyleDef = { ...st };
  if (out.font) {
    const f = Object.fromEntries(Object.entries(out.font).filter(([, v]) => v !== undefined && v !== false && v !== ''));
    if (Object.keys(f).length) out.font = f; else delete out.font;
  }
  if (out.border) {
    const b = Object.fromEntries(Object.entries(out.border).filter(([, v]) => v));
    if (Object.keys(b).length) out.border = b; else delete out.border;
  }
  for (const k of ['fill', 'h', 'v', 'fmt'] as const) if (!out[k]) delete out[k];
  if (!out.wrap) delete out.wrap;
  return out;
}

function forEachCell(g: Range, fn: (r: number, c: number) => void) {
  for (let r = g.r1; r <= g.r2; r++) for (let c = g.c1; c <= g.c2; c++) fn(r, c);
}

// ------------------------------------------------------------------ edición
export function setValue(doc: TemplateDoc, cellRef: string, value: string): TemplateDoc {
  const out = clone(doc);
  const cell = { ...(out.layout.cells[cellRef] ?? {}) };
  delete cell.f;
  const trimmed = value.trim();
  if (trimmed === '') delete cell.v;
  else if (/^-?\d+([.,]\d+)?$/.test(trimmed) && !/^0\d/.test(trimmed)) cell.v = Number(trimmed.replace(',', '.'));
  else cell.v = value;
  if (Object.keys(cell).length) out.layout.cells[cellRef] = cell; else delete out.layout.cells[cellRef];
  return out;
}

export function clearValues(doc: TemplateDoc, g: Range): TemplateDoc {
  const out = clone(doc);
  forEachCell(g, (r, c) => {
    const k = ref(r, c);
    const cell = out.layout.cells[k];
    if (!cell) return;
    delete cell.v;
    delete cell.f;
    if (!cell.s) delete out.layout.cells[k];
    delete out.bindings.cells[k];
  });
  return out;
}

/** Aplica un cambio de estilo a todas las celdas del rango (reutiliza estilos iguales). */
export function updateStyle(doc: TemplateDoc, g: Range, patch: (st: StyleDef) => StyleDef): TemplateDoc {
  const out = clone(doc);
  forEachCell(g, (r, c) => {
    const k = ref(r, c);
    const cell = { ...(out.layout.cells[k] ?? {}) };
    const next = cleanStyle(patch(clone(out.layout.styles[cell.s ?? 0] ?? {})));
    const idx = styleIndex(out.layout.styles, next);
    if (idx) cell.s = idx; else delete cell.s;
    if (Object.keys(cell).length) out.layout.cells[k] = cell; else delete out.layout.cells[k];
  });
  return out;
}

export type BorderMode = 'none' | 'all' | 'outer' | 'bottom' | 'top';
export function applyBorders(doc: TemplateDoc, g: Range, mode: BorderMode, style = 'thin', color = '#000000'): TemplateDoc {
  let out = doc;
  const line: [string, string] = [style, color.toUpperCase()];
  forEachCell(g, (r, c) => {
    out = updateStyle(out, { r1: r, c1: c, r2: r, c2: c }, (st) => {
      const b = { ...(st.border ?? {}) };
      if (mode === 'none') return { ...st, border: {} };
      if (mode === 'all') Object.assign(b, { l: line, r: line, t: line, b: line });
      if (mode === 'outer') {
        if (c === g.c1) b.l = line;
        if (c === g.c2) b.r = line;
        if (r === g.r1) b.t = line;
        if (r === g.r2) b.b = line;
      }
      if (mode === 'bottom' && r === g.r2) b.b = line;
      if (mode === 'top' && r === g.r1) b.t = line;
      return { ...st, border: b };
    });
  });
  return out;
}

export function merge(doc: TemplateDoc, g: Range): TemplateDoc {
  const out = clone(doc);
  const area = expandToMerges(out.layout, g);
  if (area.r1 === area.r2 && area.c1 === area.c2) return out;
  out.layout.merges = out.layout.merges.filter((m) => !intersects(parseRange(m)!, area));
  out.layout.merges.push(rangeRef(area));
  forEachCell(area, (r, c) => {            // como Excel: solo se conserva el contenido de la celda superior izquierda
    if (r === area.r1 && c === area.c1) return;
    const k = ref(r, c);
    if (out.layout.cells[k]) {
      delete out.layout.cells[k].v;
      delete out.layout.cells[k].f;
    }
    delete out.bindings.cells[k];
  });
  return out;
}

export function unmerge(doc: TemplateDoc, g: Range): TemplateDoc {
  const out = clone(doc);
  out.layout.merges = out.layout.merges.filter((m) => !intersects(parseRange(m)!, g));
  return out;
}

export function setBinding(doc: TemplateDoc, cellRef: string, binding: Binding | null): TemplateDoc {
  const out = clone(doc);
  if (binding && (binding.field || binding.expr)) out.bindings.cells[cellRef] = binding;
  else delete out.bindings.cells[cellRef];
  return out;
}

// ------------------------------------------------------------------ filas y columnas
type Axis = 'row' | 'col';

function shiftRef(cellRef: string, axis: Axis, at: number, delta: number): string | null {
  const p = parseRef(cellRef);
  if (!p) return cellRef;
  let [r, c] = p;
  const pos = axis === 'row' ? r : c;
  if (delta < 0 && pos >= at && pos < at - delta) return null;          // dentro de lo eliminado
  if (pos >= at) {
    if (axis === 'row') r += delta; else c += delta;
  }
  return ref(r, c);
}

function shiftRange(g: Range, axis: Axis, at: number, delta: number): Range | null {
  const [lo, hi] = axis === 'row' ? [g.r1, g.r2] : [g.c1, g.c2];
  let nlo = lo;
  let nhi = hi;
  if (delta > 0) {
    if (lo >= at) nlo += delta;
    if (hi >= at) nhi += delta;
  } else {
    const end = at - delta - 1;                                          // última eliminada
    const removed = (x: number) => x >= at && x <= end;
    if (removed(lo) && removed(hi)) return null;
    nlo = lo > end ? lo + delta : removed(lo) ? at : lo;
    nhi = hi > end ? hi + delta : removed(hi) ? at - 1 : hi;
    if (nhi < nlo) return null;
  }
  return axis === 'row' ? { ...g, r1: nlo, r2: nhi } : { ...g, c1: nlo, c2: nhi };
}

function shift(doc: TemplateDoc, axis: Axis, at: number, delta: number): TemplateDoc {
  const out = clone(doc);
  const L = out.layout;
  const cells: Record<string, CellDef> = {};
  for (const [k, v] of Object.entries(L.cells)) {
    const nk = shiftRef(k, axis, at, delta);
    if (nk) cells[nk] = v;
  }
  L.cells = cells;
  const bcells: Record<string, Binding> = {};
  for (const [k, v] of Object.entries(out.bindings.cells)) {
    const nk = shiftRef(k, axis, at, delta);
    if (nk) bcells[nk] = v;
  }
  out.bindings.cells = bcells;
  L.merges = L.merges.map((m) => shiftRange(parseRange(m)!, axis, at, delta)).filter((g): g is Range => Boolean(g))
    .filter((g) => g.r1 !== g.r2 || g.c1 !== g.c2).map(rangeRef);
  L.images = L.images.filter((img) => {
    const pos = (axis === 'row' ? img.row : img.col) + 1;
    if (delta < 0 && pos >= at && pos < at - delta) return false;
    if (pos >= at) {
      if (axis === 'row') img.row += delta; else img.col += delta;
    }
    return true;
  });
  if (L.page.print_area) {
    const g = parseRange(L.page.print_area);
    const n = g && shiftRange(g, axis, at, delta);
    L.page.print_area = n ? rangeRef(n) : '';
  }
  if (axis === 'row') {
    if (L.page.repeat_rows) {
      const [a, b] = L.page.repeat_rows.split(':').map(Number);
      const n = shiftRange({ r1: a, r2: b, c1: 1, c2: 1 }, 'row', at, delta);
      L.page.repeat_rows = n ? `${n.r1}:${n.r2}` : '';
    }
    L.page.row_breaks = L.page.row_breaks.map((b) => (b >= at ? b + delta : b)).filter((b) => b >= 1);
    const p = out.bindings.products;
    if (p) {
      const n = shiftRange({ r1: p.start, r2: p.end, c1: 1, c2: 1 }, 'row', at, delta);
      if (!n) out.bindings.products = null;
      else {
        p.start = n.r1;
        p.end = n.r2;
        if (p.header_row) p.header_row = shiftRange({ r1: p.header_row, r2: p.header_row, c1: 1, c2: 1 }, 'row', at, delta)?.r1 ?? 0;
      }
    }
  } else if (out.bindings.products) {
    const cols: Record<string, Binding> = {};
    for (const [letter, b] of Object.entries(out.bindings.products.columns)) {
      const c = colIndex(letter);
      if (delta < 0 && c >= at && c < at - delta) continue;
      cols[colLetter(c >= at ? c + delta : c)] = b;
    }
    out.bindings.products.columns = cols;
  }
  return out;
}

export function insertRows(doc: TemplateDoc, at: number, count = 1): TemplateDoc {
  const out = shift(doc, 'row', at, count);
  const h = doc.layout.rows[Math.max(0, at - 2)] ?? 15;
  out.layout.rows.splice(at - 1, 0, ...Array(count).fill(h));
  return out;
}

export function deleteRows(doc: TemplateDoc, at: number, count = 1): TemplateDoc {
  if (doc.layout.rows.length - count < 1) return doc;
  const out = shift(doc, 'row', at, -count);
  out.layout.rows.splice(at - 1, count);
  return out;
}

export function insertCols(doc: TemplateDoc, at: number, count = 1): TemplateDoc {
  if (doc.layout.cols.length + count > 60) return doc;
  const out = shift(doc, 'col', at, count);
  out.layout.cols.splice(at - 1, 0, ...Array(count).fill(doc.layout.cols[Math.max(0, at - 2)] ?? 10));
  return out;
}

export function deleteCols(doc: TemplateDoc, at: number, count = 1): TemplateDoc {
  if (doc.layout.cols.length - count < 1) return doc;
  const out = shift(doc, 'col', at, -count);
  out.layout.cols.splice(at - 1, count);
  return out;
}

// ------------------------------------------------------------------ presentación
const DAYS = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'];
const MONTHS = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre',
  'noviembre', 'diciembre'];

/** Texto aproximado de una celda en el editor (el PDF usa el formateador completo del servidor). */
export function displayValue(v: CellDef['v'], fmt?: string): string {
  if (v === undefined || v === null || v === '') return '';
  if (typeof v !== 'number') return String(v);
  const f = (fmt ?? '').replace(/\[[^\]]*\]/g, '');
  if (/[hs]/i.test(f.replace(/"[^"]*"/g, '')) && v < 1) {
    const secs = Math.round(v * 86400);
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    const s = secs % 60;
    const ampm = /AM\/PM/i.test(f);
    return `${ampm ? (h % 12 || 12) : h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}${ampm ? (h < 12 ? ' a. m.' : ' p. m.') : ''}`;
  }
  if (/[dy]/i.test(f.replace(/"[^"]*"/g, '')) && v > 1000) {
    const d = new Date(Date.UTC(1899, 11, 30) + v * 86400000);
    if (/dddd/i.test(f)) return `${DAYS[d.getUTCDay()]}, ${d.getUTCDate()} de ${MONTHS[d.getUTCMonth()]}`;
    return `${String(d.getUTCDate()).padStart(2, '0')}/${String(d.getUTCMonth() + 1).padStart(2, '0')}/${d.getUTCFullYear()}`;
  }
  if (f.includes('%')) return `${(v * 100).toLocaleString('es-CO', { maximumFractionDigits: 2 })}%`;
  const decimals = /0\.(0+)/.exec(f)?.[1].length ?? (Number.isInteger(v) ? 0 : 2);
  const text = v.toLocaleString('es-CO', { minimumFractionDigits: f ? decimals : 0, maximumFractionDigits: f ? decimals : 10,
    useGrouping: f.includes(',') || f.includes('#') });
  return f.includes('$') ? `$ ${text}` : text;
}

export function blankDoc(): TemplateDoc {
  return {
    layout: {
      v: 1, cols: [8, 12, 34, 10, 14, 16], rows: Array(30).fill(15), cells: {}, styles: [{}], merges: [], images: [],
      page: { paper: 'letter', orientation: 'portrait', margins: { l: 1.5, r: 1.5, t: 1.5, b: 1.5 }, scale: 100,
        fit_width: true, print_area: '', repeat_rows: '', header: '', footer: '', row_breaks: [] },
    },
    bindings: { cells: {}, products: null, discount_pct: '0' },
  };
}

/**
 * Modelo del editor visual de plantillas (lienzo en milímetros). Es el mismo JSON que guarda el servidor
 * («kind: canvas»); el servidor lo compila a la cuadrícula del motor para el PDF y el Excel.
 * Todas las operaciones son puras: devuelven un documento nuevo (deshacer/rehacer = guardar copias).
 */

export type ElType = 'text' | 'variable' | 'image' | 'line' | 'rect' | 'spacer' | 'table';
export interface TextProps {
  content: string; font: string; size: number; bold: boolean; italic: boolean; underline: boolean; color: string;
  align: 'left' | 'center' | 'right'; valign: 'top' | 'center' | 'bottom'; overflow: 'wrap' | 'shrink' | 'overflow'; fill?: string;
}
export interface TableColumn { field: string; header: string; width_mm: number; align: 'left' | 'center' | 'right' }
export interface TableProps {
  columns: TableColumn[]; header: { show: boolean; bold: boolean; fill: string; size: number }; size: number;
  header_height_mm: number; row_height_mm: number; borders: 'none' | 'horizontal' | 'all'; border_color: string; wrap: boolean;
}
export interface El {
  id: string; type: ElType; x: number; y: number; w: number; h: number; z: number; locked: boolean; hidden: boolean; rotation: number;
  name?: string; text?: TextProps; field?: string; fallback?: string; format?: string;
  image?: { file: string; keep_ratio: boolean; crop?: Record<string, number> };
  line?: { orientation: 'h' | 'v'; thickness: number; style: 'solid' | 'dashed' | 'dotted' | 'double'; color: string };
  rect?: { border_width: number; border_style: 'solid' | 'dashed' | 'dotted'; border_color: string; fill: string };
  table?: TableProps;
}
export interface Page {
  paper: 'roll80' | 'roll58' | 'a4' | 'letter' | 'custom'; width_mm: number; height_mm: number; orientation: 'portrait' | 'landscape';
  unit: 'mm' | 'cm' | 'in'; auto_height: boolean; printable_width_mm: number; margins: { t: number; r: number; b: number; l: number };
}
export interface CanvasDoc {
  kind: 'canvas'; v: 1; page: Page; grid: { size_mm: number; snap: boolean; show: boolean }; discount_pct: string; elements: El[];
}
export interface Box { x: number; y: number; w: number; h: number }

export const PAPERS: Record<Page['paper'], { label: string; w: number; h: number; printable: number }> = {
  roll80: { label: 'Térmica 80 mm', w: 80, h: 0, printable: 72 },
  roll58: { label: 'Térmica 58 mm', w: 58, h: 0, printable: 48 },
  a4: { label: 'A4 (210 × 297 mm)', w: 210, h: 297, printable: 0 },
  letter: { label: 'Carta (216 × 279 mm)', w: 215.9, h: 279.4, printable: 0 },
  custom: { label: 'Personalizado', w: 100, h: 150, printable: 0 },
};
export const UNITS: Record<Page['unit'], number> = { mm: 1, cm: 10, in: 25.4 };
export const PX_PER_MM = 96 / 25.4;
export const PT_TO_MM = 25.4 / 72;
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const r2 = (n: number) => Math.round(n * 100) / 100;

/** Tamaño físico de la hoja (mm), con la orientación aplicada. El alto de un rollo crece con el contenido. */
export function paperSize(doc: CanvasDoc): { w: number; h: number } {
  const p = doc.page;
  const land = p.orientation === 'landscape' && !p.paper.startsWith('roll');
  const w = land ? p.height_mm : p.width_mm;
  let h = land ? p.width_mm : p.height_mm;
  if (p.auto_height) h = Math.max(contentBottom(doc) + p.margins.b + 20, 80);
  return { w: r2(w), h: r2(h) };
}

export function contentBottom(doc: CanvasDoc): number {
  return doc.elements.filter((e) => !e.hidden).reduce((m, e) => Math.max(m, e.y + e.h), 0);
}

export function printableArea(doc: CanvasDoc): Box {
  const { w, h } = paperSize(doc);
  const m = doc.page.margins;
  return { x: m.l, y: m.t, w: r2(w - m.l - m.r), h: r2(h - m.t - m.b) };
}

/** Elementos que salen del área imprimible (se advierten en el lienzo). */
export function outOfBounds(doc: CanvasDoc): string[] {
  const a = printableArea(doc);
  return doc.elements.filter((e) => !e.hidden && (e.x < a.x - 0.3 || e.y < a.y - 0.3 || e.x + e.w > a.x + a.w + 0.3
    || (!doc.page.auto_height && e.y + e.h > a.y + a.h + 0.3))).map((e) => e.id);
}

let counter = 0;
function newId(doc: CanvasDoc): string {
  const ids = new Set(doc.elements.map((e) => e.id));
  let id = '';
  do { counter += 1; id = `e${Date.now().toString(36).slice(-4)}${counter}`; } while (ids.has(id));
  return id;
}

export function defaultText(over: Partial<TextProps> = {}): TextProps {
  return { content: '', font: 'Arial', size: 9, bold: false, italic: false, underline: false, color: '#000000', align: 'left',
    valign: 'center', overflow: 'wrap', ...over };
}

export function defaultTable(width: number): TableProps {
  const cols: [string, string, number, TableColumn['align']][] = [['cantidad', 'Cant', 0.14, 'center'], ['descripcion', 'Producto', 0.46, 'left'],
    ['precio', 'Precio', 0.2, 'right'], ['valor', 'Total', 0.2, 'right']];
  return { columns: cols.map(([field, header, f, align]) => ({ field, header, width_mm: r2(width * f), align })),
    header: { show: true, bold: true, fill: '#EEEEEE', size: 8 }, size: 8, header_height_mm: 5, row_height_mm: 5, borders: 'horizontal',
    border_color: '#000000', wrap: true };
}

/** Crea un elemento nuevo en (x, y) mm con un tamaño razonable para el papel. */
export function makeElement(doc: CanvasDoc, kind: string, x: number, y: number, extra: Partial<El> = {}): El {
  const area = printableArea(doc);
  const wide = Math.min(area.w, 60);
  const base: El = { id: newId(doc), type: 'text', x: r2(x), y: r2(y), w: wide, h: 6, z: maxZ(doc) + 1, locked: false, hidden: false, rotation: 0 };
  switch (kind) {
    case 'text': return { ...base, type: 'text', text: defaultText({ content: 'Texto' }), ...extra };
    case 'variable': return { ...base, type: 'variable', field: 'empresa_nombre', fallback: '', format: '', text: defaultText(), ...extra };
    case 'image': return { ...base, type: 'image', w: 25, h: 25, image: { file: '', keep_ratio: true }, ...extra };
    case 'hline': return { ...base, type: 'line', w: area.w, h: 1, line: { orientation: 'h', thickness: 0.75, style: 'solid', color: '#000000' }, ...extra };
    case 'vline': return { ...base, type: 'line', w: 1, h: 20, line: { orientation: 'v', thickness: 0.75, style: 'solid', color: '#000000' }, ...extra };
    case 'separator': return { ...base, type: 'line', w: area.w, h: 2, line: { orientation: 'h', thickness: 0.75, style: 'dashed', color: '#000000' }, ...extra };
    case 'rect': return { ...base, type: 'rect', w: 30, h: 15, rect: { border_width: 0.75, border_style: 'solid', border_color: '#000000', fill: '' }, ...extra };
    case 'spacer': return { ...base, type: 'spacer', w: area.w, h: 5, ...extra };
    case 'table': return { ...base, type: 'table', x: area.x, w: area.w, h: 10, table: defaultTable(area.w), ...extra };
    default: return { ...base, ...extra };
  }
}

export const maxZ = (doc: CanvasDoc) => doc.elements.reduce((m, e) => Math.max(m, e.z), 0);

export function addElement(doc: CanvasDoc, el: El): CanvasDoc {
  const out = clone(doc);
  if (el.type === 'table' && out.elements.some((e) => e.type === 'table')) return out;   // una sola tabla de productos
  out.elements.push(el);
  return out;
}

export function updateElement(doc: CanvasDoc, id: string, patch: Partial<El>): CanvasDoc {
  const out = clone(doc);
  const e = out.elements.find((x) => x.id === id);
  if (e) Object.assign(e, patch);
  return out;
}

export function move(doc: CanvasDoc, ids: string[], dx: number, dy: number): CanvasDoc {
  const out = clone(doc);
  for (const e of out.elements) {
    if (ids.includes(e.id) && !e.locked) {
      e.x = r2(e.x + dx);
      e.y = r2(e.y + dy);
    }
  }
  return out;
}

export type Handle = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw';
/** Redimensiona desde un punto de control. keepRatio conserva la proporción (imágenes). Mínimo 1 mm. */
export function resize(doc: CanvasDoc, id: string, handle: Handle, dx: number, dy: number, keepRatio = false): CanvasDoc {
  const out = clone(doc);
  const e = out.elements.find((x) => x.id === id);
  if (!e || e.locked) return out;
  let { x, y, w, h } = e;
  if (handle.includes('e')) w += dx;
  if (handle.includes('w')) { x += dx; w -= dx; }
  if (handle.includes('s')) h += dy;
  if (handle.includes('n')) { y += dy; h -= dy; }
  if (keepRatio && e.w > 0 && e.h > 0) {
    const ratio = e.w / e.h;
    if (handle === 'n' || handle === 's') w = h * ratio; else h = w / ratio;
    if (handle.includes('n')) y = e.y + e.h - h;
    if (handle.includes('w')) x = e.x + e.w - w;
  }
  const right = e.x + e.w;
  const bottom = e.y + e.h;
  const nw = Math.max(1, w);
  const nh = Math.max(1, h);
  e.x = r2(handle.includes('w') ? right - nw : x);   // el borde opuesto queda fijo
  e.y = r2(handle.includes('n') ? bottom - nh : y);
  e.w = r2(nw);
  e.h = r2(nh);
  if (e.type === 'table' && e.table) {               // la tabla reparte el ancho nuevo entre sus columnas
    const total = e.table.columns.reduce((s, c) => s + c.width_mm, 0) || 1;
    e.table.columns = e.table.columns.map((c) => ({ ...c, width_mm: r2((c.width_mm / total) * e.w) }));
  }
  return out;
}

export function duplicate(doc: CanvasDoc, ids: string[]): { doc: CanvasDoc; ids: string[] } {
  const out = clone(doc);
  const created: string[] = [];
  for (const e of doc.elements.filter((x) => ids.includes(x.id) && x.type !== 'table')) {
    const copy: El = { ...clone(e), id: newId(out), x: r2(e.x + 2), y: r2(e.y + 2), z: maxZ(out) + 1, locked: false };
    out.elements.push(copy);
    created.push(copy.id);
  }
  return { doc: out, ids: created };
}

export function remove(doc: CanvasDoc, ids: string[]): CanvasDoc {
  const out = clone(doc);
  out.elements = out.elements.filter((e) => !ids.includes(e.id) || e.locked);
  return out;
}

export function setLocked(doc: CanvasDoc, ids: string[], locked: boolean): CanvasDoc {
  const out = clone(doc);
  out.elements.forEach((e) => { if (ids.includes(e.id)) e.locked = locked; });
  return out;
}

/** Capas: adelante/atrás un paso o al frente/fondo. */
export function reorder(doc: CanvasDoc, id: string, how: 'up' | 'down' | 'front' | 'back'): CanvasDoc {
  const out = clone(doc);
  const sorted = [...out.elements].sort((a, b) => a.z - b.z);
  const i = sorted.findIndex((e) => e.id === id);
  if (i < 0) return out;
  const [el] = sorted.splice(i, 1);
  const to = how === 'front' ? sorted.length : how === 'back' ? 0 : how === 'up' ? Math.min(sorted.length, i + 1) : Math.max(0, i - 1);
  sorted.splice(to, 0, el);
  sorted.forEach((e, n) => { e.z = n + 1; });
  out.elements = sorted;
  return out;
}

export function bounds(els: El[]): Box {
  const x = Math.min(...els.map((e) => e.x));
  const y = Math.min(...els.map((e) => e.y));
  const x2 = Math.max(...els.map((e) => e.x + e.w));
  const y2 = Math.max(...els.map((e) => e.y + e.h));
  return { x, y, w: x2 - x, h: y2 - y };
}

export type AlignMode = 'left' | 'hcenter' | 'right' | 'top' | 'vcenter' | 'bottom';
/** Alinea la selección entre sí; un solo elemento se alinea con el área imprimible. */
export function align(doc: CanvasDoc, ids: string[], mode: AlignMode): CanvasDoc {
  const out = clone(doc);
  const els = out.elements.filter((e) => ids.includes(e.id) && !e.locked);
  if (!els.length) return out;
  const ref = els.length === 1 ? printableArea(doc) : bounds(els);
  for (const e of els) {
    if (mode === 'left') e.x = ref.x;
    if (mode === 'right') e.x = r2(ref.x + ref.w - e.w);
    if (mode === 'hcenter') e.x = r2(ref.x + (ref.w - e.w) / 2);
    if (mode === 'top') e.y = ref.y;
    if (mode === 'bottom') e.y = r2(ref.y + ref.h - e.h);
    if (mode === 'vcenter') e.y = r2(ref.y + (ref.h - e.h) / 2);
  }
  return out;
}

/** Distribuye el espacio libre por igual entre 3 o más elementos. */
export function distribute(doc: CanvasDoc, ids: string[], axis: 'h' | 'v'): CanvasDoc {
  const out = clone(doc);
  const els = out.elements.filter((e) => ids.includes(e.id) && !e.locked);
  if (els.length < 3) return out;
  const key = axis === 'h' ? 'x' : 'y';
  const size = axis === 'h' ? 'w' : 'h';
  els.sort((a, b) => a[key] - b[key]);
  const start = els[0][key];
  const end = els[els.length - 1][key] + els[els.length - 1][size];
  const gap = (end - start - els.reduce((s, e) => s + e[size], 0)) / (els.length - 1);
  let pos = start;
  for (const e of els) {
    e[key] = r2(pos);
    pos += e[size] + gap;
  }
  return out;
}

/** Cambia el papel. Las posiciones horizontales se convierten en proporción al ancho imprimible nuevo
 *  (los elementos no quedan fuera del papel); las verticales se conservan. */
export function changePaper(doc: CanvasDoc, paper: Page['paper'], custom?: { w: number; h: number }): CanvasDoc {
  const out = clone(doc);
  const before = printableArea(doc);
  const preset = PAPERS[paper];
  const roll = paper.startsWith('roll');
  out.page.paper = paper;
  out.page.width_mm = custom?.w ?? preset.w;
  out.page.height_mm = custom?.h ?? (preset.h || 150);
  out.page.auto_height = roll ? true : paper === 'custom' ? out.page.auto_height : false;
  out.page.printable_width_mm = preset.printable;
  if (roll) {
    const side = r2((out.page.width_mm - preset.printable) / 2);
    out.page.margins = { t: 2, b: 2, l: side, r: side };
  } else if (doc.page.paper.startsWith('roll')) {
    out.page.margins = { t: 10, r: 10, b: 10, l: 10 };
  }
  const after = printableArea(out);
  const f = after.w / (before.w || 1);
  for (const e of out.elements) {
    e.x = r2(after.x + (e.x - before.x) * f);
    e.w = r2(Math.max(1, e.w * f));
    if (e.type === 'text' || e.type === 'variable') { /* tipografía intacta: no se deforma */ }
    if (e.type === 'image') e.h = r2(Math.max(1, e.h * f));           // sin deformar: misma proporción
    if (e.table) e.table.columns = e.table.columns.map((c) => ({ ...c, width_mm: r2(c.width_mm * f) }));
  }
  return out;
}

export interface Guide { axis: 'x' | 'y'; at: number }
/** Imán: ajusta una caja a la cuadrícula y a bordes/centros de otros elementos y del área imprimible. */
export function snapBox(doc: CanvasDoc, box: Box, ignore: string[], threshold = 1.2): { box: Box; guides: Guide[] } {
  if (!doc.grid.snap) return { box, guides: [] };
  const area = printableArea(doc);
  const others = doc.elements.filter((e) => !ignore.includes(e.id) && !e.hidden);
  const xs = [area.x, area.x + area.w, area.x + area.w / 2, ...others.flatMap((e) => [e.x, e.x + e.w, e.x + e.w / 2])];
  const ys = [area.y, ...others.flatMap((e) => [e.y, e.y + e.h, e.y + e.h / 2])];
  const guides: Guide[] = [];
  const pick = (cands: number[], points: number[]): number | null => {
    let best: { d: number; delta: number; at: number } | null = null;
    for (const p of points) for (const c of cands) {
      const d = Math.abs(c - p);
      if (d <= threshold && (!best || d < best.d)) best = { d, delta: c - p, at: c };
    }
    return best ? (guides.push({ axis: cands === xs ? 'x' : 'y', at: best.at }), best.delta) : null;
  };
  const dx = pick(xs, [box.x, box.x + box.w, box.x + box.w / 2]);
  const dy = pick(ys, [box.y, box.y + box.h, box.y + box.h / 2]);
  const g = doc.grid.size_mm;
  const out = { ...box };
  out.x = r2(dx !== null ? box.x + dx : Math.round(box.x / g) * g);
  out.y = r2(dy !== null ? box.y + dy : Math.round(box.y / g) * g);
  return { box: out, guides };
}

export function toUnit(mm: number, unit: Page['unit']): number {
  return Math.round((mm / UNITS[unit]) * 100) / 100;
}

export function fromUnit(v: number, unit: Page['unit']): number {
  return r2(v * UNITS[unit]);
}

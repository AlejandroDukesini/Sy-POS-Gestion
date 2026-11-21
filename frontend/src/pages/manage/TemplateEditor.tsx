import {
  AlignCenter, AlignLeft, AlignRight, ArrowLeft, Bold, Combine, Eye, ImagePlus, Italic, Redo2, Rows3, Save, SplitSquareHorizontal,
  Star, Table2, Trash2, Underline, Undo2, WrapText,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type DragEvent, type KeyboardEvent } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { api, ApiError, put, upload } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { Dialog } from '../../components/ui/Dialog';
import { Alert, Badge, ErrorAlert, ErrorState, Loading } from '../../components/ui/Feedback';
import { Checkbox, SelectField, TextField } from '../../components/ui/Form';
import { Tabs } from '../../components/ui/Layout';
import { useToast } from '../../context/Toast';
import { dateTime } from '../../lib/format';
import { useApi } from '../../lib/hooks';
import { CanvasEditor } from './CanvasEditor';
import {
  applyBorders, clearValues, colLetter, colPx, deleteCols, deleteRows, displayValue, expandToMerges, insertCols, insertRows,
  merge, mergeAt, normalize, parseRange, ref, rangeRef, rowPx, setBinding, setValue, styleOf, unmerge, updateStyle,
  type Binding, type BorderMode, type Layout, type Range, type StyleDef, type TemplateDoc,
} from '../../lib/templateModel';
import { KIND_LABEL } from './PrintTemplates';
import '../../styles/template-editor.css';

interface CatalogField { key: string; label: string; type: string }
interface Catalog { fields: { group: string; fields: CatalogField[] }[]; line_fields: CatalogField[]; functions: string[] }

const BORDER_CSS: Record<string, string> = {
  hair: '1px dotted', thin: '1px solid', dotted: '1px dotted', dashed: '1px dashed', dashDot: '1px dashed', dashDotDot: '1px dashed',
  medium: '2px solid', mediumDashed: '2px dashed', mediumDashDot: '2px dashed', mediumDashDotDot: '2px dashed', slantDashDot: '2px dashed',
  thick: '3px solid', double: '3px double',
};
const FORMATS = [
  { value: '', label: 'General' }, { value: '"$"#,##0', label: 'Moneda ($ 1.234)' }, { value: '"$"#,##0.00', label: 'Moneda con decimales' },
  { value: '#,##0', label: 'Número (1.234)' }, { value: '#,##0.00', label: 'Número con decimales' }, { value: '0%', label: 'Porcentaje' },
  { value: 'dd/mm/yyyy', label: 'Fecha (18/11/2026)' }, { value: 'h:mm:ss AM/PM', label: 'Hora (3:04:05 p. m.)' }, { value: '@', label: 'Texto' },
];
const PAPERS = [
  { value: 'letter', label: 'Carta' }, { value: 'legal', label: 'Oficio' }, { value: 'a4', label: 'A4' }, { value: 'a5', label: 'A5' },
  { value: 'roll80', label: 'Rollo 80 mm (impresora térmica)' }, { value: 'roll58', label: 'Rollo 58 mm' }, { value: 'custom', label: 'Personalizado' },
];
const DRAG_TYPE = 'application/x-pospy-field';

export function TemplateEditor() {
  const { id } = useParams();
  const [params] = useSearchParams();
  const version = params.get('version');
  const tpl = useApi<any>(`/print-templates/${id}${version ? `?version=${version}` : ''}`);
  if (tpl.loading && !tpl.data) return <Loading label="Cargando plantilla…" />;
  if (tpl.error) return <ErrorState error={tpl.error} onRetry={tpl.reload} />;
  const key = `${tpl.data.public_id}-${tpl.data.version}-${tpl.data.loaded_version}`;
  if (tpl.data.designer === 'canvas') return <CanvasEditor key={key} tpl={tpl.data} reload={tpl.reload} />;
  return <Editor key={key} tpl={tpl.data} reload={tpl.reload} />;
}

function cssFor(st: StyleDef, zoom: number): CSSProperties {
  const css: CSSProperties = {};
  const f = st.font ?? {};
  css.fontSize = `${((f.size ?? 11) * 4 / 3) * zoom}px`;
  if (f.b) css.fontWeight = 700;
  if (f.i) css.fontStyle = 'italic';
  if (f.u) css.textDecoration = 'underline';
  if (f.color) css.color = f.color;
  if (st.fill) css.background = st.fill;
  if (st.h) css.textAlign = st.h;
  css.verticalAlign = st.v === 'top' ? 'top' : st.v === 'center' ? 'middle' : 'bottom';
  css.whiteSpace = st.wrap ? 'normal' : 'nowrap';
  return css;
}

function Editor({ tpl, reload }: { tpl: any; reload: () => void }) {
  const { notify } = useToast();
  const navigate = useNavigate();
  const catalog: Catalog = tpl.catalog;
  const [doc, setDoc] = useState<TemplateDoc>({
    layout: tpl.layout, bindings: { cells: {}, products: null, discount_pct: '0', ...tpl.bindings },
  });
  const docRef = useRef(doc);
  docRef.current = doc;
  const past = useRef<TemplateDoc[]>([]);
  const future = useRef<TemplateDoc[]>([]);
  const [dirty, setDirty] = useState(false);
  const [sel, setSel] = useState<Range>({ r1: 1, c1: 1, r2: 1, c2: 1 });
  const dragging = useRef(false);
  const [editing, setEditing] = useState<{ ref: string; text: string } | null>(null);
  const [zoom, setZoom] = useState(0.75);
  const [tab, setTab] = useState<'campos' | 'celda' | 'productos' | 'pagina' | 'imagenes'>('campos');
  const [preview, setPreview] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [note, setNote] = useState('');
  const [borderStyle, setBorderStyle] = useState('thin');
  const gridRef = useRef<HTMLDivElement>(null);
  const L = doc.layout;
  const B = doc.bindings;
  const importNotes: string[] = useMemo(() => {
    try { return JSON.parse(sessionStorage.getItem(`pospy.import-notes.${tpl.public_id}`) ?? '[]'); } catch { return []; }
  }, [tpl.public_id]);
  const labels = useMemo(() => {
    const m: Record<string, string> = {};
    catalog.fields.forEach((g) => g.fields.forEach((f) => { m[f.key] = f.label; }));
    catalog.line_fields.forEach((f) => { m[`linea.${f.key}`] = f.label; });
    return m;
  }, [catalog]);

  const commit = useCallback((next: TemplateDoc) => {
    if (next === docRef.current) return;
    past.current.push(docRef.current);
    if (past.current.length > 100) past.current.shift();
    future.current = [];
    setDoc(next);
    setDirty(true);
  }, []);
  const undo = () => {
    const prev = past.current.pop();
    if (!prev) return;
    future.current.push(docRef.current);
    setDoc(prev);
    setDirty(true);
  };
  const redo = () => {
    const next = future.current.pop();
    if (!next) return;
    past.current.push(docRef.current);
    setDoc(next);
    setDirty(true);
  };

  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);

  const area = expandToMerges(L, sel);
  const anchor = ref(sel.r1, sel.c1);
  const anchorStyle = styleOf(L, anchor);
  const inProducts = (r: number) => Boolean(B.products && r >= B.products.start && r <= B.products.end);
  const style = (patch: (st: StyleDef) => StyleDef) => commit(updateStyle(doc, area, patch));

  // ------------------------------------------------------------------ edición de celdas
  const startEdit = (initial?: string) => {
    const r = sel.r1;
    const c = sel.c1;
    const k = ref(r, c);
    if (B.cells[k] || inProducts(r)) {
      setTab('celda');
      return;
    }
    const v = L.cells[k]?.v;
    setEditing({ ref: k, text: initial ?? (v === undefined ? '' : String(v)) });
  };
  const finishEdit = (move: number) => {
    if (!editing) return;
    commit(setValue(doc, editing.ref, editing.text));
    setEditing(null);
    if (move) setSel((s) => ({ r1: Math.min(L.rows.length, s.r1 + move), c1: s.c1, r2: Math.min(L.rows.length, s.r1 + move), c2: s.c1 }));
    gridRef.current?.focus();
  };
  const onKey = (e: KeyboardEvent) => {
    if (editing) return;
    const ctrl = e.ctrlKey || e.metaKey;
    if (ctrl && e.key.toLowerCase() === 'z') { e.preventDefault(); undo(); return; }
    if (ctrl && e.key.toLowerCase() === 'y') { e.preventDefault(); redo(); return; }
    if (ctrl && e.key.toLowerCase() === 'b') { e.preventDefault(); style((st) => ({ ...st, font: { ...st.font, b: !anchorStyle.font?.b } })); return; }
    const moves: Record<string, [number, number]> = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };
    if (moves[e.key]) {
      e.preventDefault();
      const [dr, dc] = moves[e.key];
      setSel((s) => {
        const r = Math.max(1, Math.min(L.rows.length, (e.shiftKey ? s.r2 : s.r1) + dr));
        const c = Math.max(1, Math.min(L.cols.length, (e.shiftKey ? s.c2 : s.c1) + dc));
        return e.shiftKey ? { ...s, r2: r, c2: c } : { r1: r, c1: c, r2: r, c2: c };
      });
      return;
    }
    if (e.key === 'Enter' || e.key === 'F2') { e.preventDefault(); startEdit(); return; }
    if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); commit(clearValues(doc, area)); return; }
    if (e.key.length === 1 && !ctrl && !e.altKey) { e.preventDefault(); startEdit(e.key); }
  };

  // ------------------------------------------------------------------ arrastrar campos
  const onDrop = (e: DragEvent, r: number, c: number) => {
    e.preventDefault();
    const raw = e.dataTransfer.getData(DRAG_TYPE);
    if (!raw) return;
    const item = JSON.parse(raw) as { kind: 'field' | 'line' | 'table'; key?: string };
    setSel({ r1: r, c1: c, r2: r, c2: c });
    if (item.kind === 'table') { commit(addProductTable(doc, r, c)); setTab('productos'); return; }
    if (item.kind === 'line') {
      if (!inProducts(r) || !B.products) {
        notify('warning', 'Arrástrelo dentro de la tabla de productos', 'Primero cree la tabla con «Tabla de productos».');
        return;
      }
      const next = structuredClone(doc);
      next.bindings.products!.columns[colLetter(c)] = item.key === 'valor' ? { expr: 'cantidad*precio' } : { field: item.key };
      commit(next);
      return;
    }
    if (inProducts(r)) {
      notify('warning', 'Esa celda es de la tabla de productos', 'Los datos del documento van fuera de la tabla.');
      return;
    }
    const mergeRange = mergeAt(L, r, c);
    const target = mergeRange ? ref(mergeRange.r1, mergeRange.c1) : ref(r, c);
    commit(setBinding(doc, target, { field: item.key }));
    setTab('celda');
  };

  // ------------------------------------------------------------------ redimensionar columnas y filas
  const resize = (axis: 'col' | 'row', index: number, startEvent: React.MouseEvent) => {
    startEvent.preventDefault();
    startEvent.stopPropagation();
    const start = axis === 'col' ? startEvent.clientX : startEvent.clientY;
    const base = axis === 'col' ? L.cols[index - 1] : L.rows[index - 1];
    let latest = base;
    const move = (ev: MouseEvent) => {
      const delta = ((axis === 'col' ? ev.clientX : ev.clientY) - start) / zoom;
      latest = axis === 'col' ? Math.max(0, Math.round((base + delta / 7) * 10) / 10) : Math.max(0, Math.round((base + delta * 0.75) * 4) / 4);
      setDoc((d) => {
        const n = structuredClone(d);
        if (axis === 'col') n.layout.cols[index - 1] = latest; else n.layout.rows[index - 1] = latest;
        return n;
      });
    };
    const up = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
      const before = structuredClone(docRef.current);
      if (axis === 'col') before.layout.cols[index - 1] = base; else before.layout.rows[index - 1] = base;
      past.current.push(before);
      future.current = [];
      setDirty(true);
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  };

  // ------------------------------------------------------------------ guardar y vista previa
  const save = async (activate: boolean) => {
    setSaving(true);
    setError(null);
    try {
      await put(`/print-templates/${tpl.public_id}`, { layout: L, bindings: B, note: note.trim(), activate, version: tpl.version });
      notify('success', activate ? 'Plantilla guardada y activa' : 'Nueva versión guardada');
      setDirty(false);
      setNote('');
      if (tpl.loaded_version !== tpl.current_version) navigate(`/gestion/plantillas/${tpl.public_id}`, { replace: true });
      reload();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setSaving(false);
    }
  };
  const setMeta = async (body: Record<string, unknown>, ok: string) => {
    try {
      await api(`/print-templates/${tpl.public_id}`, { method: 'PATCH', body });
      notify('success', ok);
      reload();
    } catch (err) {
      notify('danger', 'No se pudo cambiar', (err as Error).message);
    }
  };

  // ------------------------------------------------------------------ cuadrícula
  const covered = useMemo(() => {
    const hidden = new Set<string>();
    const spans = new Map<string, Range>();
    for (const m of L.merges) {
      const g = parseRange(m);
      if (!g) continue;
      spans.set(ref(g.r1, g.c1), g);
      for (let r = g.r1; r <= g.r2; r++) for (let c = g.c1; c <= g.c2; c++) if (r !== g.r1 || c !== g.c1) hidden.add(ref(r, c));
    }
    return { hidden, spans };
  }, [L.merges]);
  const colX = useMemo(() => {
    const xs = [0];
    L.cols.forEach((w) => xs.push(xs[xs.length - 1] + Math.max(colPx(w), 6) * zoom));
    return xs;
  }, [L.cols, zoom]);
  const rowY = useMemo(() => {
    const ys = [0];
    L.rows.forEach((h) => ys.push(ys[ys.length - 1] + Math.max(rowPx(h), 4) * zoom));
    return ys;
  }, [L.rows, zoom]);
  const printArea = L.page.print_area ? parseRange(L.page.print_area) : null;

  const cellBorder = (r: number, c: number, g: Range | undefined): CSSProperties => {
    const pick = (cr: number, cc: number, side: 'l' | 'r' | 't' | 'b') => {
      const b = styleOf(L, ref(cr, cc)).border?.[side];
      return b ? `${BORDER_CSS[b[0]] ?? '1px solid'} ${b[1]}` : undefined;
    };
    const r2 = g?.r2 ?? r;
    const c2 = g?.c2 ?? c;
    return { borderLeft: pick(r, c, 'l'), borderTop: pick(r, c, 't'), borderRight: pick(r, c2, 'r'), borderBottom: pick(r2, c, 'b') };
  };

  const fieldChip = (b: Binding, line = false) => {
    const label = line ? labels[`linea.${b.field ?? ''}`] : labels[b.field ?? ''];
    return (
      <span className={`tpl-chip${b.expr ? ' tpl-chip-calc' : ''}`} title={b.expr ? `Cálculo: ${b.expr}` : label}>
        {b.expr ? `= ${b.expr}` : label ?? b.field}
      </span>
    );
  };

  const rows = [];
  for (let r = 1; r <= L.rows.length; r++) {
    const hiddenRow = L.rows[r - 1] === 0;
    const tds = [];
    for (let c = 1; c <= L.cols.length; c++) {
      const k = ref(r, c);
      if (covered.hidden.has(k)) continue;
      const g = covered.spans.get(k);
      const cell = L.cells[k];
      const st = styleOf(L, k);
      const binding = B.cells[k];
      const pcol = B.products && inProducts(r) ? B.products.columns[colLetter(c)] : undefined;
      const selected = r >= area.r1 && r <= area.r2 && c >= area.c1 && c <= area.c2;
      const outside = printArea && (r < printArea.r1 || r > printArea.r2 || c < printArea.c1 || c > printArea.c2);
      const classes = ['tpl-cell', selected && 'sel', inProducts(r) && 'tpl-prod', B.products?.header_row === r && 'tpl-prod-head',
        outside && 'tpl-outside', hiddenRow && 'tpl-hidden'].filter(Boolean).join(' ');
      let content: React.ReactNode = displayValue(cell?.v, st.fmt);
      if (binding) content = fieldChip(binding);
      else if (pcol) content = r === B.products!.start ? fieldChip(pcol, true) : <span className="tpl-ghost">↓</span>;
      else if (inProducts(r) && cell?.v !== undefined) content = <span className="tpl-ghost" title="Dato de ejemplo: no se imprime">{content}</span>;
      tds.push(
        <td key={k} data-ref={k} rowSpan={g ? g.r2 - g.r1 + 1 : undefined} colSpan={g ? g.c2 - g.c1 + 1 : undefined}
          className={classes} style={{ ...cssFor(st, zoom), ...cellBorder(r, c, g) }} aria-selected={selected}
          onMouseDown={(e) => {
            if (e.button !== 0) return;
            dragging.current = true;
            setEditing(null);
            setSel((s) => (e.shiftKey ? { ...s, r2: r, c2: c } : { r1: r, c1: c, r2: r, c2: c }));
            gridRef.current?.focus();
          }}
          onMouseEnter={() => { if (dragging.current) setSel((s) => ({ ...s, r2: r, c2: c })); }}
          onDoubleClick={() => startEdit()}
          onDragOver={(e) => { if (e.dataTransfer.types.includes(DRAG_TYPE)) e.preventDefault(); }}
          onDrop={(e) => onDrop(e, r, c)}>
          {editing?.ref === k ? (
            <input className="tpl-input" autoFocus value={editing.text} aria-label={`Contenido de ${k}`}
              onChange={(e) => setEditing({ ref: k, text: e.target.value })}
              onKeyDown={(e) => {
                if (e.key === 'Enter') { e.preventDefault(); finishEdit(1); }
                if (e.key === 'Escape') { e.preventDefault(); setEditing(null); gridRef.current?.focus(); }
                e.stopPropagation();
              }}
              onBlur={() => finishEdit(0)} />
          ) : content}
        </td>,
      );
    }
    rows.push(
      <tr key={r} style={{ height: Math.max(rowPx(L.rows[r - 1]), 4) * zoom }}>
        <th scope="row" className="tpl-rowhead">
          {hiddenRow ? '·' : r}
          <span className="tpl-resize-row" onMouseDown={(e) => resize('row', r, e)} aria-hidden />
        </th>
        {tds}
      </tr>,
    );
  }

  const status = tpl.active ? <Badge kind="success">Activa</Badge> : <Badge kind="warning">Borrador</Badge>;
  const forType = tpl.kind === 'documento' ? tpl.document_type?.name : KIND_LABEL[tpl.kind];

  return (
    <div className="stack tpl-editor" onMouseUp={() => { dragging.current = false; }}>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <Link to="/gestion/plantillas" className="btn btn-ghost"><ArrowLeft size={20} aria-hidden /> Plantillas</Link>
        <span className="row" style={{ gap: 6 }}>
          {status}{tpl.is_default ? <Badge kind="info">Predeterminada</Badge> : null}
          <Badge>{forType}</Badge><Badge>{tpl.inventory?.name}</Badge>
        </span>
      </div>
      <div className="row tpl-titlebar">
        <h1 className="grow" style={{ margin: 0 }}>{tpl.name}</h1>
        {tpl.has_original && <a className="btn btn-ghost btn-sm" href={`/api/print-templates/${tpl.public_id}/original`}>Descargar Excel original</a>}
        {tpl.active && !tpl.is_default ? (
          <Button size="sm" icon={<Star size={18} />} onClick={() => setMeta({ is_default: true }, 'Ahora es la predeterminada')}>Usar como predeterminada</Button>) : null}
        {tpl.active ? <Button size="sm" variant="ghost" onClick={() => setMeta({ active: false, is_default: false }, 'Plantilla desactivada')}>Desactivar</Button> : null}
      </div>
      {tpl.loaded_version !== tpl.current_version && (
        <Alert kind="warning" title={`Está viendo la versión ${tpl.loaded_version}`}>
          Si guarda, esta versión pasa a ser la actual (versión {tpl.current_version + 1}). <Link to={`/gestion/plantillas/${tpl.public_id}`}>Volver a la actual</Link>
        </Alert>
      )}
      {importNotes.length > 0 && (
        <Alert kind="info" title="Resultado de la importación (revise y confirme antes de guardar)">
          <ul>{importNotes.map((n) => <li key={n}>{n}</li>)}</ul>
        </Alert>
      )}
      {tpl.problems?.length > 0 && <Alert kind="danger" title="Problemas de la versión guardada"><ul>{tpl.problems.map((p: string) => <li key={p}>{p}</li>)}</ul></Alert>}
      <ErrorAlert error={error} />

      <div className="tpl-toolbar" role="toolbar" aria-label="Formato">
        <Button size="sm" variant="ghost" iconOnly icon={<Undo2 size={18} />} disabled={!past.current.length} onClick={undo}>Deshacer (Ctrl+Z)</Button>
        <Button size="sm" variant="ghost" iconOnly icon={<Redo2 size={18} />} disabled={!future.current.length} onClick={redo}>Rehacer (Ctrl+Y)</Button>
        <span className="tpl-sep" />
        <Button size="sm" variant={anchorStyle.font?.b ? 'primary' : 'ghost'} iconOnly icon={<Bold size={18} />}
          onClick={() => style((st) => ({ ...st, font: { ...st.font, b: !anchorStyle.font?.b } }))}>Negrita</Button>
        <Button size="sm" variant={anchorStyle.font?.i ? 'primary' : 'ghost'} iconOnly icon={<Italic size={18} />}
          onClick={() => style((st) => ({ ...st, font: { ...st.font, i: !anchorStyle.font?.i } }))}>Cursiva</Button>
        <Button size="sm" variant={anchorStyle.font?.u ? 'primary' : 'ghost'} iconOnly icon={<Underline size={18} />}
          onClick={() => style((st) => ({ ...st, font: { ...st.font, u: !anchorStyle.font?.u } }))}>Subrayado</Button>
        <label className="tpl-tool">Tamaño
          <select value={anchorStyle.font?.size ?? 11} onChange={(e) => style((st) => ({ ...st, font: { ...st.font, size: Number(e.target.value) } }))}>
            {[8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24, 28, 36, 48, 65].map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label className="tpl-tool">Letra
          <input type="color" value={anchorStyle.font?.color ?? '#000000'}
            onChange={(e) => style((st) => ({ ...st, font: { ...st.font, color: e.target.value.toUpperCase() } }))} />
        </label>
        <label className="tpl-tool">Relleno
          <input type="color" value={anchorStyle.fill ?? '#FFFFFF'} onChange={(e) => style((st) => ({ ...st, fill: e.target.value.toUpperCase() }))} />
        </label>
        <Button size="sm" variant="ghost" onClick={() => style((st) => ({ ...st, fill: undefined }))}>Sin relleno</Button>
        <span className="tpl-sep" />
        {(['left', 'center', 'right'] as const).map((h) => {
          const Icon = h === 'left' ? AlignLeft : h === 'center' ? AlignCenter : AlignRight;
          return <Button key={h} size="sm" variant={anchorStyle.h === h ? 'primary' : 'ghost'} iconOnly icon={<Icon size={18} />}
            onClick={() => style((st) => ({ ...st, h }))}>{`Alinear ${h === 'left' ? 'a la izquierda' : h === 'center' ? 'al centro' : 'a la derecha'}`}</Button>;
        })}
        <label className="tpl-tool">Vertical
          <select value={anchorStyle.v ?? 'bottom'} onChange={(e) => style((st) => ({ ...st, v: e.target.value as StyleDef['v'] }))}>
            <option value="top">Arriba</option><option value="center">Centro</option><option value="bottom">Abajo</option>
          </select>
        </label>
        <Button size="sm" variant={anchorStyle.wrap ? 'primary' : 'ghost'} iconOnly icon={<WrapText size={18} />}
          onClick={() => style((st) => ({ ...st, wrap: !anchorStyle.wrap }))}>Ajustar texto</Button>
        <label className="tpl-tool">Formato
          <select value={anchorStyle.fmt ?? ''} onChange={(e) => style((st) => ({ ...st, fmt: e.target.value || undefined }))}>
            {FORMATS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
            {anchorStyle.fmt && !FORMATS.some((f) => f.value === anchorStyle.fmt) && <option value={anchorStyle.fmt}>Del Excel: {anchorStyle.fmt.slice(0, 24)}</option>}
          </select>
        </label>
        <span className="tpl-sep" />
        <label className="tpl-tool">Bordes
          <select value="" onChange={(e) => { if (e.target.value) commit(applyBorders(doc, area, e.target.value as BorderMode, borderStyle)); }}>
            <option value="">Aplicar…</option><option value="all">Todos</option><option value="outer">Contorno</option>
            <option value="bottom">Inferior</option><option value="top">Superior</option><option value="none">Quitar</option>
          </select>
        </label>
        <label className="tpl-tool">Línea
          <select value={borderStyle} onChange={(e) => setBorderStyle(e.target.value)}>
            <option value="thin">Fina</option><option value="medium">Media</option><option value="thick">Gruesa</option>
            <option value="dashed">Guiones</option><option value="mediumDashed">Guiones medios</option><option value="dotted">Puntos</option>
          </select>
        </label>
        <Button size="sm" variant="ghost" icon={<Combine size={18} />} onClick={() => commit(merge(doc, area))}>Combinar</Button>
        <Button size="sm" variant="ghost" icon={<SplitSquareHorizontal size={18} />} onClick={() => commit(unmerge(doc, area))}>Separar</Button>
        <span className="tpl-sep" />
        <label className="tpl-tool">Filas y columnas
          <select value="" onChange={(e) => {
            const v = e.target.value;
            const n = area.r2 - area.r1 + 1;
            const m = area.c2 - area.c1 + 1;
            if (v === 'row-above') commit(insertRows(doc, area.r1, n));
            if (v === 'row-below') commit(insertRows(doc, area.r2 + 1, n));
            if (v === 'row-delete') commit(deleteRows(doc, area.r1, n));
            if (v === 'col-left') commit(insertCols(doc, area.c1, m));
            if (v === 'col-right') commit(insertCols(doc, area.c2 + 1, m));
            if (v === 'col-delete') commit(deleteCols(doc, area.c1, m));
          }}>
            <option value="">Elegir…</option><option value="row-above">Insertar filas arriba</option><option value="row-below">Insertar filas abajo</option>
            <option value="row-delete">Eliminar filas</option><option value="col-left">Insertar columnas a la izquierda</option>
            <option value="col-right">Insertar columnas a la derecha</option><option value="col-delete">Eliminar columnas</option>
          </select>
        </label>
        <label className="tpl-tool">Ancho
          <input type="number" min={0} max={255} step={0.5} value={L.cols[sel.c1 - 1]} aria-label={`Ancho de la columna ${colLetter(sel.c1)}`}
            onChange={(e) => { const n = structuredClone(doc); for (let c = area.c1; c <= area.c2; c++) n.layout.cols[c - 1] = Number(e.target.value); commit(n); }} />
        </label>
        <label className="tpl-tool">Alto
          <input type="number" min={0} max={409} step={0.75} value={L.rows[sel.r1 - 1]} aria-label={`Alto de la fila ${sel.r1}`}
            onChange={(e) => { const n = structuredClone(doc); for (let r = area.r1; r <= area.r2; r++) n.layout.rows[r - 1] = Number(e.target.value); commit(n); }} />
        </label>
        <label className="tpl-tool">Zoom
          <select value={zoom} onChange={(e) => setZoom(Number(e.target.value))}>
            {[0.35, 0.5, 0.75, 1].map((z) => <option key={z} value={z}>{z * 100} %</option>)}
          </select>
        </label>
      </div>

      <div className="tpl-workspace">
        <div className="tpl-grid-wrap">
          <div className="tpl-selinfo" aria-live="polite">
            <strong>{rangeRef(area)}</strong>
            {B.cells[anchor] ? <> · vinculada a {fieldChip(B.cells[anchor])}</> : null}
            {inProducts(sel.r1) ? <> · tabla de productos</> : null}
          </div>
          <div className="tpl-grid" ref={gridRef} tabIndex={0} onKeyDown={onKey} role="grid" aria-label="Diseño de la plantilla"
            aria-rowcount={L.rows.length} aria-colcount={L.cols.length}>
            <div style={{ position: 'relative', width: 'max-content' }}>
              <table className="tpl-table" style={{ width: colX[colX.length - 1] + 40 }}>
                <colgroup>
                  <col style={{ width: 40 }} />
                  {L.cols.map((w, i) => <col key={i} style={{ width: Math.max(colPx(w), 6) * zoom }} />)}
                </colgroup>
                <thead>
                  <tr>
                    <th className="tpl-corner" aria-label="Esquina" />
                    {L.cols.map((w, i) => (
                      <th key={i} scope="col" className={`tpl-colhead${w === 0 ? ' tpl-hidden' : ''}`}>
                        {colLetter(i + 1)}
                        <span className="tpl-resize-col" onMouseDown={(e) => resize('col', i + 1, e)} aria-hidden />
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>{rows}</tbody>
              </table>
              {L.images.map((img) => {
                const cw = img.w / Math.max(0.05, 1 - (img.crop?.l ?? 0) - (img.crop?.r ?? 0));
                const ch = img.h / Math.max(0.05, 1 - (img.crop?.t ?? 0) - (img.crop?.b ?? 0));
                const k = 4 / 3 * zoom;
                return (
                  <div key={img.id} className="tpl-image" title="Imagen (se edita en la pestaña Imágenes)" style={{
                    left: 40 + (colX[img.col] ?? 0) + img.col_off * k, top: 24 + (rowY[img.row] ?? 0) + img.row_off * k,
                    width: img.w * k, height: img.h * k }}>
                    <img alt="" src={`/api/print-templates/${tpl.public_id}/images/${img.file}`} style={{
                      width: cw * k, height: ch * k, marginLeft: -(img.crop?.l ?? 0) * cw * k, marginTop: -(img.crop?.t ?? 0) * ch * k }} />
                  </div>
                );
              })}
            </div>
          </div>
          <p className="muted tpl-help">
            Clic para elegir una celda; arrastre o use Mayús para elegir un rango. Doble clic, Enter o empiece a escribir para editar.
            Arrastre campos desde el panel hasta una celda. Las celdas grises quedan fuera del área de impresión.
          </p>
        </div>

        <aside className="tpl-side" aria-label="Panel de la plantilla">
          <Tabs label="Panel" value={tab} onChange={setTab} tabs={[
            { value: 'campos', label: 'Campos' }, { value: 'celda', label: 'Celda' }, { value: 'productos', label: 'Productos' },
            { value: 'pagina', label: 'Página' }, { value: 'imagenes', label: 'Imágenes' },
          ]} />
          <div className="tpl-side-body">
            {tab === 'campos' && <FieldsPanel catalog={catalog} onAssign={(key) => {
              if (inProducts(sel.r1)) { notify('warning', 'Esa celda es de la tabla de productos'); return; }
              commit(setBinding(doc, anchor, { field: key }));
              setTab('celda');
            }} onTable={() => { commit(addProductTable(doc, sel.r1, sel.c1)); setTab('productos'); }} />}
            {tab === 'celda' && <CellPanel doc={doc} anchor={anchor} col={sel.c1} catalog={catalog} commit={commit} inProducts={inProducts(sel.r1)} />}
            {tab === 'productos' && <ProductsPanel doc={doc} sel={area} catalog={catalog} commit={commit} />}
            {tab === 'pagina' && <PagePanel doc={doc} sel={area} commit={commit} />}
            {tab === 'imagenes' && <ImagesPanel doc={doc} sel={sel} commit={commit} templateId={tpl.public_id} />}
          </div>
        </aside>
      </div>

      <div className="tpl-savebar">
        <TextField label="Nota de esta versión (opcional)" value={note} onChange={setNote} maxLength={200} />
        <Button icon={<Eye size={20} />} onClick={() => setPreview(true)}>Vista previa</Button>
        <Button icon={<Save size={20} />} busy={saving} onClick={() => save(false)}>Guardar versión</Button>
        <Button variant="primary" icon={<Save size={20} />} busy={saving} onClick={() => save(true)}>
          {tpl.active ? 'Guardar' : 'Guardar y activar'}
        </Button>
        {dirty && <span className="muted">Cambios sin guardar</span>}
      </div>
      <Versions tpl={tpl} />
      {preview && <PreviewDialog templateId={tpl.public_id} doc={doc} onClose={() => setPreview(false)} />}
    </div>
  );
}

/** Tabla de productos lista para usar: encabezados, 5 filas con bordes y totales debajo. */
function addProductTable(doc: TemplateDoc, r: number, c: number): TemplateDoc {
  let out = structuredClone(doc);
  if (out.bindings.products) return out;
  const need = c + 4 - out.layout.cols.length;
  if (need > 0) out = insertCols(out, out.layout.cols.length + 1, need);
  const lastRow = r + 9;
  if (lastRow > out.layout.rows.length) out.layout.rows.push(...Array(lastRow - out.layout.rows.length).fill(15));
  const heads = ['CANT', 'CÓDIGO', 'DESCRIPCIÓN', 'V. UNIT', 'VALOR'];
  const fields: Binding[] = [{ field: 'cantidad' }, { field: 'codigo' }, { field: 'descripcion' }, { field: 'precio' }, { expr: 'cantidad*precio' }];
  heads.forEach((h, i) => { out = setValue(out, ref(r, c + i), h); });
  out = updateStyle(out, { r1: r, c1: c, r2: r, c2: c + 4 }, (st) => ({ ...st, font: { ...st.font, b: true }, h: 'center', fill: '#EEF2F7' }));
  out = applyBorders(out, { r1: r, c1: c, r2: r + 5, c2: c + 4 }, 'all', 'thin');
  out = updateStyle(out, { r1: r + 1, c1: c + 3, r2: r + 5, c2: c + 4 }, (st) => ({ ...st, fmt: '"$"#,##0', h: 'right' }));
  out.bindings.products = { start: r + 1, end: r + 5, header_row: r, columns: Object.fromEntries(fields.map((f, i) => [colLetter(c + i), f])) };
  const labelCol = c + 3;
  [['Subtotal', 'subtotal'], ['Descuento', 'descuento'], ['TOTAL A PAGAR', 'total']].forEach(([label, field], i) => {
    out = setValue(out, ref(r + 7 + i, labelCol), label);
    out = setBinding(out, ref(r + 7 + i, labelCol + 1), { field });
  });
  out = updateStyle(out, { r1: r + 7, c1: labelCol, r2: r + 9, c2: labelCol }, (st) => ({ ...st, font: { ...st.font, b: true }, h: 'right' }));
  out = updateStyle(out, { r1: r + 7, c1: labelCol + 1, r2: r + 9, c2: labelCol + 1 }, (st) => ({ ...st, fmt: '"$"#,##0', h: 'right' }));
  out.layout.page.repeat_rows = `${r}:${r}`;
  return out;
}

function FieldsPanel({ catalog, onAssign, onTable }: { catalog: Catalog; onAssign: (key: string) => void; onTable: () => void }) {
  const drag = (e: DragEvent, payload: object) => {
    e.dataTransfer.setData(DRAG_TYPE, JSON.stringify(payload));
    e.dataTransfer.effectAllowed = 'copy';
  };
  return (
    <div className="stack">
      <p className="muted">Arrastre un campo hasta una celda, o elija una celda y pulse el campo.</p>
      <div className="tpl-palette-group">
        <h3>Bloques</h3>
        <button type="button" className="tpl-field tpl-field-block" draggable onDragStart={(e) => drag(e, { kind: 'table' })} onClick={onTable}>
          <Table2 size={16} aria-hidden /> Tabla de productos (con totales)
        </button>
      </div>
      {catalog.fields.map((g) => (
        <div key={g.group} className="tpl-palette-group">
          <h3>{g.group}</h3>
          {g.fields.map((f) => (
            <button key={f.key} type="button" className="tpl-field" draggable onDragStart={(e) => drag(e, { kind: 'field', key: f.key })}
              onClick={() => onAssign(f.key)}>{f.label}</button>
          ))}
        </div>
      ))}
      <div className="tpl-palette-group">
        <h3>Productos (dentro de la tabla)</h3>
        {catalog.line_fields.map((f) => (
          <button key={f.key} type="button" className="tpl-field tpl-field-line" draggable
            onDragStart={(e) => drag(e, { kind: 'line', key: f.key })}><Rows3 size={14} aria-hidden /> {f.label}</button>
        ))}
      </div>
    </div>
  );
}

function BindingEditor({ value, onChange, options, line }: {
  value: Binding | undefined; onChange: (b: Binding | null) => void; options: { value: string; label: string }[]; line?: boolean;
}) {
  const mode = value?.expr !== undefined ? 'expr' : value?.field ? 'field' : 'none';
  return (
    <div className="stack">
      <SelectField label="Contenido" value={mode} onChange={(m) => {
        if (m === 'none') onChange(null);
        else if (m === 'field') onChange({ field: options[0]?.value });
        else onChange({ expr: line ? 'cantidad*precio' : 'subtotal' });
      }} options={[{ value: 'none', label: line ? 'Nada' : 'Texto fijo de la plantilla' }, { value: 'field', label: 'Dato del POS' },
        { value: 'expr', label: 'Cálculo' }]} />
      {mode === 'field' && (
        <SelectField label="Dato" value={value?.field ?? ''} onChange={(f) => onChange({ ...value, field: f, expr: undefined })} options={options} />
      )}
      {mode === 'expr' && (
        <TextField label="Fórmula" value={value?.expr ?? ''} onChange={(x) => onChange({ ...value, expr: x, field: undefined })}
          hint={line ? 'Ej.: cantidad*precio. Variables de cada producto: cantidad, precio, precio_lista, descuento_linea, iva_pct.'
            : 'Ej.: subtotal - descuento, REDONDEAR(total; 0), SUMA(cantidad*precio). Separe argumentos con «;».'} />
      )}
      {mode === 'field' && !line && (
        <>
          <TextField label="Valor alternativo si viene vacío" value={value?.fallback ?? ''} maxLength={200}
            onChange={(x) => onChange({ ...value!, fallback: x || undefined })} hint="Ej.: 222222222222 cuando el cliente no tiene identificación." />
          <TextField label="Formato de fecha u hora (opcional)" value={value?.format ?? ''} maxLength={80}
            onChange={(x) => onChange({ ...value!, format: x || undefined })} hint="Ej.: dd/mm/yyyy o h:mm:ss AM/PM. Vacío: el formato de la celda." />
        </>
      )}
    </div>
  );
}

function CellPanel({ doc, anchor, col, catalog, commit, inProducts }: {
  doc: TemplateDoc; anchor: string; col: number; catalog: Catalog; commit: (d: TemplateDoc) => void; inProducts: boolean;
}) {
  const B = doc.bindings;
  if (inProducts && B.products) {
    const letter = colLetter(col);
    return (
      <div className="stack">
        <h3>Columna {letter} de la tabla de productos</h3>
        <p className="muted">Se repite en cada producto de la operación.</p>
        <BindingEditor line value={B.products.columns[letter]} options={catalog.line_fields.map((f) => ({ value: f.key, label: f.label }))}
          onChange={(b) => {
            const n = structuredClone(doc);
            if (b && (b.field || b.expr !== undefined)) n.bindings.products!.columns[letter] = b; else delete n.bindings.products!.columns[letter];
            commit(n);
          }} />
      </div>
    );
  }
  const opts = catalog.fields.flatMap((g) => g.fields.map((f) => ({ value: f.key, label: `${g.group}: ${f.label}` })));
  const cell = doc.layout.cells[anchor];
  return (
    <div className="stack">
      <h3>Celda {anchor}</h3>
      <BindingEditor value={B.cells[anchor]} options={opts} onChange={(b) => commit(setBinding(doc, anchor, b))} />
      {!B.cells[anchor] && (
        <TextField label="Texto fijo" value={cell?.v === undefined ? '' : String(cell.v)} onChange={(v) => commit(setValue(doc, anchor, v))} />
      )}
      {cell?.f && <Alert kind="info">Fórmula original de Excel: <code>{cell.f}</code>. POS-PY no ejecuta fórmulas de Excel: vincule la celda a un dato o cálculo.</Alert>}
    </div>
  );
}

function ProductsPanel({ doc, sel, catalog, commit }: { doc: TemplateDoc; sel: Range; catalog: Catalog; commit: (d: TemplateDoc) => void }) {
  const p = doc.bindings.products;
  const set = (patch: (d: TemplateDoc) => void) => { const n = structuredClone(doc); patch(n); commit(n); };
  return (
    <div className="stack">
      <TextField label="Descuento de la plantilla (%)" value={doc.bindings.discount_pct} inputMode="decimal"
        onChange={(v) => set((n) => { n.bindings.discount_pct = v.replace(',', '.'); })}
        hint="Se aplica una sola vez sobre el subtotal (ej.: 20 en la ORDEN). Precios y cantidades no cambian." />
      {!p ? (
        <>
          <Alert kind="info">No hay tabla de productos. Elija en la cuadrícula las filas de productos (por ejemplo A15:E25) y pulse el botón, o arrastre «Tabla de productos» desde Campos.</Alert>
          <Button variant="primary" onClick={() => set((n) => {
            n.bindings.products = { start: sel.r1, end: sel.r2, header_row: Math.max(0, sel.r1 - 1), columns: {} };
          })}>Usar filas {sel.r1} a {sel.r2} como tabla</Button>
        </>
      ) : (
        <>
          <div className="grid-3" style={{ gap: 8 }}>
            <TextField label="Primera fila" type="number" value={String(p.start)} onChange={(v) => set((n) => { n.bindings.products!.start = Number(v); })} />
            <TextField label="Última fila" type="number" value={String(p.end)} onChange={(v) => set((n) => { n.bindings.products!.end = Number(v); })} />
            <TextField label="Fila de títulos" type="number" value={String(p.header_row || '')} onChange={(v) => set((n) => { n.bindings.products!.header_row = Number(v) || 0; })} />
          </div>
          <Button size="sm" onClick={() => set((n) => { n.bindings.products!.start = sel.r1; n.bindings.products!.end = sel.r2; })}>
            Usar filas seleccionadas ({sel.r1} a {sel.r2})
          </Button>
          <p className="muted">Con más productos que filas, se agregan filas con el formato de la última y lo de abajo se desplaza.</p>
          <h3>Columnas</h3>
          {doc.layout.cols.map((_, i) => {
            const letter = colLetter(i + 1);
            const b = p.columns[letter];
            const value = b?.expr !== undefined ? `expr:${b.expr}` : b?.field ?? '';
            return (
              <SelectField key={letter} label={`Columna ${letter}`} value={value} onChange={(v) => set((n) => {
                const cols = n.bindings.products!.columns;
                if (!v) delete cols[letter];
                else if (v.startsWith('expr:')) cols[letter] = { expr: v.slice(5) };
                else cols[letter] = { field: v };
              })} options={[{ value: '', label: '—' }, ...catalog.line_fields.map((f) => ({ value: f.key, label: f.label })),
                { value: 'expr:cantidad*precio', label: 'Cálculo: cantidad × precio' },
                ...(b?.expr && b.expr !== 'cantidad*precio' ? [{ value: `expr:${b.expr}`, label: `Cálculo: ${b.expr}` }] : [])]} />
            );
          })}
          <Button variant="danger" size="sm" icon={<Trash2 size={16} />} onClick={() => set((n) => { n.bindings.products = null; })}>Quitar la tabla de productos</Button>
        </>
      )}
    </div>
  );
}

function PagePanel({ doc, sel, commit }: { doc: TemplateDoc; sel: Range; commit: (d: TemplateDoc) => void }) {
  const P = doc.layout.page;
  const set = (patch: (p: Layout['page']) => void) => { const n = structuredClone(doc); patch(n.layout.page); commit(n); };
  return (
    <div className="stack">
      <SelectField label="Papel" value={P.paper} onChange={(v) => set((p) => { p.paper = v; })} options={PAPERS} />
      {P.paper === 'custom' && (
        <div className="grid-2" style={{ gap: 8 }}>
          <TextField label="Ancho (mm)" type="number" value={String(P.width_mm ?? 210)} onChange={(v) => set((p) => { p.width_mm = Number(v); })} />
          <TextField label="Alto (mm)" type="number" value={String(P.height_mm ?? 297)} onChange={(v) => set((p) => { p.height_mm = Number(v); })} />
        </div>
      )}
      {!P.paper.startsWith('roll') && (
        <SelectField label="Orientación" value={P.orientation} onChange={(v) => set((p) => { p.orientation = v as 'portrait' | 'landscape'; })}
          options={[{ value: 'portrait', label: 'Vertical' }, { value: 'landscape', label: 'Horizontal' }]} />
      )}
      <div className="grid-2" style={{ gap: 8 }}>
        {(['l', 'r', 't', 'b'] as const).map((k) => (
          <TextField key={k} label={`Margen ${{ l: 'izquierdo', r: 'derecho', t: 'superior', b: 'inferior' }[k]} (cm)`} type="number" step="0.1"
            value={String(P.margins[k])} onChange={(v) => set((p) => { p.margins[k] = Number(v); })} />
        ))}
      </div>
      <Checkbox label="Ajustar al ancho del papel" checked={P.fit_width} onChange={(v) => set((p) => { p.fit_width = v; })} />
      {!P.fit_width && <TextField label="Escala (%)" type="number" value={String(P.scale)} onChange={(v) => set((p) => { p.scale = Number(v); })} />}
      <TextField label="Área de impresión" value={P.print_area} placeholder="Todo el diseño" onChange={(v) => set((p) => { p.print_area = v.toUpperCase(); })} />
      <Button size="sm" onClick={() => set((p) => { p.print_area = rangeRef(normalize(sel)); })}>Usar la selección ({rangeRef(normalize(sel))})</Button>
      <TextField label="Filas que se repiten en cada página" value={P.repeat_rows} placeholder="Ej.: 14:14"
        hint="Normalmente la fila de títulos de la tabla de productos." onChange={(v) => set((p) => { p.repeat_rows = v; })} />
      <TextField label="Encabezado de página" value={P.header} maxLength={200} onChange={(v) => set((p) => { p.header = v; })} />
      <TextField label="Pie de página" value={P.footer} maxLength={200} hint="&P = número de página, &N = total de páginas."
        onChange={(v) => set((p) => { p.footer = v; })} />
      <TextField label="Saltos de página después de las filas" value={P.row_breaks.join(', ')} placeholder="Ej.: 30, 60"
        onChange={(v) => set((p) => { p.row_breaks = v.split(/[,\s]+/).map(Number).filter((n) => n > 0); })} />
    </div>
  );
}

function ImagesPanel({ doc, sel, commit, templateId }: { doc: TemplateDoc; sel: Range; commit: (d: TemplateDoc) => void; templateId: string }) {
  const { notify } = useToast();
  const [busy, setBusy] = useState(false);
  const add = async (file: File) => {
    setBusy(true);
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await upload(`/print-templates/${templateId}/images`, form);
      const n = structuredClone(doc);
      n.layout.images.push({ id: `img${Date.now() % 100000}`, file: res.file, col: sel.c1 - 1, col_off: 0, row: sel.r1 - 1, row_off: 0, w: res.w, h: res.h });
      commit(n);
    } catch (err) {
      notify('danger', 'No se pudo agregar la imagen', (err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const set = (i: number, patch: Partial<Layout['images'][number]>) => { const n = structuredClone(doc); Object.assign(n.layout.images[i], patch); commit(n); };
  return (
    <div className="stack">
      <label className="btn btn-outline" aria-busy={busy || undefined}>
        <ImagePlus size={18} aria-hidden /> Agregar imagen o logotipo en {ref(sel.r1, sel.c1)}
        <input type="file" accept="image/png,image/jpeg" className="sr-only" onChange={(e) => { const f = e.target.files?.[0]; if (f) void add(f); e.target.value = ''; }} />
      </label>
      {doc.layout.images.length === 0 ? <p className="muted">Sin imágenes.</p> : doc.layout.images.map((img, i) => (
        <div key={img.id} className="card card-body stack" style={{ gap: 8 }}>
          <strong>Imagen en {ref(img.row + 1, img.col + 1)}</strong>
          <div className="grid-2" style={{ gap: 8 }}>
            <TextField label="Ancho (pt)" type="number" value={String(img.w)} onChange={(v) => set(i, { w: Number(v) })} />
            <TextField label="Alto (pt)" type="number" value={String(img.h)} onChange={(v) => set(i, { h: Number(v) })} />
          </div>
          <div className="row">
            <Button size="sm" onClick={() => set(i, { row: sel.r1 - 1, col: sel.c1 - 1, row_off: 0, col_off: 0 })}>Mover a {ref(sel.r1, sel.c1)}</Button>
            <Button size="sm" variant="danger" icon={<Trash2 size={16} />} onClick={() => { const n = structuredClone(doc); n.layout.images.splice(i, 1); commit(n); }}>Quitar</Button>
          </div>
        </div>
      ))}
    </div>
  );
}

function PreviewDialog({ templateId, doc, onClose }: { templateId: string; doc: TemplateDoc; onClose: () => void }) {
  const [lines, setLines] = useState(3);
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let alive = true;
    let current: string | null = null;
    setBusy(true);
    setError(null);
    api<Blob>(`/print-templates/${templateId}/preview`, { method: 'POST', body: { layout: doc.layout, bindings: doc.bindings, lines } })
      .then((blob) => { if (!alive) return; current = URL.createObjectURL(blob); setUrl(current); })
      .catch((err) => { if (alive) setError(err as ApiError); })
      .finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; if (current) URL.revokeObjectURL(current); };
  }, [templateId, doc, lines]);
  return (
    <Dialog open size="xl" title="Vista previa con datos de demostración" onClose={onClose}
      footer={<Button onClick={onClose}>Cerrar</Button>}>
      <div className="row">
        <SelectField label="Productos de demostración" value={String(lines)} onChange={(v) => setLines(Number(v))}
          options={[1, 3, 10, 30, 100].map((n) => ({ value: String(n), label: `${n}` }))} />
        <p className="muted grow">Es el PDF real que genera el servidor, con datos de demostración marcados. No es un documento válido.</p>
      </div>
      <ErrorAlert error={error} />
      {busy && !url ? <Loading label="Generando PDF…" /> : url ? <iframe className="tpl-preview" title="Vista previa en PDF" src={url} /> : null}
    </Dialog>
  );
}

function Versions({ tpl }: { tpl: any }) {
  return (
    <details className="card card-body">
      <summary>Historial de versiones ({tpl.versions.length})</summary>
      <ul className="result-list">
        {tpl.versions.map((v: any) => (
          <li key={v.number} className="result-item" style={{ cursor: 'default' }}>
            <span><strong>Versión {v.number}</strong>{v.number === tpl.current_version ? ' (actual)' : ''} · {v.note || 'Sin nota'}
              <br /><small className="muted">{dateTime(v.created_at)} · {v.created_by_name ?? ''}</small></span>
            {v.number !== tpl.loaded_version && <Link className="btn btn-ghost btn-sm" to={`?version=${v.number}`}>Abrir</Link>}
          </li>
        ))}
      </ul>
    </details>
  );
}

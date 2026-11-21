import {
  AlignCenterHorizontal, AlignCenterVertical, AlignEndHorizontal, AlignEndVertical, AlignStartHorizontal, AlignStartVertical,
  ArrowDown, ArrowLeft, ArrowUp, Copy, Eye, EyeOff, FileSpreadsheet, ImagePlus, Lock, Minus, Printer, Redo2, Save, Square,
  Table2, Trash2, Type, Undo2, Unlock, Variable,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type PointerEvent as RPointerEvent } from 'react';
import { Link } from 'react-router-dom';
import { api, ApiError, put, upload } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { Dialog } from '../../components/ui/Dialog';
import { Alert, Badge, ErrorAlert, Loading } from '../../components/ui/Feedback';
import { Checkbox, SelectField, TextField } from '../../components/ui/Form';
import { Tabs } from '../../components/ui/Layout';
import { useToast } from '../../context/Toast';
import { useApi } from '../../lib/hooks';
import {
  addElement, align, changePaper, distribute, duplicate, fromUnit, makeElement, move, outOfBounds, paperSize, PAPERS,
  printableArea, PT_TO_MM, PX_PER_MM, remove, reorder, resize, setLocked, snapBox, toUnit, updateElement,
  type AlignMode, type CanvasDoc, type El, type Guide, type Handle, type Page,
} from '../../lib/canvasModel';
import '../../styles/canvas-editor.css';

const DRAG = 'application/x-pospy-canvas';
const HANDLES: Handle[] = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'];
const BASIC = [
  { kind: 'text', label: 'Texto estático', icon: <Type size={16} aria-hidden /> },
  { kind: 'variable', label: 'Texto dinámico', icon: <Variable size={16} aria-hidden /> },
  { kind: 'image', label: 'Imagen', icon: <ImagePlus size={16} aria-hidden /> },
  { kind: 'logo', label: 'Logotipo de empresa', icon: <ImagePlus size={16} aria-hidden /> },
  { kind: 'hline', label: 'Línea horizontal', icon: <Minus size={16} aria-hidden /> },
  { kind: 'vline', label: 'Línea vertical', icon: <Minus size={16} aria-hidden style={{ transform: 'rotate(90deg)' }} /> },
  { kind: 'rect', label: 'Rectángulo', icon: <Square size={16} aria-hidden /> },
  { kind: 'separator', label: 'Separador', icon: <Minus size={16} aria-hidden /> },
  { kind: 'spacer', label: 'Espacio', icon: <Square size={16} aria-hidden style={{ opacity: 0.4 }} /> },
  { kind: 'table', label: 'Tabla de productos', icon: <Table2 size={16} aria-hidden /> },
];
const FONTS = ['Arial', 'Calibri', 'Times New Roman', 'Courier New', 'Verdana', 'Tahoma'];
const LINE_FIELDS: Record<string, string> = { n: 'N.º', cantidad: 'Cantidad', codigo: 'Código', descripcion: 'Producto', unidad: 'Unidad',
  precio: 'Precio unitario', precio_lista: 'Precio sin descuento', descuento_linea: 'Descuento', valor: 'Total', iva_pct: 'IVA %' };

interface Catalog { fields: { group: string; fields: { key: string; label: string; type: string }[] }[] }

export function CanvasEditor({ tpl, reload }: { tpl: any; reload: () => void }) {
  const { notify } = useToast();
  const catalog: Catalog = tpl.catalog;
  const labels = useMemo(() => Object.fromEntries(catalog.fields.flatMap((g) => g.fields.map((f) => [f.key, f.label]))), [catalog]);
  const [doc, setDoc] = useState<CanvasDoc>(tpl.layout);
  const docRef = useRef(doc);
  docRef.current = doc;
  const past = useRef<CanvasDoc[]>([]);
  const future = useRef<CanvasDoc[]>([]);
  const [dirty, setDirty] = useState(false);
  const [sel, setSel] = useState<string[]>([]);
  const [zoom, setZoom] = useState(1.5);
  const [guides, setGuides] = useState<Guide[]>([]);
  const [left, setLeft] = useState<'elementos' | 'datos' | 'papel' | 'capas'>('elementos');
  const [preview, setPreview] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const sheetRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const pendingImage = useRef<{ x: number; y: number; replace?: string } | null>(null);
  const k = PX_PER_MM * zoom;                                 // píxeles por milímetro en pantalla
  const size = paperSize(doc);
  const area = printableArea(doc);
  const outside = useMemo(() => new Set(outOfBounds(doc)), [doc]);
  const selected = doc.elements.filter((e) => sel.includes(e.id));
  const one = selected.length === 1 ? selected[0] : null;
  const unit = doc.page.unit;

  const commit = useCallback((next: CanvasDoc) => {
    if (next === docRef.current) return;
    past.current.push(docRef.current);
    if (past.current.length > 150) past.current.shift();
    future.current = [];
    setDoc(next);
    setDirty(true);
  }, []);
  const undo = () => { const p = past.current.pop(); if (p) { future.current.push(docRef.current); setDoc(p); setDirty(true); } };
  const redo = () => { const n = future.current.pop(); if (n) { past.current.push(docRef.current); setDoc(n); setDirty(true); } };

  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);

  // ------------------------------------------------------------------ insertar
  const insert = async (kind: string, x: number, y: number, field?: string) => {
    if (kind === 'image') {
      pendingImage.current = { x, y };
      fileRef.current?.click();
      return;
    }
    if (kind === 'logo') {
      try {
        const res = await api(`/print-templates/${tpl.public_id}/company-logo`, { method: 'POST', body: {} });
        const ratio = res.w / res.h || 1;
        const w = Math.min(30, area.w);
        const el = makeElement(doc, 'image', x, y, { w, h: Math.round((w / ratio) * 100) / 100, name: 'Logotipo', image: { file: res.file, keep_ratio: true } });
        commit(addElement(doc, el));
        setSel([el.id]);
      } catch (err) {
        notify('danger', 'No se pudo insertar el logotipo', (err as Error).message);
      }
      return;
    }
    if (kind === 'table' && doc.elements.some((e) => e.type === 'table')) {
      notify('warning', 'Ya hay una tabla de productos', 'Cada plantilla tiene una sola tabla; crece con los productos de la venta.');
      return;
    }
    const el = makeElement(doc, kind, x, y, field ? { field, name: labels[field] } : {});
    commit(addElement(doc, el));
    setSel([el.id]);
  };
  const onFile = async (file: File | undefined) => {
    const at = pendingImage.current;
    pendingImage.current = null;
    if (!file || !at) return;
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await upload(`/print-templates/${tpl.public_id}/images`, form);
      const ratio = res.w / res.h || 1;
      if (at.replace) {
        const e = doc.elements.find((x) => x.id === at.replace)!;
        commit(updateElement(doc, e.id, { image: { ...e.image!, file: res.file }, h: Math.round((e.w / ratio) * 100) / 100 }));
        return;
      }
      const w = Math.min(30, area.w);
      const el = makeElement(doc, 'image', at.x, at.y, { w, h: Math.round((w / ratio) * 100) / 100, name: file.name.slice(0, 40),
        image: { file: res.file, keep_ratio: true } });
      commit(addElement(doc, el));
      setSel([el.id]);
    } catch (err) {
      notify('danger', 'Imagen no válida', (err as Error).message);
    }
  };
  const toMm = (clientX: number, clientY: number) => {
    const r = sheetRef.current!.getBoundingClientRect();
    return { x: Math.round(((clientX - r.left) / k) * 10) / 10, y: Math.round(((clientY - r.top) / k) * 10) / 10 };
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    const raw = e.dataTransfer.getData(DRAG);
    if (!raw) return;
    const item = JSON.parse(raw) as { kind: string; field?: string };
    const { x, y } = toMm(e.clientX, e.clientY);
    void insert(item.kind, x, y, item.field);
  };

  // ------------------------------------------------------------------ mover y redimensionar (puntero)
  const startDrag = (e: RPointerEvent, el: El, handle?: Handle) => {
    e.stopPropagation();
    e.preventDefault();
    const additive = e.shiftKey || e.ctrlKey || e.metaKey;
    const ids = handle ? [el.id] : additive ? (sel.includes(el.id) ? sel.filter((i) => i !== el.id) : [...sel, el.id])
      : sel.includes(el.id) ? sel : [el.id];
    setSel(ids);
    if (additive && !handle) return;
    const moving = docRef.current.elements.filter((x) => ids.includes(x.id) && !x.locked);
    if (!moving.length) return;
    const start = { x: e.clientX, y: e.clientY };
    const base = docRef.current;
    let moved = false;
    const target = e.currentTarget as HTMLElement;
    target.setPointerCapture(e.pointerId);
    const onMove = (ev: PointerEvent) => {
      const dx = (ev.clientX - start.x) / k;
      const dy = (ev.clientY - start.y) / k;
      if (!moved && Math.hypot(ev.clientX - start.x, ev.clientY - start.y) < 3) return;   // evita movimientos accidentales
      moved = true;
      if (handle) {
        const next = resize(base, el.id, handle, dx, dy, (el.image?.keep_ratio ?? false) || ev.shiftKey);
        setDoc(next);
      } else {
        const lead = moving[0];
        const snapped = snapBox(base, { x: lead.x + dx, y: lead.y + dy, w: lead.w, h: lead.h }, ids);
        setGuides(snapped.guides);
        setDoc(move(base, ids, snapped.box.x - lead.x, snapped.box.y - lead.y));
      }
    };
    const onUp = () => {
      target.removeEventListener('pointermove', onMove);
      target.removeEventListener('pointerup', onUp);
      setGuides([]);
      if (moved) {
        past.current.push(base);
        future.current = [];
        setDirty(true);
      }
    };
    target.addEventListener('pointermove', onMove);
    target.addEventListener('pointerup', onUp);
  };

  const onKey = (e: KeyboardEvent) => {
    const target = e.target as HTMLElement;
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable) return;
    if (target.closest('[role="dialog"]')) return;
    const ctrl = e.ctrlKey || e.metaKey;
    if (ctrl && e.key.toLowerCase() === 'z') { e.preventDefault(); undo(); return; }
    if (ctrl && e.key.toLowerCase() === 'y') { e.preventDefault(); redo(); return; }
    if (ctrl && e.key.toLowerCase() === 'a') { e.preventDefault(); setSel(doc.elements.map((x) => x.id)); return; }
    if (!sel.length) return;
    if (ctrl && e.key.toLowerCase() === 'd') { e.preventDefault(); const r = duplicate(doc, sel); commit(r.doc); setSel(r.ids); return; }
    if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); commit(remove(doc, sel)); setSel([]); return; }
    const step = e.shiftKey ? 5 : 0.5;
    const arrows: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (arrows[e.key]) { e.preventDefault(); commit(move(doc, sel, ...arrows[e.key])); }
  };

  // Atajos de teclado en toda la página (el foco suele volver al cuerpo tras editar un campo).
  const keyRef = useRef(onKey);
  keyRef.current = onKey;
  useEffect(() => {
    const handler = (e: KeyboardEvent) => keyRef.current(e);
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, []);

  // ------------------------------------------------------------------ guardar, vista previa, Excel
  const save = async (activate: boolean) => {
    setSaving(true);
    setError(null);
    try {
      await put(`/print-templates/${tpl.public_id}`, { layout: doc, bindings: {}, activate, version: tpl.version });
      notify('success', activate ? 'Diseño guardado y plantilla activa' : 'Diseño guardado', 'La plantilla Excel se genera con este diseño.');
      setDirty(false);
      reload();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setSaving(false);
    }
  };
  const downloadBlob = async (path: string, body: unknown, name: string) => {
    try {
      const blob = await api<Blob>(path, body === undefined ? {} : { method: 'POST', body });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      notify('danger', 'No se pudo generar el Excel', (err as Error).message);
    }
  };

  // ------------------------------------------------------------------ dibujo
  const elementStyle = (e: El): React.CSSProperties => ({ left: e.x * k, top: e.y * k, width: e.w * k, height: e.h * k, zIndex: e.z });
  const textCss = (t: NonNullable<El['text']>): React.CSSProperties => ({
    fontFamily: t.font, fontSize: t.size * PT_TO_MM * k, fontWeight: t.bold ? 700 : 400, fontStyle: t.italic ? 'italic' : 'normal',
    textDecoration: t.underline ? 'underline' : 'none', color: t.color, textAlign: t.align, background: t.fill || undefined,
    justifyContent: t.valign === 'top' ? 'flex-start' : t.valign === 'bottom' ? 'flex-end' : 'center',
    whiteSpace: t.overflow === 'wrap' ? 'normal' : 'nowrap',
  });
  const renderBody = (e: El) => {
    if (e.type === 'text' || e.type === 'variable') {
      const content = e.type === 'text' ? e.text!.content : `{${labels[e.field ?? ''] ?? e.field}}`;
      return <div className={`cv-text${e.type === 'variable' ? ' cv-var' : ''}`} style={{ ...textCss(e.text!), transform: e.rotation ? `rotate(${-e.rotation}deg)` : undefined }}>{content}</div>;
    }
    if (e.type === 'image') {
      return e.image?.file
        ? <img alt="" draggable={false} src={`/api/print-templates/${tpl.public_id}/images/${e.image.file}`} style={{ objectFit: e.image.keep_ratio ? 'contain' : 'fill' }} />
        : <div className="cv-empty">Imagen</div>;
    }
    if (e.type === 'line') {
      const l = e.line!;
      const border = `${Math.max(1, l.thickness * PT_TO_MM * k)}px ${l.style === 'double' ? 'double' : l.style} ${l.color}`;
      return <div className={`cv-line cv-line-${l.orientation}`} style={l.orientation === 'h' ? { borderTop: border } : { borderLeft: border }} />;
    }
    if (e.type === 'rect') {
      const r = e.rect!;
      return <div className="cv-rect" style={{ border: r.border_width ? `${Math.max(1, r.border_width * PT_TO_MM * k)}px ${r.border_style} ${r.border_color}` : undefined, background: r.fill || undefined }} />;
    }
    if (e.type === 'spacer') return <div className="cv-spacer" />;
    if (e.type === 'table') {
      const t = e.table!;
      const fs = t.size * PT_TO_MM * k;
      return (
        <div className="cv-table" style={{ fontSize: fs }}>
          {t.header.show && (
            <div className="cv-tr cv-th" style={{ height: t.header_height_mm * k, background: t.header.fill || undefined, fontWeight: t.header.bold ? 700 : 400, fontSize: t.header.size * PT_TO_MM * k }}>
              {t.columns.map((c, i) => <span key={i} style={{ width: c.width_mm * k, textAlign: c.align }}>{c.header}</span>)}
            </div>
          )}
          {[0, 1].map((r) => (
            <div key={r} className={`cv-tr${r ? ' cv-ghost' : ''}`} style={{ height: t.row_height_mm * k, borderBottom: t.borders !== 'none' ? `1px solid ${t.border_color}` : undefined }}>
              {t.columns.map((c, i) => <span key={i} style={{ width: c.width_mm * k, textAlign: c.align }}>{`{${LINE_FIELDS[c.field] ?? c.field}}`}</span>)}
            </div>
          ))}
          <div className="cv-grow">↓ crece con los productos</div>
        </div>
      );
    }
    return null;
  };

  const rulerTicks = (lenMm: number) => Array.from({ length: Math.floor(lenMm / 5) + 1 }, (_, i) => i * 5);
  const ordered = [...doc.elements].sort((a, b) => a.z - b.z);

  return (
    <div className="stack cv-editor">
      <div className="cv-topbar" role="toolbar" aria-label="Plantilla">
        <Link to="/gestion/plantillas" className="btn btn-ghost btn-sm"><ArrowLeft size={18} aria-hidden /> Plantillas</Link>
        <strong className="cv-title">{tpl.name}</strong>
        {tpl.active ? <Badge kind="success">Activa</Badge> : <Badge kind="warning">Borrador</Badge>}
        {dirty && <span className="muted">Cambios sin guardar</span>}
        <span className="grow" />
        <Button size="sm" variant="ghost" iconOnly icon={<Undo2 size={18} />} disabled={!past.current.length} onClick={undo}>Deshacer (Ctrl+Z)</Button>
        <Button size="sm" variant="ghost" iconOnly icon={<Redo2 size={18} />} disabled={!future.current.length} onClick={redo}>Rehacer (Ctrl+Y)</Button>
        <label className="cv-zoom">Zoom
          <select value={zoom} onChange={(e) => setZoom(Number(e.target.value))}>
            {[0.75, 1, 1.5, 2, 3].map((z) => <option key={z} value={z}>{Math.round(z * 100)} %</option>)}
          </select>
        </label>
        <Button size="sm" icon={<Eye size={18} />} onClick={() => setPreview(true)}>Vista previa</Button>
        <Button size="sm" icon={<FileSpreadsheet size={18} />} onClick={() => downloadBlob(`/print-templates/${tpl.public_id}/preview.xlsx`, { layout: doc, lines: 5 }, `${tpl.name}-ejemplo.xlsx`)}>Excel de ejemplo</Button>
        <Button size="sm" icon={<FileSpreadsheet size={18} />} disabled={dirty} title={dirty ? 'Guarde primero' : undefined}
          onClick={() => downloadBlob(`/print-templates/${tpl.public_id}/template.xlsx`, undefined, `${tpl.name}.xlsx`)}>Exportar plantilla Excel</Button>
        <Button size="sm" busy={saving} icon={<Save size={18} />} onClick={() => save(false)}>Guardar</Button>
        <Button size="sm" variant="primary" busy={saving} icon={<Save size={18} />} onClick={() => save(true)}>{tpl.active ? 'Guardar' : 'Guardar y activar'}</Button>
      </div>
      <ErrorAlert error={error} />
      {outside.size > 0 && <Alert kind="warning">{outside.size} elemento(s) salen del área imprimible (marcados en rojo): se recortarán al imprimir.</Alert>}

      <div className="cv-workspace">
        <aside className="cv-left" aria-label="Elementos y papel">
          <Tabs label="Panel izquierdo" value={left} onChange={setLeft} tabs={[
            { value: 'elementos', label: 'Elementos' }, { value: 'datos', label: 'Datos' }, { value: 'papel', label: 'Papel' }, { value: 'capas', label: 'Capas' }]} />
          <div className="cv-left-body">
            {left === 'elementos' && (
              <div className="cv-palette">
                <p className="muted">Arrastre al papel o pulse para insertar.</p>
                {BASIC.map((b) => (
                  <button key={b.kind} type="button" className="cv-tool" draggable onDragStart={(e) => e.dataTransfer.setData(DRAG, JSON.stringify({ kind: b.kind }))}
                    onClick={() => insert(b.kind, area.x, Math.max(area.y, contentEnd(doc) + 2))}>{b.icon} {b.label}</button>
                ))}
              </div>
            )}
            {left === 'datos' && (
              <div className="cv-palette">
                <p className="muted">Datos reales del POS (se llenan al imprimir).</p>
                {catalog.fields.map((g) => (
                  <div key={g.group}>
                    <h3>{g.group}</h3>
                    {g.fields.map((f) => (
                      <button key={f.key} type="button" className="cv-tool cv-tool-var" draggable
                        onDragStart={(e) => e.dataTransfer.setData(DRAG, JSON.stringify({ kind: 'variable', field: f.key }))}
                        onClick={() => insert('variable', area.x, Math.max(area.y, contentEnd(doc) + 2), f.key)}>{f.label}</button>
                    ))}
                  </div>
                ))}
              </div>
            )}
            {left === 'papel' && <PaperPanel doc={doc} commit={commit} />}
            {left === 'capas' && (
              <ul className="cv-layers" aria-label="Capas">
                {[...ordered].reverse().map((e) => (
                  <li key={e.id} className={sel.includes(e.id) ? 'sel' : undefined}>
                    <button type="button" className="cv-layer-name" onClick={() => setSel([e.id])}>{layerName(e, labels)}</button>
                    <Button size="sm" variant="ghost" iconOnly icon={e.locked ? <Lock size={14} /> : <Unlock size={14} />} onClick={() => commit(setLocked(doc, [e.id], !e.locked))}>{e.locked ? 'Desbloquear' : 'Bloquear'}</Button>
                    <Button size="sm" variant="ghost" iconOnly icon={e.hidden ? <EyeOff size={14} /> : <Eye size={14} />} onClick={() => commit(updateElement(doc, e.id, { hidden: !e.hidden }))}>{e.hidden ? 'Mostrar' : 'Ocultar'}</Button>
                    <Button size="sm" variant="ghost" iconOnly icon={<ArrowUp size={14} />} onClick={() => commit(reorder(doc, e.id, 'up'))}>Subir capa</Button>
                    <Button size="sm" variant="ghost" iconOnly icon={<ArrowDown size={14} />} onClick={() => commit(reorder(doc, e.id, 'down'))}>Bajar capa</Button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>

        <div className="cv-stage" tabIndex={0} aria-label="Lienzo de diseño" onPointerDown={() => setSel([])}>
          <div className="cv-rulers" style={{ width: size.w * k + 24, height: size.h * k + 24 }}>
            <div className="cv-ruler cv-ruler-x" style={{ width: size.w * k }} aria-hidden>
              {rulerTicks(size.w).map((t) => <span key={t} style={{ left: t * k }} className={t % 10 ? 'minor' : ''}>{t % 10 ? '' : t}</span>)}
            </div>
            <div className="cv-ruler cv-ruler-y" style={{ height: size.h * k }} aria-hidden>
              {rulerTicks(size.h).map((t) => <span key={t} style={{ top: t * k }} className={t % 10 ? 'minor' : ''}>{t % 10 ? '' : t}</span>)}
            </div>
            <div ref={sheetRef} className={`cv-sheet${doc.grid.show ? ' cv-gridded' : ''}`} data-testid="cv-sheet"
              style={{ width: size.w * k, height: size.h * k, backgroundSize: `${doc.grid.size_mm * 5 * k}px ${doc.grid.size_mm * 5 * k}px` }}
              onDragOver={(e) => { if (e.dataTransfer.types.includes(DRAG)) e.preventDefault(); }} onDrop={onDrop}>
              <div className="cv-printable" style={{ left: area.x * k, top: area.y * k, width: area.w * k, height: area.h * k }} title="Área imprimible" />
              {ordered.filter((e) => !e.hidden).map((e) => (
                <div key={e.id} data-id={e.id} className={`cv-el cv-el-${e.type}${sel.includes(e.id) ? ' sel' : ''}${e.locked ? ' locked' : ''}${outside.has(e.id) ? ' out' : ''}`}
                  style={elementStyle(e)} onPointerDown={(ev) => startDrag(ev, e)} role="button" tabIndex={-1}
                  aria-label={layerName(e, labels)} aria-pressed={sel.includes(e.id)}>
                  {renderBody(e)}
                  {one?.id === e.id && !e.locked && HANDLES.map((h) => (
                    <span key={h} className={`cv-handle cv-h-${h}`} onPointerDown={(ev) => startDrag(ev, e, h)} aria-label={`Redimensionar ${h}`} />
                  ))}
                </div>
              ))}
              {guides.map((g, i) => <div key={i} className={`cv-guide cv-guide-${g.axis}`} style={g.axis === 'x' ? { left: g.at * k } : { top: g.at * k }} />)}
            </div>
          </div>
          <p className="muted cv-help">Arrastre para mover (Mayús: añadir a la selección). Flechas: mover 0,5 mm (Mayús: 5 mm). Supr: eliminar. Ctrl+D: duplicar.
            {doc.page.auto_height ? ' Rollo térmico: el alto crece con el contenido y los productos.' : ''}</p>
        </div>

        <aside className="cv-right" aria-label="Propiedades">
          {selected.length > 1 ? (
            <MultiPanel ids={sel} doc={doc} commit={commit} onDelete={() => { commit(remove(doc, sel)); setSel([]); }} />
          ) : one ? (
            <PropsPanel templateId={tpl.public_id} el={one} doc={doc} unit={unit} labels={labels} catalog={catalog} commit={commit}
              onDuplicate={() => { const r = duplicate(doc, [one.id]); commit(r.doc); setSel(r.ids); }}
              onDelete={() => { commit(remove(doc, [one.id])); setSel([]); }}
              onReplaceImage={() => { pendingImage.current = { x: one.x, y: one.y, replace: one.id }; fileRef.current?.click(); }} />
          ) : (
            <div className="stack">
              <h3>Propiedades</h3>
              <p className="muted">Seleccione un elemento del papel para editarlo. Use la pestaña «Papel» para el tamaño, los márgenes y la cuadrícula.</p>
              {tpl.design_notes?.length > 0 && <Alert kind="info" title="Al generar el Excel"><ul>{tpl.design_notes.map((n: string) => <li key={n}>{n}</li>)}</ul></Alert>}
            </div>
          )}
        </aside>
      </div>
      <input ref={fileRef} type="file" accept="image/png,image/jpeg" className="sr-only" aria-label="Archivo de imagen"
        onChange={(e) => { void onFile(e.target.files?.[0]); e.target.value = ''; }} />
      {preview && <CanvasPreview templateId={tpl.public_id} doc={doc} onClose={() => setPreview(false)} />}
    </div>
  );
}

const contentEnd = (doc: CanvasDoc) => doc.elements.reduce((m, e) => Math.max(m, e.y + e.h), 0);

function layerName(e: El, labels: Record<string, string>) {
  if (e.name) return e.name;
  if (e.type === 'text') return `Texto «${(e.text?.content ?? '').slice(0, 18)}»`;
  if (e.type === 'variable') return `Dato: ${labels[e.field ?? ''] ?? e.field}`;
  return { image: 'Imagen', line: e.line?.orientation === 'v' ? 'Línea vertical' : 'Línea', rect: 'Rectángulo', spacer: 'Espacio', table: 'Tabla de productos' }[e.type as string] ?? e.type;
}

function NumberIn({ label, value, onChange, step = 0.5 }: { label: string; value: number; onChange: (v: number) => void; step?: number }) {
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  return (
    <label className="cv-num">{label}
      <input type="number" step={step} value={text} onChange={(e) => setText(e.target.value)}
        onBlur={() => { const v = Number(text.replace(',', '.')); if (Number.isFinite(v)) onChange(v); else setText(String(value)); }}
        onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }} />
    </label>
  );
}

function PropsPanel({ templateId, el, doc, unit, labels, catalog, commit, onDuplicate, onDelete, onReplaceImage }: {
  templateId: string; el: El; doc: CanvasDoc; unit: Page['unit']; labels: Record<string, string>; catalog: Catalog; commit: (d: CanvasDoc) => void;
  onDuplicate: () => void; onDelete: () => void; onReplaceImage: () => void;
}) {
  const set = (patch: Partial<El>) => commit(updateElement(doc, el.id, patch));
  const setText = (patch: Partial<NonNullable<El['text']>>) => set({ text: { ...el.text!, ...patch } });
  const u = unit;
  const alignBtn = (mode: AlignMode, icon: React.ReactNode, label: string) => (
    <Button size="sm" variant="ghost" iconOnly icon={icon} onClick={() => commit(align(doc, [el.id], mode))}>{label}</Button>);
  return (
    <div className="stack cv-props">
      <h3>{layerName(el, labels)}</h3>
      <div className="cv-grid2">
        <NumberIn label={`X (${u})`} value={toUnit(el.x, u)} onChange={(v) => set({ x: fromUnit(v, u) })} />
        <NumberIn label={`Y (${u})`} value={toUnit(el.y, u)} onChange={(v) => set({ y: fromUnit(v, u) })} />
        <NumberIn label={`Ancho (${u})`} value={toUnit(el.w, u)} onChange={(v) => commit(resize(doc, el.id, 'e', fromUnit(v, u) - el.w, 0, el.image?.keep_ratio))} />
        <NumberIn label={`Alto (${u})`} value={toUnit(el.h, u)} onChange={(v) => commit(resize(doc, el.id, 's', 0, fromUnit(v, u) - el.h, el.image?.keep_ratio))} />
      </div>
      <div className="row" style={{ gap: 2 }} aria-label="Alinear con el área imprimible">
        {alignBtn('left', <AlignStartVertical size={16} />, 'Alinear a la izquierda')}
        {alignBtn('hcenter', <AlignCenterVertical size={16} />, 'Centrar horizontalmente')}
        {alignBtn('right', <AlignEndVertical size={16} />, 'Alinear a la derecha')}
        {alignBtn('top', <AlignStartHorizontal size={16} />, 'Alinear arriba')}
        {alignBtn('vcenter', <AlignCenterHorizontal size={16} />, 'Centrar verticalmente')}
        {alignBtn('bottom', <AlignEndHorizontal size={16} />, 'Alinear abajo')}
      </div>
      {(el.type === 'text' || el.type === 'variable') && el.text && (
        <>
          {el.type === 'text' ? (
            <TextField label="Contenido" value={el.text.content} onChange={(v) => setText({ content: v })} maxLength={2000} />
          ) : (
            <>
              <SelectField label="Campo de origen" value={el.field ?? ''} onChange={(v) => set({ field: v, name: labels[v] })}
                options={catalog.fields.flatMap((g) => g.fields.map((f) => ({ value: f.key, label: `${g.group}: ${f.label}` })))} />
              <TextField label="Si no hay datos, mostrar" value={el.fallback ?? ''} onChange={(v) => set({ fallback: v })} maxLength={200}
                hint="Vacío: la celda queda en blanco." />
              <TextField label="Formato (opcional)" value={el.format ?? ''} onChange={(v) => set({ format: v })} maxLength={60}
                hint='Ej.: dd/mm/yyyy, h:mm AM/PM o "$"#,##0' />
            </>
          )}
          <div className="cv-grid2">
            <SelectField label="Fuente" value={el.text.font} onChange={(v) => setText({ font: v })} options={FONTS.map((f) => ({ value: f, label: f }))} />
            <NumberIn label="Tamaño (pt)" value={el.text.size} step={1} onChange={(v) => setText({ size: Math.max(4, Math.min(120, v)) })} />
          </div>
          <div className="row" style={{ gap: 8 }}>
            <Checkbox label="Negrita" checked={el.text.bold} onChange={(v) => setText({ bold: v })} />
            <Checkbox label="Cursiva" checked={el.text.italic} onChange={(v) => setText({ italic: v })} />
            <Checkbox label="Subrayado" checked={el.text.underline} onChange={(v) => setText({ underline: v })} />
          </div>
          <div className="cv-grid2">
            <SelectField label="Alineación" value={el.text.align} onChange={(v) => setText({ align: v as 'left' })}
              options={[{ value: 'left', label: 'Izquierda' }, { value: 'center', label: 'Centro' }, { value: 'right', label: 'Derecha' }]} />
            <SelectField label="Vertical" value={el.text.valign} onChange={(v) => setText({ valign: v as 'top' })}
              options={[{ value: 'top', label: 'Arriba' }, { value: 'center', label: 'Centro' }, { value: 'bottom', label: 'Abajo' }]} />
            <SelectField label="Texto largo" value={el.text.overflow} onChange={(v) => setText({ overflow: v as 'wrap' })}
              options={[{ value: 'wrap', label: 'Ajustar en varias líneas' }, { value: 'shrink', label: 'Reducir hasta que quepa' }, { value: 'overflow', label: 'Una línea' }]} />
            <SelectField label="Giro" value={String(el.rotation)} onChange={(v) => set({ rotation: Number(v) })}
              options={[{ value: '0', label: 'Sin giro' }, { value: '90', label: '90°' }, { value: '270', label: '270°' }]} />
          </div>
          <label className="cv-color">Color <input type="color" value={el.text.color} onChange={(e) => setText({ color: e.target.value.toUpperCase() })} /></label>
        </>
      )}
      {el.type === 'image' && el.image && (
        <>
          {el.image.file && <img className="cv-thumb" alt="Vista previa de la imagen" src={`/api/print-templates/${templateId}/images/${el.image.file}`} />}
          <Button size="sm" icon={<ImagePlus size={16} />} onClick={onReplaceImage}>{el.image.file ? 'Reemplazar imagen' : 'Seleccionar archivo'}</Button>
          <Checkbox label="Mantener proporciones" checked={el.image.keep_ratio} onChange={(v) => set({ image: { ...el.image!, keep_ratio: v } })} />
          <p className="muted">JPG o PNG, hasta 3 MB. Se incrusta en el Excel como imagen.</p>
        </>
      )}
      {el.type === 'line' && el.line && (
        <div className="cv-grid2">
          <NumberIn label="Grosor (pt)" value={el.line.thickness} step={0.25} onChange={(v) => set({ line: { ...el.line!, thickness: Math.max(0.25, Math.min(6, v)) } })} />
          <SelectField label="Estilo" value={el.line.style} onChange={(v) => set({ line: { ...el.line!, style: v as 'solid' } })}
            options={[{ value: 'solid', label: 'Continua' }, { value: 'dashed', label: 'Guiones' }, { value: 'dotted', label: 'Puntos' }, { value: 'double', label: 'Doble' }]} />
          <label className="cv-color">Color <input type="color" value={el.line.color} onChange={(e) => set({ line: { ...el.line!, color: e.target.value.toUpperCase() } })} /></label>
        </div>
      )}
      {el.type === 'rect' && el.rect && (
        <div className="cv-grid2">
          <NumberIn label="Borde (pt)" value={el.rect.border_width} step={0.25} onChange={(v) => set({ rect: { ...el.rect!, border_width: Math.max(0, Math.min(6, v)) } })} />
          <SelectField label="Estilo" value={el.rect.border_style} onChange={(v) => set({ rect: { ...el.rect!, border_style: v as 'solid' } })}
            options={[{ value: 'solid', label: 'Continua' }, { value: 'dashed', label: 'Guiones' }, { value: 'dotted', label: 'Puntos' }]} />
          <label className="cv-color">Borde <input type="color" value={el.rect.border_color} onChange={(e) => set({ rect: { ...el.rect!, border_color: e.target.value.toUpperCase() } })} /></label>
          <label className="cv-color">Relleno <input type="color" value={el.rect.fill || '#FFFFFF'} onChange={(e) => set({ rect: { ...el.rect!, fill: e.target.value.toUpperCase() } })} /></label>
        </div>
      )}
      {el.type === 'table' && el.table && <TablePanel el={el} set={set} />}
      <div className="row" style={{ gap: 6 }}>
        <Checkbox label="Bloqueado" checked={el.locked} onChange={(v) => commit(setLocked(doc, [el.id], v))} />
        {el.type !== 'table' && <Button size="sm" icon={<Copy size={16} />} onClick={onDuplicate}>Duplicar</Button>}
        <Button size="sm" variant="danger" icon={<Trash2 size={16} />} disabled={el.locked} onClick={onDelete}>Eliminar</Button>
      </div>
      <div className="row" style={{ gap: 6 }}>
        <Button size="sm" variant="ghost" onClick={() => commit(reorder(doc, el.id, 'front'))}>Traer al frente</Button>
        <Button size="sm" variant="ghost" onClick={() => commit(reorder(doc, el.id, 'back'))}>Enviar al fondo</Button>
      </div>
    </div>
  );
}

function TablePanel({ el, set }: { el: El; set: (p: Partial<El>) => void }) {
  const t = el.table!;
  const setT = (patch: Partial<typeof t>) => set({ table: { ...t, ...patch } });
  const setCol = (i: number, patch: Partial<(typeof t.columns)[number]>) => setT({ columns: t.columns.map((c, j) => (j === i ? { ...c, ...patch } : c)) });
  const moveCol = (i: number, d: number) => {
    const cols = [...t.columns];
    const [c] = cols.splice(i, 1);
    cols.splice(Math.max(0, Math.min(cols.length, i + d)), 0, c);
    setT({ columns: cols });
  };
  const used = t.columns.reduce((s, c) => s + c.width_mm, 0);
  return (
    <div className="stack">
      <h4>Columnas ({Math.round(used * 10) / 10} de {el.w} mm)</h4>
      {t.columns.map((c, i) => (
        <div key={i} className="cv-col">
          <SelectField label={`Columna ${i + 1}`} value={c.field} onChange={(v) => setCol(i, { field: v, header: LINE_FIELDS[v] ?? v })}
            options={Object.entries(LINE_FIELDS).map(([value, label]) => ({ value, label }))} />
          <div className="cv-grid2">
            <TextField label="Encabezado" value={c.header} onChange={(v) => setCol(i, { header: v })} maxLength={40} />
            <NumberIn label="Ancho (mm)" value={c.width_mm} onChange={(v) => setCol(i, { width_mm: Math.max(2, v) })} />
            <SelectField label="Alineación" value={c.align} onChange={(v) => setCol(i, { align: v as 'left' })}
              options={[{ value: 'left', label: 'Izquierda' }, { value: 'center', label: 'Centro' }, { value: 'right', label: 'Derecha' }]} />
          </div>
          <div className="row" style={{ gap: 2 }}>
            <Button size="sm" variant="ghost" iconOnly icon={<ArrowUp size={14} />} onClick={() => moveCol(i, -1)}>Mover columna antes</Button>
            <Button size="sm" variant="ghost" iconOnly icon={<ArrowDown size={14} />} onClick={() => moveCol(i, 1)}>Mover columna después</Button>
            <Button size="sm" variant="ghost" iconOnly icon={<Trash2 size={14} />} disabled={t.columns.length <= 1}
              onClick={() => setT({ columns: t.columns.filter((_, j) => j !== i) })}>Quitar columna</Button>
          </div>
        </div>
      ))}
      {t.columns.length < 8 && <Button size="sm" onClick={() => setT({ columns: [...t.columns, { field: 'codigo', header: 'Código', width_mm: 10, align: 'left' }] })}>Agregar columna</Button>}
      <div className="cv-grid2">
        <NumberIn label="Letra (pt)" value={t.size} step={1} onChange={(v) => setT({ size: Math.max(4, v) })} />
        <NumberIn label="Alto de fila (mm)" value={t.row_height_mm} onChange={(v) => setT({ row_height_mm: Math.max(2, v) })} />
        <SelectField label="Bordes" value={t.borders} onChange={(v) => setT({ borders: v as 'all' })}
          options={[{ value: 'none', label: 'Sin bordes' }, { value: 'horizontal', label: 'Entre filas' }, { value: 'all', label: 'Todos' }]} />
        <Checkbox label="Mostrar encabezados" checked={t.header.show} onChange={(v) => setT({ header: { ...t.header, show: v } })} />
      </div>
      <Checkbox label="Ajustar descripciones largas" checked={t.wrap} onChange={(v) => setT({ wrap: v })} />
      <p className="muted">Se repite una fila por cada producto de la venta; lo que está debajo (totales, pie) se desplaza.</p>
    </div>
  );
}

function MultiPanel({ ids, doc, commit, onDelete }: { ids: string[]; doc: CanvasDoc; commit: (d: CanvasDoc) => void; onDelete: () => void }) {
  const al = (m: AlignMode, label: string) => <Button size="sm" onClick={() => commit(align(doc, ids, m))}>{label}</Button>;
  return (
    <div className="stack">
      <h3>{ids.length} elementos seleccionados</h3>
      <div className="row" style={{ gap: 4 }}>{al('left', 'Izquierda')}{al('hcenter', 'Centro')}{al('right', 'Derecha')}</div>
      <div className="row" style={{ gap: 4 }}>{al('top', 'Arriba')}{al('vcenter', 'Medio')}{al('bottom', 'Abajo')}</div>
      <div className="row" style={{ gap: 4 }}>
        <Button size="sm" disabled={ids.length < 3} onClick={() => commit(distribute(doc, ids, 'h'))}>Distribuir horizontal</Button>
        <Button size="sm" disabled={ids.length < 3} onClick={() => commit(distribute(doc, ids, 'v'))}>Distribuir vertical</Button>
      </div>
      <div className="row" style={{ gap: 4 }}>
        <Button size="sm" icon={<Lock size={14} />} onClick={() => commit(setLocked(doc, ids, true))}>Bloquear</Button>
        <Button size="sm" icon={<Unlock size={14} />} onClick={() => commit(setLocked(doc, ids, false))}>Desbloquear</Button>
        <Button size="sm" variant="danger" icon={<Trash2 size={14} />} onClick={onDelete}>Eliminar</Button>
      </div>
    </div>
  );
}

function PaperPanel({ doc, commit }: { doc: CanvasDoc; commit: (d: CanvasDoc) => void }) {
  const p = doc.page;
  const setPage = (patch: Partial<Page>) => commit({ ...doc, page: { ...p, ...patch } });
  const roll = p.paper.startsWith('roll');
  return (
    <div className="stack">
      <SelectField label="Tamaño de papel" value={p.paper} onChange={(v) => commit(changePaper(doc, v as Page['paper']))}
        options={Object.entries(PAPERS).map(([value, x]) => ({ value, label: x.label }))} />
      {roll && (
        <NumberIn label="Ancho imprimible real (mm)" value={p.printable_width_mm}
          onChange={(v) => { const pw = Math.max(20, Math.min(p.width_mm, v)); const side = Math.round(((p.width_mm - pw) / 2) * 100) / 100;
            setPage({ printable_width_mm: pw, margins: { ...p.margins, l: side, r: side } }); }} />
      )}
      {roll && <p className="muted">Muchas impresoras de rollo de 80 mm imprimen unos 72 mm (y las de 58 mm, unos 48 mm). Ajústelo al manual de su impresora.</p>}
      {p.paper === 'custom' && (
        <div className="cv-grid2">
          <NumberIn label="Ancho (mm)" value={p.width_mm} onChange={(v) => commit(changePaper(doc, 'custom', { w: Math.max(30, v), h: p.height_mm }))} />
          <NumberIn label="Alto (mm)" value={p.height_mm} onChange={(v) => setPage({ height_mm: Math.max(20, v) })} />
          <Checkbox label="Alto variable (crece con el contenido)" checked={p.auto_height} onChange={(v) => setPage({ auto_height: v })} />
        </div>
      )}
      {!roll && (
        <SelectField label="Orientación" value={p.orientation} onChange={(v) => setPage({ orientation: v as 'portrait' })}
          options={[{ value: 'portrait', label: 'Vertical' }, { value: 'landscape', label: 'Horizontal' }]} />
      )}
      <div className="cv-grid2">
        {((roll ? ['t', 'b'] : ['t', 'b', 'l', 'r']) as ('t' | 'b' | 'l' | 'r')[]).map((side) => (
          <NumberIn key={side} label={`Margen ${{ t: 'superior', b: 'inferior', l: 'izquierdo', r: 'derecho' }[side]} (mm)`} value={p.margins[side]}
            onChange={(v) => setPage({ margins: { ...p.margins, [side]: Math.max(0, Math.min(60, v)) } })} />
        ))}
      </div>
      <SelectField label="Unidad de medida" value={p.unit} onChange={(v) => setPage({ unit: v as 'mm' })}
        options={[{ value: 'mm', label: 'Milímetros' }, { value: 'cm', label: 'Centímetros' }, { value: 'in', label: 'Pulgadas' }]} />
      <h3>Cuadrícula</h3>
      <Checkbox label="Mostrar cuadrícula" checked={doc.grid.show} onChange={(v) => commit({ ...doc, grid: { ...doc.grid, show: v } })} />
      <Checkbox label="Imán (ajustar a la cuadrícula y a las guías)" checked={doc.grid.snap} onChange={(v) => commit({ ...doc, grid: { ...doc.grid, snap: v } })} />
      <NumberIn label="Tamaño de la cuadrícula (mm)" value={doc.grid.size_mm} onChange={(v) => commit({ ...doc, grid: { ...doc.grid, size_mm: Math.max(0.5, Math.min(20, v)) } })} />
      <TextField label="Descuento de la plantilla (%)" value={doc.discount_pct} inputMode="decimal"
        onChange={(v) => commit({ ...doc, discount_pct: v.replace(',', '.') })} hint="Se aplica una sola vez al subtotal (por ejemplo, 20 en órdenes)." />
    </div>
  );
}

function CanvasPreview({ templateId, doc, onClose }: { templateId: string; doc: CanvasDoc; onClose: () => void }) {
  const [mode, setMode] = useState<'demo' | 'venta'>('demo');
  const [lines, setLines] = useState(5);
  const [saleId, setSaleId] = useState('');
  const sales = useApi<any>(mode === 'venta' ? '/sales?page_size=20' : null);
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (mode === 'venta' && !saleId) { setUrl(null); return; }
    let alive = true;
    let current: string | null = null;
    setBusy(true);
    setError(null);
    api<Blob>(`/print-templates/${templateId}/preview`, { method: 'POST', body: { layout: doc, lines, ...(mode === 'venta' ? { sale_id: Number(saleId) } : {}) } })
      .then((blob) => { if (!alive) return; current = URL.createObjectURL(blob); setUrl(current); })
      .catch((err) => { if (alive) setError(err as ApiError); })
      .finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; if (current) URL.revokeObjectURL(current); };
  }, [templateId, doc, lines, mode, saleId]);
  const printIt = () => {
    const frame = document.querySelector<HTMLIFrameElement>('iframe.tpl-preview');
    frame?.contentWindow?.print();
  };
  return (
    <Dialog open size="xl" title="Vista previa" onClose={onClose} footer={<>
      <Button icon={<Printer size={18} />} disabled={!url} onClick={printIt}>Imprimir</Button>
      <Button onClick={onClose}>Cerrar</Button>
    </>}>
      <div className="row">
        <SelectField label="Datos" value={mode} onChange={(v) => setMode(v as 'demo')}
          options={[{ value: 'demo', label: 'De demostración (marcados)' }, { value: 'venta', label: 'De una venta real (no se modifica)' }]} />
        {mode === 'demo' ? (
          <SelectField label="Productos" value={String(lines)} onChange={(v) => setLines(Number(v))}
            options={[1, 5, 15, 40, 100].map((n) => ({ value: String(n), label: String(n) }))} />
        ) : (
          <SelectField label="Venta" value={saleId} onChange={setSaleId} placeholder="Elija una venta…"
            options={(sales.data?.items ?? []).map((s: any) => ({ value: String(s.id), label: `${s.number} · ${s.customer_name || 'Consumidor final'}` }))} />
        )}
      </div>
      <p className="muted">Es el PDF real que genera el servidor con este diseño (el mismo que se usa para el Excel). La vista previa no registra ni modifica ventas.</p>
      <ErrorAlert error={error} />
      {busy && !url ? <Loading label="Generando…" /> : url ? <iframe className="tpl-preview" title="Vista previa del documento" src={url} /> : null}
    </Dialog>
  );
}

import { Paperclip, Save, Search, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { ApiError, post, put, upload } from '../../../api/client';
import { Button } from '../../../components/ui/Button';
import { Dialog } from '../../../components/ui/Dialog';
import { Alert, Badge, ErrorAlert, Loading } from '../../../components/ui/Feedback';
import { NumberField, SelectField, TextArea, TextField } from '../../../components/ui/Form';
import { useToast } from '../../../context/Toast';
import { money, qty as fmtQty, toApiNumber, today } from '../../../lib/format';
import { useApi, useDebounced } from '../../../lib/hooks';
import type { Observation } from './labels';

export interface ObservationMeta {
  categories: { id: number; code: string; name: string }[];
  suppliers: { id: number; name: string; active: number }[];
  users: { id: number; full_name: string; active: number }[];
  priorities: { value: string; label: string }[];
  statuses: { value: string; label: string }[];
  max_file_mb: number; max_files: number; file_types: string[]; recent_days: number;
}

interface ProductHit { id: number; code: string; description: string; unit: string; active: number; external_ref: string | null }

/** Selección del producto: busca en el inventario existente (nombre, código/SKU o código de barras). */
function ProductPicker({ value, onChange, error }: { value: number | null; onChange: (id: number | null) => void; error?: string }) {
  const [q, setQ] = useState('');
  const term = useDebounced(q.trim(), 250);
  const hits = useApi<ProductHit[]>(!value && term ? `/observations/products?q=${encodeURIComponent(term)}` : null);
  const context = useApi<any>(value ? `/observations/products/${value}` : null);
  const p = context.data;

  if (value) {
    return (
      <div className="obs-product card">
        {context.loading && !p ? <Loading label="Cargando producto…" /> : p && (
          <div className="card-body stack" style={{ gap: 8 }}>
            <div className="row-between">
              <div>
                <strong>{p.description}</strong> {!p.active && <Badge kind="danger">Inactivo</Badge>}
                <div className="muted">Código: {p.code}{p.external_ref ? ` · Ref.: ${p.external_ref}` : ''}</div>
              </div>
              <Button size="sm" variant="ghost" icon={<X size={18} />} onClick={() => onChange(null)}>Cambiar producto</Button>
            </div>
            <dl className="dl">
              <dt>Categoría</dt><dd>{p.category_name ?? 'Sin categoría'}</dd>
              <dt>Existencia actual</dt><dd>{fmtQty(p.stock)} {p.unit}</dd>
              {p.cost !== undefined && <><dt>Precio de compra</dt><dd>{money(p.cost)} <small className="muted">(costo promedio)</small></dd></>}
              <dt>Proveedor asociado</dt><dd>{p.last_supplier?.name ?? <span className="muted">Sin compras a crédito registradas</span>}</dd>
              <dt>Observaciones abiertas</dt><dd>{p.open_observations}{p.critical_observations ? ` (${p.critical_observations} crítica${p.critical_observations > 1 ? 's' : ''})` : ''}</dd>
            </dl>
          </div>
        )}
      </div>
    );
  }
  return (
    <div className="stack" style={{ gap: 8 }}>
      <TextField label="Producto relacionado" required type="search" value={q} onChange={setQ} error={error} autoComplete="off"
        placeholder="Nombre, código o código de barras" hint="Seleccione un producto existente del inventario." />
      {hits.loading && <Loading label="Buscando…" />}
      {hits.data && (hits.data.length ? (
        <ul className="result-list obs-hits" aria-label="Productos encontrados">
          {hits.data.map((h) => (
            <li key={h.id}>
              <button type="button" className="result-item" onClick={() => { onChange(h.id); setQ(''); }}>
                <span><strong>{h.code}</strong> · {h.description}</span>
                {!h.active && <Badge kind="danger">Inactivo</Badge>}
              </button>
            </li>
          ))}
        </ul>
      ) : <p className="muted"><Search size={16} aria-hidden /> Ningún producto coincide con «{term}».</p>)}
    </div>
  );
}

/** Registro y edición. Al crear se pueden elegir adjuntos, que se suben después de guardar. */
export function ObservationForm({ meta, observation, productId, onClose, onSaved }: {
  meta: ObservationMeta; observation?: Observation | null; productId?: number | null;
  onClose: () => void; onSaved: (o: Observation) => void;
}) {
  const { notify } = useToast();
  const editing = Boolean(observation);
  const o = observation;
  const [f, setF] = useState({
    product_id: o?.product_id ?? productId ?? null as number | null,
    category_id: o ? String(o.category_id) : '', priority: o?.priority ?? '', description: o?.description ?? '',
    qty: o?.qty ?? '', supplier_id: o?.supplier_id ? String(o.supplier_id) : '', reference_doc: o?.reference_doc ?? '',
    detected_on: o?.detected_on ?? today(), follow_up_date: o?.follow_up_date ?? '', notes: o?.notes ?? '',
    assigned_to: o?.assigned_to ? String(o.assigned_to) : '', comment: '',
  });
  const [files, setFiles] = useState<File[]>([]);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (v: any) => setF((x) => ({ ...x, [k]: v }));

  useEffect(() => { setErrors({}); }, [f.product_id]);

  const validate = () => {
    const e: Record<string, string> = {};
    if (!f.product_id) e.product_id = 'Seleccione el producto relacionado.';
    if (!f.category_id) e.category_id = 'Seleccione la categoría.';
    if (!f.priority) e.priority = 'Seleccione la prioridad.';
    if (f.description.trim().length < 5) e.description = 'Describa la novedad (mínimo 5 caracteres).';
    if (f.follow_up_date && f.follow_up_date < f.detected_on) e.follow_up_date = 'Debe ser posterior a la fecha de la novedad.';
    const tooBig = files.find((file) => file.size > meta.max_file_mb * 1024 * 1024);
    if (tooBig) e.file = `«${tooBig.name}» supera ${meta.max_file_mb} MB.`;
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const save = async () => {
    if (!validate()) return;
    setBusy(true);
    setError(null);
    const body: Record<string, unknown> = {
      category_id: Number(f.category_id), priority: f.priority, description: f.description.trim(),
      qty: f.qty.trim() ? toApiNumber(f.qty) : null, supplier_id: f.supplier_id ? Number(f.supplier_id) : null,
      reference_doc: f.reference_doc.trim(), detected_on: f.detected_on, follow_up_date: f.follow_up_date || null,
      notes: f.notes.trim(), assigned_to: f.assigned_to ? Number(f.assigned_to) : null,
    };
    try {
      let saved: Observation;
      if (o) {
        if (f.comment.trim() && f.priority !== o.priority) body.comment = f.comment.trim();
        saved = await put(`/observations/${o.id}`, { ...body, version: o.version });
      } else {
        saved = await post('/observations', { ...body, product_id: f.product_id });
      }
      const failed: string[] = [];
      for (const file of files) {
        const form = new FormData();
        form.append('file', file);
        try { await upload(`/observations/${saved.id}/files`, form); } catch (err) { failed.push(`${file.name}: ${(err as ApiError).message}`); }
      }
      notify('success', editing ? 'Observación actualizada' : 'Observación registrada', saved.code);
      if (failed.length) notify('warning', 'Algunos adjuntos no se cargaron', failed.join(' · '));
      onSaved(saved);
    } catch (err) {
      const apiErr = err as ApiError;
      setError(apiErr);
      setErrors(apiErr.fields ?? {});
    } finally {
      setBusy(false);
    }
  };

  const opts = <T,>(list: T[], value: (x: T) => number | string, label: (x: T) => string) => list.map((x) => ({ value: value(x), label: label(x) }));
  const activeUsers = meta.users.filter((u) => u.active || u.id === o?.assigned_to);
  const suppliers = meta.suppliers.filter((s) => s.active || s.id === o?.supplier_id);
  return (
    <Dialog open size="wide" title={o ? `Editar ${o.code}` : 'Nueva observación de inventario'} onClose={onClose} footer={
      <><Button onClick={onClose}>Cancelar</Button>
        <Button variant="primary" busy={busy} icon={<Save size={20} />} onClick={save}>{o ? 'Guardar cambios' : 'Registrar observación'}</Button></>}>
      <ErrorAlert error={error} />
      {o ? (
        <Alert kind="info" title={`${o.product_code} · ${o.product_description}`}>
          El producto de una observación no se cambia. Si la novedad corresponde a otro producto, registre una nueva.
        </Alert>
      ) : <ProductPicker value={f.product_id} onChange={set('product_id')} error={errors.product_id} />}

      <fieldset className="obs-fieldset">
        <legend>Datos de la novedad</legend>
        <div className="form-grid">
          <SelectField label="Categoría" required value={f.category_id} onChange={set('category_id')} placeholder="Seleccione…"
            error={errors.category_id} options={opts(meta.categories, (c) => c.id, (c) => c.name)} />
          <SelectField label="Prioridad" required value={f.priority} onChange={set('priority')} placeholder="Seleccione…"
            error={errors.priority} options={meta.priorities}
            hint="Baja: informativa · Media: seguimiento · Alta: atención pronta · Crítica: afecta ventas u operación." />
          <NumberField label="Cantidad afectada" value={f.qty} onChange={set('qty')} error={errors.qty} hint="Opcional. No modifica la existencia." />
        </div>
        <TextArea label="Descripción" required value={f.description} onChange={set('description')} error={errors.description}
          maxLength={2000} rows={3} placeholder="Ej.: En el conteo físico faltan 5 unidades frente al sistema." />
        {o && f.priority !== o.priority && (
          <TextField label="Motivo del cambio de prioridad" value={f.comment} onChange={set('comment')} maxLength={2000}
            hint="Opcional; queda en el historial de seguimiento." />
        )}
      </fieldset>

      <fieldset className="obs-fieldset">
        <legend>Seguimiento y referencias</legend>
        <div className="form-grid">
          <TextField label="Fecha de la novedad" type="date" value={f.detected_on} onChange={set('detected_on')} error={errors.detected_on} max={today()} />
          <TextField label="Fecha límite de seguimiento" type="date" value={f.follow_up_date} onChange={set('follow_up_date')}
            error={errors.follow_up_date} min={f.detected_on} />
          <SelectField label="Responsable" value={f.assigned_to} onChange={set('assigned_to')} error={errors.assigned_to}
            placeholder={o ? 'Quien la registró' : 'Yo (quien registra)'} options={opts(activeUsers, (u) => u.id, (u) => u.full_name)} />
          <SelectField label="Proveedor relacionado" value={f.supplier_id} onChange={set('supplier_id')} error={errors.supplier_id}
            placeholder="Ninguno" options={opts(suppliers, (s) => s.id, (s) => s.name)} />
          <TextField label="Factura o documento de referencia" value={f.reference_doc} onChange={set('reference_doc')}
            error={errors.reference_doc} maxLength={80} />
        </div>
        <TextArea label="Comentarios adicionales" value={f.notes} onChange={set('notes')} error={errors.notes} maxLength={2000} rows={2} />
      </fieldset>

      {!o && (
        <fieldset className="obs-fieldset">
          <legend>Fotografías o documentos</legend>
          <label className="btn btn-outline" style={{ alignSelf: 'flex-start' }}>
            <Paperclip size={18} aria-hidden /> Elegir archivos
            <input type="file" multiple className="sr-only" accept={meta.file_types.join(',')}
              onChange={(e) => setFiles(Array.from(e.target.files ?? []).slice(0, meta.max_files))} />
          </label>
          <span className="field-hint">{meta.file_types.join(', ')} · máximo {meta.max_file_mb} MB por archivo.</span>
          {errors.file && <span className="field-error">{errors.file}</span>}
          {files.length > 0 && <ul className="obs-files">{files.map((file) => <li key={file.name}>{file.name}</li>)}</ul>}
        </fieldset>
      )}
      <p className="muted">Registrar una observación no modifica existencias, costos ni movimientos. Para corregir cantidades use un ajuste de inventario.</p>
    </Dialog>
  );
}

export function useObservationMeta() {
  return useApi<ObservationMeta>('/observations/meta');
}

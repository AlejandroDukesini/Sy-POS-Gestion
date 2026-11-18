import { Archive, ArrowDown, ArrowUp, Lock, Pencil, Plus, RotateCcw, Save, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { ApiError, del, post, put } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { ConfirmDialog, Dialog } from '../../components/ui/Dialog';
import { Alert, Badge, ErrorAlert, ErrorState, Loading } from '../../components/ui/Feedback';
import { Checkbox, NumberField, SelectField, TextArea, TextField } from '../../components/ui/Form';
import { Card } from '../../components/ui/Layout';
import { useToast } from '../../context/Toast';
import { date, qty } from '../../lib/format';
import { useApi } from '../../lib/hooks';

export interface InventoryColumn {
  id: number; name: string; data_type: string; description: string; required: number; default_value: string | null;
  options: string[]; position: number; is_system: number; active: number; version: number; values_count?: number;
}

export const COLUMN_TYPES: Record<string, string> = {
  texto: 'Texto', texto_largo: 'Texto largo', entero: 'Número entero', decimal: 'Número decimal', fecha: 'Fecha',
  si_no: 'Sí / No', lista: 'Lista de opciones',
};

/** Columnas adicionales activas, en su orden. */
export function useInventoryColumns() {
  return useApi<{ columns: InventoryColumn[]; core: any[] }>('/inventory/columns');
}

/** Valor de una columna adicional para mostrar (los textos largos se recortan en la tabla). */
export function CustomValue({ column, value, clip }: { column: InventoryColumn; value?: string | null; clip?: boolean }) {
  if (value === undefined || value === null || value === '') return <span className="muted">—</span>;
  let text = value;
  if (column.data_type === 'si_no') text = value === '1' ? 'Sí' : 'No';
  else if (column.data_type === 'fecha') text = date(value);
  else if (column.data_type === 'decimal' || column.data_type === 'entero') text = qty(value);
  if (!clip) return <span style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{text}</span>;
  return <span className={`cell-clip${column.data_type === 'texto_largo' ? ' cell-clip-long' : ''}`} title={text}>{text}</span>;
}

/** Campo de captura según el tipo de la columna. */
export function CustomField({ column, value, onChange, error }: {
  column: InventoryColumn; value: string; onChange: (v: string) => void; error?: string;
}) {
  const common = { label: column.name, value, onChange, error, required: Boolean(column.required), hint: column.description || undefined };
  switch (column.data_type) {
    case 'texto_largo': return <TextArea {...common} rows={3} maxLength={5000} />;
    case 'entero': case 'decimal': return <NumberField {...common} />;
    case 'fecha': return <TextField {...common} type="date" />;
    case 'si_no': return <SelectField {...common} placeholder={column.required ? undefined : '—'} options={[{ value: '1', label: 'Sí' }, { value: '0', label: 'No' }]} />;
    case 'lista': return <SelectField {...common} placeholder={column.required ? undefined : '—'} options={column.options.map((o) => ({ value: o, label: o }))} />;
    default: return <TextField {...common} maxLength={200} />;
  }
}

/** «Administrar columnas»: campos principales fijos y columnas adicionales configurables. */
export function ColumnsAdmin() {
  const { notify } = useToast();
  const data = useApi<{ columns: InventoryColumn[]; core: any[] }>('/inventory/columns?include_archived=true');
  const [editing, setEditing] = useState<InventoryColumn | 'new' | null>(null);
  const [removing, setRemoving] = useState<{ column: InventoryColumn; values: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const columns = data.data?.columns ?? [];
  const active = columns.filter((c) => c.active);
  const archived = columns.filter((c) => !c.active);

  const act = async (run: () => Promise<unknown>, ok: string, detail?: string) => {
    setBusy(true);
    try {
      await run();
      notify('success', ok, detail);
      data.reload();
    } catch (err) {
      notify('danger', 'No se pudo completar', (err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const move = (index: number, delta: number) => {
    const ids = active.map((c) => c.id);
    [ids[index], ids[index + delta]] = [ids[index + delta], ids[index]];
    void act(() => put('/inventory/columns/order', { ids }), 'Orden guardado');
  };
  const askDelete = async (column: InventoryColumn) => {
    try {
      const check = await del<{ values: number }>(`/inventory/columns/${column.id}?dry_run=true`);
      setRemoving({ column, values: check.values });
    } catch (err) {
      notify('danger', 'No se pudo comprobar la columna', (err as Error).message);
    }
  };

  if (data.loading && !data.data) return <Loading />;
  if (data.error) return <ErrorState error={data.error} onRetry={data.reload} />;
  return (
    <div className="stack">
      <Card title="Columnas adicionales" actions={
        <Button variant="primary" icon={<Plus size={20} />} onClick={() => setEditing('new')}>Agregar columna</Button>}>
        <p className="card-body muted" style={{ margin: 0, paddingBottom: 0 }}>
          Aparecen en la tabla de productos después de los campos principales, en este orden. Use las flechas para moverlas.
          Archivar oculta la columna y conserva sus datos; eliminar borra sus datos.
        </p>
        <ul className="column-list" aria-label="Columnas adicionales activas">
          {active.map((c, i) => (
            <li key={c.id}>
              <div className="column-main">
                <strong>{i + 1}. {c.name}</strong>{' '}
                <Badge>{COLUMN_TYPES[c.data_type]}</Badge>{' '}
                {c.is_system ? <Badge kind="info">Del sistema</Badge> : <Badge>Personalizada</Badge>}{' '}
                {c.required ? <Badge kind="warning">Obligatoria</Badge> : null}
                <p>{c.description || 'Sin descripción.'}{c.data_type === 'lista' && ` Opciones: ${c.options.join(', ')}.`}
                  {c.default_value !== null && ` Predeterminado: ${c.data_type === 'si_no' ? (c.default_value === '1' ? 'Sí' : 'No') : c.default_value}.`}
                  {` ${c.values_count ?? 0} producto(s) con valor.`}</p>
              </div>
              <div className="column-actions">
                <Button size="sm" variant="ghost" iconOnly icon={<ArrowUp size={18} />} disabled={busy || i === 0} onClick={() => move(i, -1)}>
                  Subir {c.name}</Button>
                <Button size="sm" variant="ghost" iconOnly icon={<ArrowDown size={18} />} disabled={busy || i === active.length - 1}
                  onClick={() => move(i, 1)}>Bajar {c.name}</Button>
                <Button size="sm" icon={<Pencil size={18} />} onClick={() => setEditing(c)}>Editar</Button>
                {!c.is_system && <>
                  <Button size="sm" icon={<Archive size={18} />} busy={busy}
                    onClick={() => act(() => post(`/inventory/columns/${c.id}/archive`), 'Columna archivada', `${c.name}: sus datos se conservan.`)}>Archivar</Button>
                  <Button size="sm" variant="danger" icon={<Trash2 size={18} />} onClick={() => void askDelete(c)}>Eliminar</Button>
                </>}
              </div>
            </li>
          ))}
        </ul>
      </Card>
      {archived.length > 0 && (
        <Card title="Columnas archivadas">
          <ul className="column-list">
            {archived.map((c) => (
              <li key={c.id} className="is-archived">
                <div className="column-main"><strong>{c.name}</strong> <Badge>{COLUMN_TYPES[c.data_type]}</Badge>
                  <p>Oculta en la tabla y en los formularios. {c.values_count ?? 0} producto(s) conservan su valor.</p></div>
                <div className="column-actions">
                  <Button size="sm" icon={<RotateCcw size={18} />} busy={busy}
                    onClick={() => act(() => post(`/inventory/columns/${c.id}/restore`), 'Columna restaurada', c.name)}>Restaurar</Button>
                  <Button size="sm" variant="danger" icon={<Trash2 size={18} />} onClick={() => void askDelete(c)}>Eliminar</Button>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}
      <Card title="Campos principales">
        <p className="card-body muted" style={{ margin: 0, paddingBottom: 0 }}>
          Los usan ventas, compras, movimientos y contabilidad: no se pueden eliminar, renombrar ni mover.</p>
        <ul className="column-list">
          {(data.data?.core ?? []).map((c) => (
            <li key={c.key}>
              <div className="column-main"><Lock size={14} aria-hidden /> <strong>{c.name}</strong> <Badge>{COLUMN_TYPES[c.data_type]}</Badge>{' '}
                {c.required ? <Badge kind="warning">Obligatorio</Badge> : null}</div>
            </li>
          ))}
        </ul>
      </Card>
      {editing && <ColumnDialog column={editing === 'new' ? null : editing} onClose={() => setEditing(null)}
        onSaved={() => { setEditing(null); data.reload(); }} />}
      <ConfirmDialog open={Boolean(removing)} title="Eliminar columna" danger busy={busy} confirmLabel="Eliminar definitivamente"
        message={removing && (removing.values
          ? <>La columna «{removing.column.name}» tiene datos en <strong>{removing.values} producto(s)</strong>. Se borrarán y no se pueden
            recuperar. Si solo quiere ocultarla, use «Archivar».</>
          : <>La columna «{removing.column.name}» no tiene datos. ¿Eliminarla?</>)}
        onClose={() => setRemoving(null)} onConfirm={() => { const c = removing!.column; setRemoving(null);
          void act(() => del(`/inventory/columns/${c.id}`), 'Columna eliminada', c.name); }} />
    </div>
  );
}

function ColumnDialog({ column, onClose, onSaved }: { column: InventoryColumn | null; onClose: () => void; onSaved: () => void }) {
  const { notify } = useToast();
  const system = Boolean(column?.is_system);
  const [form, setForm] = useState({
    name: column?.name ?? '', data_type: column?.data_type ?? 'texto', description: column?.description ?? '',
    required: Boolean(column?.required), default_value: column?.default_value ?? '', options: (column?.options ?? []).join('\n'),
  });
  const [error, setError] = useState<ApiError | null>(null);
  const [impact, setImpact] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const set = (key: string) => (v: string) => { setImpact(null); setForm((f) => ({ ...f, [key]: v })); };
  const body = () => {
    const b: Record<string, unknown> = { name: form.name, description: form.description };
    if (!system) {
      b.data_type = form.data_type;
      b.required = form.required;
      b.default_value = form.default_value.trim() === '' ? null : form.default_value;
      if (form.data_type === 'lista') b.options = form.options.split('\n').map((o) => o.trim()).filter(Boolean);
    }
    if (column) b.version = column.version;
    return b;
  };
  // Un cambio que afecta valores existentes se revisa primero (dry_run) y se muestra la advertencia.
  const affects = column && !system && (form.data_type !== column.data_type || form.options !== column.options.join('\n')
    || (form.required && !column.required));
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      if (column && affects && !impact) {
        const check = await put<any>(`/inventory/columns/${column.id}?dry_run=true`, body());
        setImpact(check.impact);
        return;
      }
      const result = column ? await put<any>(`/inventory/columns/${column.id}`, body()) : await post<any>('/inventory/columns', body());
      const filled = column ? result.impact?.filled : result.filled;
      notify('success', column ? 'Columna actualizada' : 'Columna agregada',
        filled ? `${form.name}: ${filled} producto(s) tomaron el valor predeterminado.` : form.name);
      onSaved();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  const fe = error?.fields ?? {};
  const preview: InventoryColumn = { id: 0, name: 'Valor predeterminado', data_type: form.data_type, description: '', required: 0,
    default_value: null, options: form.options.split('\n').map((o) => o.trim()).filter(Boolean), position: 0, is_system: 0, active: 1, version: 1 };
  return (
    <Dialog open title={column ? `Editar columna «${column.name}»` : 'Agregar columna'} onClose={onClose} size="wide" footer={<>
      <Button onClick={onClose}>Cancelar</Button>
      <Button variant="primary" busy={busy} icon={<Save size={20} />} disabled={impact?.invalid_count > 0} onClick={save}>
        {impact ? 'Aplicar el cambio' : affects ? 'Revisar el cambio' : 'Guardar'}</Button>
    </>}>
      <ErrorAlert error={error} />
      {impact && (impact.invalid_count > 0 ? (
        <Alert kind="danger" title="No se puede aplicar">
          {impact.invalid_count} producto(s) tienen valores que no se pueden convertir. Corríjalos primero:
          <ul>{impact.invalid.slice(0, 10).map((i: any) => <li key={i.code}>{i.code}: «{i.value}» — {i.error}</li>)}</ul>
        </Alert>
      ) : (
        <Alert kind="warning" title="Este cambio afecta productos existentes">
          {impact.values} producto(s) tienen valor en esta columna{impact.converted ? `; se convertirán ${impact.converted}` : ''}.
          {impact.will_fill ? ` ${impact.will_fill} producto(s) sin valor tomarán el predeterminado.` : ''} Pulse «Aplicar el cambio» para confirmar.
        </Alert>
      ))}
      {system && <Alert kind="info">Columna del sistema: solo se pueden cambiar el nombre y la descripción.</Alert>}
      <div className="form-grid">
        <TextField label="Nombre" value={form.name} onChange={set('name')} error={fe.name} maxLength={60} required autoFocus />
        <SelectField label="Tipo de dato" value={form.data_type} onChange={set('data_type')} error={fe.data_type} disabled={system}
          options={Object.entries(COLUMN_TYPES).map(([value, label]) => ({ value, label }))}
          hint={column && !system ? 'Solo se cambia si todos los valores se pueden convertir.' : undefined} />
      </div>
      <TextArea label="Descripción (opcional)" value={form.description} onChange={set('description')} maxLength={300} rows={2} />
      {form.data_type === 'lista' && !system && (
        <TextArea label="Opciones (una por línea)" value={form.options} onChange={set('options')} error={fe.options} rows={4} required />)}
      {!system && <>
        <Checkbox label="Obligatoria" checked={form.required} onChange={(v) => { setImpact(null); setForm((f) => ({ ...f, required: v })); }}
          hint="Necesita un valor predeterminado: se asigna a los productos que no tengan valor." />
        <CustomField column={preview} value={form.default_value} onChange={set('default_value')} error={fe.default_value} />
      </>}
    </Dialog>
  );
}

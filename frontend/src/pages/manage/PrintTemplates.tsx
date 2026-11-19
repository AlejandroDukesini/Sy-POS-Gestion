import { Copy, FileSpreadsheet, LayoutTemplate, Pencil, Plus, Star, Trash2, Upload } from 'lucide-react';
import { useState } from 'react';
import { Route, Routes, useNavigate } from 'react-router-dom';
import { ApiError, del, post, upload } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { ConfirmDialog, Dialog } from '../../components/ui/Dialog';
import { Alert, Badge, EmptyState, ErrorAlert, ErrorState, Loading } from '../../components/ui/Feedback';
import { Field, SelectField, TextField } from '../../components/ui/Form';
import { Card } from '../../components/ui/Layout';
import { DataTable } from '../../components/ui/Table';
import { useInventory } from '../../context/Inventory';
import { useToast } from '../../context/Toast';
import { dateTime } from '../../lib/format';
import { useApi } from '../../lib/hooks';
import { api } from '../../api/client';
import { ManageBack } from './ManageRoutes';
import { TemplateEditor } from './TemplateEditor';

export interface TemplateRow {
  public_id: string; name: string; kind: 'documento' | 'venta' | 'recibo'; source: 'excel' | 'editor'; active: number;
  is_default: number; current_version: number; document_type: { id: number; code: string; name: string } | null;
  group: { key: string; name: string }; outputs: number; updated_at: string; has_original: boolean; original_name?: string;
}

export const KIND_LABEL: Record<string, string> = { documento: 'Documento', venta: 'Venta', recibo: 'Recibo' };

export function PrintTemplatesPage() {
  return (
    <Routes>
      <Route index element={<TemplateList />} />
      <Route path=":id" element={<TemplateEditor />} />
    </Routes>
  );
}

function typeLabel(t: TemplateRow) {
  return t.kind === 'documento' ? t.document_type?.name ?? 'Documento' : KIND_LABEL[t.kind];
}

function TemplateList() {
  const navigate = useNavigate();
  const { notify } = useToast();
  const { current } = useInventory();
  const list = useApi<TemplateRow[]>('/print-templates');
  const [importing, setImporting] = useState(false);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<TemplateRow | null>(null);
  const [busy, setBusy] = useState(false);

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    try {
      await fn();
      notify('success', ok);
      list.reload();
    } catch (err) {
      notify('danger', 'No se pudo completar', (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      <ManageBack title="Plantillas de impresión"
        description={`Diseños de cotizaciones, órdenes, ventas y recibos para ${current?.name ?? 'este inventario'}. Importe el Excel de la empresa o diseñe uno desde cero.`}
        actions={<>
          <Button icon={<Plus size={20} />} onClick={() => setCreating(true)}>Crear desde cero</Button>
          <Button variant="primary" icon={<Upload size={20} />} onClick={() => setImporting(true)}>Importar Excel</Button>
        </>} />
      <Card>
        {list.loading && !list.data ? <Loading /> : list.error ? <ErrorState error={list.error} onRetry={list.reload} /> :
          !list.data?.length ? (
            <EmptyState title="Aún no hay plantillas" icon={<LayoutTemplate size={40} aria-hidden />}>
              <p>Importe el Excel con el que ya imprime (se conserva su diseño) o cree uno desde cero.</p>
            </EmptyState>
          ) : (
            <DataTable caption="Plantillas de impresión" rows={list.data} rowKey={(t) => t.public_id}
              onSelect={(t) => navigate(t.public_id)} columns={[
                { key: 'n', header: 'Nombre', render: (t) => <strong>{t.name}</strong> },
                { key: 't', header: 'Para', render: (t) => typeLabel(t) },
                { key: 'o', header: 'Origen', render: (t) => (t.source === 'excel'
                  ? <span className="row" style={{ gap: 4 }}><FileSpreadsheet size={16} aria-hidden /> Excel</span> : 'Editor') },
                { key: 's', header: 'Estado', render: (t) => (
                  <span className="row" style={{ gap: 4 }}>
                    {t.active ? <Badge kind="success">Activa</Badge> : <Badge kind="warning">Borrador</Badge>}
                    {t.is_default ? <Badge kind="info">Predeterminada</Badge> : null}
                  </span>) },
                { key: 'v', header: 'Versión', numeric: true, render: (t) => t.current_version },
                { key: 'e', header: 'Emitidos', numeric: true, render: (t) => t.outputs },
                { key: 'u', header: 'Actualizada', render: (t) => dateTime(t.updated_at) },
                { key: 'a', header: 'Acciones', render: (t) => (
                  <span className="row" style={{ gap: 4, flexWrap: 'nowrap' }} onClick={(e) => e.stopPropagation()}>
                    <Button size="sm" variant="ghost" iconOnly icon={<Pencil size={18} />} onClick={() => navigate(t.public_id)}>Editar {t.name}</Button>
                    <Button size="sm" variant="ghost" iconOnly icon={<Copy size={18} />} disabled={busy}
                      onClick={() => act(() => post(`/print-templates/${t.public_id}/duplicate`, {}), 'Plantilla duplicada')}>Duplicar {t.name}</Button>
                    {t.active && !t.is_default ? (
                      <Button size="sm" variant="ghost" iconOnly icon={<Star size={18} />} disabled={busy}
                        onClick={() => act(() => api(`/print-templates/${t.public_id}`, { method: 'PATCH', body: { is_default: true } }),
                          'Ahora es la plantilla predeterminada')}>Usar {t.name} como predeterminada</Button>) : null}
                    <Button size="sm" variant="ghost" iconOnly icon={<Trash2 size={18} />} disabled={busy}
                      onClick={() => setDeleting(t)}>Eliminar {t.name}</Button>
                  </span>) },
              ]} />
          )}
      </Card>
      {importing && <ImportWizard onClose={() => setImporting(false)} onDone={(id) => navigate(id)} />}
      {creating && <CreateDialog onClose={() => setCreating(false)} onDone={(id) => navigate(id)} />}
      <ConfirmDialog open={Boolean(deleting)} danger title="Eliminar plantilla" confirmLabel="Eliminar" busy={busy}
        message={`¿Eliminar «${deleting?.name}»? Dejará de estar disponible para imprimir. Los documentos ya emitidos con ella se conservan.`}
        onClose={() => setDeleting(null)}
        onConfirm={() => { const t = deleting!; setDeleting(null); void act(() => del(`/print-templates/${t.public_id}`), 'Plantilla eliminada'); }} />
    </div>
  );
}

function KindFields({ kind, setKind, docType, setDocType, errors }: {
  kind: string; setKind: (v: string) => void; docType: string; setDocType: (v: string) => void; errors: Record<string, string>;
}) {
  const types = useApi<any[]>('/document-types');
  return (
    <>
      <SelectField label="Para qué se usa" value={kind} onChange={setKind} options={[
        { value: 'documento', label: 'Documento comercial (cotización, orden…)' }, { value: 'venta', label: 'Venta' },
        { value: 'recibo', label: 'Recibo' }]} />
      {kind === 'documento' && (
        <SelectField label="Tipo de documento" required value={docType} onChange={setDocType} error={errors.document_type_id}
          placeholder="Elija…" options={(types.data ?? []).map((t) => ({ value: t.id, label: t.name }))} />
      )}
    </>
  );
}

interface SheetInfo {
  name: string; state: string; dimensions: string; used_cells: number; formulas: number; merged: number; images: number;
  print_area: string; sample: string[];
}

function ImportWizard({ onClose, onDone }: { onClose: () => void; onDone: (id: string) => void }) {
  const { notify } = useToast();
  const [kind, setKind] = useState('documento');
  const [docType, setDocType] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [staged, setStaged] = useState<{ token: string; file_name: string; sheets: SheetInfo[]; notes: string[] } | null>(null);
  const [sheet, setSheet] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const analyze = async () => {
    if (!file) { setErrors({ file: 'Elija el archivo .xlsx o .xlsm.' }); return; }
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await upload('/print-templates/inspect', form);
      setStaged(res);
      setName(file.name.replace(/\.(xlsx|xlsm)$/i, ''));
      setSheet('');                                   // nunca se elige una hoja automáticamente
    } catch (err) {
      setError(err as ApiError);
      setErrors((err as ApiError).fields ?? {});
    } finally {
      setBusy(false);
    }
  };
  const confirm = async () => {
    const e: Record<string, string> = {};
    if (!sheet) e.sheet = 'Elija la hoja que se usará como plantilla.';
    if (kind === 'documento' && !docType) e.document_type_id = 'Elija el tipo de documento.';
    setErrors(e);
    if (Object.keys(e).length) return;
    setBusy(true);
    setError(null);
    try {
      const t = await post('/print-templates/import', { token: staged!.token, sheet, name, kind,
        document_type_id: kind === 'documento' ? Number(docType) : null });
      notify('success', 'Excel importado', 'Revise las vinculaciones sugeridas y guarde para activarla.');
      sessionStorage.setItem(`pospy.import-notes.${t.public_id}`, JSON.stringify(t.import_notes ?? []));
      onDone(t.public_id);
    } catch (err) {
      setError(err as ApiError);
      setErrors((err as ApiError).fields ?? {});
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open title="Importar plantilla de Excel" size="wide" onClose={onClose} footer={<>
      <Button onClick={onClose}>Cancelar</Button>
      {staged ? <Button variant="primary" busy={busy} onClick={confirm}>Importar hoja</Button>
        : <Button variant="primary" busy={busy} onClick={analyze}>Analizar archivo</Button>}
    </>}>
      <ErrorAlert error={error} />
      {!staged ? (
        <div className="stack">
          <p className="muted">El archivo original se guarda intacto. Las macros nunca se ejecutan.</p>
          <KindFields kind={kind} setKind={setKind} docType={docType} setDocType={setDocType} errors={errors} />
          <Field label="Archivo de Excel (.xlsx o .xlsm, máximo 10 MB)" required error={errors.file}>
            {({ id, describedBy }) => (
              <input id={id} type="file" className="input" accept=".xlsx,.xlsm" aria-describedby={describedBy}
                onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            )}
          </Field>
        </div>
      ) : (
        <div className="stack">
          {staged.notes.map((n) => <Alert key={n} kind="info">{n}</Alert>)}
          <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
            <legend className="field-label">Elija la hoja que se usará como plantilla ({staged.file_name})</legend>
            {errors.sheet && <Alert kind="danger">{errors.sheet}</Alert>}
            <div className="sheet-cards">
              {staged.sheets.map((s) => (
                <label key={s.name} className={`sheet-card${sheet === s.name ? ' selected' : ''}`}>
                  <input type="radio" name="sheet" value={s.name} checked={sheet === s.name} onChange={() => setSheet(s.name)} />
                  <span className="stack" style={{ gap: 4 }}>
                    <strong>{s.name}{s.state !== 'visible' ? ' (oculta)' : ''}</strong>
                    <small className="muted">
                      Dimensiones {s.dimensions} · {s.used_cells} celdas con datos · {s.merged} combinadas · {s.formulas} fórmulas
                      {s.images ? ` · ${s.images} imagen(es)` : ''}{s.print_area ? ` · área de impresión ${s.print_area}` : ' · sin área de impresión'}
                    </small>
                    {s.sample.length > 0 && <small>Contenido: {s.sample.join(' · ')}</small>}
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
          <TextField label="Nombre de la plantilla" value={name} onChange={setName} maxLength={80} />
          <KindFields kind={kind} setKind={setKind} docType={docType} setDocType={setDocType} errors={errors} />
        </div>
      )}
    </Dialog>
  );
}

function CreateDialog({ onClose, onDone }: { onClose: () => void; onDone: (id: string) => void }) {
  const [name, setName] = useState('');
  const [kind, setKind] = useState('documento');
  const [docType, setDocType] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const submit = async () => {
    const e: Record<string, string> = {};
    if (!name.trim()) e.name = 'Escriba el nombre.';
    if (kind === 'documento' && !docType) e.document_type_id = 'Elija el tipo de documento.';
    setErrors(e);
    if (Object.keys(e).length) return;
    setBusy(true);
    try {
      const t = await post('/print-templates', { name: name.trim(), kind, document_type_id: kind === 'documento' ? Number(docType) : null });
      onDone(t.public_id);
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open title="Crear plantilla desde cero" onClose={onClose} footer={<>
      <Button onClick={onClose}>Cancelar</Button><Button variant="primary" busy={busy} onClick={submit}>Crear y diseñar</Button></>}>
      <ErrorAlert error={error} />
      <TextField label="Nombre" required value={name} onChange={setName} error={errors.name} maxLength={80} autoFocus />
      <KindFields kind={kind} setKind={setKind} docType={docType} setDocType={setDocType} errors={errors} />
    </Dialog>
  );
}

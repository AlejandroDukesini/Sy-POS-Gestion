import { ArrowLeft, Download, FileSpreadsheet, Plus, Save, Trash2, Upload } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { ApiError, download, post, put, upload } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { Alert, Badge, ErrorAlert, ErrorState, Loading } from '../../components/ui/Feedback';
import { Checkbox, Field, NumberField, SelectField, TextField } from '../../components/ui/Form';
import { Card, PageHeader } from '../../components/ui/Layout';
import { DataTable } from '../../components/ui/Table';
import { useToast } from '../../context/Toast';
import { dateTime } from '../../lib/format';
import { useApi } from '../../lib/hooks';
import { ManageBack } from './ManageRoutes';

export function DocumentTypesPage() {
  return (
    <Routes>
      <Route index element={<TypeList />} />
      <Route path="nuevo" element={<TypeEditor />} />
      <Route path=":id" element={<TypeEditor />} />
    </Routes>
  );
}

function TypeList() {
  const navigate = useNavigate();
  const types = useApi<any[]>('/document-types?include_inactive=true');
  return (
    <div className="stack">
      <ManageBack title="Tipos de documento y plantillas" description="Cree tantos tipos como necesite; cada uno usa su propia plantilla de Excel."
        actions={<Button variant="primary" icon={<Plus size={20} />} onClick={() => navigate('nuevo')}>Nuevo tipo</Button>} />
      <Card>
        {types.loading && !types.data ? <Loading /> : types.error ? <ErrorState error={types.error} /> : (
          <DataTable caption="Tipos de documento" rows={types.data ?? []} rowKey={(t: any) => t.id} onSelect={(t: any) => navigate(String(t.id))} columns={[
            { key: 'n', header: 'Nombre', render: (t: any) => <strong>{t.name}</strong> },
            { key: 'p', header: 'Plantilla', render: (t: any) => (!t.has_template ? <Badge kind="warning">Sin plantilla</Badge>
              : t.template_problems.length ? <Badge kind="danger">Revisar mapeo</Badge> : <Badge kind="success">Lista</Badge>) },
            { key: 'i', header: 'Impresora', render: (t: any) => t.printer || '—' },
            { key: 'u', header: 'Documentos (30 días)', numeric: true, render: (t: any) => `${t.documents} (${t.last_30_days})` },
            { key: 'g', header: 'Impresos', numeric: true, render: (t: any) => t.printed },
            { key: 'l', header: 'Último uso', render: (t: any) => dateTime(t.last_used_at) },
            { key: 's', header: 'Estado', render: (t: any) => (t.active ? <Badge kind="success">Activo</Badge> : <Badge>Inactivo</Badge>) },
          ]} />
        )}
      </Card>
    </div>
  );
}

const DEFAULT_PAGE = { paper: 'letter', orientation: 'portrait', margins_cm: 1.5, fit_width: true, scale: 100 };

function TypeEditor() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { notify } = useToast();
  const type = useApi(id ? `/document-types/${id}` : null);
  const printers = useApi('/printing/printers');
  const [form, setForm] = useState<any>({ name: '', prefix: '', next_number: 1, numbering: true, validity_days: 0, printer: '',
    page_setup: DEFAULT_PAGE, fields: [], active: true });
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const t = type.data;

  useEffect(() => {
    if (t) setForm({ name: t.name, prefix: t.prefix, next_number: t.next_number, numbering: Boolean(t.numbering), validity_days: t.validity_days,
      printer: t.printer, page_setup: { ...DEFAULT_PAGE, ...t.page_setup }, fields: t.fields, active: Boolean(t.active) });
  }, [t]);

  const set = (k: string) => (v: any) => setForm((f: any) => ({ ...f, [k]: v }));
  const setPage = (k: string) => (v: any) => setForm((f: any) => ({ ...f, page_setup: { ...f.page_setup, [k]: v } }));
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const body = { ...form, next_number: Number(form.next_number) || 1, validity_days: Number(form.validity_days) || 0,
        page_setup: { ...form.page_setup, margins_cm: Number(form.page_setup.margins_cm), scale: Number(form.page_setup.scale) },
        fields: form.fields.map((f: any) => ({ key: f.key || null, label: f.label, required: Boolean(f.required) })),
        ...(t ? { version: t.version } : {}) };
      const saved = t ? await put(`/document-types/${t.id}`, body) : await post('/document-types', body);
      notify('success', 'Tipo de documento guardado', saved.name);
      if (!t) navigate(`../${saved.id}`, { replace: true });
      else type.reload();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };

  if (id && type.loading && !t) return <Loading />;
  const fe = error?.fields ?? {};
  const printerOptions = (printers.data?.printers ?? []).map((p: any) => ({ value: p.name, label: p.name }));
  if (form.printer && !printerOptions.some((o: any) => o.value === form.printer)) printerOptions.unshift({ value: form.printer, label: `${form.printer} (no instalada)` });
  return (
    <div className="stack">
      <Link to="/gestion/documentos" className="btn btn-ghost" style={{ alignSelf: 'flex-start' }}><ArrowLeft size={20} aria-hidden /> Tipos de documento</Link>
      <PageHeader title={t ? t.name : 'Nuevo tipo de documento'} />
      <ErrorAlert error={error} />
      <Card title="Datos y numeración">
        <div className="card-body stack">
          <div className="form-grid">
            <TextField label="Nombre del documento" value={form.name} onChange={set('name')} error={fe.name} required />
            <TextField label="Prefijo del número" value={form.prefix} onChange={set('prefix')} error={fe.prefix} hint="Ej.: COT-" />
            <NumberField label="Siguiente número" value={String(form.next_number)} onChange={set('next_number')} error={fe.next_number} />
            <NumberField label="Vigencia (días)" value={String(form.validity_days)} onChange={set('validity_days')} error={fe.validity_days}
              hint="0 = sin fecha de vencimiento." />
          </div>
          <Checkbox label="Numeración automática consecutiva" checked={form.numbering} onChange={set('numbering')}
            hint="Si la desactiva, se escribe el número al crear cada documento." />
          <Checkbox label="Tipo activo" checked={form.active} onChange={set('active')} />
        </div>
      </Card>
      <Card title="Campos adicionales">
        <div className="card-body stack">
          <p className="muted">Datos propios de este documento (por ejemplo: placa, forma de entrega). En la plantilla se usan como {'{{extra.clave}}'}.</p>
          {form.fields.map((f: any, i: number) => (
            <div key={i} className="row" style={{ alignItems: 'flex-end' }}>
              <div className="grow"><TextField label={`Nombre del campo ${i + 1}`} value={f.label}
                onChange={(v) => set('fields')(form.fields.map((x: any, j: number) => (j === i ? { ...x, label: v } : x)))} /></div>
              <Checkbox label="Obligatorio" checked={Boolean(f.required)}
                onChange={(v) => set('fields')(form.fields.map((x: any, j: number) => (j === i ? { ...x, required: v } : x)))} />
              {f.key && <code>{`{{extra.${f.key}}}`}</code>}
              <Button variant="ghost" iconOnly icon={<Trash2 size={18} />} onClick={() => set('fields')(form.fields.filter((_: any, j: number) => j !== i))}>
                Quitar campo</Button>
            </div>
          ))}
          <div><Button variant="outline" icon={<Plus size={18} />} onClick={() => set('fields')([...form.fields, { label: '', required: false }])}>Agregar campo</Button></div>
        </div>
      </Card>
      <Card title="Impresión">
        <div className="card-body form-grid">
          <SelectField label="Impresora predeterminada" value={form.printer} onChange={set('printer')} placeholder="(elegir al imprimir)"
            options={printerOptions} hint={printers.data && !printers.data.available ? printers.data.reason : undefined} />
          <SelectField label="Tamaño de papel" value={form.page_setup.paper} onChange={setPage('paper')} options={[
            { value: 'letter', label: 'Carta' }, { value: 'legal', label: 'Oficio' }, { value: 'a4', label: 'A4' }, { value: 'a5', label: 'A5' }]} />
          <SelectField label="Orientación" value={form.page_setup.orientation} onChange={setPage('orientation')} options={[
            { value: 'portrait', label: 'Vertical' }, { value: 'landscape', label: 'Horizontal' }]} />
          <NumberField label="Márgenes (cm)" value={String(form.page_setup.margins_cm)} onChange={setPage('margins_cm')} error={fe.margins_cm} />
          <Checkbox label="Ajustar al ancho de la página" checked={form.page_setup.fit_width} onChange={setPage('fit_width')} />
          {!form.page_setup.fit_width && <NumberField label="Escala (%)" value={String(form.page_setup.scale)} onChange={setPage('scale')} error={fe.scale} />}
        </div>
      </Card>
      <div className="form-actions"><Button variant="primary" size="lg" busy={busy} icon={<Save size={22} />} onClick={save}>Guardar tipo de documento</Button></div>
      {t && <TemplateCard type={t} onChanged={type.reload} />}
    </div>
  );
}

function TemplateCard({ type, onChanged }: { type: any; onChanged: () => void }) {
  const { notify } = useToast();
  const [busy, setBusy] = useState('');
  const [error, setError] = useState<ApiError | null>(null);
  const [cells, setCells] = useState<Record<string, string>>({});
  const mapping = type.mapping ?? {};
  const all: Record<string, string> = { ...type.available_fields.header, ...type.available_fields.extra };

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    setBusy('upload');
    setError(null);
    try {
      const form = new FormData();
      form.append('file', file);
      const r = await upload(`/document-types/${type.id}/template`, form);
      notify(r.template_problems.length ? 'warning' : 'success', 'Plantilla cargada',
        r.template_problems.length ? 'Revise el mapeo: faltan campos.' : 'La plantilla coincide con el mapeo.');
      onChanged();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy('');
    }
  };
  const assign = async (field: string, cell: string | null) => {
    setError(null);
    try {
      await post(`/document-types/${type.id}/mapping`, { field, cell });
      onChanged();
    } catch (err) {
      setError(err as ApiError);
    }
  };
  const capacity = async (value: string) => {
    try {
      await post(`/document-types/${type.id}/capacity`, { capacity: Number(value) });
      onChanged();
    } catch (err) {
      setError(err as ApiError);
    }
  };
  return (
    <Card title="Plantilla de Excel">
      <div className="card-body stack">
        <Alert kind="info" title="Cómo preparar la plantilla">
          Use su archivo de Excel tal como está y escriba marcadores donde van los datos: {'{{numero}}'}, {'{{fecha}}'}, {'{{cliente_nombre}}'},
          {' {{total}}'}… En la primera fila de productos: {'{{linea.codigo}}'}, {'{{linea.descripcion}}'}, {'{{linea.cantidad}}'}, {'{{linea.precio}}'},
          {' {{linea.total}}'}. Los formatos, fórmulas, bordes y celdas combinadas se conservan. Si la plantilla tiene imágenes o gráficos,
          se rellena con Microsoft Excel para no perderlos.
        </Alert>
        <ErrorAlert error={error} />
        <div className="row">
          <Field label={type.has_template ? 'Reemplazar plantilla (.xlsx o .xlsm)' : 'Subir plantilla (.xlsx o .xlsm)'}>
            {({ id }) => <input id={id} className="input" type="file" accept=".xlsx,.xlsm" disabled={busy === 'upload'}
              onChange={(e) => void onFile(e.target.files?.[0])} />}
          </Field>
          <Button variant="outline" icon={<FileSpreadsheet size={20} />}
            onClick={() => download(`/document-types/${type.id}/sample-template`, 'plantilla.xlsx')}>Descargar plantilla base</Button>
          {type.has_template && <Button variant="outline" icon={<Download size={20} />}
            onClick={() => download(`/document-types/${type.id}/template`, type.template_file)}>Descargar plantilla actual</Button>}
        </div>
        {busy === 'upload' && <Loading label="Analizando la plantilla…" />}
        {type.has_template && (
          <>
            {type.template_problems.length
              ? <Alert kind="danger" title="La plantilla no coincide con el mapeo"><ul>{type.template_problems.map((p: string) => <li key={p}>{p}</li>)}</ul></Alert>
              : <Alert kind="success">Plantilla lista. Hoja «{mapping.sheet}», productos desde la fila {mapping.line_row}.</Alert>}
            {type.template_needs_excel?.length > 0 && (
              <Alert kind="warning">La plantilla contiene {type.template_needs_excel.join(', ')}: se necesita Microsoft Excel en el equipo del servidor para generarla.</Alert>
            )}
            {mapping.line_row > 0 && (
              <div style={{ maxWidth: 320 }}>
                <NumberField label="Filas de productos disponibles" value={String(mapping.capacity)} onChange={(v) => { if (Number(v) > 0) void capacity(v); }}
                  hint="Detectadas automáticamente; ajústelas si la tabla de la plantilla es más larga o más corta." />
              </div>
            )}
            <div className="table-wrap">
              <table className="table">
                <caption className="sr-only">Mapeo de campos</caption>
                <thead><tr><th>Campo</th><th>Celda</th><th>Cómo se asignó</th><th>Asignar manualmente</th></tr></thead>
                <tbody>
                  {Object.entries(all).map(([key, label]) => {
                    const coord = mapping.fields?.[key];
                    const manual = mapping.manual?.includes(key);
                    return (
                      <tr key={key}>
                        <td>{label}<br /><code className="muted">{`{{${key}}}`}</code></td>
                        <td>{coord ?? <span className="muted">—</span>}</td>
                        <td>{coord ? (manual ? 'Manual' : 'Marcador') : 'Sin asignar'}</td>
                        <td>
                          <div className="row" style={{ flexWrap: 'nowrap' }}>
                            <input className="input" style={{ width: 90, minHeight: 'var(--control-h-sm)' }} aria-label={`Celda para ${label}`}
                              placeholder="B5" value={cells[key] ?? ''} onChange={(e) => setCells((c) => ({ ...c, [key]: e.target.value }))} />
                            <Button size="sm" disabled={!cells[key]} icon={<Upload size={16} />} onClick={() => assign(key, cells[key])}>Asignar</Button>
                            {manual && <Button size="sm" variant="ghost" onClick={() => assign(key, null)}>Quitar</Button>}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="muted">Columnas de productos: {Object.entries(mapping.line_columns ?? {}).map(([k, c]) => `${type.available_fields.line[k] ?? k} → ${c}`).join(' · ') || 'ninguna'}</p>
          </>
        )}
      </div>
    </Card>
  );
}

import { KeyRound, Link2, Plug, Plus, RefreshCw, Save, ShieldAlert } from 'lucide-react';
import { useState } from 'react';
import { ApiError, post, put } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { ConfirmDialog, Dialog } from '../../components/ui/Dialog';
import { Alert, Badge, EmptyState, ErrorAlert, Loading, StatusBadge } from '../../components/ui/Feedback';
import { Checkbox, NumberField, SelectField, TextField } from '../../components/ui/Form';
import { Card } from '../../components/ui/Layout';
import { DataTable } from '../../components/ui/Table';
import { useToast } from '../../context/Toast';
import { dateTime } from '../../lib/format';
import { useApi } from '../../lib/hooks';
import { ImportPreview } from '../inventory/ImportExport';
import { ManageBack } from './ManageRoutes';
import { SettingsSection } from './Settings';

const PROVIDERS: Record<string, string> = {
  excel: 'Archivo Excel o CSV', carpeta: 'Carpeta local o de red', onedrive: 'Microsoft OneDrive', gdrive: 'Google Drive',
};
const FIELDS = { code: 'Código', description: 'Descripción', price: 'Precio sin descuento', discount_price: 'Precio con descuento',
  cost: 'Costo', stock: 'Cantidad disponible', min_stock: 'Existencia mínima', category: 'Categoría', tax_rate: 'IVA %', unit: 'Unidad' };

export function IntegrationsPage() {
  const list = useApi<any[]>('/integrations');
  const [editing, setEditing] = useState<any>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const master = (list.data ?? []).find((c) => c.is_master && c.active);
  return (
    <div className="stack">
      <ManageBack title="Integraciones de inventario" actions={<Button variant="primary" icon={<Plus size={20} />} onClick={() => setEditing({})}>Nueva conexión</Button>} />
      <Alert kind="info" title="¿Quién manda sobre las existencias?">
        {master
          ? <>La fuente maestra es <strong>{master.name}</strong>{master.stock_policy === 'ajustar'
            ? ': sus diferencias de existencias se aplican como movimientos de conciliación (con historial y asiento contable).'
            : ', pero su política es «informar»: las diferencias solo se reportan.'}</>
          : <>POS-PY es la autoridad: las existencias son la suma de los movimientos registrados y ninguna fuente externa las sobrescribe.</>}
        {' '}El costo de los productos existentes siempre lo calcula POS-PY (costo promedio).
      </Alert>
      <Card title="Conexiones">
        {list.loading && !list.data ? <Loading /> : !list.data?.length ? (
          <EmptyState title="Aún no hay conexiones" icon={<Plug size={40} aria-hidden />}>
            <p>La base de datos local de POS-PY ya funciona sin conexiones. Agréguelas solo si el inventario también vive en Excel o en la nube.</p>
          </EmptyState>
        ) : (
          <DataTable caption="Conexiones" rows={list.data} rowKey={(c: any) => c.id} onSelect={(c: any) => setSelected(c.id)} columns={[
            { key: 'n', header: 'Nombre', render: (c: any) => <strong>{c.name}</strong> },
            { key: 'p', header: 'Fuente', render: (c: any) => <>{c.provider_label}<br /><small className="muted">{c.source}</small></> },
            { key: 'm', header: 'Rol', render: (c: any) => (c.is_master ? <Badge kind="info">Maestra</Badge> : 'Secundaria') },
            { key: 's', header: 'Sincronización', render: (c: any) => (c.sync_mode === 'intervalo' ? `Cada ${c.sync_interval_min} min` : 'Manual') },
            { key: 'a', header: 'Autorización', render: (c: any) => (c.needs_oauth ? (c.authorized ? <Badge kind="success">Autorizada</Badge>
              : <Badge kind="warning">Pendiente</Badge>) : 'No requiere') },
            { key: 'l', header: 'Última sincronización', render: (c: any) => (c.last_sync_at ? <>{dateTime(c.last_sync_at)} <StatusBadge status={c.last_status} /></> : 'Nunca') },
            { key: 'e', header: 'Estado', render: (c: any) => (c.active ? <Badge kind="success">Activa</Badge> : <Badge>Inactiva</Badge>) },
          ]} />
        )}
      </Card>
      <Credentials />
      {editing && <ConnectionForm connection={editing} onClose={() => setEditing(null)} onSaved={(c) => { setEditing(null); list.reload(); setSelected(c.id); }} />}
      {selected && <ConnectionDetail id={selected} onClose={() => { setSelected(null); list.reload(); }} onEdit={(c) => { setSelected(null); setEditing(c); }} />}
    </div>
  );
}

function Credentials() {
  const { notify } = useToast();
  const status = useApi('/integrations/credentials');
  const [secret, setSecret] = useState('');
  const saveSecret = async () => {
    try {
      await put('/integrations/credentials/google-secret', { client_secret: secret });
      notify('success', secret ? 'Secreto guardado cifrado' : 'Secreto eliminado');
      setSecret('');
      status.reload();
    } catch (err) {
      notify('danger', 'No se pudo guardar', (err as Error).message);
    }
  };
  return (
    <>
      <SettingsSection section="oauth" title="Credenciales de aplicación (OneDrive y Google Drive)" />
      <Card title="Secreto del cliente de Google">
        <div className="card-body stack">
          <p className="muted">Se guarda cifrado en el servidor y nunca se envía a la interfaz. Estado:{' '}
            {status.data?.google_client_secret_set ? <Badge kind="success">Configurado</Badge> : <Badge kind="warning">No configurado</Badge>}</p>
          <div className="row" style={{ alignItems: 'flex-end' }}>
            <div className="grow"><TextField label="Secreto del cliente" type="password" value={secret} onChange={setSecret} autoComplete="off" /></div>
            <Button icon={<KeyRound size={20} />} onClick={saveSecret}>{secret ? 'Guardar secreto' : 'Eliminar secreto'}</Button>
          </div>
          <p className="muted">Pasos de registro en Microsoft Entra y Google Cloud Console: ver README › Integraciones.</p>
        </div>
      </Card>
    </>
  );
}

function ConnectionForm({ connection, onClose, onSaved }: { connection: any; onClose: () => void; onSaved: (c: any) => void }) {
  const [form, setForm] = useState<any>({
    name: connection.name ?? '', provider: connection.provider ?? 'excel', config: { columns: {}, ...(connection.config ?? {}) },
    is_master: Boolean(connection.is_master), sync_mode: connection.sync_mode ?? 'manual', sync_interval_min: connection.sync_interval_min ?? 60,
    stock_policy: connection.stock_policy ?? 'informar', update_catalog: connection.update_catalog === undefined ? true : Boolean(connection.update_catalog),
    create_missing: connection.create_missing === undefined ? true : Boolean(connection.create_missing),
    active: connection.active === undefined ? true : Boolean(connection.active),
  });
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: string) => (v: any) => setForm((f: any) => ({ ...f, [k]: v }));
  const setCfg = (k: string) => (v: any) => setForm((f: any) => ({ ...f, config: { ...f.config, [k]: v } }));
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const body = { ...form, sync_interval_min: Number(form.sync_interval_min) || 60,
        config: { ...form.config, header_row: Number(form.config.header_row) || 0 }, ...(connection.id ? { version: connection.version } : {}) };
      onSaved(connection.id ? await put(`/integrations/${connection.id}`, body) : await post('/integrations', body));
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  const fe = error?.fields ?? {};
  return (
    <Dialog open title={connection.id ? `Conexión ${connection.name}` : 'Nueva conexión'} onClose={onClose} size="wide"
      footer={<><Button onClick={onClose}>Cancelar</Button><Button variant="primary" busy={busy} icon={<Save size={20} />} onClick={save}>Guardar</Button></>}>
      <ErrorAlert error={error} />
      <div className="form-grid">
        <TextField label="Nombre" value={form.name} onChange={set('name')} error={fe.name} required />
        <SelectField label="Fuente" value={form.provider} onChange={set('provider')} disabled={Boolean(connection.id)}
          options={Object.entries(PROVIDERS).map(([value, label]) => ({ value, label }))} />
        {form.provider === 'excel' && <TextField label="Ruta del archivo en el servidor" value={form.config.path ?? ''} onChange={setCfg('path')}
          error={fe.path} hint="Ej.: C:\Inventario\existencias.xlsx o \\servidor\compartido\inventario.xlsx" required />}
        {form.provider === 'carpeta' && <>
          <TextField label="Carpeta" value={form.config.folder ?? ''} onChange={setCfg('folder')} error={fe.folder} required
            hint="Local o de red (\\servidor\recurso). Se toma el archivo más reciente." />
          <TextField label="Patrón de nombre" value={form.config.pattern ?? '*.xlsx'} onChange={setCfg('pattern')} />
        </>}
        {form.provider === 'onedrive' && <TextField label="Ruta en OneDrive" value={form.config.item_path ?? ''} onChange={setCfg('item_path')}
          error={fe.item_path} hint="Ej.: /Inventario/existencias.xlsx" required />}
        {form.provider === 'gdrive' && <TextField label="Id. del archivo de Google Drive" value={form.config.file_id ?? ''} onChange={setCfg('file_id')}
          error={fe.file_id} hint="Está en el enlace: docs.google.com/…/d/<Id>/" required />}
        <TextField label="Hoja (opcional)" value={form.config.sheet ?? ''} onChange={setCfg('sheet')} />
        <NumberField label="Fila de encabezados" value={String(form.config.header_row ?? 0)} onChange={setCfg('header_row')} hint="0 = detectar." />
      </div>
      <fieldset>
        <legend>Columnas (deje vacío para detectarlas por nombre)</legend>
        <div className="form-grid">
          {Object.entries(FIELDS).map(([k, label]) => (
            <TextField key={k} label={label} value={form.config.columns?.[k] ?? ''} placeholder="Nombre de la columna"
              onChange={(v) => setCfg('columns')({ ...form.config.columns, [k]: v })} />
          ))}
        </div>
      </fieldset>
      <fieldset>
        <legend>Política</legend>
        <Checkbox label="Crear productos que no existen en POS-PY" checked={form.create_missing} onChange={set('create_missing')} />
        <Checkbox label="Actualizar descripción, precios y datos del catálogo" checked={form.update_catalog} onChange={set('update_catalog')} />
        <Checkbox label="Fuente maestra de inventario" checked={form.is_master} onChange={(v) => setForm((f: any) => ({ ...f, is_master: v, stock_policy: v ? f.stock_policy : 'informar' }))}
          hint="Solo puede haber una. Marcarla quita la condición de maestra a las demás." />
        <SelectField label="Diferencias de existencias" value={form.stock_policy} onChange={set('stock_policy')} disabled={!form.is_master} error={fe.stock_policy}
          options={[{ value: 'informar', label: 'Solo informar (POS-PY conserva sus existencias)' },
            { value: 'ajustar', label: 'Ajustar con movimientos de conciliación' }]} />
        <div className="form-grid">
          <SelectField label="Sincronización" value={form.sync_mode} onChange={set('sync_mode')} options={[
            { value: 'manual', label: 'Manual (con vista previa)' }, { value: 'intervalo', label: 'Automática por intervalo' }]} />
          {form.sync_mode === 'intervalo' && <NumberField label="Cada (minutos)" value={String(form.sync_interval_min)} onChange={set('sync_interval_min')}
            error={fe.sync_interval_min} hint="Entre 5 y 1440." />}
        </div>
        {form.sync_mode === 'intervalo' && <Alert kind="warning">La sincronización automática aplica los cambios sin vista previa, según esta política. Las filas con errores se omiten y quedan en el historial.</Alert>}
      </fieldset>
    </Dialog>
  );
}

function ConnectionDetail({ id, onClose, onEdit }: { id: number; onClose: () => void; onEdit: (c: any) => void }) {
  const { notify } = useToast();
  const conn = useApi(`/integrations/${id}`);
  const [test, setTest] = useState<any>(null);
  const [run, setRun] = useState<any>(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState<ApiError | null>(null);
  const [confirm, setConfirm] = useState(false);
  const c = conn.data;
  const act = async (name: string, fn: () => Promise<void>) => {
    setBusy(name);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy('');
    }
  };
  const authorize = () => act('auth', async () => {
    const r = await post(`/integrations/${id}/authorize`);
    window.open(r.authorize_url, '_blank', 'noopener');
    notify('info', 'Complete la autorización en la ventana del proveedor', 'Después vuelva aquí y pulse «Probar conexión».');
  });
  return (
    <Dialog open title={c ? c.name : 'Conexión'} onClose={onClose} size="xl">
      {conn.loading && !c ? <Loading /> : c && (
        <>
          <p>{c.provider_label} · {c.source}</p>
          <ErrorAlert error={error} />
          {c.needs_oauth && !c.authorized && <Alert kind="warning" title="Falta autorizar">Pulse «Autorizar» e inicie sesión con la cuenta que tiene el archivo. Se solicita solo permiso de lectura.</Alert>}
          <div className="row">
            {c.needs_oauth && <Button icon={<Link2 size={20} />} busy={busy === 'auth'} onClick={authorize}>{c.authorized ? 'Volver a autorizar' : 'Autorizar'}</Button>}
            <Button icon={<Plug size={20} />} busy={busy === 'test'} onClick={() => act('test', async () => setTest(await post(`/integrations/${id}/test`)))}>Probar conexión</Button>
            <Button variant="primary" icon={<RefreshCw size={20} />} busy={busy === 'preview'} disabled={!c.active}
              onClick={() => act('preview', async () => setRun(await post(`/integrations/${id}/preview`)))}>Sincronizar ahora (vista previa)</Button>
            <Button variant="outline" onClick={() => onEdit(c)}>Editar</Button>
            {c.active ? <Button variant="ghost" icon={<ShieldAlert size={20} />} onClick={() => setConfirm(true)}>Desactivar</Button> : null}
          </div>
          {test && (test.ok ? (
            <Alert kind="success" title={test.message}>Hoja «{test.sheet}», encabezados en la fila {test.header_row}: {test.headers.filter(Boolean).join(', ')}.</Alert>
          ) : <Alert kind="danger" title="La prueba falló">{test.message}</Alert>)}
          {run && <ImportPreview run={run} onDone={() => { setRun(null); conn.reload(); }} />}
          {c.last_message && <p className="muted">Último resultado: {c.last_message}</p>}
          <h3>Historial de sincronizaciones</h3>
          <DataTable caption="Historial" rows={c.runs} rowKey={(r: any) => r.id} columns={[
            { key: 'd', header: 'Fecha', render: (r: any) => dateTime(r.started_at) },
            { key: 't', header: 'Origen', render: (r: any) => (r.trigger === 'automatica' ? 'Automática' : 'Manual') },
            { key: 's', header: 'Estado', render: (r: any) => <StatusBadge status={r.status} /> },
            { key: 'r', header: 'Resultado', render: (r: any) => (r.summary.applied
              ? `${r.summary.applied.created} nuevos · ${r.summary.applied.updated} actualizados · ${r.summary.applied.stock_adjusted} ajustes · ${r.summary.applied.errors.length} errores`
              : `${r.summary.counts?.rows ?? 0} filas leídas`) },
            { key: 'u', header: 'Usuario', render: (r: any) => r.username ?? 'sistema' },
          ]} />
        </>
      )}
      <ConfirmDialog open={confirm} title="Desactivar conexión" danger confirmLabel="Desactivar" onClose={() => setConfirm(false)}
        onConfirm={() => act('off', async () => { await post(`/integrations/${id}/deactivate`); setConfirm(false); conn.reload(); })}
        message="Se detiene la sincronización, deja de ser fuente maestra y se eliminan sus credenciales guardadas. El historial se conserva." />
    </Dialog>
  );
}

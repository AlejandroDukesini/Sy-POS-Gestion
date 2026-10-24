import { DatabaseBackup, Download, RotateCcw, ShieldCheck, Upload } from 'lucide-react';
import { useState } from 'react';
import { ApiError, download, get, post, upload } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { Dialog } from '../../components/ui/Dialog';
import { Alert, Badge, EmptyState, ErrorAlert, Loading } from '../../components/ui/Feedback';
import { Field, TextField } from '../../components/ui/Form';
import { Card } from '../../components/ui/Layout';
import { DataTable } from '../../components/ui/Table';
import { useAuth } from '../../context/Auth';
import { useToast } from '../../context/Toast';
import { dateTime } from '../../lib/format';
import { useApi } from '../../lib/hooks';
import { ManageBack } from './ManageRoutes';
import { SettingsSection } from './Settings';

function size(bytes: number): string {
  return bytes > 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`;
}

export function BackupsPage() {
  const { notify } = useToast();
  const { refresh } = useAuth();
  const list = useApi<any[]>('/backups');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState<ApiError | null>(null);
  const [verified, setVerified] = useState<Record<string, any>>({});
  const [restoring, setRestoring] = useState<string | null>(null);
  const [typed, setTyped] = useState('');

  const create = async () => {
    setBusy('create');
    setError(null);
    try {
      const b = await post('/backups');
      notify('success', 'Copia creada y verificada', b.file);
      list.reload();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy('');
    }
  };
  const verify = async (file: string) => {
    setBusy(file);
    try {
      const r = await get(`/backups/${file}/verify`);
      setVerified((v) => ({ ...v, [file]: r }));
    } catch (err) {
      setVerified((v) => ({ ...v, [file]: { ok: false, detail: (err as Error).message } }));
    } finally {
      setBusy('');
    }
  };
  const onUpload = async (file: File | undefined) => {
    if (!file) return;
    setBusy('upload');
    setError(null);
    try {
      const form = new FormData();
      form.append('file', file);
      const r = await upload('/backups/upload', form);
      notify('success', 'Copia cargada y verificada', r.file);
      list.reload();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy('');
    }
  };
  const restore = async () => {
    setBusy('restore');
    setError(null);
    try {
      const r = await post('/backups/restore', { file: restoring, confirm: typed });
      setRestoring(null);
      notify('success', 'Copia restaurada', `Copia de seguridad previa: ${r.safety_backup}. Inicie sesión de nuevo.`);
      await refresh();
    } catch (err) {
      setError(err as ApiError);
      setRestoring(null);
    } finally {
      setBusy('');
      setTyped('');
    }
  };

  return (
    <div className="stack">
      <ManageBack title="Copias de seguridad" description="Cada copia se verifica (integridad de la base y huella SHA-256) al crearla."
        actions={<Button variant="primary" busy={busy === 'create'} icon={<DatabaseBackup size={20} />} onClick={create}>Crear copia ahora</Button>} />
      <Alert kind="info">Guarde copias fuera de este equipo (disco externo o nube de la empresa). Las credenciales de integraciones viajan cifradas en la copia.</Alert>
      <ErrorAlert error={error} />
      <Card title="Copias disponibles">
        {list.loading && !list.data ? <Loading /> : !list.data?.length ? <EmptyState title="Aún no hay copias" /> : (
          <DataTable caption="Copias de seguridad" rows={list.data} rowKey={(b: any) => b.file} columns={[
            { key: 'f', header: 'Archivo', render: (b: any) => <><strong>{b.file}</strong><br /><small className="muted">{b.label}</small></> },
            { key: 'd', header: 'Fecha', render: (b: any) => dateTime(b.created_at) },
            { key: 's', header: 'Tamaño', numeric: true, render: (b: any) => size(b.size) },
            { key: 'c', header: 'Contenido', render: (b: any) => (b.counts ? `${b.counts.products} productos · ${b.counts.sales} ventas` : '—') },
            { key: 'v', header: 'Verificación', render: (b: any) => (verified[b.file]
              ? (verified[b.file].ok ? <Badge kind="success">Íntegra</Badge> : <Badge kind="danger">{verified[b.file].detail}</Badge>)
              : <Button size="sm" variant="ghost" busy={busy === b.file} icon={<ShieldCheck size={16} />} onClick={() => verify(b.file)}>Verificar</Button>) },
            { key: 'a', header: 'Acciones', render: (b: any) => (
              <div className="row" style={{ gap: 6 }}>
                <Button size="sm" variant="outline" icon={<Download size={16} />} onClick={() => download(`/backups/${b.file}/download`, b.file)}>Descargar</Button>
                <Button size="sm" variant="outline" icon={<RotateCcw size={16} />} onClick={() => setRestoring(b.file)}>Restaurar</Button>
              </div>) },
          ]} />
        )}
      </Card>
      <Card title="Cargar una copia externa">
        <div className="card-body">
          <Field label="Archivo de copia de POS-PY (.db)">
            {({ id }) => <input id={id} className="input" type="file" accept=".db" disabled={busy === 'upload'} onChange={(e) => void onUpload(e.target.files?.[0])} />}
          </Field>
          <p className="muted" style={{ marginTop: 8 }}><Upload size={16} aria-hidden /> Se comprueba antes de aceptarla; después puede restaurarla desde la lista.</p>
        </div>
      </Card>
      <SettingsSection section="respaldos" title="Copias automáticas" />
      <Dialog open={Boolean(restoring)} title="Restaurar copia de seguridad" onClose={() => { setRestoring(null); setTyped(''); }} footer={
        <><Button onClick={() => setRestoring(null)}>Cancelar</Button>
          <Button variant="danger" busy={busy === 'restore'} disabled={typed !== 'RESTAURAR'} onClick={restore}>Restaurar</Button></>}>
        <Alert kind="warning" title="Esta operación reemplaza todos los datos actuales">
          Se volverá al estado de <strong>{restoring}</strong>. Antes se crea automáticamente una copia del estado actual y se cierran todas las sesiones.
        </Alert>
        <TextField label="Para confirmar escriba RESTAURAR" value={typed} onChange={setTyped} autoComplete="off" />
      </Dialog>
    </div>
  );
}

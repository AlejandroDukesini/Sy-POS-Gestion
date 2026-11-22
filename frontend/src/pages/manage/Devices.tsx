import { Ban, Check, Laptop, Pencil, ShieldCheck, X } from 'lucide-react';
import { useState } from 'react';
import { ApiError, post, put } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { ConfirmDialog, Dialog } from '../../components/ui/Dialog';
import { Alert, Badge, ErrorAlert, ErrorState, Loading } from '../../components/ui/Feedback';
import { Checkbox, TextField } from '../../components/ui/Form';
import { Card } from '../../components/ui/Layout';
import { DataTable } from '../../components/ui/Table';
import { useToast } from '../../context/Toast';
import { deviceProof, deviceSupported, suggestedDeviceName } from '../../lib/device';
import { dateTime } from '../../lib/format';
import { useApi } from '../../lib/hooks';
import { ManageBack } from './ManageRoutes';

interface DeviceRow {
  id: number; public_id: string; name: string; status: 'pendiente' | 'autorizado' | 'revocado' | 'rechazado'; user_agent: string;
  created_at: string; decided_at: string | null; last_seen_at: string | null; fingerprint: string; requested_by_name: string | null;
  decided_by_name: string | null; last_user_name: string | null; active_sessions: number; note: string;
}
const BADGE = { autorizado: 'success', pendiente: 'warning', revocado: 'danger', rechazado: 'danger' } as const;
const ACTION_LABEL: Record<string, string> = {
  'dispositivo.solicitado': 'Solicitud de equipo', 'dispositivo.autorizado': 'Equipo autorizado', 'dispositivo.revocado': 'Equipo revocado',
  'dispositivo.rechazado': 'Solicitud rechazada', 'dispositivo.renombrado': 'Equipo renombrado', 'dispositivo.solicitud_fallida': 'Solicitud con credenciales inválidas',
  'sesion.equipo_rechazado': 'Ingreso rechazado por el equipo', 'seguridad.dispositivos_activada': 'Restricción activada',
  'seguridad.dispositivos_desactivada': 'Restricción desactivada',
};

/** Gestión › Equipos autorizados: restricción de acceso por dispositivo. */
export function DevicesPage() {
  const { notify } = useToast();
  const data = useApi<{ enforced: boolean; devices: DeviceRow[]; history: any[] }>('/devices');
  const current = useApi<{ enforced: boolean; local: boolean; device: { public_id: string; name: string; status: string } | null }>('/devices/current');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState<ApiError | null>(null);
  const [confirm, setConfirm] = useState<{ device: DeviceRow; status: 'revocado' | 'rechazado' } | null>(null);
  const [renaming, setRenaming] = useState<DeviceRow | null>(null);
  const reload = () => { data.reload(); current.reload(); };

  const run = async (key: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(key);
    setError(null);
    try {
      await fn();
      notify('success', ok);
      reload();
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, 'Equipo', (err as Error).message));
    } finally {
      setBusy('');
    }
  };
  const registerThis = () => run('this', async () => post('/devices/register', { name: suggestedDeviceName(), device: await deviceProof() }),
    'Este equipo quedó autorizado y su sesión vinculada');

  if (data.loading && !data.data) return <Loading />;
  if (data.error) return <ErrorState error={data.error} onRetry={reload} />;
  const d = data.data!;
  const me = current.data;
  const thisAuthorized = me?.device?.status === 'autorizado';
  return (
    <div className="stack">
      <ManageBack title="Equipos autorizados"
        description="Limite el uso del POS a los computadores que usted autorice: aunque alguien copie la dirección y tenga una contraseña, no podrá ingresar desde otro equipo." />
      <ErrorAlert error={error} />
      <Card title="Restricción por equipo">
        <div className="card-body stack">
          <Checkbox label="Solo permitir el ingreso desde equipos autorizados" checked={d.enforced} disabled={busy === 'policy'}
            onChange={(v) => run('policy', () => put('/devices/policy', { enforced: v }), v ? 'Restricción activada' : 'Restricción desactivada')} />
          <p className="muted">
            Con la restricción activa, cada equipo demuestra su identidad con una clave criptográfica propia (no con la dirección IP ni con
            datos del navegador). Los equipos nuevos quedan pendientes hasta que un administrador los apruebe; revocar un equipo cierra sus
            sesiones de inmediato. El equipo donde está instalado el servidor siempre puede ingresar (evita quedar bloqueado).
          </p>
          {!deviceSupported() && !me?.local && (
            <Alert kind="warning">Este navegador no puede identificar el equipo porque la conexión no es segura. Use la dirección https del POS.</Alert>
          )}
        </div>
      </Card>
      <Card title="Este equipo">
        <div className="card-body row" style={{ gap: 12, alignItems: 'center' }}>
          <Laptop size={28} aria-hidden />
          <div className="grow">
            {me?.local ? <strong>Equipo servidor (siempre autorizado).</strong>
              : me?.device ? <><strong>{me.device.name}</strong> · {me.device.public_id} <Badge kind={BADGE[me.device.status as keyof typeof BADGE] ?? 'warning'}>{me.device.status}</Badge></>
                : <span>Esta sesión no está vinculada a un equipo registrado.</span>}
          </div>
          {!me?.local && !thisAuthorized && deviceSupported() && (
            <Button variant="primary" icon={<ShieldCheck size={18} />} busy={busy === 'this'} onClick={registerThis}>Autorizar este equipo</Button>
          )}
        </div>
      </Card>
      <Card title={`Equipos (${d.devices.length})`}>
        {d.devices.length === 0 ? <div className="card-body"><p className="muted">Aún no hay equipos registrados.</p></div> : (
          <DataTable caption="Equipos registrados" rows={d.devices} rowKey={(x) => x.id} columns={[
            { key: 'n', header: 'Equipo', render: (x) => <span><strong>{x.name}</strong><br /><span className="muted">{x.public_id} · huella {x.fingerprint}</span></span> },
            { key: 's', header: 'Estado', render: (x) => <Badge kind={BADGE[x.status]}>{x.status}</Badge> },
            { key: 'r', header: 'Solicitado por', render: (x) => x.requested_by_name ?? '—' },
            { key: 'u', header: 'Última actividad', render: (x) => (x.last_seen_at ? `${dateTime(x.last_seen_at)}${x.last_user_name ? ` · ${x.last_user_name}` : ''}` : '—') },
            { key: 'a', header: 'Sesiones activas', numeric: true, render: (x) => x.active_sessions },
            { key: 'x', header: 'Acciones', render: (x) => (
              <span className="row" style={{ gap: 4, flexWrap: 'nowrap' }}>
                {x.status !== 'autorizado' && (
                  <Button size="sm" variant="primary" icon={<Check size={16} />} busy={busy === `a${x.id}`}
                    onClick={() => run(`a${x.id}`, () => put(`/devices/${x.id}/status`, { status: 'autorizado' }), `«${x.name}» autorizado`)}>Autorizar</Button>
                )}
                {x.status === 'pendiente' && (
                  <Button size="sm" icon={<X size={16} />} onClick={() => setConfirm({ device: x, status: 'rechazado' })}>Rechazar</Button>
                )}
                {x.status === 'autorizado' && (
                  <Button size="sm" variant="danger" icon={<Ban size={16} />} onClick={() => setConfirm({ device: x, status: 'revocado' })}>Revocar</Button>
                )}
                <Button size="sm" variant="ghost" iconOnly icon={<Pencil size={16} />} onClick={() => setRenaming(x)}>Renombrar {x.name}</Button>
              </span>) },
          ]} />
        )}
      </Card>
      <Card title="Historial">
        <div className="card-body">
          {d.history.length === 0 ? <p className="muted">Sin eventos.</p> : (
            <ul className="history">
              {d.history.map((h, i) => (
                <li key={i}><strong>{ACTION_LABEL[h.action] ?? h.action}</strong> · {dateTime(h.created_at)}{h.full_name ? ` · ${h.full_name}` : ''}</li>
              ))}
            </ul>
          )}
        </div>
      </Card>
      <ConfirmDialog open={Boolean(confirm)} danger title={confirm?.status === 'revocado' ? 'Revocar equipo' : 'Rechazar solicitud'}
        confirmLabel={confirm?.status === 'revocado' ? 'Revocar' : 'Rechazar'}
        message={confirm?.status === 'revocado'
          ? `«${confirm?.device.name}» no podrá volver a ingresar y sus ${confirm?.device.active_sessions} sesión(es) abierta(s) se cerrarán de inmediato.`
          : `La solicitud de «${confirm?.device.name}» se rechazará.`}
        onClose={() => setConfirm(null)}
        onConfirm={() => { const c = confirm!; setConfirm(null); void run(`c${c.device.id}`, () => put(`/devices/${c.device.id}/status`, { status: c.status }),
          c.status === 'revocado' ? 'Equipo revocado y sesiones cerradas' : 'Solicitud rechazada'); }} />
      {renaming && <RenameDialog device={renaming} onClose={() => setRenaming(null)}
        onSave={(name) => { const r = renaming; setRenaming(null); void run(`n${r.id}`, () => put(`/devices/${r.id}/name`, { name }), 'Equipo renombrado'); }} />}
    </div>
  );
}

function RenameDialog({ device, onClose, onSave }: { device: DeviceRow; onClose: () => void; onSave: (name: string) => void }) {
  const [name, setName] = useState(device.name);
  return (
    <Dialog open title="Renombrar equipo" onClose={onClose} footer={<>
      <Button onClick={onClose}>Cancelar</Button><Button variant="primary" disabled={!name.trim()} onClick={() => onSave(name.trim())}>Guardar</Button></>}>
      <TextField label="Nombre" value={name} onChange={setName} maxLength={60} autoFocus />
    </Dialog>
  );
}

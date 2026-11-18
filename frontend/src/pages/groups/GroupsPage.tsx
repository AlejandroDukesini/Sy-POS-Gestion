import { ArrowLeft, Check, Copy, DoorOpen, Link2, Lock, LockOpen, Pencil, Plus, Save, Share2, UserMinus, Users, X } from 'lucide-react';
import { useState } from 'react';
import { Link, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { ApiError, post, put } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { ConfirmDialog, Dialog } from '../../components/ui/Dialog';
import { Alert, Badge, EmptyState, ErrorAlert, ErrorState, Loading } from '../../components/ui/Feedback';
import { Checkbox, NumberField, SelectField, TextArea, TextField } from '../../components/ui/Form';
import { Card, Metric, PageHeader } from '../../components/ui/Layout';
import { DataTable } from '../../components/ui/Table';
import { useAuth } from '../../context/Auth';
import { useToast } from '../../context/Toast';
import { date, dateTime } from '../../lib/format';
import { useApi } from '../../lib/hooks';
import { useRealtimeEvents, useRealtimeStatus } from '../../lib/realtime';
import { SettingsSection } from '../manage/Settings';
import { TaskBoard } from '../tasks/TaskBoard';
import { ConnectionBadge, eventText, GroupStatusBadge, InvitationBadge, MemberBadge, POLICY_LABEL } from './labels';

export default function GroupsRoutes() {
  return (
    <Routes>
      <Route index element={<GroupsList />} />
      <Route path=":id" element={<GroupDetail />} />
    </Routes>
  );
}

/** Indicador de la conexión de este dispositivo con el servidor. */
function MyConnection() {
  const status = useRealtimeStatus();
  return <span className="row" style={{ gap: 6 }}><span className="muted">Este dispositivo:</span><ConnectionBadge status={status} /></span>;
}

// ------------------------------------------------------------------ listado
function GroupsList() {
  const groups = useApi<any>('/groups');
  const [creating, setCreating] = useState(false);
  const navigate = useNavigate();
  useRealtimeEvents((e) => { if (['grupo', 'presencia', 'resync'].includes(e.type)) groups.reload(); });
  const data = groups.data;
  return (
    <div className="stack">
      <PageHeader title="Grupos de trabajo"
        description={data?.can_manage ? 'Cree grupos, invite a sus empleados con un enlace y vea quién está conectado.'
          : 'Los grupos a los que pertenece y su estado de conexión.'}
        actions={data?.can_manage && <Button variant="primary" icon={<Plus size={20} />} onClick={() => setCreating(true)}>Nuevo grupo</Button>} />
      <MyConnection />
      {groups.loading && !data ? <Loading /> : groups.error ? <ErrorState error={groups.error} onRetry={groups.reload} /> : data && (
        <>
          {data.can_manage && (
            <Card title="Grupos que administro">
              {!data.owned.length ? (
                <EmptyState title="Todavía no ha creado grupos" icon={<Users size={40} aria-hidden />}>
                  <p>Cree un grupo y comparta su enlace de invitación con los empleados, estén donde estén.</p>
                  <Button variant="primary" icon={<Plus size={20} />} onClick={() => setCreating(true)}>Crear el primer grupo</Button>
                </EmptyState>
              ) : (
                <div className="tiles card-body">
                  {data.owned.map((g: any) => (
                    <Link key={g.public_id} to={g.public_id} className="tile">
                      <span className="tile-icon"><Users size={28} aria-hidden /></span>
                      <span>
                        <span className="tile-name">{g.name}</span>
                        <span className="tile-desc" style={{ display: 'block' }}>{g.public_id} · {g.members} integrante(s) · {g.online} conectado(s)</span>
                        <span className="row" style={{ marginTop: 8, gap: 6 }}>
                          <GroupStatusBadge status={g.status} />
                          {g.pending > 0 && <Badge kind="warning">{g.pending} por aprobar</Badge>}
                        </span>
                      </span>
                    </Link>
                  ))}
                </div>
              )}
            </Card>
          )}
          <Card title="Grupos a los que pertenezco">
            {!data.member_of.length ? (
              <EmptyState title="Aún no pertenece a ningún grupo" icon={<Link2 size={40} aria-hidden />}>
                <p>Cuando un administrador le envíe un enlace de invitación, ábralo en este dispositivo e inicie sesión con su cuenta.</p>
              </EmptyState>
            ) : (
              <div className="tiles card-body">
                {data.member_of.map((g: any) => (
                  <Link key={g.public_id} to={g.public_id} className="tile">
                    <span className="tile-icon"><Users size={28} aria-hidden /></span>
                    <span>
                      <span className="tile-name">{g.name}</span>
                      <span className="tile-desc" style={{ display: 'block' }}>Administrador: {g.owner_name}</span>
                      <span className="row" style={{ marginTop: 8, gap: 6 }}><MemberBadge status={g.my_status} />
                        {g.status !== 'activo' && <GroupStatusBadge status={g.status} />}</span>
                    </span>
                  </Link>
                ))}
              </div>
            )}
          </Card>
        </>
      )}
      {creating && <GroupDialog onClose={() => setCreating(false)} onSaved={(g) => navigate(g.group.public_id)} />}
    </div>
  );
}

function GroupDialog({ group, onClose, onSaved }: { group?: any; onClose: () => void; onSaved: (g: any) => void }) {
  const { notify } = useToast();
  const [form, setForm] = useState({ name: group?.name ?? '', description: group?.description ?? '',
    join_policy: group?.join_policy ?? 'automatica', members_visible: group?.members_visible ?? true });
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const saved = group ? await put(`/groups/${group.public_id}`, { ...form, version: group.version }) : await post('/groups', form);
      notify('success', group ? 'Grupo actualizado' : 'Grupo creado', form.name);
      onSaved(saved);
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  const fe = error?.fields ?? {};
  return (
    <Dialog open title={group ? 'Editar grupo' : 'Nuevo grupo de trabajo'} onClose={onClose} footer={
      <><Button onClick={onClose}>Cancelar</Button><Button variant="primary" busy={busy} icon={<Save size={20} />} onClick={save}>Guardar</Button></>}>
      <ErrorAlert error={error} />
      <div className="stack">
        <TextField label="Nombre del grupo" value={form.name} onChange={(v) => setForm({ ...form, name: v })} error={fe.name} maxLength={80} required autoFocus />
        <TextArea label="Descripción" value={form.description} onChange={(v) => setForm({ ...form, description: v })} maxLength={500} />
        <SelectField label="Ingreso con el enlace" value={form.join_policy} onChange={(v) => setForm({ ...form, join_policy: v })}
          options={Object.entries(POLICY_LABEL).map(([value, label]) => ({ value, label }))} />
        <Checkbox label="Los integrantes pueden ver quiénes más están en el grupo" checked={form.members_visible}
          onChange={(v) => setForm({ ...form, members_visible: v })} />
      </div>
    </Dialog>
  );
}

// ------------------------------------------------------------------ detalle
function GroupDetail() {
  const { id = '' } = useParams();
  const detail = useApi<any>(`/groups/${id}`);
  useRealtimeEvents((e) => {
    if (e.type === 'resync' || ((e.type === 'grupo' || e.type === 'presencia') && e.group === id)) detail.reload();
  });
  if (detail.loading && !detail.data) return <Loading />;
  if (detail.error) {
    if (detail.error.status === 404) {
      return (
        <EmptyState title="Grupo no encontrado" icon={<Lock size={40} aria-hidden />}>
          <p>No existe, o usted no pertenece a él.</p>
          <Link to="/grupos" className="btn btn-outline">Volver a mis grupos</Link>
        </EmptyState>
      );
    }
    return <ErrorState error={detail.error} onRetry={detail.reload} />;
  }
  const data = detail.data;
  return data.view === 'admin' ? <AdminView data={data} reload={detail.reload} /> : <MemberView data={data} />;
}

function BackLink() {
  return <div><Link to="/grupos" className="btn btn-ghost"><ArrowLeft size={18} aria-hidden /> Grupos de trabajo</Link></div>;
}

function AdminView({ data, reload }: { data: any; reload: () => void }) {
  const { can } = useAuth();
  const { notify } = useToast();
  const g = data.group;
  const [editing, setEditing] = useState(false);
  const [inviting, setInviting] = useState(false);
  const [confirm, setConfirm] = useState<null | { title: string; message: string; label: string; run: () => Promise<unknown> }>(null);
  const [busy, setBusy] = useState(false);
  const active = g.status === 'activo';

  const act = async (run: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    try {
      await run();
      notify('success', ok);
      reload();
    } catch (err) {
      notify('danger', 'No se pudo completar', (err as Error).message);
    } finally {
      setBusy(false);
      setConfirm(null);
    }
  };
  const memberAction = (m: any, action: 'aprobar' | 'rechazar' | 'retirar') =>
    act(() => post(`/groups/${g.public_id}/members/${m.user_id}/${action}`),
      { aprobar: `${m.full_name} ya es integrante`, rechazar: 'Solicitud rechazada', retirar: `${m.full_name} fue retirado del grupo` }[action]);

  const current = data.members.filter((m: any) => ['activo', 'pendiente'].includes(m.status));
  const former = data.members.filter((m: any) => !['activo', 'pendiente'].includes(m.status));
  return (
    <div className="stack">
      <BackLink />
      <PageHeader title={g.name} description={g.description || undefined} actions={<>
        <Button icon={<Pencil size={18} />} onClick={() => setEditing(true)}>Editar</Button>
        {active
          ? <Button variant="danger" icon={<Lock size={18} />} onClick={() => setConfirm({ title: 'Cerrar grupo', label: 'Cerrar grupo',
            message: 'Se revocarán todos los enlaces vigentes y nadie más podrá unirse. Los integrantes conservan su historial. Puede reabrirlo después.',
            run: () => post(`/groups/${g.public_id}/close`) })}>Cerrar grupo</Button>
          : <Button icon={<LockOpen size={18} />} busy={busy} onClick={() => act(() => post(`/groups/${g.public_id}/reopen`), 'Grupo reabierto')}>Reabrir</Button>}
      </>} />
      <div className="metrics">
        <Metric label="Identificador" value={g.public_id} />
        <Metric label="Administrador" value={g.owner_name} />
        <Metric label="Integrantes" value={g.member_count} hint={`${data.members.filter((m: any) => m.status === 'activo' && m.connection === 'conectado').length} conectado(s) ahora`} />
        <Metric label="Estado" value={<GroupStatusBadge status={g.status} />} hint={`Creado el ${date(g.created_at)}`} />
      </div>
      <MyConnection />

      <Card title="Integrantes">
        {!current.length ? (
          <EmptyState title="Aún no hay integrantes" icon={<Users size={40} aria-hidden />}>
            <p>Genere un enlace de invitación y compártalo con sus empleados. Aparecerán aquí al unirse, sin recargar la página.</p>
          </EmptyState>
        ) : (
          <DataTable caption="Integrantes del grupo" rows={current} rowKey={(m: any) => m.user_id} columns={[
            { key: 'n', header: 'Persona', render: (m: any) => <span><strong>{m.full_name}</strong><br /><small className="muted">{m.username}{!m.account_active && ' · cuenta desactivada'}</small></span> },
            { key: 's', header: 'Participación', render: (m: any) => <MemberBadge status={m.status} /> },
            { key: 'c', header: 'Conexión', render: (m: any) => <ConnectionBadge status={m.connection} since={m.last_disconnected_at ?? m.last_connected_at} /> },
            { key: 'j', header: 'Desde', render: (m: any) => dateTime(m.joined_at ?? m.requested_at) },
            { key: 'p', header: 'Funciones autorizadas', render: (m: any) => m.role === 'admin' ? 'Todas (administrador)'
              : can('gestion.usuarios') ? <Link to="/gestion/usuarios">{m.permission_count} permiso(s)</Link> : `${m.permission_count} permiso(s)` },
            { key: 'a', header: 'Acciones', render: (m: any) => m.status === 'pendiente' ? (
              <span className="row" style={{ gap: 6 }}>
                <Button size="sm" variant="primary" icon={<Check size={16} />} disabled={busy} onClick={() => void memberAction(m, 'aprobar')}>Aprobar</Button>
                <Button size="sm" icon={<X size={16} />} disabled={busy} onClick={() => void memberAction(m, 'rechazar')}>Rechazar</Button>
              </span>
            ) : (
              <Button size="sm" variant="outline" icon={<UserMinus size={16} />} onClick={() => setConfirm({ title: 'Retirar del grupo',
                label: 'Retirar', message: `${m.full_name} dejará de pertenecer al grupo. Para volver necesitará un enlace nuevo. Su cuenta y sus permisos no cambian.`,
                run: () => post(`/groups/${g.public_id}/members/${m.user_id}/retirar`) })}>Retirar</Button>
            ) },
          ]} />
        )}
        {former.length > 0 && (
          <details className="card-body">
            <summary>Antiguos integrantes ({former.length})</summary>
            <ul>{former.map((m: any) => <li key={m.user_id}>{m.full_name} — <MemberBadge status={m.status} /> {dateTime(m.ended_at)}</li>)}</ul>
          </details>
        )}
      </Card>

      <Card title="Tareas del grupo">
        <div className="card-body"><TaskBoard kind="asignadas" group={g.public_id} /></div>
      </Card>

      <Card title="Invitaciones por enlace" actions={active &&
        <Button variant="primary" icon={<Link2 size={18} />} onClick={() => setInviting(true)}>Generar enlace</Button>}>
        <div className="card-body stack">
          <PublicUrlNotice info={data.invite_base} onSaved={reload} />
          {!active && <Alert kind="info">El grupo está cerrado: reábralo para generar enlaces.</Alert>}
          {!data.invitations.length ? <p className="muted">Todavía no ha generado enlaces.</p> : (
            <DataTable caption="Enlaces de invitación" rows={data.invitations} rowKey={(i: any) => i.id} columns={[
              { key: 'h', header: 'Enlace', render: (i: any) => <code>…/unirse/{i.hint}…</code> },
              { key: 's', header: 'Estado', render: (i: any) => <InvitationBadge status={i.status} /> },
              { key: 'u', header: 'Usado', numeric: true, render: (i: any) => `${i.uses} de ${i.max_uses}` },
              { key: 'e', header: 'Vence', render: (i: any) => dateTime(i.expires_at) },
              { key: 'c', header: 'Creado', render: (i: any) => `${dateTime(i.created_at)} · ${i.created_by_name}` },
              { key: 'a', header: 'Acciones', render: (i: any) => i.status === 'vigente' && (
                <Button size="sm" variant="outline" onClick={() => setConfirm({ title: 'Revocar enlace', label: 'Revocar',
                  message: 'Nadie más podrá unirse con este enlace. Quienes ya se unieron siguen en el grupo.',
                  run: () => post(`/groups/${g.public_id}/invitations/${i.id}/revoke`) })}>Revocar</Button>) },
            ]} />
          )}
        </div>
      </Card>

      <Card title="Actividad reciente">
        {!data.events.length ? <p className="card-body muted">Sin actividad.</p> : (
          <ul className="card-body" style={{ margin: 0, paddingLeft: 36 }}>
            {data.events.map((e: any) => <li key={e.id}><span className="muted">{dateTime(e.created_at)}</span> — {eventText(e)}</li>)}
          </ul>
        )}
      </Card>

      {editing && <GroupDialog group={g} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); reload(); }} />}
      {inviting && <InviteDialog group={g} onClose={() => { setInviting(false); reload(); }} />}
      <ConfirmDialog open={Boolean(confirm)} title={confirm?.title ?? ''} message={confirm?.message ?? ''} confirmLabel={confirm?.label ?? ''}
        danger busy={busy} onClose={() => setConfirm(null)} onConfirm={() => confirm && void act(confirm.run, `${confirm.title}: listo`)} />
    </div>
  );
}

/** Aviso si los enlaces usarían una dirección que no funciona fuera de este equipo o de la red local. */
function PublicUrlNotice({ info, onSaved }: { info: any; onSaved: () => void }) {
  const { can } = useAuth();
  const [open, setOpen] = useState(false);
  if (!info) return null;
  const local = info.reachable_from_internet === false;
  return (
    <div className="stack">
      {local ? (
        <Alert kind="warning" title="Los enlaces solo funcionarán en este equipo o en su red local">
          Ahora usan <code>{info.url}</code>. Para que los empleados se unan desde otras redes o con datos móviles, publique POS-PY
          con HTTPS (por ejemplo, con un túnel) y escriba aquí su dirección pública.
        </Alert>
      ) : (
        <p className="muted" style={{ margin: 0 }}>Los enlaces usan la dirección <code>{info.url}</code>
          {info.source === 'entorno' ? ' (definida en el servidor).' : '.'}</p>
      )}
      {info.source !== 'entorno' && can('gestion.configuracion') && (
        open ? <SettingsSection section="grupos" title="Dirección pública" onSaved={() => { setOpen(false); onSaved(); }} />
          : <div><Button size="sm" variant="outline" onClick={() => setOpen(true)}>Configurar dirección pública</Button></div>
      )}
    </div>
  );
}

const DURATIONS = [
  { value: '1', label: '1 hora' }, { value: '24', label: '24 horas' }, { value: '72', label: '3 días' },
  { value: '168', label: '7 días' }, { value: '720', label: '30 días' },
];

function InviteDialog({ group, onClose }: { group: any; onClose: () => void }) {
  const { notify } = useToast();
  const [hours, setHours] = useState('72');
  const [maxUses, setMaxUses] = useState('10');
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const canShare = typeof navigator !== 'undefined' && typeof navigator.share === 'function';

  const generate = async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(await post(`/groups/${group.public_id}/invitations`, { expires_in_hours: Number(hours), max_uses: Number(maxUses) || 0 }));
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(result.url);
      notify('success', 'Enlace copiado', 'Péguelo en WhatsApp, correo o el medio que prefiera.');
    } catch {
      notify('warning', 'No se pudo copiar automáticamente', 'Seleccione el enlace y cópielo manualmente.');
    }
  };
  const share = async () => {
    try {
      await navigator.share({ title: `Invitación a ${group.name}`, text: `Únase al grupo de trabajo «${group.name}»:`, url: result.url });
    } catch { /* el usuario canceló */ }
  };

  return (
    <Dialog open title={result ? 'Enlace listo para compartir' : 'Generar enlace de invitación'} onClose={onClose} footer={result
      ? <Button variant="primary" onClick={onClose}>Listo</Button>
      : <><Button onClick={onClose}>Cancelar</Button><Button variant="primary" busy={busy} icon={<Link2 size={18} />} onClick={generate}>Generar</Button></>}>
      <ErrorAlert error={error} />
      {!result ? (
        <div className="stack">
          <p className="muted" style={{ margin: 0 }}>Cualquier persona con cuenta en POS-PY que abra el enlace podrá pedir unirse a «{group.name}».
            El enlace no da acceso por sí solo: cada persona debe iniciar sesión con su usuario.</p>
          <SelectField label="Vigencia" value={hours} onChange={setHours} options={DURATIONS} />
          <NumberField label="Número máximo de personas" value={maxUses} onChange={setMaxUses} error={error?.fields?.max_uses}
            hint="Entre 1 y 500. Cuando se alcanza, el enlace deja de funcionar." />
        </div>
      ) : (
        <div className="stack">
          <TextField label="Enlace de invitación" value={result.url} readOnly onChange={() => undefined}
            onFocus={(e) => e.currentTarget.select()} />
          <div className="row">
            <Button variant="primary" icon={<Copy size={18} />} onClick={copy}>Copiar enlace</Button>
            {canShare && <Button icon={<Share2 size={18} />} onClick={share}>Compartir…</Button>}
          </div>
          <p className="muted" style={{ margin: 0 }}>Vence el {dateTime(result.invitation.expires_at)} · hasta {result.invitation.max_uses} persona(s).</p>
          <Alert kind="info" title="Guárdelo ahora">Por seguridad el enlace solo se muestra esta vez. Si lo pierde, genere uno nuevo
            (y revoque el anterior si cree que alguien más lo tiene).</Alert>
          {result.invite_base?.reachable_from_internet === false && (
            <Alert kind="warning">Este enlace usa una dirección local y no funcionará desde otras redes.</Alert>
          )}
        </div>
      )}
    </Dialog>
  );
}

// ------------------------------------------------------------------ vista del empleado
function MemberView({ data }: { data: any }) {
  const { user } = useAuth();
  const { notify } = useToast();
  const navigate = useNavigate();
  const catalog = useApi<any[]>('/permissions/catalog');
  const myConnection = useRealtimeStatus();
  const [leaving, setLeaving] = useState(false);
  const [busy, setBusy] = useState(false);
  const g = data.group;
  const labels = new Map((catalog.data ?? []).map((p) => [p.code, p.label]));
  const leave = async () => {
    setBusy(true);
    try {
      await post(`/groups/${g.public_id}/leave`);
      notify('success', 'Salió del grupo', g.name);
      navigate('/grupos', { replace: true });
    } catch (err) {
      notify('danger', 'No se pudo salir del grupo', (err as Error).message);
      setBusy(false);
      setLeaving(false);
    }
  };
  return (
    <div className="stack">
      <BackLink />
      <PageHeader title={g.name} description={g.description || undefined}
        actions={<Button variant="outline" icon={<DoorOpen size={18} />} onClick={() => setLeaving(true)}>Salir del grupo</Button>} />
      {data.me.status === 'pendiente' && <Alert kind="warning" title="Solicitud pendiente">El administrador debe aprobar su ingreso. Esta página se actualizará sola.</Alert>}
      {g.status !== 'activo' && <Alert kind="info">El administrador cerró este grupo.</Alert>}
      <Card title="Mi participación">
        <dl className="dl card-body">
          <dt>Administrador</dt><dd>{g.owner_name}</dd>
          <dt>Identificador</dt><dd>{g.public_id}</dd>
          <dt>Estado del grupo</dt><dd><GroupStatusBadge status={g.status} /></dd>
          <dt>Mi participación</dt><dd><MemberBadge status={data.me.status} /></dd>
          <dt>Mi conexión</dt><dd><ConnectionBadge status={myConnection} /></dd>
          <dt>Desde</dt><dd>{dateTime(data.me.joined_at ?? data.me.requested_at)}</dd>
        </dl>
      </Card>
      {data.me.status === 'activo' && (
        <Card title={`Integrantes (${g.member_count})`}>
          {!data.members_visible ? <p className="card-body muted">El administrador no comparte la lista de integrantes.</p> : (
            <ul className="card-body" style={{ margin: 0, paddingLeft: 36 }}>
              {data.members.map((m: any) => <li key={m.full_name + m.joined_at}>{m.full_name}{m.full_name === user?.full_name ? ' (usted)' : ''}</li>)}
            </ul>
          )}
        </Card>
      )}
      {data.me.status === 'activo' && (
        <Card title="Mis tareas en este grupo">
          <div className="card-body"><TaskBoard kind="asignadas" group={g.public_id} /></div>
        </Card>
      )}
      <Card title="Funciones autorizadas">
        <div className="card-body">
          {user?.role === 'admin' ? <p>Tiene todas las funciones (administrador).</p> : !data.permissions.length ? <p className="muted">Sin funciones asignadas.</p> : (
            <ul style={{ margin: 0 }}>{data.permissions.map((p: string) => <li key={p}>{labels.get(p) ?? p}</li>)}</ul>
          )}
          <p className="muted">Las asigna el administrador en Gestión › Usuarios. Si cambian, esta página se actualiza sola.</p>
        </div>
      </Card>
      <ConfirmDialog open={leaving} title="Salir del grupo" danger busy={busy} confirmLabel="Salir"
        message={`Dejará de pertenecer a «${g.name}». Para volver necesitará un enlace de invitación.`}
        onClose={() => setLeaving(false)} onConfirm={() => void leave()} />
    </div>
  );
}

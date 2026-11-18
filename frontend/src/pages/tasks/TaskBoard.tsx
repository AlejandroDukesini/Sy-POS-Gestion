import { Check, Eye, MessageSquare, Pencil, Play, Plus, Save, Send, Trash2, Users } from 'lucide-react';
import { useState } from 'react';
import { ApiError, del, post, put } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { ConfirmDialog, Dialog } from '../../components/ui/Dialog';
import { Alert, Badge, EmptyState, ErrorAlert, ErrorState, Loading } from '../../components/ui/Feedback';
import { Checkbox, SelectField, TextArea, TextField } from '../../components/ui/Form';
import { Metric, Tabs } from '../../components/ui/Layout';
import { useToast } from '../../context/Toast';
import { useAuth } from '../../context/Auth';
import { date, dateTime, today } from '../../lib/format';
import { useApi } from '../../lib/hooks';
import { useRealtimeEvents } from '../../lib/realtime';

export const TASK_STATUS: Record<string, string> = {
  pendiente: 'Pendiente', en_curso: 'En progreso', en_revision: 'En revisión', completada: 'Completada', cancelada: 'Cancelada',
};
const STATUS_KIND: Record<string, 'info' | 'success' | 'warning' | 'danger' | undefined> = {
  pendiente: 'warning', en_curso: 'info', en_revision: undefined, completada: 'success', cancelada: 'danger',
};
export const PRIORITY: Record<string, string> = { baja: 'Baja', media: 'Media', alta: 'Alta', urgente: 'Urgente' };
const PRIORITY_KIND: Record<string, 'info' | 'warning' | 'danger' | undefined> = {
  baja: undefined, media: 'info', alta: 'warning', urgente: 'danger',
};
const MINE = ['pendiente', 'en_curso', 'completada'];
const opts = (map: Record<string, string>, keys = Object.keys(map)) => keys.map((value) => ({ value, label: map[value] }));

export function StatusBadge({ status }: { status: string }) {
  return <Badge kind={STATUS_KIND[status]}>{TASK_STATUS[status] ?? status}</Badge>;
}
export function PriorityBadge({ priority }: { priority: string }) {
  return <Badge kind={PRIORITY_KIND[priority]}>Prioridad {PRIORITY[priority]?.toLowerCase() ?? priority}</Badge>;
}

/**
 * Tablero de tareas. Lo usan «Notas y tareas» (personales y asignadas) y la página de cada grupo
 * (group = id público del grupo: solo las tareas de ese grupo). El servidor decide qué ve cada persona.
 */
export function TaskBoard({ kind, group }: { kind: 'personal' | 'asignadas'; group?: string }) {
  const { can } = useAuth();
  const { notify } = useToast();
  const personal = kind === 'personal';
  const manager = !personal && can('tareas.gestionar');
  const employee = !personal && !manager;
  const [filter, setFilter] = useState(employee ? 'todas' : 'abiertas');
  const [priority, setPriority] = useState('');
  const [assignee, setAssignee] = useState('');
  const [groupFilter, setGroupFilter] = useState('');
  const [dueFrom, setDueFrom] = useState('');
  const [dueTo, setDueTo] = useState('');
  const [editing, setEditing] = useState<any>(null);
  const [viewing, setViewing] = useState<number | null>(null);
  const [deleting, setDeleting] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  const params = new URLSearchParams();
  if (personal) params.set('scope', 'personales');
  if (employee) { if (filter !== 'todas') params.set('my_status', filter); } else if (filter !== 'todas') params.set('status', filter);
  if (priority) params.set('priority', priority);
  if (group || groupFilter) params.set('group', group || groupFilter);
  if (manager && assignee) params.set('assignee_id', assignee);
  if (dueFrom) params.set('due_from', dueFrom);
  if (dueTo) params.set('due_to', dueTo);
  const tasks = useApi<any[]>(`/tasks?${params}`);
  const all = useApi<any[]>(manager ? `/tasks${group ? `?group=${group}` : ''}` : null);   // seguimiento: totales sin filtros
  const people = useApi<any[]>(manager ? '/tasks/assignees' : null);
  const groups = useApi<any[]>(manager ? '/tasks/groups' : null);
  useRealtimeEvents((e) => {
    if (e.type === 'tarea' || e.type === 'resync' || e.type === 'grupo') { tasks.reload(); all.reload(); groups.reload(); }
  });
  const reload = () => { tasks.reload(); all.reload(); };

  const setStatus = async (t: any, status: string) => {
    try {
      if (personal) await put(`/tasks/${t.id}`, { status, version: t.version });
      else await put(`/tasks/${t.id}/mine`, { status });
      notify('success', status === 'completada' ? 'Tarea completada' : 'Estado actualizado', `${t.title}: ${TASK_STATUS[status]}`);
    } catch (err) {
      notify('danger', 'No se pudo actualizar', (err as Error).message);
    }
    reload();
  };
  const remove = async () => {
    setBusy(true);
    try {
      await del(`/tasks/${deleting.id}`);
      notify('success', 'Tarea eliminada', deleting.title);
      setDeleting(null);
      reload();
    } catch (err) {
      notify('danger', 'No se pudo eliminar', (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const tabs = employee
    ? [{ value: 'todas', label: 'Todas' }, { value: 'pendiente', label: 'Pendientes' }, { value: 'en_curso', label: 'En progreso' },
      { value: 'completada', label: 'Completadas' }]
    : manager
      ? [{ value: 'abiertas', label: 'Abiertas' }, { value: 'en_curso', label: 'En progreso' }, { value: 'en_revision', label: 'En revisión' },
        { value: 'completada', label: 'Completadas' }, { value: 'cancelada', label: 'Canceladas' }, { value: 'todas', label: 'Todas' }]
      : [{ value: 'abiertas', label: 'Pendientes' }, { value: 'completada', label: 'Completadas' }, { value: 'todas', label: 'Todas' }];
  const filtered = Boolean(priority || assignee || groupFilter || dueFrom || dueTo);
  const empty = filtered ? 'Ninguna tarea coincide con los filtros.'
    : personal ? (filter === 'todas' ? 'Todavía no tiene tareas. Cree una para organizar su trabajo.' : filter === 'completada'
      ? 'No hay tareas completadas.' : 'No tiene tareas pendientes.')
      : manager ? (group ? 'Este grupo no tiene tareas en esta vista.' : 'No hay tareas asignadas en esta vista.')
        : 'No tiene tareas en esta vista.';
  const stats = all.data && summarize(all.data);

  return (
    <div className="stack">
      {manager && stats && (
        <div className="metrics" aria-label="Seguimiento de tareas">
          <Metric label="Abiertas" value={stats.open} hint={`${stats.pending} pendientes · ${stats.progress} en progreso`} />
          <Metric label="En revisión" value={stats.review} />
          <Metric label="Completadas" value={stats.done} />
          <Metric label="Vencidas" value={stats.overdue} hint={stats.overdue ? 'Con fecha límite pasada' : 'Ninguna'} />
        </div>
      )}
      <div className="row-between" style={{ flexWrap: 'wrap', gap: 12 }}>
        <div style={{ minWidth: 0, maxWidth: '100%' }}>
          <Tabs label="Mostrar" value={filter} onChange={setFilter} tabs={tabs} />
        </div>
        {(personal || manager) && (
          <Button variant="primary" icon={<Plus size={20} />} onClick={() => setEditing({})}>{personal ? 'Nueva tarea' : 'Asignar tarea'}</Button>)}
      </div>
      {!personal && (
        <div className="filters">
          <SelectField label="Prioridad" value={priority} onChange={setPriority} placeholder="Todas" options={opts(PRIORITY)} />
          {manager && <SelectField label="Responsable" value={assignee} onChange={setAssignee} placeholder="Todos"
            options={(people.data ?? []).map((p) => ({ value: String(p.id), label: p.full_name }))} />}
          {manager && !group && <SelectField label="Grupo" value={groupFilter} onChange={setGroupFilter} placeholder="Todos"
            options={(groups.data ?? []).map((g) => ({ value: g.public_id, label: g.name }))} />}
          <TextField label="Fecha límite desde" type="date" value={dueFrom} onChange={setDueFrom} />
          <TextField label="Fecha límite hasta" type="date" value={dueTo} onChange={setDueTo} />
        </div>
      )}
      {employee && <p className="muted" style={{ margin: 0 }}>
        Las asigna el administrador. Usted marca su avance, comenta o pide cambios; no puede editarlas ni eliminarlas.</p>}
      {tasks.loading && !tasks.data ? <Loading /> : tasks.error ? <ErrorState error={tasks.error} onRetry={tasks.reload} /> : (
        !tasks.data?.length ? (
          <EmptyState title={empty}>
            {(personal || manager) && !filtered && filter !== 'completada' && filter !== 'cancelada' && (
              <Button icon={<Plus size={20} />} onClick={() => setEditing({})}>{manager ? 'Asignar una tarea' : 'Nueva tarea'}</Button>)}
          </EmptyState>
        ) : (
          <div className="cards">
            {tasks.data.map((t) => (
              <TaskCard key={t.id} task={t} showGroup={!group} onStatus={(s) => void setStatus(t, s)}
                onView={() => setViewing(t.id)} onEdit={() => setEditing(t)} onDelete={() => setDeleting(t)} />
            ))}
          </div>
        )
      )}
      {editing && <TaskDialog task={editing} personal={personal} fixedGroup={group} groups={groups.data ?? []} people={people.data ?? []}
        onClose={() => setEditing(null)} onSaved={() => { setEditing(null); reload(); }} />}
      {viewing && <TaskDetail id={viewing} onClose={() => setViewing(null)} onChanged={reload}
        onEdit={(t) => { setViewing(null); setEditing(t); }} />}
      <ConfirmDialog open={Boolean(deleting)} title="Eliminar tarea" danger busy={busy} confirmLabel="Eliminar"
        message={deleting && <>¿Eliminar la tarea «{deleting.title}»?{!personal && ' Los responsables dejarán de verla.'} No se puede deshacer.</>}
        onConfirm={() => void remove()} onClose={() => setDeleting(null)} />
    </div>
  );
}

function summarize(list: any[]) {
  const by = (s: string) => list.filter((t) => t.status === s).length;
  const now = today();
  return {
    pending: by('pendiente'), progress: by('en_curso'), review: by('en_revision'), done: by('completada'),
    open: by('pendiente') + by('en_curso') + by('en_revision'),
    overdue: list.filter((t) => t.due_date && t.due_date < now && !['completada', 'cancelada'].includes(t.status)).length,
  };
}

function TaskCard({ task: t, showGroup, onStatus, onView, onEdit, onDelete }: {
  task: any; showGroup: boolean; onStatus: (s: string) => void; onView: () => void; onEdit: () => void; onDelete: () => void;
}) {
  const closed = ['completada', 'cancelada'].includes(t.status);
  const overdue = Boolean(t.due_date) && !closed && t.due_date < today();
  const assignee = !t.personal && t.my_status !== null && !t.can_manage;
  const mine = t.personal ? t.status : t.my_status;
  const done = t.personal ? t.status === 'completada' : assignee ? t.my_status === 'completada' : t.status === 'completada';
  const frozen = t.status === 'cancelada';
  return (
    <article className={`item-card${done ? ' done' : ''}`} aria-label={t.title}>
      <div className="row-between" style={{ alignItems: 'flex-start', gap: 8 }}>
        <h3 className="item-card-title">{t.title}</h3>
        <StatusBadge status={t.status} />
      </div>
      {t.description && <p className="item-card-text">{t.description}</p>}
      <div className="item-card-meta">
        <PriorityBadge priority={t.priority} />
        {t.due_date && <span className={overdue ? 'overdue' : undefined}>Fecha límite: {date(t.due_date)}{overdue && ' (vencida)'}</span>}
        {showGroup && t.group_name && <span>Grupo: <strong>{t.group_name}</strong></span>}
        {!t.personal && !t.can_manage && t.created_by_name && <span>Asignada por: {t.created_by_name}</span>}
      </div>
      {!t.personal && (
        t.can_manage ? (
          <ul className="assignees" aria-label="Responsables">
            {t.assignees.map((a: any) => (
              <li key={a.user_id}>
                <span>{a.full_name}{!a.in_group && <small className="muted"> (ya no está en el grupo)</small>}</span>
                <Badge kind={STATUS_KIND[a.status]}>{TASK_STATUS[a.status]}</Badge>
              </li>
            ))}
          </ul>
        ) : t.progress.total > 1 && (
          <span className="muted" style={{ fontSize: '0.875rem' }}><Users size={14} aria-hidden /> Equipo: {t.progress.done} de {t.progress.total} terminaron</span>
        )
      )}
      {t.can_manage && !t.personal && t.progress.total > 1 && (
        <span className="muted" style={{ fontSize: '0.875rem' }}>Avance: {t.progress.done} de {t.progress.total} completaron</span>)}
      {(t.personal || assignee) && (
        <SelectField label={t.personal ? 'Estado' : 'Mi estado'} value={mine} onChange={onStatus} disabled={frozen} options={opts(TASK_STATUS, MINE)} />)}
      <div className="item-card-actions">
        {(t.personal || assignee) && !frozen && mine === 'pendiente' && !t.personal && (
          <Button size="sm" icon={<Play size={18} />} onClick={() => onStatus('en_curso')}>Iniciar</Button>)}
        {(t.personal || assignee) && !frozen && mine !== 'completada' && (
          <Button size="sm" variant="primary" icon={<Check size={18} />} onClick={() => onStatus('completada')}>Marcar como completada</Button>)}
        {!t.personal && <Button size="sm" icon={<Eye size={18} />} onClick={onView}>Detalle</Button>}
        {t.can_manage && <Button size="sm" icon={<Pencil size={18} />} onClick={onEdit}>Editar</Button>}
        {t.can_manage && <Button size="sm" icon={<Trash2 size={18} />} onClick={onDelete}>Eliminar</Button>}
      </div>
    </article>
  );
}

function TaskDialog({ task, personal, fixedGroup, groups, people, onClose, onSaved }: {
  task: any; personal: boolean; fixedGroup?: string; groups: any[]; people: any[]; onClose: () => void; onSaved: () => void;
}) {
  const { notify } = useToast();
  const isNew = !task.id;
  const [form, setForm] = useState({
    title: task.title ?? '', description: task.description ?? '', notes: task.notes ?? '', priority: task.priority ?? 'media',
    due_date: task.due_date ?? '', status: task.status ?? 'pendiente',
    group: task.id ? (task.group_public_id ?? '') : (fixedGroup ?? (groups.length ? groups[0].public_id : '')),
    assignees: new Set<number>((task.assignees ?? []).map((a: any) => a.user_id)),
  });
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (key: string) => (v: string) => setForm((f) => ({ ...f, [key]: v }));
  const chosenGroup = groups.find((g) => g.public_id === form.group);
  // Integrantes del grupo elegido; sin grupo, cualquier persona activa. Se conservan los responsables actuales.
  const base: { id: number; full_name: string; note?: string }[] = form.group
    ? (chosenGroup?.members ?? []) : people.map((p) => ({ id: p.id, full_name: p.full_name }));
  const current = (task.assignees ?? []).filter((a: any) => !base.some((m) => m.id === a.user_id))
    .map((a: any) => ({ id: a.user_id, full_name: a.full_name, note: a.in_group === 0 ? 'ya no está en el grupo' : 'responsable actual' }));
  const candidates = [...base, ...current];
  const toggle = (id: number, on: boolean) => setForm((f) => {
    const next = new Set(f.assignees);
    if (on) next.add(id); else next.delete(id);
    return { ...f, assignees: next };
  });

  const save = async () => {
    setBusy(true);
    setError(null);
    const body: Record<string, unknown> = { title: form.title, description: form.description, priority: form.priority,
      due_date: form.due_date || null };
    if (!personal) {
      body.notes = form.notes;
      body.assignee_ids = [...form.assignees];
      if (isNew && form.group) body.group = form.group;
    }
    if (!isNew) { body.status = form.status; body.version = task.version; }
    try {
      if (isNew) await post('/tasks', personal ? { ...body, personal: true } : body);
      else await put(`/tasks/${task.id}`, body);
      notify('success', isNew ? (personal ? 'Tarea creada' : 'Tarea asignada') : 'Tarea actualizada',
        !personal && isNew ? `${form.title} · ${form.assignees.size} responsable(s)` : form.title);
      onSaved();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  const fe = error?.fields ?? {};
  const statuses = personal ? MINE : Object.keys(TASK_STATUS);
  return (
    <Dialog open size="wide" title={isNew ? (personal ? 'Nueva tarea' : 'Asignar tarea') : 'Editar tarea'} onClose={onClose} footer={
      <><Button onClick={onClose}>Cancelar</Button><Button variant="primary" busy={busy} icon={<Save size={20} />} onClick={save}>
        {isNew && !personal ? 'Asignar' : 'Guardar'}</Button></>}>
      <ErrorAlert error={error} />
      <div className="stack">
        <TextField label="Tarea" value={form.title} onChange={set('title')} error={fe.title} maxLength={200} required autoFocus />
        <TextArea label="Descripción (opcional)" value={form.description} onChange={set('description')} maxLength={2000} rows={3} />
        <div className="form-grid">
          <SelectField label="Prioridad" value={form.priority} onChange={set('priority')} error={fe.priority} options={opts(PRIORITY)} />
          <TextField label="Fecha límite (opcional)" type="date" value={form.due_date} onChange={set('due_date')} error={fe.due_date} />
          {!isNew && <SelectField label={personal ? 'Estado' : 'Estado general'} value={form.status} onChange={set('status')}
            options={opts(TASK_STATUS, statuses)} hint={!personal ? 'Se recalcula con el avance de los responsables; puede marcarla En revisión, Completada o Cancelada.' : undefined} />}
        </div>
        {!personal && <>
          <TextArea label="Observaciones (opcional)" value={form.notes} onChange={set('notes')} maxLength={2000} rows={2} />
          {isNew && !fixedGroup ? (
            <SelectField label="Grupo de trabajo" value={form.group} onChange={(v) => setForm((f) => ({ ...f, group: v, assignees: new Set() }))}
              placeholder="Sin grupo (cualquier persona activa)" options={groups.map((g) => ({ value: g.public_id, label: g.name }))}
              hint={groups.length ? 'Solo se puede asignar a integrantes activos del grupo.' : 'No tiene grupos activos: la tarea queda sin grupo.'} />
          ) : (task.group_name || chosenGroup) && <p style={{ margin: 0 }}>Grupo: <strong>{task.group_name ?? chosenGroup?.name}</strong></p>}
          <fieldset>
            <legend>Responsables <span className="req" aria-hidden>*</span></legend>
            {!candidates.length ? <p className="muted">{form.group ? 'El grupo todavía no tiene integrantes activos. Invítelos desde Grupos de trabajo.' : 'No hay personas activas.'}</p> : (
              <div className="check-grid">
                {candidates.map((m) => (
                  <Checkbox key={m.id} label={m.full_name} hint={m.note} checked={form.assignees.has(m.id)} onChange={(on) => toggle(m.id, on)} />
                ))}
              </div>
            )}
            {fe.assignee_ids && <span className="field-error">{fe.assignee_ids}</span>}
          </fieldset>
        </>}
      </div>
    </Dialog>
  );
}

const EVENT_TEXT: Record<string, (e: any) => string> = {
  creada: (e) => `creó la tarea${e.details?.responsables?.length ? ` para ${e.details.responsables.join(', ')}` : ''}`,
  edicion: (e) => `editó: ${Object.keys(e.details ?? {}).map((k) => ({ title: 'título', description: 'descripción', notes: 'observaciones',
    priority: 'prioridad', due_date: 'fecha límite' } as Record<string, string>)[k] ?? k).join(', ')}`,
  responsables: (e) => [e.details?.agregados?.length && `agregó a ${e.details.agregados.join(', ')}`,
    e.details?.retirados?.length && `retiró a ${e.details.retirados.join(', ')}`].filter(Boolean).join(' y '),
  estado: (e) => `${e.details?.automatico ? 'Estado general' : 'cambió el estado'}: ${TASK_STATUS[e.details?.antes] ?? ''} → ${TASK_STATUS[e.details?.despues] ?? ''}`,
  avance: (e) => `marcó su parte como ${TASK_STATUS[e.details?.despues]?.toLowerCase() ?? ''}`,
  comentario: () => 'comentó',
  solicitud: () => 'pidió un cambio',
};

function TaskDetail({ id, onClose, onChanged, onEdit }: { id: number; onClose: () => void; onChanged: () => void; onEdit: (t: any) => void }) {
  const { notify } = useToast();
  const detail = useApi<any>(`/tasks/${id}`);
  const [comment, setComment] = useState('');
  const [request, setRequest] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<string | null>(null);
  useRealtimeEvents((e) => { if ((e.type === 'tarea' && e.task === id) || e.type === 'resync') detail.reload(); });
  const t = detail.data;

  const run = async (action: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    try {
      await action();
      notify('success', ok, t?.title);
      detail.reload();
      onChanged();
    } catch (err) {
      notify('danger', 'No se pudo completar', (err as Error).message);
    } finally {
      setBusy(false);
      setConfirm(null);
    }
  };
  const send = () => run(async () => {
    await post(`/tasks/${id}/comments`, { comment, request_change: request });
    setComment('');
    setRequest(false);
  }, request ? 'Solicitud enviada' : 'Comentario agregado');
  const assignee = t && t.my_status !== null && !t.can_manage;

  return (
    <Dialog open size="wide" title={t?.title ?? 'Tarea'} onClose={onClose} footer={<Button onClick={onClose}>Cerrar</Button>}>
      {detail.loading && !t ? <Loading /> : detail.error ? <ErrorState error={detail.error} onRetry={detail.reload} /> : t && (
        <div className="stack">
          <div className="row" style={{ gap: 8 }}><StatusBadge status={t.status} /><PriorityBadge priority={t.priority} /></div>
          {t.description && <p style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{t.description}</p>}
          <dl className="dl">
            {t.group_name && <><dt>Grupo</dt><dd>{t.group_name}</dd></>}
            <dt>Fecha límite</dt><dd>{t.due_date ? date(t.due_date) : 'Sin fecha'}</dd>
            <dt>Creada</dt><dd>{dateTime(t.created_at)}{t.created_by_name ? ` · ${t.created_by_name}` : ''}</dd>
            {t.notes && <><dt>Observaciones</dt><dd style={{ whiteSpace: 'pre-wrap' }}>{t.notes}</dd></>}
            <dt>Avance</dt><dd>{t.progress.done} de {t.progress.total} responsable(s) completaron</dd>
          </dl>
          <div className="table-wrap">
            <table className="table">
              <caption className="sr-only">Responsables y su estado</caption>
              <thead><tr><th scope="col">Responsable</th><th scope="col">Estado</th><th scope="col">Inició</th><th scope="col">Terminó</th></tr></thead>
              <tbody>
                {t.assignees.map((a: any) => (
                  <tr key={a.user_id}>
                    <td>{a.full_name}{!a.in_group && <small className="muted"> (ya no está en el grupo)</small>}</td>
                    <td><Badge kind={STATUS_KIND[a.status]}>{TASK_STATUS[a.status]}</Badge></td>
                    <td>{a.started_at ? dateTime(a.started_at) : '—'}</td>
                    <td>{a.completed_at ? dateTime(a.completed_at) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {t.status === 'cancelada' && <Alert kind="info">La tarea fue cancelada: ya no admite avances.</Alert>}
          {assignee && t.status !== 'cancelada' && (
            <div className="row">
              {t.my_status === 'pendiente' && <Button icon={<Play size={18} />} busy={busy}
                onClick={() => run(() => put(`/tasks/${id}/mine`, { status: 'en_curso' }), 'Tarea iniciada')}>Iniciar</Button>}
              {t.my_status !== 'completada' && <Button variant="primary" icon={<Check size={18} />} busy={busy}
                onClick={() => run(() => put(`/tasks/${id}/mine`, { status: 'completada' }), 'Tarea completada')}>Marcar como completada</Button>}
              {t.my_status === 'completada' && <Button busy={busy}
                onClick={() => run(() => put(`/tasks/${id}/mine`, { status: 'en_curso' }), 'Tarea reabierta')}>Volver a «En progreso»</Button>}
            </div>
          )}
          {t.can_manage && (
            <div className="row">
              <Button icon={<Pencil size={18} />} onClick={() => onEdit(t)}>Editar o reasignar</Button>
              {!['en_revision', 'completada', 'cancelada'].includes(t.status) && <Button busy={busy}
                onClick={() => run(() => put(`/tasks/${id}`, { status: 'en_revision', version: t.version }), 'Tarea en revisión')}>Marcar en revisión</Button>}
              {t.status !== 'completada' && t.status !== 'cancelada' && <Button busy={busy} icon={<Check size={18} />}
                onClick={() => setConfirm('completada')}>Dar por completada</Button>}
              {t.status !== 'cancelada' ? <Button variant="danger" busy={busy} onClick={() => setConfirm('cancelada')}>Cancelar tarea</Button>
                : <Button busy={busy} onClick={() => run(() => put(`/tasks/${id}`, { status: 'pendiente', version: t.version }), 'Tarea reabierta')}>Reabrir</Button>}
            </div>
          )}
          <section aria-label="Comentarios e historial" className="stack">
            <h3 className="row" style={{ margin: 0 }}><MessageSquare size={20} aria-hidden /> Comentarios e historial</h3>
            <TextArea label={assignee ? 'Comentario o novedad' : 'Comentario'} value={comment} onChange={setComment} maxLength={1000} rows={2} />
            <div className="row-between" style={{ flexWrap: 'wrap', gap: 8 }}>
              {assignee ? <Checkbox label="Es una solicitud de cambio (fecha, prioridad, responsables…)" checked={request} onChange={setRequest} /> : <span />}
              <Button icon={<Send size={18} />} busy={busy} disabled={!comment.trim()} onClick={() => void send()}>Enviar</Button>
            </div>
            <ul className="history">
              {t.events.map((e: any) => (
                <li key={e.id} className={e.kind === 'solicitud' ? 'history-request' : undefined}>
                  <div><strong>{e.user_name ?? 'Sistema'}</strong> {EVENT_TEXT[e.kind]?.(e) ?? e.kind}
                    {e.kind === 'solicitud' && <> <Badge kind="warning">Solicitud de cambio</Badge></>}</div>
                  {e.comment && <p style={{ margin: '4px 0 0', whiteSpace: 'pre-wrap' }}>{e.comment}</p>}
                  <small className="muted">{dateTime(e.created_at)}</small>
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
      <ConfirmDialog open={Boolean(confirm)} title={confirm === 'cancelada' ? 'Cancelar tarea' : 'Dar por completada'}
        danger={confirm === 'cancelada'} busy={busy} confirmLabel={confirm === 'cancelada' ? 'Cancelar tarea' : 'Completar'}
        message={confirm === 'cancelada' ? 'Los responsables ya no podrán registrar avances. La tarea y su historial se conservan; puede reabrirla.'
          : 'La tarea quedará completada aunque algún responsable no haya marcado su parte.'}
        onClose={() => setConfirm(null)} onConfirm={() => void run(() => put(`/tasks/${id}`, { status: confirm, version: t.version }),
          confirm === 'cancelada' ? 'Tarea cancelada' : 'Tarea completada')} />
    </Dialog>
  );
}

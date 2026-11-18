import { Check, Pencil, Plus, Save, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { ApiError, del, post, put } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { ConfirmDialog, Dialog } from '../../components/ui/Dialog';
import { Badge, EmptyState, ErrorAlert, ErrorState, Loading } from '../../components/ui/Feedback';
import { SelectField, TextArea, TextField } from '../../components/ui/Form';
import { LinkTabs, PageHeader, Tabs } from '../../components/ui/Layout';
import { useAuth } from '../../context/Auth';
import { useToast } from '../../context/Toast';
import { date, today } from '../../lib/format';
import { useApi } from '../../lib/hooks';
import { useRealtimeEvents } from '../../lib/realtime';
import NotesTab from './NotesTab';

export const TASK_STATUS: Record<string, string> = {
  pendiente: 'Pendiente', en_curso: 'En progreso', completada: 'Completada', cancelada: 'Cancelada',
};
const STATUS_KIND: Record<string, 'info' | 'success' | 'warning' | undefined> = {
  pendiente: 'warning', en_curso: 'info', completada: 'success', cancelada: undefined,
};
const CHOICES = ['pendiente', 'en_curso', 'completada'];

/** Notas y tareas: notas personales, tareas personales y tareas asignadas por un administrador. */
export default function TasksPage() {
  const { can } = useAuth();
  const manager = can('tareas.gestionar');
  return (
    <div className="stack">
      <PageHeader title="Notas y tareas" description={manager
        ? 'Sus notas y tareas personales, y las tareas que asigna a los empleados.'
        : 'Sus notas, sus tareas personales y las tareas que le asignaron.'} />
      <LinkTabs label="Apartados" tabs={[
        { to: '/tareas/notas', label: 'Mis notas' },
        { to: '/tareas/mias', label: 'Mis tareas' },
        { to: '/tareas/asignadas', label: 'Tareas asignadas' },
      ]} />
      <Routes>
        <Route index element={<Navigate to="asignadas" replace />} />
        <Route path="notas" element={<NotesTab />} />
        <Route path="mias" element={<TaskBoard kind="personal" />} />
        <Route path="asignadas" element={<TaskBoard kind="asignadas" />} />
        <Route path="*" element={<Navigate to="/tareas" replace />} />
      </Routes>
    </div>
  );
}

type Filter = 'abiertas' | 'completada' | 'todas';

function TaskBoard({ kind }: { kind: 'personal' | 'asignadas' }) {
  const { can, user } = useAuth();
  const { notify } = useToast();
  const personal = kind === 'personal';
  const manager = !personal && can('tareas.gestionar');
  const [filter, setFilter] = useState<Filter>('abiertas');
  const [assignee, setAssignee] = useState('');
  const [editing, setEditing] = useState<any>(null);
  const [deleting, setDeleting] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const params = new URLSearchParams();
  if (personal) params.set('scope', 'personales');
  if (filter !== 'todas') params.set('status', filter);
  if (manager && assignee) params.set('assignee_id', assignee);
  const tasks = useApi<any[]>(`/tasks?${params}`);
  const people = useApi<any[]>(manager ? '/tasks/assignees' : null);
  useRealtimeEvents((e) => { if (e.type === 'tarea' || e.type === 'resync') tasks.reload(); });

  const setStatus = async (t: any, status: string) => {
    try {
      await put(`/tasks/${t.id}`, { status, version: t.version });
      notify('success', status === 'completada' ? 'Tarea completada' : 'Estado actualizado', `${t.title}: ${TASK_STATUS[status]}`);
      tasks.reload();
    } catch (err) {
      notify('danger', 'No se pudo actualizar', (err as Error).message);
      tasks.reload();
    }
  };
  const remove = async () => {
    setBusy(true);
    try {
      await del(`/tasks/${deleting.id}`);
      notify('success', 'Tarea eliminada', deleting.title);
      setDeleting(null);
      tasks.reload();
    } catch (err) {
      notify('danger', 'No se pudo eliminar', (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const canCreate = personal || manager;
  const empty = filter === 'completada' ? 'No hay tareas completadas.'
    : filter === 'abiertas' && personal ? 'No tiene tareas pendientes.'
      : personal ? 'Todavía no tiene tareas. Cree una para organizar su trabajo.'
        : manager ? 'No hay tareas asignadas para mostrar.' : 'No tiene tareas asignadas.';

  return (
    <div className="stack">
      <div className="row-between" style={{ flexWrap: 'wrap', gap: 12 }}>
        <div className="row" style={{ gap: 12, flexWrap: 'wrap', alignItems: 'flex-end', minWidth: 0, maxWidth: '100%' }}>
          <div style={{ minWidth: 0, maxWidth: '100%' }}>
            <Tabs label="Mostrar" value={filter} onChange={setFilter} tabs={[
              { value: 'abiertas', label: 'Pendientes' }, { value: 'completada', label: 'Completadas' }, { value: 'todas', label: 'Todas' }]} />
          </div>
          {manager && <SelectField label="Responsable" value={assignee} onChange={setAssignee} placeholder="Todos"
            options={(people.data ?? []).map((p) => ({ value: String(p.id), label: p.full_name }))} />}
        </div>
        {canCreate && <Button variant="primary" icon={<Plus size={20} />} onClick={() => setEditing({})}>Nueva tarea</Button>}
      </div>
      {!personal && !manager && <p className="muted" style={{ margin: 0 }}>
        Las asigna el administrador. Usted puede cambiar su estado y marcarlas como completadas.</p>}
      {tasks.loading && !tasks.data ? <Loading /> : tasks.error ? <ErrorState error={tasks.error} onRetry={tasks.reload} /> : (
        !tasks.data?.length ? (
          <EmptyState title={empty}>
            {canCreate && filter !== 'completada' && (
              <Button icon={<Plus size={20} />} onClick={() => setEditing({})}>{manager ? 'Asignar una tarea' : 'Nueva tarea'}</Button>)}
          </EmptyState>
        ) : (
          <div className="cards">
            {tasks.data.map((t) => (
              <TaskCard key={t.id} task={t} showAssignee={manager} showCreator={!personal && !manager}
                canEdit={personal || manager} canStatus={personal || manager || t.assignee_id === user?.id}
                onStatus={(s) => void setStatus(t, s)} onEdit={() => setEditing(t)} onDelete={() => setDeleting(t)} />
            ))}
          </div>
        )
      )}
      {editing && <TaskDialog task={editing} personal={personal} people={people.data ?? []}
        onClose={() => setEditing(null)} onSaved={() => { setEditing(null); tasks.reload(); }} />}
      <ConfirmDialog open={Boolean(deleting)} title="Eliminar tarea" danger busy={busy} confirmLabel="Eliminar"
        message={deleting && <>¿Eliminar la tarea «{deleting.title}»?{manager && ' El empleado dejará de verla.'} No se puede deshacer.</>}
        onConfirm={() => void remove()} onClose={() => setDeleting(null)} />
    </div>
  );
}

function TaskCard({ task: t, showAssignee, showCreator, canEdit, canStatus, onStatus, onEdit, onDelete }: {
  task: any; showAssignee: boolean; showCreator: boolean; canEdit: boolean; canStatus: boolean;
  onStatus: (s: string) => void; onEdit: () => void; onDelete: () => void;
}) {
  const done = t.status === 'completada';
  const overdue = Boolean(t.due_date) && !done && t.status !== 'cancelada' && t.due_date < today();
  const options = (t.status === 'cancelada' ? [...CHOICES, 'cancelada'] : CHOICES).map((value) => ({ value, label: TASK_STATUS[value] }));
  return (
    <article className={`item-card${done ? ' done' : ''}`} aria-label={t.title}>
      <div className="row-between" style={{ alignItems: 'flex-start', gap: 8 }}>
        <h3 className="item-card-title">{t.title}</h3>
        <Badge kind={STATUS_KIND[t.status]}>{TASK_STATUS[t.status] ?? t.status}</Badge>
      </div>
      {t.description && <p className="item-card-text">{t.description}</p>}
      {(t.due_date || showAssignee || showCreator) && (
        <div className="item-card-meta">
          {t.due_date && <span className={overdue ? 'overdue' : undefined}>Fecha límite: {date(t.due_date)}{overdue && ' (vencida)'}</span>}
          {showAssignee && <span>Responsable: <strong>{t.assignee_name}</strong>{!t.assignee_active && <> <Badge kind="danger">Inactivo</Badge></>}</span>}
          {showCreator && t.created_by_name && <span>Asignada por: {t.created_by_name}</span>}
        </div>
      )}
      {canStatus && <SelectField label="Estado" value={t.status} onChange={onStatus} options={options} />}
      <div className="item-card-actions">
        {canStatus && !done && <Button size="sm" variant="primary" icon={<Check size={18} />} onClick={() => onStatus('completada')}>
          Marcar como completada</Button>}
        {canEdit && <Button size="sm" icon={<Pencil size={18} />} onClick={onEdit}>Editar</Button>}
        {canEdit && <Button size="sm" icon={<Trash2 size={18} />} onClick={onDelete}>Eliminar</Button>}
      </div>
    </article>
  );
}

function TaskDialog({ task, personal, people, onClose, onSaved }: {
  task: any; personal: boolean; people: any[]; onClose: () => void; onSaved: () => void;
}) {
  const { notify } = useToast();
  const isNew = !task.id;
  const [form, setForm] = useState({ title: task.title ?? '', description: task.description ?? '',
    assignee_id: task.assignee_id ? String(task.assignee_id) : '', due_date: task.due_date ?? '' });
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    setError(null);
    const body: Record<string, unknown> = { title: form.title, description: form.description, due_date: form.due_date || null };
    if (!personal) body.assignee_id = Number(form.assignee_id) || undefined;
    try {
      if (isNew) await post('/tasks', personal ? { ...body, personal: true } : body);
      else await put(`/tasks/${task.id}`, { ...body, version: task.version });
      notify('success', isNew ? (personal ? 'Tarea creada' : 'Tarea asignada') : 'Tarea actualizada', form.title);
      onSaved();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  const fe = error?.fields ?? {};
  return (
    <Dialog open title={isNew ? (personal ? 'Nueva tarea' : 'Asignar tarea') : 'Editar tarea'} onClose={onClose} footer={
      <><Button onClick={onClose}>Cancelar</Button><Button variant="primary" busy={busy} icon={<Save size={20} />} onClick={save}>Guardar</Button></>}>
      <ErrorAlert error={error} />
      <div className="stack">
        <TextField label="Tarea" value={form.title} onChange={(v) => setForm({ ...form, title: v })} error={fe.title} maxLength={200} required autoFocus />
        <TextArea label="Descripción (opcional)" value={form.description} onChange={(v) => setForm({ ...form, description: v })} maxLength={2000} rows={3} />
        {!personal && <SelectField label="Responsable" value={form.assignee_id} onChange={(v) => setForm({ ...form, assignee_id: v })} error={fe.assignee_id}
          placeholder="Elija una persona" required
          options={people.map((p) => ({ value: String(p.id), label: `${p.full_name}${p.role === 'admin' ? ' (administrador)' : ''}` }))} />}
        <TextField label="Fecha límite (opcional)" type="date" value={form.due_date} onChange={(v) => setForm({ ...form, due_date: v })} error={fe.due_date} />
      </div>
    </Dialog>
  );
}

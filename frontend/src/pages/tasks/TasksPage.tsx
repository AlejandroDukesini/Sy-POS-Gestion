import { Plus, Save } from 'lucide-react';
import { useState } from 'react';
import { ApiError, post, put } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { Dialog } from '../../components/ui/Dialog';
import { Badge, ErrorAlert, ErrorState, Loading } from '../../components/ui/Feedback';
import { SelectField, TextArea, TextField } from '../../components/ui/Form';
import { Card, PageHeader, Tabs } from '../../components/ui/Layout';
import { DataTable } from '../../components/ui/Table';
import { useAuth } from '../../context/Auth';
import { useToast } from '../../context/Toast';
import { useApi } from '../../lib/hooks';

export const TASK_STATUS: Record<string, string> = {
  pendiente: 'Pendiente', en_curso: 'En curso', completada: 'Completada', cancelada: 'Cancelada',
};
const STATUS_KIND: Record<string, 'info' | 'success' | 'warning' | 'danger' | undefined> = {
  pendiente: 'warning', en_curso: 'info', completada: 'success', cancelada: undefined,
};

/** Tareas: cada persona ve las suyas; con «tareas.gestionar» se crean y asignan a cualquiera. */
export default function TasksPage() {
  const { can, user } = useAuth();
  const { notify } = useToast();
  const manager = can('tareas.gestionar');
  const [filter, setFilter] = useState<'abiertas' | 'todas'>('abiertas');
  const [scope, setScope] = useState<'mias' | 'todas'>(manager ? 'todas' : 'mias');
  const [editing, setEditing] = useState<any>(null);
  const params = new URLSearchParams();
  if (filter === 'abiertas') params.set('status', 'abiertas');
  if (scope === 'mias' && user) params.set('assignee_id', String(user.id));
  const tasks = useApi<any[]>(`/tasks?${params}`);

  const setStatus = async (t: any, status: string) => {
    try {
      await put(`/tasks/${t.id}`, { status, version: t.version });
      notify('success', 'Tarea actualizada', `${t.title}: ${TASK_STATUS[status]}`);
      tasks.reload();
    } catch (err) {
      notify('danger', 'No se pudo actualizar', (err as Error).message);
    }
  };

  return (
    <div className="stack">
      <PageHeader title="Tareas" description={manager ? 'Asigne tareas a los empleados y consulte su avance.' : 'Sus tareas asignadas.'}
        actions={manager && <Button variant="primary" icon={<Plus size={20} />} onClick={() => setEditing({})}>Nueva tarea</Button>} />
      <div className="row" style={{ gap: 16, flexWrap: 'wrap' }}>
        <Tabs label="Estado" value={filter} onChange={setFilter} tabs={[{ value: 'abiertas', label: 'Abiertas' }, { value: 'todas', label: 'Todas' }]} />
        {manager && <Tabs label="Responsable" value={scope} onChange={setScope}
          tabs={[{ value: 'todas', label: 'De todos' }, { value: 'mias', label: 'Mías' }]} />}
      </div>
      <Card>
        {tasks.loading && !tasks.data ? <Loading /> : tasks.error ? <ErrorState error={tasks.error} onRetry={tasks.reload} /> : (
          !tasks.data?.length ? <p className="card-body muted">No hay tareas para mostrar.</p> : (
            <DataTable caption="Tareas" rows={tasks.data} rowKey={(t: any) => t.id} onSelect={manager ? setEditing : undefined} columns={[
              { key: 't', header: 'Tarea', render: (t: any) => <span><strong>{t.title}</strong>{t.description && <><br /><small className="muted">{t.description}</small></>}</span> },
              { key: 'a', header: 'Responsable', render: (t: any) => <>{t.assignee_name}{!t.assignee_active && <> <Badge kind="danger">Inactivo</Badge></>}</> },
              { key: 'd', header: 'Vence', render: (t: any) => t.due_date ?? '—' },
              { key: 's', header: 'Estado', render: (t: any) => (manager || t.assignee_id === user?.id) ? (
                <span onClick={(e) => e.stopPropagation()}>
                  <SelectField label={`Estado de ${t.title}`} value={t.status} onChange={(v) => void setStatus(t, v)}
                    options={Object.entries(TASK_STATUS).map(([value, label]) => ({ value, label }))} />
                </span>) : <Badge kind={STATUS_KIND[t.status]}>{TASK_STATUS[t.status]}</Badge> },
            ]} />
          )
        )}
      </Card>
      {editing && <TaskDialog task={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); tasks.reload(); }} />}
    </div>
  );
}

function TaskDialog({ task, onClose, onSaved }: { task: any; onClose: () => void; onSaved: () => void }) {
  const { notify } = useToast();
  const people = useApi<any[]>('/tasks/assignees');
  const isNew = !task.id;
  const [form, setForm] = useState({ title: task.title ?? '', description: task.description ?? '',
    assignee_id: task.assignee_id ? String(task.assignee_id) : '', due_date: task.due_date ?? '' });
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    setError(null);
    const body = { title: form.title, description: form.description, assignee_id: Number(form.assignee_id) || undefined,
      due_date: form.due_date || null };
    try {
      if (isNew) await post('/tasks', body);
      else await put(`/tasks/${task.id}`, { ...body, version: task.version });
      notify('success', isNew ? 'Tarea asignada' : 'Tarea actualizada', form.title);
      onSaved();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  const fe = error?.fields ?? {};
  return (
    <Dialog open title={isNew ? 'Nueva tarea' : 'Editar tarea'} onClose={onClose} footer={
      <><Button onClick={onClose}>Cancelar</Button><Button variant="primary" busy={busy} icon={<Save size={20} />} onClick={save}>Guardar</Button></>}>
      <ErrorAlert error={error} />
      <div className="stack">
        <TextField label="Tarea" value={form.title} onChange={(v) => setForm({ ...form, title: v })} error={fe.title} maxLength={200} required />
        <TextArea label="Descripción" value={form.description} onChange={(v) => setForm({ ...form, description: v })} maxLength={2000} />
        <SelectField label="Responsable" value={form.assignee_id} onChange={(v) => setForm({ ...form, assignee_id: v })} error={fe.assignee_id}
          placeholder="Elija una persona" required
          options={(people.data ?? []).map((p) => ({ value: String(p.id), label: `${p.full_name}${p.role === 'admin' ? ' (administrador)' : ''}` }))} />
        <TextField label="Fecha límite" type="date" value={form.due_date} onChange={(v) => setForm({ ...form, due_date: v })} error={fe.due_date} />
      </div>
    </Dialog>
  );
}

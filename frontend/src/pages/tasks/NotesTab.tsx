import { Pencil, Plus, Save, Search, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { ApiError, del, post, put } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { ConfirmDialog, Dialog } from '../../components/ui/Dialog';
import { EmptyState, ErrorAlert, ErrorState, Loading } from '../../components/ui/Feedback';
import { TextArea, TextField } from '../../components/ui/Form';
import { useToast } from '../../context/Toast';
import { dateTime } from '../../lib/format';
import { useApi, useDebounced } from '../../lib/hooks';

/** Bloc de notas personal: solo la persona que inició sesión ve sus notas. */
export default function NotesTab() {
  const { notify } = useToast();
  const [q, setQ] = useState('');
  const query = useDebounced(q.trim(), 300);
  const notes = useApi<any[]>(`/notes${query ? `?q=${encodeURIComponent(query)}` : ''}`);
  const [editing, setEditing] = useState<any>(null);
  const [deleting, setDeleting] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  const remove = async () => {
    setBusy(true);
    try {
      await del(`/notes/${deleting.id}`);
      notify('success', 'Nota eliminada', deleting.title || 'Sin título');
      setDeleting(null);
      notes.reload();
    } catch (err) {
      notify('danger', 'No se pudo eliminar', (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      <div className="row-between" style={{ flexWrap: 'wrap', gap: 12, alignItems: 'flex-end' }}>
        <div className="grow" style={{ maxWidth: 420, minWidth: 0 }}>
          <TextField label="Buscar notas" type="search" value={q} onChange={setQ} placeholder="Título o contenido" />
        </div>
        <Button variant="primary" icon={<Plus size={20} />} onClick={() => setEditing({})}>Nueva nota</Button>
      </div>
      {notes.loading && !notes.data ? <Loading /> : notes.error ? <ErrorState error={notes.error} onRetry={notes.reload} /> : (
        !notes.data?.length ? (
          query ? <EmptyState title={`Ninguna nota coincide con «${query}».`} icon={<Search size={40} aria-hidden />} /> : (
            <EmptyState title="Todavía no tiene notas. Cree una para guardar sus ideas.">
              <Button icon={<Plus size={20} />} onClick={() => setEditing({})}>Nueva nota</Button>
            </EmptyState>
          )
        ) : (
          <div className="cards">
            {notes.data.map((n) => (
              <article key={n.id} className="item-card" aria-label={n.title || 'Nota sin título'}>
                <h3 className="item-card-title">{n.title || <span className="muted">Sin título</span>}</h3>
                {n.content && <p className="item-card-text">{n.content}</p>}
                <div className="item-card-meta">
                  <span>Creada: {dateTime(n.created_at)}</span>
                  {n.updated_at !== n.created_at && <span>Modificada: {dateTime(n.updated_at)}</span>}
                </div>
                <div className="item-card-actions">
                  <Button size="sm" icon={<Pencil size={18} />} onClick={() => setEditing(n)}>Editar</Button>
                  <Button size="sm" icon={<Trash2 size={18} />} onClick={() => setDeleting(n)}>Eliminar</Button>
                </div>
              </article>
            ))}
          </div>
        )
      )}
      {editing && <NoteDialog note={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); notes.reload(); }} />}
      <ConfirmDialog open={Boolean(deleting)} title="Eliminar nota" danger busy={busy} confirmLabel="Eliminar"
        message={deleting && <>¿Eliminar la nota «{deleting.title || 'Sin título'}»? No se puede deshacer.</>}
        onConfirm={() => void remove()} onClose={() => setDeleting(null)} />
    </div>
  );
}

function NoteDialog({ note, onClose, onSaved }: { note: any; onClose: () => void; onSaved: () => void }) {
  const { notify } = useToast();
  const isNew = !note.id;
  const [form, setForm] = useState({ title: note.title ?? '', content: note.content ?? '' });
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      if (isNew) await post('/notes', form);
      else await put(`/notes/${note.id}`, { ...form, version: note.version });
      notify('success', isNew ? 'Nota guardada' : 'Nota actualizada', form.title || 'Sin título');
      onSaved();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  const fe = error?.fields ?? {};
  return (
    <Dialog open title={isNew ? 'Nueva nota' : 'Editar nota'} onClose={onClose} footer={
      <><Button onClick={onClose}>Cancelar</Button><Button variant="primary" busy={busy} icon={<Save size={20} />} onClick={save}>Guardar</Button></>}>
      <ErrorAlert error={error} />
      <div className="stack">
        <TextField label="Título" value={form.title} onChange={(v) => setForm({ ...form, title: v })} error={fe.title} maxLength={200} autoFocus />
        <TextArea label="Nota" value={form.content} onChange={(v) => setForm({ ...form, content: v })} error={fe.content} maxLength={20000} rows={8} />
      </div>
    </Dialog>
  );
}

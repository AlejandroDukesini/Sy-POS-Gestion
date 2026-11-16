import { ArrowLeft, Download, ExternalLink, MessageSquarePlus, Paperclip, Pencil, RefreshCw, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ApiError, download, del, post, upload } from '../../../api/client';
import { Button } from '../../../components/ui/Button';
import { ConfirmDialog, Dialog } from '../../../components/ui/Dialog';
import { Alert, Badge, ErrorAlert, ErrorState, Loading } from '../../../components/ui/Feedback';
import { SelectField, TextArea } from '../../../components/ui/Form';
import { Card } from '../../../components/ui/Layout';
import { useAuth } from '../../../context/Auth';
import { useToast } from '../../../context/Toast';
import { date, dateTime, money, qty } from '../../../lib/format';
import { useApi, useOnline } from '../../../lib/hooks';
import { ObservationForm, type ObservationMeta } from './ObservationForm';
import { EVENT_LABELS, FIELD_LABELS, PRIORITY_LABELS, PriorityBadge, STATUS_LABELS, StatusBadge, type Observation } from './labels';

interface Detail extends Observation {
  product: any;
  events: { id: number; kind: string; from_value: string | null; to_value: string | null; comment: string; details: any;
    user_name: string | null; created_at: string }[];
  files: { id: number; original_name: string; size_bytes: number; uploaded_at: string; uploaded_by_name: string | null; available: boolean }[];
}

const kb = (n: number) => (n > 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);

export function ObservationDetail({ meta }: { meta: ObservationMeta }) {
  const { id } = useParams();
  const { can } = useAuth();
  const { notify } = useToast();
  const online = useOnline();
  const navigate = useNavigate();
  const detail = useApi<Detail>(`/observations/${id}`);
  const [editing, setEditing] = useState(false);
  const [statusOpen, setStatusOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [removingFile, setRemovingFile] = useState<Detail['files'][number] | null>(null);
  const [comment, setComment] = useState('');
  const [commentError, setCommentError] = useState('');
  const [busy, setBusy] = useState(false);
  const o = detail.data;

  if (detail.loading && !o) return <Loading />;
  if (detail.error) return (
    <div className="stack">
      <Link to=".." relative="path" className="btn btn-ghost" style={{ alignSelf: 'flex-start' }}><ArrowLeft size={20} aria-hidden /> Volver</Link>
      <ErrorState error={detail.error} onRetry={detail.reload} />
    </div>
  );
  if (!o) return null;
  const p = o.product;
  const nameOf = (field: string, value: any) => {
    if (value === null || value === undefined || value === '') return '—';
    if (field === 'category_id') return meta.categories.find((c) => c.id === Number(value))?.name ?? value;
    if (field === 'supplier_id') return meta.suppliers.find((s) => s.id === Number(value))?.name ?? value;
    if (field === 'assigned_to') return meta.users.find((u) => u.id === Number(value))?.full_name ?? value;
    if (field === 'qty_milli') return qty(Number(value) / 1000);
    if (field.endsWith('_on') || field.endsWith('_date')) return date(value);
    return String(value);
  };

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    try {
      await fn();
      notify('success', ok);
      detail.reload();
      return true;
    } catch (err) {
      notify('danger', 'No se pudo completar la operación', (err as ApiError).message);
      return false;
    } finally {
      setBusy(false);
    }
  };
  const addComment = async () => {
    if (!comment.trim()) { setCommentError('Escriba el comentario.'); return; }
    setCommentError('');
    if (await run(() => post(`/observations/${o.id}/comments`, { comment: comment.trim() }), 'Comentario agregado')) setComment('');
  };
  const attach = async (files: FileList | null) => {
    for (const file of Array.from(files ?? [])) {
      const form = new FormData();
      form.append('file', file);
      await run(() => upload(`/observations/${o.id}/files`, form), `Archivo adjuntado: ${file.name}`);
    }
  };
  const remove = async (reason: string) => {
    setBusy(true);
    try {
      await post(`/observations/${o.id}/delete`, { reason });
      notify('success', 'Observación eliminada', `${o.code}: el historial se conserva en la auditoría.`);
      navigate('..', { relative: 'path' });
    } catch (err) {
      notify('danger', 'No se pudo eliminar', (err as ApiError).message);
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      <div className="row-between">
        <Link to=".." relative="path" className="btn btn-ghost"><ArrowLeft size={20} aria-hidden /> Todas las observaciones</Link>
        <div className="row">
          {can('observaciones.estado') && <Button variant="primary" disabled={!online} icon={<RefreshCw size={20} />} onClick={() => setStatusOpen(true)}>Cambiar estado</Button>}
          {can('observaciones.editar') && <Button disabled={!online} icon={<Pencil size={20} />} onClick={() => setEditing(true)}>Editar</Button>}
          {can('observaciones.eliminar') && <Button variant="ghost" disabled={!online} icon={<Trash2 size={20} />} onClick={() => setDeleting(true)}>Eliminar</Button>}
        </div>
      </div>

      <div className="obs-detail">
        <div className="stack">
          <Card title={<div><h2>{o.code} · {o.category_name}</h2>
            <div className="row" style={{ marginTop: 8 }}><PriorityBadge priority={o.priority} /><StatusBadge status={o.status} />
              {o.follow_up_overdue && <Badge kind="warning">Seguimiento vencido</Badge>}</div></div>}>
            <div className="card-body stack">
              <p style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{o.description}</p>
              <dl className="dl">
                <dt>Cantidad afectada</dt><dd>{o.qty !== null ? `${qty(o.qty)} ${o.product_unit}` : '—'}</dd>
                <dt>Responsable</dt><dd>{o.responsible_name ?? '—'}</dd>
                <dt>Registrada por</dt><dd>{o.created_by_name ?? 'sistema'}</dd>
                <dt>Fecha de la novedad</dt><dd>{date(o.detected_on)}</dd>
                <dt>Fecha de registro</dt><dd>{dateTime(o.created_at)}</dd>
                <dt>Última actualización</dt><dd>{dateTime(o.updated_at)}</dd>
                <dt>Seguimiento hasta</dt><dd>{o.follow_up_date ? date(o.follow_up_date) : '—'}</dd>
                <dt>Proveedor</dt><dd>{o.supplier_name ?? '—'}</dd>
                <dt>Documento de referencia</dt><dd>{o.reference_doc || '—'}</dd>
                {o.resolved_at && <><dt>Resuelta</dt><dd>{dateTime(o.resolved_at)}</dd></>}
                {o.closed_at && <><dt>Cerrada</dt><dd>{dateTime(o.closed_at)}</dd></>}
              </dl>
              {o.notes && <p style={{ whiteSpace: 'pre-wrap', margin: 0 }}><span className="muted">Comentarios adicionales:</span> {o.notes}</p>}
            </div>
          </Card>

          <Card title="Historial de seguimiento">
            <div className="card-body stack">
              <ol className="obs-timeline" aria-label="Historial cronológico">
                {o.events.map((e) => (
                  <li key={e.id} className={`obs-event obs-event-${e.kind}`}>
                    <div className="obs-event-head">
                      <strong>{EVENT_LABELS[e.kind] ?? e.kind}</strong>
                      <small className="muted">{dateTime(e.created_at)} · {e.user_name ?? 'sistema'}</small>
                    </div>
                    {e.kind === 'estado' && <div>{STATUS_LABELS[e.from_value ?? ''] ?? e.from_value} → <strong>{STATUS_LABELS[e.to_value ?? ''] ?? e.to_value}</strong></div>}
                    {e.kind === 'prioridad' && <div>{PRIORITY_LABELS[e.from_value ?? '']} → <strong>{PRIORITY_LABELS[e.to_value ?? '']}</strong></div>}
                    {(e.kind === 'adjunto' || e.kind === 'adjunto_eliminado') && <div>{e.to_value ?? e.from_value}</div>}
                    {e.kind === 'edicion' && e.details && (
                      <ul className="obs-changes">{Object.entries(e.details).map(([field, change]: [string, any]) => (
                        <li key={field}><span className="muted">{FIELD_LABELS[field] ?? field}:</span> {nameOf(field, change.antes)} → {nameOf(field, change.despues)}</li>))}
                      </ul>
                    )}
                    {e.comment && <p className="obs-event-comment">{e.comment}</p>}
                  </li>
                ))}
              </ol>
              {can('observaciones.comentar') && (
                <div className="stack" style={{ gap: 8 }}>
                  <TextArea label="Agregar comentario de seguimiento" value={comment} onChange={setComment} error={commentError}
                    maxLength={2000} rows={2} placeholder="Ej.: Se inició la revisión de entradas y salidas." />
                  <Button style={{ alignSelf: 'flex-start' }} busy={busy} disabled={!online} icon={<MessageSquarePlus size={20} />}
                    onClick={addComment}>Agregar comentario</Button>
                </div>
              )}
            </div>
          </Card>
        </div>

        <div className="stack">
          <Card title="Producto relacionado">
            <div className="card-body stack">
              <div>
                <strong>{p.description}</strong> {!p.active && <Badge kind="danger">Inactivo</Badge>}
                <div className="muted">Código: {p.code}{p.external_ref ? ` · Ref.: ${p.external_ref}` : ''}</div>
              </div>
              <dl className="dl">
                <dt>Categoría</dt><dd>{p.category_name ?? 'Sin categoría'}</dd>
                <dt>Existencia actual</dt><dd>{qty(p.stock)} {p.unit}</dd>
                {p.cost !== undefined && <><dt>Precio de compra</dt><dd>{money(p.cost)}</dd></>}
                <dt>Proveedor asociado</dt><dd>{p.last_supplier?.name ?? '—'}</dd>
                <dt>Observaciones abiertas</dt><dd>{p.open_observations}</dd>
              </dl>
              <div className="row">
                <Link className="btn btn-outline" to={`/inventario?producto=${p.id}`}><ExternalLink size={18} aria-hidden /> Ficha del producto</Link>
                <Link className="btn btn-ghost" to={`/inventario/observaciones?producto=${p.id}`}>Sus observaciones</Link>
              </div>
            </div>
          </Card>

          <Card title="Documentos adjuntos">
            <div className="card-body stack">
              {o.files.length ? (
                <ul className="result-list">
                  {o.files.map((file) => (
                    <li key={file.id} className="result-item" style={{ cursor: 'default' }}>
                      <span><strong>{file.original_name}</strong><br />
                        <small className="muted">{kb(file.size_bytes)} · {dateTime(file.uploaded_at)} · {file.uploaded_by_name ?? ''}</small>
                        {!file.available && <><br /><Badge kind="warning">No está en el disco</Badge></>}</span>
                      <span className="row" style={{ gap: 4, flexWrap: 'nowrap' }}>
                        <Button size="sm" variant="ghost" iconOnly icon={<Download size={18} />} disabled={!file.available}
                          onClick={() => download(`/observations/${o.id}/files/${file.id}/download`, file.original_name)
                            .catch((err) => notify('danger', 'No se pudo descargar', err.message))}>Descargar {file.original_name}</Button>
                        {can('observaciones.editar') && (
                          <Button size="sm" variant="ghost" iconOnly icon={<Trash2 size={18} />} onClick={() => setRemovingFile(file)}>
                            Eliminar {file.original_name}</Button>)}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : <p className="muted">Sin documentos adjuntos.</p>}
              {(can('observaciones.crear') || can('observaciones.editar')) && o.files.length < meta.max_files && (
                <label className={`btn btn-outline${!online || busy ? ' is-disabled' : ''}`} style={{ alignSelf: 'flex-start' }}>
                  <Paperclip size={18} aria-hidden /> Adjuntar archivo
                  <input type="file" className="sr-only" accept={meta.file_types.join(',')} disabled={!online || busy}
                    onChange={(e) => { attach(e.target.files); e.target.value = ''; }} />
                </label>
              )}
              <span className="field-hint">{meta.file_types.join(', ')} · máximo {meta.max_file_mb} MB.</span>
            </div>
          </Card>
          <Alert kind="info">Esta observación documenta una novedad: no cambia existencias, costos ni movimientos.
            {o.qty !== null && ' Si debe corregir la cantidad, registre un ajuste desde la ficha del producto.'}</Alert>
        </div>
      </div>

      {editing && <ObservationForm meta={meta} observation={o} onClose={() => setEditing(false)}
        onSaved={() => { setEditing(false); detail.reload(); }} />}
      {statusOpen && <StatusDialog observation={o} onClose={() => setStatusOpen(false)} onDone={() => { setStatusOpen(false); detail.reload(); }} />}
      <ConfirmDialog open={deleting} title={`Eliminar ${o.code}`} danger requireReason busy={busy} confirmLabel="Eliminar observación"
        onClose={() => setDeleting(false)} onConfirm={remove}
        message={<p>La observación dejará de aparecer en los listados. Su historial y el motivo se conservan para auditoría.</p>} />
      <ConfirmDialog open={Boolean(removingFile)} title="Eliminar adjunto" danger busy={busy} confirmLabel="Eliminar archivo"
        onClose={() => setRemovingFile(null)}
        onConfirm={async () => { const file = removingFile!; setRemovingFile(null);
          await run(() => del(`/observations/${o.id}/files/${file.id}`), 'Archivo eliminado'); }}
        message={<p>Se eliminará «{removingFile?.original_name}». El historial registrará la eliminación.</p>} />
    </div>
  );
}

function StatusDialog({ observation: o, onClose, onDone }: { observation: Observation; onClose: () => void; onDone: () => void }) {
  const { notify } = useToast();
  const [status, setStatus] = useState(o.status === 'pendiente' ? 'en_proceso' : o.status === 'en_proceso' ? 'resuelta' : '');
  const [comment, setComment] = useState('');
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const needsReason = status === 'cerrada' || ((o.status === 'resuelta' || o.status === 'cerrada') && (status === 'pendiente' || status === 'en_proceso'));
  const save = async () => {
    if (!status) { setError(new ApiError(422, 'Revise los datos', 'Elija el nuevo estado.', { status: 'Elija el nuevo estado.' })); return; }
    if (needsReason && !comment.trim()) {
      setError(new ApiError(422, 'Revise los datos', 'Escriba el motivo del cambio.', { comment: 'Para cerrar o reabrir explique el motivo.' }));
      return;
    }
    setBusy(true);
    try {
      await post(`/observations/${o.id}/status`, { status, comment: comment.trim(), version: o.version });
      notify('success', 'Estado actualizado', `${o.code}: ${STATUS_LABELS[status]}`);
      onDone();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open title={`Cambiar estado de ${o.code}`} onClose={onClose} footer={
      <><Button onClick={onClose}>Cancelar</Button><Button variant="primary" busy={busy} onClick={save}>Guardar estado</Button></>}>
      <ErrorAlert error={error} />
      <p>Estado actual: <StatusBadge status={o.status} /></p>
      <SelectField label="Nuevo estado" required value={status} onChange={setStatus} placeholder="Seleccione…" error={error?.fields.status}
        options={Object.entries(STATUS_LABELS).filter(([v]) => v !== o.status).map(([value, label]) => ({ value, label }))} />
      <TextArea label={needsReason ? 'Motivo del cambio' : 'Comentario del cambio'} required={needsReason} value={comment} onChange={setComment}
        error={error?.fields.comment} maxLength={2000} rows={3} hint="Queda en el historial con fecha, hora y su usuario." />
    </Dialog>
  );
}

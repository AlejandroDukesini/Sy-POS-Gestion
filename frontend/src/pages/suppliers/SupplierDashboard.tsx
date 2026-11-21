import { ArrowLeft, CheckCircle2, Download, FileSpreadsheet, Pencil, Plus, RotateCcw, Star, Trash2, Upload } from 'lucide-react';
import { useRef, useState } from 'react';
import { Link, Navigate, Route, Routes, useParams } from 'react-router-dom';
import { ApiError, del, download, put, upload } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { ConfirmDialog } from '../../components/ui/Dialog';
import { Alert, Badge, EmptyState, ErrorAlert, ErrorState, Loading } from '../../components/ui/Feedback';
import { Card, LinkTabs, Metric, PageHeader, Tabs } from '../../components/ui/Layout';
import { DataTable } from '../../components/ui/Table';
import { useToast } from '../../context/Toast';
import { date, dateTime, money } from '../../lib/format';
import { useApi, type Resource } from '../../lib/hooks';
import { AdvisorDialog, NOTE_CATEGORIES, NoteDialog, QUOTE_STATUS, QuoteDialog, SupplierInfoDialog, VisitDialog } from './SupplierDialogs';

const kb = (bytes: number) => (bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`);

/** Expediente digital de un proveedor. Cada pestaña tiene su propia dirección. */
export function SupplierDashboard() {
  const id = Number(useParams().id);
  const dash = useApi<any>(`/suppliers/${id}`);
  if (dash.loading && !dash.data) return <Loading />;
  if (dash.error) return <ErrorState error={dash.error} onRetry={dash.reload} />;
  const s = dash.data.supplier;
  const base = `/gestion/proveedores/${id}`;
  return (
    <div className="stack">
      <Link to="/gestion/proveedores" className="btn btn-ghost" style={{ alignSelf: 'flex-start' }}><ArrowLeft size={20} aria-hidden /> Proveedores</Link>
      <PageHeader title={s.name} description={[s.identification && `NIT ${s.identification}`, `Código interno P-${String(s.id).padStart(4, '0')}`,
        `Registrado el ${date(s.created_at)}`].filter(Boolean).join(' · ')}
        actions={s.active ? <Badge kind="success">Activo</Badge> : <Badge>Inactivo</Badge>} />
      <LinkTabs label="Secciones del proveedor" tabs={[
        { to: `${base}/resumen`, label: 'Resumen' },
        { to: `${base}/notas`, label: `Notas y pendientes${dash.data.pending_notes ? ` (${dash.data.pending_notes})` : ''}` },
        { to: `${base}/visitas`, label: 'Visitas' },
        { to: `${base}/cotizaciones`, label: 'Cotizaciones' },
        { to: `${base}/productos`, label: 'Lista de productos' },
      ]} />
      <Routes>
        <Route index element={<Navigate to="resumen" replace />} />
        <Route path="resumen" element={<Summary dash={dash} />} />
        <Route path="notas" element={<NotesTab supplierId={id} onChange={dash.reload} />} />
        <Route path="visitas" element={<VisitsTab supplier={s} onChange={dash.reload} />} />
        <Route path="cotizaciones" element={<QuotesTab supplier={s} onChange={dash.reload} />} />
        <Route path="productos" element={<ProductsTab supplierId={id} onChange={dash.reload} />} />
      </Routes>
    </div>
  );
}

// ------------------------------------------------------------------ resumen
function Summary({ dash }: { dash: Resource<any> }) {
  const d = dash.data;
  const s = d.supplier;
  const [editInfo, setEditInfo] = useState(false);
  const [editAdvisor, setEditAdvisor] = useState(false);
  const line = (label: string, value: string) => value ? <p><span className="muted">{label}:</span> {value}</p> : null;
  return (
    <div className="stack">
      <div className="metrics">
        <Metric label="Notas pendientes" value={d.pending_notes}
          hint={[d.important_notes && `${d.important_notes} importantes`, d.overdue_notes && `${d.overdue_notes} vencidas`].filter(Boolean).join(' · ') || undefined} />
        <Metric label="Última vez que vino" value={d.last_visit ? date(d.last_visit.visit_date) : '—'}
          hint={d.next_visit ? `Próxima: ${date(d.next_visit)}` : d.last_visit ? d.last_visit.reason : 'Sin visitas registradas'} />
        <Metric label="Última cotización" value={d.latest_quote ? d.latest_quote.number : '—'}
          hint={d.latest_quote ? `${date(d.latest_quote.issue_date)} · ${QUOTE_STATUS[d.latest_quote.status]}${d.latest_quote.total ? ` · ${money(d.latest_quote.total)}` : ''}` : 'Sin cotizaciones'} />
        <Metric label="Visitas / cotizaciones" value={`${d.visits} / ${d.quotes}`} />
      </div>
      <div className="grid-2">
        <Card title="Contacto" actions={<Button size="sm" icon={<Pencil size={16} />} onClick={() => setEditInfo(true)}>Editar</Button>}>
          <div className="card-body">
            {line('Teléfono', s.phone)}{line('WhatsApp', s.whatsapp)}{line('Correo', s.email)}
            {line('Dirección', s.address)}{line('Ciudad', s.city)}{line('Días de pago', String(s.payment_days))}
            {s.contact_notes && <p style={{ whiteSpace: 'pre-wrap' }}><span className="muted">Información adicional:</span> {s.contact_notes}</p>}
            {!s.phone && !s.whatsapp && !s.email && <p className="muted">Sin datos de contacto. Pulse «Editar» para agregarlos.</p>}
          </div>
        </Card>
        <Card title="Asesor comercial" actions={<Button size="sm" icon={<Pencil size={16} />} onClick={() => setEditAdvisor(true)}>
          {s.advisor_name ? 'Cambiar' : 'Registrar'}</Button>}>
          <div className="card-body">
            {s.advisor_name ? <>
              <p><strong>{s.advisor_name}</strong></p>
              {line('Teléfono', s.advisor_phone)}{line('Correo', s.advisor_email)}
              {s.advisor_notes && <p style={{ whiteSpace: 'pre-wrap' }}><span className="muted">Observaciones:</span> {s.advisor_notes}</p>}
            </> : <p className="muted">Sin asesor registrado.</p>}
          </div>
        </Card>
      </div>
      <Card title="Lista de productos del proveedor">
        <div className="card-body row" style={{ flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center' }}>
          {d.product_file ? <span><FileSpreadsheet size={18} aria-hidden /> <strong>{d.product_file.original_name}</strong>
            <span className="muted"> · cargado el {dateTime(d.product_file.uploaded_at)}</span></span>
            : <span className="muted">Aún no se ha cargado la lista de productos.</span>}
          <span className="row" style={{ gap: 8 }}>
            {d.product_file?.available && <DownloadButton supplierId={s.id} file={d.product_file} />}
            <Link className="btn btn-outline" to={`/gestion/proveedores/${s.id}/productos`}>Ver versiones</Link>
          </span>
        </div>
      </Card>
      {editInfo && <SupplierInfoDialog supplier={s} onClose={() => setEditInfo(false)} onSaved={() => { setEditInfo(false); dash.reload(); }} />}
      {editAdvisor && <AdvisorDialog supplier={s} onClose={() => setEditAdvisor(false)} onSaved={() => { setEditAdvisor(false); dash.reload(); }} />}
    </div>
  );
}

function DownloadButton({ supplierId, file, label = 'Descargar' }: { supplierId: number; file: any; label?: string }) {
  const { notify } = useToast();
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      await download(`/suppliers/${supplierId}/files/${file.file_id ?? file.id}/download`, file.original_name ?? file.file_name ?? 'archivo');
    } catch (err) {
      notify('danger', 'No se pudo descargar', (err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return <Button size="sm" busy={busy} icon={<Download size={16} />} onClick={run}>{label}</Button>;
}

/** Borrado con confirmación; muestra el error del servidor si falla. */
function useDelete(onDone: () => void) {
  const { notify } = useToast();
  const [target, setTarget] = useState<null | { path: string; title: string; message: string; done: string }>(null);
  const [busy, setBusy] = useState(false);
  const dialog = (
    <ConfirmDialog open={target !== null} title={target?.title ?? ''} message={target?.message ?? ''} confirmLabel="Eliminar" danger busy={busy}
      onClose={() => setTarget(null)} onConfirm={async () => {
        setBusy(true);
        try {
          await del(target!.path);
          notify('success', target!.done);
          setTarget(null);
          onDone();
        } catch (err) {
          notify('danger', 'No se pudo eliminar', (err as ApiError).message);
        } finally {
          setBusy(false);
        }
      }} />
  );
  return { ask: setTarget, dialog };
}

// ------------------------------------------------------------------ notas y pendientes
function NotesTab({ supplierId, onChange }: { supplierId: number; onChange: () => void }) {
  const { notify } = useToast();
  const [status, setStatus] = useState<'pendiente' | 'resuelta' | ''>('pendiente');
  const [category, setCategory] = useState('');
  const notes = useApi<any[]>(`/suppliers/${supplierId}/notes?status=${status}&category=${category}`);
  const [editing, setEditing] = useState<any>(null);
  const reload = () => { notes.reload(); onChange(); };
  const { ask, dialog } = useDelete(reload);
  const toggle = async (n: any) => {
    try {
      await put(`/suppliers/${supplierId}/notes/${n.id}`, { status: n.status === 'pendiente' ? 'resuelta' : 'pendiente', version: n.version });
      notify('success', n.status === 'pendiente' ? 'Marcada como resuelta' : 'Reabierta como pendiente', n.title);
      reload();
    } catch (err) {
      notify('danger', 'No se pudo actualizar', (err as Error).message);
    }
  };
  const overdue = (n: any) => n.status === 'pendiente' && n.due_date && n.due_date < new Date().toISOString().slice(0, 10);
  return (
    <div className="stack">
      <div className="row" style={{ flexWrap: 'wrap', gap: 12, justifyContent: 'space-between' }}>
        <div className="row" style={{ flexWrap: 'wrap', gap: 12 }}>
          <Tabs label="Estado" value={status} onChange={setStatus}
            tabs={[{ value: 'pendiente', label: 'Pendientes' }, { value: 'resuelta', label: 'Resueltas' }, { value: '', label: 'Todas' }]} />
          <Tabs label="Categoría" value={category} onChange={setCategory}
            tabs={[{ value: '', label: 'Todas' }, ...Object.entries(NOTE_CATEGORIES).map(([value, label]) => ({ value, label }))]} />
        </div>
        <Button variant="primary" icon={<Plus size={20} />} onClick={() => setEditing({})}>Nueva nota</Button>
      </div>
      <Alert kind="info">Registro informativo: una nota de deuda o pago no modifica cuentas por pagar, compras ni inventario.</Alert>
      <Card>
        {notes.loading && !notes.data ? <Loading /> : notes.error ? <ErrorState error={notes.error} onRetry={notes.reload} />
          : !notes.data?.length ? <EmptyState title="No hay notas en esta vista" /> : (
            <DataTable caption="Notas" rows={notes.data} rowKey={(n: any) => n.id} onSelect={setEditing} columns={[
              { key: 'c', header: 'Categoría', render: (n: any) => <Badge kind={n.category === 'deuda' || n.category === 'reclamacion' ? 'warning' : 'info'}>{NOTE_CATEGORIES[n.category]}</Badge> },
              { key: 't', header: 'Nota', render: (n: any) => (
                <span>{n.important ? <Star size={14} aria-label="Importante" style={{ color: 'var(--danger)' }} /> : null} <strong>{n.title}</strong>
                  {n.body && <><br /><small className="muted" style={{ whiteSpace: 'pre-wrap' }}>{n.body}</small></>}</span>) },
              { key: 'v', header: 'Vence', render: (n: any) => n.due_date ? <>{date(n.due_date)}{overdue(n) && <> <Badge kind="danger">Vencida</Badge></>}</> : '—' },
              { key: 's', header: 'Estado', render: (n: any) => n.status === 'pendiente' ? <Badge kind="warning">Pendiente</Badge>
                : <Badge kind="success">Resuelta {n.resolved_at ? date(n.resolved_at) : ''}</Badge> },
              { key: 'f', header: 'Creada / actualizada', render: (n: any) => <small>{dateTime(n.created_at)}<br />{dateTime(n.updated_at)}</small> },
              { key: 'a', header: 'Acciones', render: (n: any) => (
                <span className="row" style={{ gap: 6 }} onClick={(e) => e.stopPropagation()}>
                  <Button size="sm" icon={n.status === 'pendiente' ? <CheckCircle2 size={16} /> : <RotateCcw size={16} />} onClick={() => void toggle(n)}>
                    {n.status === 'pendiente' ? 'Resolver' : 'Reabrir'}</Button>
                  <Button size="sm" variant="ghost" icon={<Trash2 size={16} />} onClick={() => ask({ path: `/suppliers/${supplierId}/notes/${n.id}`,
                    title: 'Eliminar nota', message: `Se eliminará la nota «${n.title}». Queda constancia en el historial de actividad.`, done: 'Nota eliminada' })}>
                    Eliminar</Button>
                </span>) },
            ]} />
          )}
      </Card>
      {editing && <NoteDialog supplierId={supplierId} note={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); reload(); }} />}
      {dialog}
    </div>
  );
}

// ------------------------------------------------------------------ visitas
function VisitsTab({ supplier, onChange }: { supplier: any; onChange: () => void }) {
  const visits = useApi<any[]>(`/suppliers/${supplier.id}/visits`);
  const [editing, setEditing] = useState<any>(null);
  const reload = () => { visits.reload(); onChange(); };
  const { ask, dialog } = useDelete(reload);
  const last = visits.data?.[0];
  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <div className="card metric" style={{ minWidth: 260 }}>
          <span className="metric-label">Última vez que vino</span>
          <span className="metric-value">{last ? date(last.visit_date) : '—'}</span>
          {last && <span className="muted">{last.reason}{last.advisor_name ? ` · ${last.advisor_name}` : ''}</span>}
        </div>
        <Button variant="primary" icon={<Plus size={20} />} onClick={() => setEditing({})}>Registrar visita</Button>
      </div>
      <Card>
        {visits.loading && !visits.data ? <Loading /> : visits.error ? <ErrorState error={visits.error} onRetry={visits.reload} />
          : !visits.data?.length ? <EmptyState title="Sin visitas registradas" /> : (
            <DataTable caption="Historial de visitas" rows={visits.data} rowKey={(v: any) => v.id} onSelect={setEditing} columns={[
              { key: 'd', header: 'Fecha', render: (v: any) => date(v.visit_date) },
              { key: 'a', header: 'Asesor', render: (v: any) => v.advisor_name || '—' },
              { key: 'm', header: 'Motivo y resumen', render: (v: any) => <span><strong>{v.reason}</strong>
                {v.summary && <><br /><small className="muted" style={{ whiteSpace: 'pre-wrap' }}>{v.summary}</small></>}</span> },
              { key: 'g', header: 'Acuerdos', render: (v: any) => <small style={{ whiteSpace: 'pre-wrap' }}>{v.agreements || '—'}</small> },
              { key: 'n', header: 'Próxima', render: (v: any) => (v.next_visit_date ? date(v.next_visit_date) : '—') },
              { key: 'x', header: 'Acciones', render: (v: any) => (
                <span onClick={(e) => e.stopPropagation()}>
                  <Button size="sm" variant="ghost" icon={<Trash2 size={16} />} onClick={() => ask({ path: `/suppliers/${supplier.id}/visits/${v.id}`,
                    title: 'Eliminar visita', message: `Se eliminará la visita del ${date(v.visit_date)} («${v.reason}»). Las demás visitas no cambian.`,
                    done: 'Visita eliminada' })}>Eliminar</Button>
                </span>) },
            ]} />
          )}
      </Card>
      {editing && <VisitDialog supplier={supplier} visit={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); reload(); }} />}
      {dialog}
    </div>
  );
}

// ------------------------------------------------------------------ cotizaciones
function QuotesTab({ supplier, onChange }: { supplier: any; onChange: () => void }) {
  const [status, setStatus] = useState('');
  const quotes = useApi<any[]>(`/suppliers/${supplier.id}/quotes?status=${status}`);
  const [editing, setEditing] = useState<any>(null);
  const reload = () => { quotes.reload(); onChange(); };
  const { ask, dialog } = useDelete(reload);
  const latest = status === '' ? quotes.data?.[0] : undefined;
  const statusBadge = (q: any) => (
    <>{<Badge kind={q.status === 'aceptada' ? 'success' : q.status === 'rechazada' ? 'danger' : q.status === 'vencida' ? undefined : 'warning'}>
      {QUOTE_STATUS[q.status]}</Badge>}{q.expired && <> <Badge kind="danger">Venció</Badge></>}</>);
  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <Tabs label="Estado" value={status} onChange={setStatus}
          tabs={[{ value: '', label: 'Todas' }, ...Object.entries(QUOTE_STATUS).map(([value, label]) => ({ value, label }))]} />
        <Button variant="primary" icon={<Plus size={20} />} onClick={() => setEditing({})}>Registrar cotización</Button>
      </div>
      {latest && (
        <Card title={`Cotización más reciente: ${latest.number}`} actions={<Button size="sm" icon={<Pencil size={16} />} onClick={() => setEditing(latest)}>Ver / editar</Button>}>
          <div className="card-body row" style={{ flexWrap: 'wrap', gap: 24 }}>
            <span><span className="muted">Emitida:</span> {date(latest.issue_date)}</span>
            {latest.due_date && <span><span className="muted">Vence:</span> {date(latest.due_date)}</span>}
            <span><span className="muted">Valor:</span> {latest.total ? money(latest.total) : 'No indicado'}</span>
            <span>{statusBadge(latest)}</span>
            {latest.file_id && <DownloadButton supplierId={supplier.id} file={latest} label="Adjunto" />}
          </div>
        </Card>
      )}
      <Alert kind="info">Una cotización, aunque se marque como aceptada, no registra una compra ni modifica el inventario.</Alert>
      <Card>
        {quotes.loading && !quotes.data ? <Loading /> : quotes.error ? <ErrorState error={quotes.error} onRetry={quotes.reload} />
          : !quotes.data?.length ? <EmptyState title="Sin cotizaciones en esta vista" /> : (
            <DataTable caption="Historial de cotizaciones" rows={quotes.data} rowKey={(q: any) => q.id} onSelect={setEditing} columns={[
              { key: 'n', header: 'Número', render: (q: any) => <strong>{q.number}</strong> },
              { key: 'e', header: 'Emisión', render: (q: any) => date(q.issue_date) },
              { key: 'v', header: 'Vence', render: (q: any) => (q.due_date ? date(q.due_date) : '—') },
              { key: 'a', header: 'Asesor', render: (q: any) => q.advisor_name || '—' },
              { key: 'd', header: 'Descripción', render: (q: any) => <small>{q.description || '—'}</small> },
              { key: 't', header: 'Valor', numeric: true, render: (q: any) => (q.total ? money(q.total) : '—') },
              { key: 's', header: 'Estado', render: statusBadge },
              { key: 'x', header: 'Acciones', render: (q: any) => (
                <span className="row" style={{ gap: 6 }} onClick={(e) => e.stopPropagation()}>
                  {q.file_id && <DownloadButton supplierId={supplier.id} file={q} label="Adjunto" />}
                  <Button size="sm" variant="ghost" icon={<Trash2 size={16} />} onClick={() => ask({ path: `/suppliers/${supplier.id}/quotes/${q.id}`,
                    title: 'Eliminar cotización', message: `Se eliminará la cotización ${q.number}${q.file_name ? ' y su archivo adjunto' : ''}. Las demás no cambian.`,
                    done: 'Cotización eliminada' })}>Eliminar</Button>
                </span>) },
            ]} />
          )}
      </Card>
      {editing && <QuoteDialog supplier={supplier} quote={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); reload(); }} />}
      {dialog}
    </div>
  );
}

// ------------------------------------------------------------------ lista de productos (Excel)
function ProductsTab({ supplierId, onChange }: { supplierId: number; onChange: () => void }) {
  const { notify } = useToast();
  const files = useApi<any[]>(`/suppliers/${supplierId}/files`);
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const reload = () => { files.reload(); onChange(); };
  const { ask, dialog } = useDelete(reload);
  const current = files.data?.[0];

  const send = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    const form = new FormData();
    form.append('file', file);
    try {
      await upload(`/suppliers/${supplierId}/files`, form);
      notify('success', current ? 'Lista reemplazada' : 'Lista cargada', current ? 'La versión anterior se conserva en el historial.' : file.name);
      reload();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = '';
    }
  };

  return (
    <div className="stack">
      <Card title="Lista de productos del proveedor">
        <div className="card-body stack">
          <ErrorAlert error={error} title="No se pudo cargar el archivo" />
          {current ? (
            <div className="row" style={{ flexWrap: 'wrap', gap: 12, alignItems: 'center' }}>
              <FileSpreadsheet size={28} aria-hidden />
              <span className="grow"><strong>{current.original_name}</strong><br />
                <small className="muted">Cargado el {dateTime(current.uploaded_at)} · {kb(current.size_bytes)} · versión {current.version}</small></span>
              {current.available ? <DownloadButton supplierId={supplierId} file={current} label="Descargar original" />
                : <Badge kind="danger">Archivo no encontrado en el disco</Badge>}
            </div>
          ) : <p className="muted">Todavía no hay una lista de productos para este proveedor.</p>}
          <input ref={input} type="file" accept=".xlsx,.xls,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
            style={{ display: 'none' }} onChange={(e) => void send(e.target.files?.[0])} aria-label="Elegir archivo de Excel" />
          <div className="form-actions" style={{ justifyContent: 'flex-start' }}>
            <Button variant="primary" busy={busy} icon={<Upload size={20} />} onClick={() => input.current?.click()}>
              {current ? 'Reemplazar por una versión nueva' : 'Subir archivo de Excel'}</Button>
          </div>
          <p className="muted">Formatos .xlsx o .xls. El archivo solo se guarda para consulta y descarga: no se importa al inventario.
            Para importar productos use Inventario › Importar.</p>
        </div>
      </Card>
      {files.data && files.data.length > 0 && (
        <Card title="Versiones">
          <DataTable caption="Versiones de la lista de productos" rows={files.data} rowKey={(f: any) => f.id} columns={[
            { key: 'v', header: 'Versión', render: (f: any) => <>{f.version}{f.current && <> <Badge kind="success">Vigente</Badge></>}</> },
            { key: 'n', header: 'Archivo', render: (f: any) => f.original_name },
            { key: 'd', header: 'Cargado', render: (f: any) => dateTime(f.uploaded_at) },
            { key: 's', header: 'Tamaño', numeric: true, render: (f: any) => kb(f.size_bytes) },
            { key: 'x', header: 'Acciones', render: (f: any) => (
              <span className="row" style={{ gap: 6 }}>
                {f.available ? <DownloadButton supplierId={supplierId} file={f} /> : <Badge kind="danger">No disponible</Badge>}
                <Button size="sm" variant="ghost" icon={<Trash2 size={16} />} onClick={() => ask({ path: `/suppliers/${supplierId}/files/${f.id}`,
                  title: 'Eliminar archivo', message: `Se eliminará definitivamente «${f.original_name}» (versión ${f.version}). Las demás versiones se conservan.`,
                  done: 'Archivo eliminado' })}>Eliminar</Button>
              </span>) },
          ]} />
        </Card>
      )}
      {files.error && <ErrorState error={files.error} onRetry={files.reload} />}
      {dialog}
    </div>
  );
}

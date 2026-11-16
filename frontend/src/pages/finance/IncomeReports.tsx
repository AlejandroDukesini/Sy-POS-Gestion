import { CalendarRange, FileDown, FileSpreadsheet, Pencil, Plus, Printer, RefreshCw, Save, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { Link, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { ApiError, del, download, newKey, post, put, qs } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { ConfirmDialog, Dialog } from '../../components/ui/Dialog';
import { Alert, Badge, EmptyState, ErrorAlert, ErrorState, Loading } from '../../components/ui/Feedback';
import { Checkbox, NumberField, SelectField, TextArea, TextField } from '../../components/ui/Form';
import { Card, Metric, PageHeader, Tabs } from '../../components/ui/Layout';
import { DataTable } from '../../components/ui/Table';
import { useAuth } from '../../context/Auth';
import { useToast } from '../../context/Toast';
import { date, dateTime, money, toApiNumber } from '../../lib/format';
import { useApi, useDebounced } from '../../lib/hooks';
import { FinanceBack } from './FinanceRoutes';

export const REPORT_KINDS: Record<string, string> = {
  diario: 'Diario', semanal: 'Semanal', mensual: 'Mensual', anual: 'Anual', personalizado: 'Personalizado',
};
export const NOTE_CATEGORIES: Record<string, string> = {
  general: 'Observación general', incidencia: 'Incidencia', diferencia_caja: 'Diferencia de caja',
  aclaracion: 'Aclaración sobre ingresos', extraordinaria: 'Situación extraordinaria',
};
const WEEKDAYS = ['lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo'];
const WEEKDAY_LABEL = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo'];
const MONTHS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
const opts = (map: Record<string, string>) => Object.entries(map).map(([value, label]) => ({ value, label }));
const num = (v: string | null | undefined) => Number(v ?? 0);
/** Día de la semana (0 = lunes) de una fecha AAAA-MM-DD, sin depender de la zona horaria del navegador. */
const weekday = (d: string) => (new Date(`${d}T12:00:00Z`).getUTCDay() + 6) % 7;
const dayLabel = (d: string) => `${WEEKDAY_LABEL[weekday(d)]} ${date(d)}`;
/** Importe en negativo para mostrar restas ("0.00" queda en cero, sin «-$ 0»). */
const neg = (v: string) => (num(v) ? `-${v}` : '0');
const shiftDays = (d: string, n: number) => new Date(Date.parse(`${d}T12:00:00Z`) + n * 86400000).toISOString().slice(0, 10);

export default function IncomeReportsRoutes() {
  return (
    <Routes>
      <Route index element={<ReportsHome />} />
      <Route path=":id" element={<SavedReport />} />
    </Routes>
  );
}

// ------------------------------------------------------------------ inicio: accesos rápidos, generación e historial
interface Request { kind: string; date_from: string; date_to: string }

function ReportsHome() {
  const presets = useApi<any>('/finance/reports/presets');
  const [request, setRequest] = useState<Request | null>(null);
  const [preview, setPreview] = useState<any>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const generate = async (r: Request) => {
    setRequest(r);
    setBusy(true);
    setError(null);
    try {
      setPreview(await post('/finance/reports/preview', r));
      setTimeout(() => document.getElementById('vista-previa')?.scrollIntoView?.({ behavior: 'smooth', block: 'start' }), 50);
    } catch (e) {
      setPreview(null);
      setError(e as ApiError);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="stack">
      <FinanceBack abbr="INF" title="Informes de ingresos" />
      <p className="muted">
        Cuánto dinero ingresó al negocio en un periodo. Las cifras salen de las ventas, cobros y devoluciones registrados;
        generar o guardar un informe nunca modifica ventas, caja, cartera ni inventario.
      </p>
      <Card title="Accesos rápidos">
        <div className="card-body">
          {presets.loading && !presets.data ? <Loading /> : presets.error ? <ErrorState error={presets.error} onRetry={presets.reload} /> : (
            <>
              <div className="preset-grid">
                {presets.data.presets.map((p: any) => (
                  <button key={p.key} type="button" className="preset" disabled={busy}
                    aria-pressed={request?.date_from === p.date_from && request?.date_to === p.date_to && request?.kind === p.kind}
                    onClick={() => generate({ kind: p.kind, date_from: p.date_from, date_to: p.date_to })}>
                    <strong>{p.label}</strong>
                    <span className="muted">{p.date_from === p.date_to ? date(p.date_from) : `${date(p.date_from)} – ${date(p.date_to)}`}</span>
                  </button>
                ))}
              </div>
              <p className="muted" style={{ marginTop: 12 }}>
                La semana del negocio empieza el <strong>{presets.data.week_start_label}</strong>. Cámbielo en
                Gestión › Ventas e inventario › Informes financieros.
              </p>
            </>
          )}
        </div>
      </Card>
      <CustomForm busy={busy} onGenerate={generate} weekStart={presets.data?.week_start ?? 'lunes'} today={presets.data?.today} />
      {error && <ErrorAlert error={error} title="No se pudo generar el informe" />}
      {preview && request && <div id="vista-previa"><PreviewPanel preview={preview} request={request} /></div>}
      <History />
    </div>
  );
}

function CustomForm({ busy, onGenerate, weekStart, today }: { busy: boolean; onGenerate: (r: Request) => void; weekStart: string; today?: string }) {
  const [f, setF] = useState({ kind: 'personalizado', date_from: '', date_to: today ?? '' });
  const set = (k: keyof typeof f) => (v: string) => setF((x) => ({ ...x, [k]: v }));
  const ws = WEEKDAYS.indexOf(weekStart);
  const hints: Record<string, string> = {
    diario: 'Un solo día: la fecha inicial y la final son la misma.',
    semanal: `Empieza el ${WEEKDAY_LABEL[ws]}. Si termina antes del ${WEEKDAY_LABEL[(ws + 6) % 7]}, queda como cierre anticipado.`,
    mensual: 'Desde el día 1. Si termina antes del último día del mes, queda como cierre anticipado.',
    anual: 'Desde el 1 de enero. Si termina antes del 31 de diciembre, queda como cierre anticipado.',
    personalizado: 'Cualquier intervalo (por ejemplo, del 5 al 18 de noviembre).',
  };
  return (
    <Card title="Generar un informe">
      <form className="card-body stack" onSubmit={(e) => { e.preventDefault(); if (f.date_from && f.date_to) onGenerate({ ...f }); }}>
        <div className="form-grid">
          <SelectField label="Tipo de informe" value={f.kind} onChange={set('kind')} options={opts(REPORT_KINDS)} hint={hints[f.kind]} />
          <TextField label="Fecha inicial" type="date" required value={f.date_from} onChange={set('date_from')} max={today} />
          <TextField label="Fecha final" type="date" required value={f.date_to} onChange={set('date_to')} max={today} />
        </div>
        <p className="muted">El intervalo elegido manda sobre el periodo habitual: puede cerrar la semana el viernes o generar
          informes de periodos pasados. El nombre y las observaciones se agregan al guardarlo.</p>
        <div className="row"><Button type="submit" variant="primary" busy={busy} icon={<CalendarRange size={18} />}>Generar informe</Button></div>
      </form>
    </Card>
  );
}

function PreviewPanel({ preview, request }: { preview: any; request: Request }) {
  const { can } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const [name, setName] = useState(preview.suggested_name);
  const [notes, setNotes] = useState('');
  const [key] = useState(newKey);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);
  const [lastName, setLastName] = useState(preview.suggested_name);
  if (lastName !== preview.suggested_name) {  // otro periodo: proponer su nombre
    setLastName(preview.suggested_name);
    setName(preview.suggested_name);
  }
  const save = async (allowSame: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const saved = await post('/finance/reports', { ...request, name: name.trim() || undefined, notes: notes.trim() || undefined,
        allow_same_period: allowSame }, allowSame ? newKey() : key);
      toast.notify('success', `Informe ${saved.number} guardado`);
      navigate(`/finanzas/informes/${saved.id}`);
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 409) setConflict(err.message);
      else setError(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="stack">
      <Card title="Vista previa (sin guardar)">
        <div className="card-body stack">
          <ReportView period={preview.period} data={preview.data} />
          {can('finanzas.cierres') ? (
            <div className="stack no-print">
              <h3>Guardar el informe</h3>
              {preview.same_period?.length > 0 && (
                <Alert kind="warning" title="Ya hay un informe de este mismo periodo">
                  {preview.same_period.map((r: any) => `${r.number} · ${r.name}`).join('; ')}. Guárdelo solo si es un cierre independiente.
                </Alert>
              )}
              <TextField label="Nombre del informe" value={name} onChange={setName} maxLength={160} hint="Opcional: se propone uno según el periodo." />
              <TextArea label="Observaciones" value={notes} onChange={setNotes} maxLength={4000}
                hint="Opcional: incidencias, diferencias de caja, aclaraciones. Puede agregar más después." />
              <ErrorAlert error={error} title="No se pudo guardar" />
              <div className="row"><Button variant="primary" icon={<Save size={18} />} busy={busy} onClick={() => save(false)}>Guardar informe</Button></div>
            </div>
          ) : <p className="muted">Para guardar informes necesita el permiso «Guardar informes de ingresos».</p>}
        </div>
      </Card>
      <ConfirmDialog open={conflict !== null} title="Informe del mismo periodo" busy={busy}
        message={<><p>{conflict}</p><p>Se guardará como un cierre independiente y ambos quedarán en el historial, identificados con su número y hora de generación.</p></>}
        confirmLabel="Guardar como cierre independiente" onClose={() => setConflict(null)}
        onConfirm={() => { setConflict(null); void save(true); }} />
    </div>
  );
}

function History() {
  const navigate = useNavigate();
  const [f, setF] = useState({ kind: '', date_from: '', date_to: '', q: '', include_replaced: false });
  const q = useDebounced(f.q);
  const list = useApi<any>(`/finance/reports${qs({ ...f, q })}`);
  const set = (k: keyof typeof f) => (v: any) => setF((x) => ({ ...x, [k]: v }));
  return (
    <Card title="Historial de informes">
      <div className="card-body stack">
        <div className="form-grid">
          <TextField label="Buscar" value={f.q} onChange={set('q')} placeholder="Nombre o número" />
          <SelectField label="Tipo" value={f.kind} onChange={set('kind')} placeholder="Todos" options={opts(REPORT_KINDS)} />
          <TextField label="Periodo desde" type="date" value={f.date_from} onChange={set('date_from')} />
          <TextField label="Periodo hasta" type="date" value={f.date_to} onChange={set('date_to')} />
        </div>
        <Checkbox label="Incluir versiones reemplazadas por revisiones" checked={f.include_replaced} onChange={set('include_replaced')} />
        {list.loading && !list.data ? <Loading /> : list.error ? <ErrorState error={list.error} onRetry={list.reload} /> : !list.data.items.length ? (
          <EmptyState title="Sin informes guardados">Genere un informe y pulse «Guardar informe» para conservarlo aquí.</EmptyState>
        ) : (
          <DataTable caption="Informes guardados" rows={list.data.items} rowKey={(r: any) => r.id}
            onSelect={(r: any) => navigate(`/finanzas/informes/${r.id}`)} columns={[
              { key: 'number', header: 'Número', render: (r: any) => <Link to={`/finanzas/informes/${r.id}`}>{r.number}</Link> },
              { key: 'name', header: 'Informe', render: (r: any) => (
                <span>{r.name}{' '}
                  {r.revision > 1 && <Badge kind="info">Revisión {r.revision}</Badge>}{' '}
                  {r.status !== 'vigente' && <Badge>Reemplazado</Badge>}{' '}
                  {r.same_period_count > 0 && <Badge kind="warning">Mismo periodo que otro cierre</Badge>}
                </span>) },
              { key: 'kind', header: 'Tipo', render: (r: any) => r.kind_label },
              { key: 'period', header: 'Periodo', render: (r: any) => (r.date_from === r.date_to ? date(r.date_from) : `${date(r.date_from)} – ${date(r.date_to)}`) },
              { key: 'closure', header: 'Cierre', render: (r: any) => (
                <Badge kind={r.closure === 'anticipado' ? 'warning' : r.closure === 'habitual' ? 'success' : undefined}>{r.closure_label}</Badge>) },
              { key: 'generated', header: 'Generado', render: (r: any) => dateTime(r.generated_at) },
              { key: 'total', header: 'Total recibido', numeric: true, render: (r: any) => money(r.total_received) },
              { key: 'notes', header: 'Observaciones', numeric: true, render: (r: any) => r.notes_count || '—' },
            ]} />
        )}
      </div>
    </Card>
  );
}

// ------------------------------------------------------------------ informe guardado
function SavedReport() {
  const id = Number(useParams().id);
  const { can } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const rep = useApi<any>(`/finance/reports/${id}`);
  const [revising, setRevising] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  if (rep.loading && !rep.data) return <Loading />;
  if (rep.error) return <ErrorState error={rep.error} onRetry={rep.reload} />;
  const r = rep.data;
  const editable = r.status === 'vigente' && can('finanzas.cierres');
  const exportAs = async (fmt: 'pdf' | 'xlsx') => {
    setError(null);
    try {
      await download(`/finance/reports/${id}/export/${fmt}`, `${r.number}.${fmt}`);
    } catch (e) {
      setError(e as ApiError);
    }
  };
  const revise = async (reason: string) => {
    setBusy(true);
    try {
      const next = await post(`/finance/reports/${id}/revise`, { reason });
      setRevising(false);
      toast.notify('success', `Revisión ${next.revision} generada`, 'La versión anterior se conserva en el historial.');
      navigate(`/finanzas/informes/${next.id}`);
    } catch (e) {
      setRevising(false);
      setError(e as ApiError);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="stack">
      <div className="no-print">
        <Link to="/finanzas/informes" className="btn btn-ghost">← Informes</Link>
      </div>
      <p className="print-only"><strong>{r.company}</strong></p>
      <PageHeader title={r.name}
        description={`${r.number} · revisión ${r.revision} · generado el ${dateTime(r.generated_at)}${r.generated_by_name ? ` por ${r.generated_by_name}` : ''}`}
        actions={<span className="row no-print">
          <Button icon={<FileDown size={18} />} onClick={() => exportAs('pdf')}>PDF</Button>
          <Button icon={<FileSpreadsheet size={18} />} onClick={() => exportAs('xlsx')}>Excel</Button>
          <Button icon={<Printer size={18} />} onClick={() => window.print()}>Imprimir</Button>
        </span>} />
      <ErrorAlert error={error} title="No se pudo completar la operación" />
      {r.status !== 'vigente' && (
        <Alert kind="warning" title="Versión reemplazada">
          Este informe se conserva con sus cifras originales por trazabilidad.{' '}
          {r.replaced_by_id && <Link to={`/finanzas/informes/${r.replaced_by_id}`}>Abrir la revisión vigente</Link>}
        </Alert>
      )}
      {r.changed && r.status === 'vigente' && (
        <div className="no-print">
          <Alert kind="warning" title="Las operaciones del periodo cambiaron después de guardar este informe">
            <p>El informe guardado no se modifica. Diferencias con los datos actuales:</p>
            <ul>{r.changes.map((c: any) => (
              <li key={c.key}>{CHANGE_LABELS[c.key] ?? c.key}: guardado {typeof c.saved === 'string' ? money(c.saved) : c.saved} → actual{' '}
                {typeof c.current === 'string' ? money(c.current) : c.current}</li>
            ))}</ul>
            {can('finanzas.cierres') && <Button icon={<RefreshCw size={18} />} onClick={() => setRevising(true)}>Generar revisión con los datos actuales</Button>}
          </Alert>
        </div>
      )}
      {r.revisions.length > 1 && (
        <p className="muted no-print">Versiones: {r.revisions.map((v: any, i: number) => (
          <span key={v.id}>{i > 0 && ' · '}{v.id === r.id ? <strong>Revisión {v.revision}</strong>
            : <Link to={`/finanzas/informes/${v.id}`}>Revisión {v.revision} ({v.status})</Link>}</span>
        ))}</p>
      )}
      {r.same_period.length > 0 && (
        <Alert kind="info" title="Otros cierres del mismo periodo">
          {r.same_period.map((o: any, i: number) => (
            <span key={o.id}>{i > 0 && ' · '}<Link to={`/finanzas/informes/${o.id}`}>{o.number}</Link> ({dateTime(o.generated_at)},
              total {money(o.total_received)})</span>
          ))}. Son cierres independientes guardados por separado.
        </Alert>
      )}
      <ReportView period={r.period} data={r.data} />
      <NotesCard report={r} editable={editable} onChange={rep.reload} />
      <ConfirmDialog open={revising} title="Generar revisión" busy={busy} requireReason confirmLabel="Generar revisión"
        message={<p>Se creará la revisión {r.revision + 1} con los datos actuales y esta versión quedará como «reemplazada», sin cambiar sus
          cifras. Las observaciones se copian a la revisión nueva.</p>}
        onClose={() => setRevising(false)} onConfirm={revise} />
    </div>
  );
}

const CHANGE_LABELS: Record<string, string> = {
  net_sales: 'Ventas netas', total_received: 'Total recibido', returns: 'Devoluciones', refunds_paid: 'Reembolsos', sales_count: 'Cantidad de ventas',
};

function NotesCard({ report, editable, onChange }: { report: any; editable: boolean; onChange: () => void }) {
  const [editing, setEditing] = useState<any>(null);
  const [deleting, setDeleting] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const remove = async () => {
    setBusy(true);
    try {
      await del(`/finance/reports/${report.id}/notes/${deleting.id}`);
      toast.notify('success', 'Observación eliminada');
      setDeleting(null);
      onChange();
    } catch (e) {
      toast.notify('danger', 'No se pudo eliminar', (e as ApiError).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card title="Observaciones del administrador" actions={editable &&
      <Button size="sm" icon={<Plus size={16} />} onClick={() => setEditing({})} className="no-print">Agregar</Button>}>
      <div className="card-body stack">
        {!report.notes.length && <p className="muted">Sin observaciones.</p>}
        {report.notes.map((n: any) => (
          <div key={n.id} className="note-item">
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <span><Badge kind={n.category === 'diferencia_caja' ? 'warning' : n.category === 'incidencia' ? 'danger' : 'info'}>{n.category_label}</Badge>
                {n.amount !== null && <strong> {money(n.amount)}</strong>}</span>
              {editable && (
                <span className="row no-print">
                  <Button size="sm" variant="ghost" icon={<Pencil size={16} />} onClick={() => setEditing(n)}>Editar</Button>
                  <Button size="sm" variant="ghost" icon={<Trash2 size={16} />} onClick={() => setDeleting(n)}>Eliminar</Button>
                </span>
              )}
            </div>
            <p style={{ whiteSpace: 'pre-wrap', margin: '6px 0' }}>{n.body}</p>
            <p className="muted">{n.author || 'Sin autor'} · {dateTime(n.created_at)}{n.version > 1 && ` · editada el ${dateTime(n.updated_at)}`}
              {n.copied_from_id && ' · copiada de la versión anterior'}</p>
          </div>
        ))}
      </div>
      {editing && <NoteDialog reportId={report.id} note={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); onChange(); }} />}
      <ConfirmDialog open={deleting !== null} title="Eliminar observación" danger busy={busy} confirmLabel="Eliminar"
        message="La observación se quitará del informe (su texto queda en el historial de actividad). Las cifras del informe no cambian."
        onClose={() => setDeleting(null)} onConfirm={remove} />
    </Card>
  );
}

function NoteDialog({ reportId, note, onClose, onSaved }: { reportId: number; note: any; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [f, setF] = useState({ category: note.category ?? 'general', body: note.body ?? '', amount: note.amount ?? '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const set = (k: keyof typeof f) => (v: string) => setF((x) => ({ ...x, [k]: v }));
  const save = async () => {
    setBusy(true);
    setError(null);
    const body = { category: f.category, body: f.body, amount: f.amount === '' ? null : toApiNumber(String(f.amount)),
      ...(note.id ? { version: note.version } : {}) };
    try {
      if (note.id) await put(`/finance/reports/${reportId}/notes/${note.id}`, body);
      else await post(`/finance/reports/${reportId}/notes`, body);
      toast.notify('success', note.id ? 'Observación actualizada' : 'Observación agregada');
      onSaved();
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open title={note.id ? 'Editar observación' : 'Nueva observación'} onClose={onClose}
      footer={<><Button onClick={onClose}>Cancelar</Button><Button variant="primary" busy={busy} onClick={save}>Guardar</Button></>}>
      <div className="stack">
        <ErrorAlert error={error} />
        <SelectField label="Categoría" value={f.category} onChange={set('category')} options={opts(NOTE_CATEGORIES)} error={error?.fields?.category} />
        <TextArea label="Observación" required value={f.body} onChange={set('body')} maxLength={4000} error={error?.fields?.body} />
        <NumberField label="Importe relacionado" value={f.amount} onChange={set('amount')} error={error?.fields?.amount}
          hint="Opcional (ej.: -2.000 si faltó dinero en caja). Es informativo: no cambia las cifras del informe." />
      </div>
    </Dialog>
  );
}

// ------------------------------------------------------------------ contenido del informe (vista previa y guardado)
export function ReportView({ period: p, data: d }: { period: any; data: any }) {
  const s = d.summary;
  const a = d.activity;
  const range = p.date_from === p.date_to ? date(p.date_from) : `del ${date(p.date_from)} al ${date(p.date_to)}`;
  return (
    <div className="stack">
      <div className="row">
        <Badge kind={p.closure === 'anticipado' ? 'warning' : p.closure === 'habitual' ? 'success' : undefined}>{p.closure_label}</Badge>
        <Badge>{p.kind_label}</Badge>
        <span>Periodo {range} · {p.days} día(s)</span>
      </div>
      {p.closure === 'anticipado' && (
        <Alert kind="warning" title="Cierre anticipado">
          Cubre {p.days} de {p.period_days} días del periodo {p.kind_label.toLowerCase()} (que termina el {date(p.natural_end)}). No es un periodo completo.
        </Alert>
      )}
      {p.in_progress && <Alert kind="info">El periodo incluye hoy: las operaciones registradas después de generar el informe no están incluidas.</Alert>}
      <div className="metrics">
        <Metric label="Total de ingresos recibidos" value={money(s.total_received)} hint="Dinero que efectivamente entró" />
        <Metric label="Ingresos netos por ventas" value={money(s.net_sales)} hint="Ventas registradas − devoluciones" />
        <Metric label="Ventas" value={s.sales_count} hint={a.average_ticket !== null ? `Ticket promedio ${money(a.average_ticket)}` : 'Sin ventas'} />
        <Metric label="Comparación" value={<Change row={d.comparison.rows[1]} />}
          hint={`vs. ${date(d.comparison.date_from)} – ${date(d.comparison.date_to)}`} />
      </div>
      <div className="grid-2">
        <Card title="Ventas registradas">
          <AmountTable rows={[
            ['Ingresos brutos por ventas', s.gross_sales],
            ['Descuentos aplicados', neg(s.discounts)],
            ['Ventas registradas', s.sales_total, true],
            [`Devoluciones (${s.returns_count})`, neg(s.returns)],
            ['Ingresos netos por ventas', s.net_sales, true],
            ['De las ventas, a crédito (no cobrado en la venta)', s.credit_sales],
            ['Otros ingresos registrados (no ventas)', s.other_income_registered],
          ]} />
          {s.voided_count > 0 && <p className="card-body muted">{s.voided_count} venta(s) anulada(s) por {money(s.voided_total)}: no suman.</p>}
        </Card>
        <Card title="Dinero efectivamente recibido">
          <AmountTable rows={[
            ['Cobrado en las ventas (sin crédito)', s.received_sales],
            ['Cobros de cartera', s.collections],
            ['Otros ingresos recibidos', s.other_income_received],
            ['Reembolsos pagados', neg(s.refunds_paid)],
            ['Total de ingresos recibidos', s.total_received, true],
          ]} />
        </Card>
      </div>
      <div className="grid-2">
        <Card title="Distribución por método de pago">
          <div className="card-body">
            {d.by_kind.length ? <Bars caption="Ingreso neto por método de pago" items={d.by_kind.map((k: any) => ({ label: k.label, value: num(k.net) }))} share />
              : <p className="muted">Sin ingresos en el periodo.</p>}
          </div>
        </Card>
        <Card title="Actividad">
          <AmountTable rows={[
            ['Cantidad de ventas', String(a.sales_count), false, true],
            ['Ticket promedio', a.average_ticket ?? null],
            ['Días con movimientos', `${a.days_with_activity} de ${p.days}`, false, true],
            [a.best_day ? `Día con mayores ingresos (${dayLabel(a.best_day.day)})` : 'Día con mayores ingresos', a.best_day?.received ?? null],
            [a.worst_day ? `Día con menores ingresos (${dayLabel(a.worst_day.day)})` : 'Día con menores ingresos', a.worst_day?.received ?? null],
          ]} />
        </Card>
      </div>
      <IncomeChart days={d.by_day} weekStart={p.week_start} />
      <Card title={`Comparación con el periodo anterior equivalente (${date(d.comparison.date_from)} – ${date(d.comparison.date_to)})`}>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Indicador</th><th className="num">Este periodo</th><th className="num">Periodo anterior</th><th className="num">Diferencia</th><th className="num">Variación</th></tr></thead>
            <tbody>{d.comparison.rows.map((r: any) => (
              <tr key={r.key}><td>{r.label}</td>
                <td className="num">{r.is_money ? money(r.current) : r.current}</td>
                <td className="num">{r.is_money ? money(r.previous) : r.previous}</td>
                <td className="num">{r.is_money ? money(r.difference) : r.difference}</td>
                <td className="num"><Change row={r} /></td></tr>
            ))}</tbody>
          </table>
        </div>
        {d.comparison.previous_empty && <p className="card-body muted">El periodo anterior no tiene ventas ni ingresos: no se calcula variación porcentual.</p>}
      </Card>
      <Card title="Desglose por método de pago">
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Método</th><th className="num">Ventas</th><th className="num">Cobros de cartera</th><th className="num">Reembolsos</th><th className="num">Neto recibido</th></tr></thead>
            <tbody>
              {d.by_method.map((m: any) => (
                <tr key={m.method_id}><td>{m.name}</td><td className="num">{money(m.sales)}</td><td className="num">{money(m.collections)}</td>
                  <td className="num">{money(neg(m.refunds))}</td><td className="num">{money(m.net)}</td></tr>
              ))}
              {num(s.other_income_received) !== 0 && <tr><td>Otros ingresos (no ventas)</td><td className="num">—</td><td className="num">—</td><td className="num">—</td><td className="num">{money(s.other_income_received)}</td></tr>}
              {!d.by_method.length && num(s.other_income_received) === 0 && <tr><td colSpan={5} className="muted">Sin pagos en el periodo.</td></tr>}
            </tbody>
            <tfoot><tr><td>Total</td><td className="num">{money(s.received_sales)}</td><td className="num">{money(s.collections)}</td>
              <td className="num">{money(neg(s.refunds_paid))}</td><td className="num">{money(s.total_received)}</td></tr></tfoot>
          </table>
        </div>
      </Card>
      <DaysTable days={d.by_day} total={s} />
      {d.other_income.length > 0 && (
        <Card title="Otros ingresos registrados (asientos)">
          <div className="table-wrap"><table className="table">
            <thead><tr><th>Fecha</th><th>Descripción</th><th className="num">Registrado</th><th className="num">Recibido</th></tr></thead>
            <tbody>{d.other_income.map((o: any, i: number) => (
              <tr key={i}><td>{date(o.date)}</td><td>{o.description}</td><td className="num">{money(o.registered)}</td><td className="num">{money(o.received)}</td></tr>
            ))}</tbody>
          </table></div>
        </Card>
      )}
      <CashCheck check={d.cash_check} />
    </div>
  );
}

function AmountTable({ rows }: { rows: [string, string | null, boolean?, boolean?][] }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <tbody>{rows.map(([label, value, strong, plain]) => {
          const shown = value === null ? '—' : plain ? value : money(value);
          return <tr key={label}><td>{strong ? <strong>{label}</strong> : label}</td><td className="num">{strong ? <strong>{shown}</strong> : shown}</td></tr>;
        })}</tbody>
      </table>
    </div>
  );
}

function Change({ row }: { row: any }) {
  if (!row || row.change_pct === null) return <span className="muted">—</span>;
  const v = Number(row.change_pct);
  return <span>{v > 0 ? '▲' : v < 0 ? '▼' : '='} {`${row.change_pct.replace('.', ',')} %`}</span>;
}

function CashCheck({ check }: { check: any }) {
  const diff = num(check.difference);
  return (
    <Card title="Verificación con el libro de caja y bancos">
      <div className="card-body stack">
        <AmountTable rows={[
          ['Calculado desde ventas, cobros y reembolsos', check.operational],
          ['Movimiento de caja y bancos en el libro diario', check.journal],
          ['Diferencia', check.difference, true],
        ]} />
        {diff === 0
          ? <Alert kind="success">El cálculo coincide con el libro de caja y bancos.</Alert>
          : <Alert kind="warning" title="Hay una diferencia">
              Suele deberse a ventas o cobros anulados en una fecha distinta a la original (el libro registra el reverso el día de la
              anulación). Se muestra para que pueda explicarla en las observaciones; no se corrige automáticamente.
            </Alert>}
      </div>
    </Card>
  );
}

function DaysTable({ days, total }: { days: any[]; total: any }) {
  return (
    <Card title="Detalle de ingresos por día">
      {!days.length ? <p className="card-body muted">Sin movimientos en el periodo.</p> : (
        <div className="table-wrap"><table className="table">
          <caption className="sr-only">Ingresos por día (solo días con movimientos)</caption>
          <thead><tr><th>Día</th><th className="num">Ventas</th><th className="num">Ventas registradas</th><th className="num">Devoluciones</th><th className="num">Ingresos recibidos</th></tr></thead>
          <tbody>{days.map((x) => (
            <tr key={x.day}><td>{dayLabel(x.day)}</td><td className="num">{x.sales}</td><td className="num">{money(x.sales_total)}</td>
              <td className="num">{money(neg(x.returns))}</td><td className="num">{money(x.received)}</td></tr>
          ))}</tbody>
          <tfoot><tr><td>Total</td><td className="num">{total.sales_count}</td><td className="num">{money(total.sales_total)}</td>
            <td className="num">{money(neg(total.returns))}</td><td className="num">{money(total.total_received)}</td></tr></tfoot>
        </table></div>
      )}
      {days.length > 0 && <p className="card-body muted">Solo se listan los días con movimientos; los demás no tuvieron ventas, cobros ni devoluciones.</p>}
    </Card>
  );
}

// ------------------------------------------------------------------ gráficos (datos reales del informe)
type Grain = 'dia' | 'semana' | 'mes';

function IncomeChart({ days, weekStart }: { days: any[]; weekStart: string }) {
  const [grain, setGrain] = useState<Grain>(days.length > 31 ? 'semana' : 'dia');
  if (!days.length) return null;
  const ws = Math.max(0, WEEKDAYS.indexOf(weekStart));
  const groups = new Map<string, { label: string; value: number }>();
  for (const x of days) {
    let key = x.day;
    let label = dayLabel(x.day);
    if (grain === 'semana') {
      key = shiftDays(x.day, -((weekday(x.day) - ws + 7) % 7));
      label = `Semana del ${date(key)}`;
    } else if (grain === 'mes') {
      key = x.day.slice(0, 7);
      label = `${MONTHS[Number(key.slice(5, 7)) - 1]} ${key.slice(0, 4)}`;
    }
    const g = groups.get(key) ?? { label, value: 0 };
    g.value += num(x.received);
    groups.set(key, g);
  }
  const items = [...groups.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([, g]) => g);
  return (
    <Card title="Ingresos recibidos" actions={<span className="no-print"><Tabs label="Agrupar por" value={grain} onChange={setGrain} tabs={[
      { value: 'dia', label: 'Día' }, { value: 'semana', label: 'Semana' }, { value: 'mes', label: 'Mes' }]} /></span>}>
      <div className="card-body">
        <Bars caption="Ingresos recibidos por periodo (solo periodos con movimientos)" items={items} />
      </div>
    </Card>
  );
}

/** Barras horizontales de una sola serie: etiqueta, barra y valor siempre visibles (no depende del color ni del puntero). */
function Bars({ items, caption, share }: { items: { label: string; value: number }[]; caption: string; share?: boolean }) {
  const max = Math.max(...items.map((i) => Math.abs(i.value)), 0);
  const total = items.reduce((t, i) => t + i.value, 0);
  return (
    <figure className="hbars" aria-label={caption}>
      {items.map((i) => {
        const width = max > 0 ? Math.max(1, (Math.abs(i.value) / max) * 100) : 0;
        const pct = share && total > 0 && i.value > 0 ? ` · ${Math.round((i.value / total) * 100)} %` : '';
        return (
          <div key={i.label} className="hbar" title={`${i.label}: ${money(i.value)}${pct}`}>
            <span className="hbar-label">{i.label}</span>
            <span className="hbar-track" aria-hidden><span className={`hbar-fill${i.value < 0 ? ' negative' : ''}`} style={{ width: `${width}%` }} /></span>
            <span className="hbar-value">{money(i.value)}{pct}</span>
          </div>
        );
      })}
    </figure>
  );
}

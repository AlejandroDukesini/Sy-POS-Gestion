import { ClipboardList, Eye, Pencil, Plus, RotateCcw, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { Route, Routes, useNavigate, useSearchParams } from 'react-router-dom';
import { post, qs } from '../../../api/client';
import { Button } from '../../../components/ui/Button';
import { ConfirmDialog } from '../../../components/ui/Dialog';
import { EmptyState, ErrorState, Loading } from '../../../components/ui/Feedback';
import { SelectField, TextField } from '../../../components/ui/Form';
import { Card, Metric, Tabs } from '../../../components/ui/Layout';
import { DataTable, Pagination, type Column } from '../../../components/ui/Table';
import { useAuth } from '../../../context/Auth';
import { useToast } from '../../../context/Toast';
import { date, dateTime } from '../../../lib/format';
import { useApi, useDebounced } from '../../../lib/hooks';
import { ObservationDetail } from './ObservationDetail';
import { ObservationForm, useObservationMeta, type ObservationMeta } from './ObservationForm';
import { PriorityBadge, StatusBadge, type Observation } from './labels';

const QUICK = [
  { value: 'todas', label: 'Todas' }, { value: 'pendientes', label: 'Pendientes' }, { value: 'criticas', label: 'Críticas' },
  { value: 'en_proceso', label: 'En proceso' }, { value: 'resueltas', label: 'Resueltas' }, { value: 'recientes', label: 'Recientes' },
] as const;
type Quick = (typeof QUICK)[number]['value'];
const SORTS = [
  { value: 'recientes', label: 'Más recientes' }, { value: 'antiguas', label: 'Más antiguas' },
  { value: 'prioridad', label: 'Mayor prioridad' }, { value: 'producto', label: 'Producto' }, { value: 'estado', label: 'Estado' },
];
const EMPTY = { q: '', category_id: '', priority: '', status: '', responsible_id: '', supplier_id: '', date_from: '', date_to: '' };

export default function ObservationsRoutes() {
  const meta = useObservationMeta();
  if (meta.loading && !meta.data) return <Loading />;
  if (meta.error) return <ErrorState error={meta.error} onRetry={meta.reload} />;
  return (
    <Routes>
      <Route index element={<ObservationsList meta={meta.data!} />} />
      <Route path=":id" element={<ObservationDetail meta={meta.data!} />} />
    </Routes>
  );
}

function ObservationsList({ meta }: { meta: ObservationMeta }) {
  const { can } = useAuth();
  const { notify } = useToast();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const productId = params.get('producto');
  const [quick, setQuick] = useState<Quick>('todas');
  const [f, setF] = useState(EMPTY);
  const [sort, setSort] = useState('recientes');
  const [page, setPage] = useState(1);
  const [form, setForm] = useState<Observation | 'new' | null>(params.get('nueva') ? 'new' : null);
  const [deleting, setDeleting] = useState<Observation | null>(null);
  const [busy, setBusy] = useState(false);
  const q = useDebounced(f.q.trim(), 300);
  const list = useApi(`/observations${qs({ ...f, q, product_id: productId, quick, sort, page, page_size: 25 })}`);
  const set = (k: keyof typeof EMPTY) => (v: string) => { setF((x) => ({ ...x, [k]: v })); setPage(1); };
  const filtered = Object.values(f).some(Boolean) || Boolean(productId);
  const m = list.data?.metrics;

  const remove = async (reason: string) => {
    if (!deleting) return;
    setBusy(true);
    try {
      await post(`/observations/${deleting.id}/delete`, { reason });
      notify('success', 'Observación eliminada', `${deleting.code}: el historial se conserva en la auditoría.`);
      setDeleting(null);
      list.reload();
    } catch (err) {
      notify('danger', 'No se pudo eliminar', (err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const clearProduct = () => { params.delete('producto'); setParams(params); setPage(1); };

  const columns: Column<Observation>[] = [
    { key: 'code', header: 'ID', render: (o) => <strong className="nowrap">{o.code}</strong> },
    { key: 'created_at', header: 'Fecha', render: (o) => <span className="nowrap">{dateTime(o.created_at)}</span> },
    { key: 'product', header: 'Producto', render: (o) => <span className="obs-clip">{o.product_description}</span> },
    { key: 'product_code', header: 'Código', render: (o) => <span className="nowrap">{o.product_code}</span> },
    { key: 'category', header: 'Categoría', render: (o) => o.category_name },
    { key: 'priority', header: 'Prioridad', render: (o) => <PriorityBadge priority={o.priority} /> },
    { key: 'description', header: 'Descripción', render: (o) => <span className="obs-clip" title={o.description}>{o.description}</span> },
    { key: 'responsible', header: 'Responsable', render: (o) => o.responsible_name ?? '—' },
    { key: 'status', header: 'Estado', render: (o) => (
      <span className="row" style={{ gap: 6, flexWrap: 'nowrap' }}>
        <StatusBadge status={o.status} />
        {o.follow_up_overdue && <span className="badge badge-warning" title={`Fecha límite: ${date(o.follow_up_date)}`}>Vencida</span>}
      </span>) },
    { key: 'actions', header: 'Acciones', render: (o) => (
      <span className="row" style={{ gap: 4, flexWrap: 'nowrap' }} onClick={(e) => e.stopPropagation()}>
        <Button size="sm" variant="ghost" iconOnly icon={<Eye size={18} />} onClick={() => navigate(String(o.id))}>Consultar {o.code}</Button>
        {can('observaciones.editar') && (
          <Button size="sm" variant="ghost" iconOnly icon={<Pencil size={18} />} onClick={() => setForm(o)}>Editar {o.code}</Button>)}
        {can('observaciones.eliminar') && (
          <Button size="sm" variant="ghost" iconOnly icon={<Trash2 size={18} />} onClick={() => setDeleting(o)}>Eliminar {o.code}</Button>)}
      </span>) },
  ];

  const opts = <T,>(list: T[], v: (x: T) => number | string, l: (x: T) => string) => list.map((x) => ({ value: v(x), label: l(x) }));
  return (
    <div className="stack">
      {m && (
        <div className="metrics" aria-label="Indicadores de observaciones">
          <Metric label="Total de observaciones" value={m.total} />
          <Metric label="Pendientes" value={m.pendiente} />
          <Metric label="En proceso" value={m.en_proceso} />
          <Metric label="Resueltas" value={m.resuelta} hint={m.cerrada ? `${m.cerrada} cerradas` : undefined} />
          <Metric label="Críticas abiertas" value={<span className={m.criticas ? 'obs-critical-value' : undefined}>{m.criticas}</span>}
            hint={m.criticas ? 'Requieren atención' : 'Sin alertas'} />
          <Metric label={`Recientes (${meta.recent_days} días)`} value={m.recientes}
            hint={m.seguimiento_vencido ? `${m.seguimiento_vencido} con seguimiento vencido` : undefined} />
        </div>
      )}
      <Card title={<h2 className="row"><ClipboardList size={22} aria-hidden /> Observaciones de inventario</h2>} actions={
        can('observaciones.crear') && <Button variant="primary" icon={<Plus size={20} />} onClick={() => setForm('new')}>Nueva observación</Button>}>
        <div className="card-body stack" style={{ paddingBottom: 0 }}>
          <Tabs label="Filtros rápidos" value={quick} onChange={(v) => { setQuick(v); setPage(1); }} tabs={[...QUICK]} />
          {productId && list.data && (
            <div className="row">
              <span className="badge badge-info">Producto filtrado{list.data.items[0] ? `: ${list.data.items[0].product_code}` : ''}</span>
              <Button size="sm" variant="ghost" onClick={clearProduct}>Ver todos los productos</Button>
            </div>
          )}
          <div className="obs-filters">
            <TextField label="Buscar" type="search" value={f.q} onChange={set('q')} autoComplete="off"
              placeholder="Producto, código, OBS-00012, documento…" />
            <SelectField label="Categoría" value={f.category_id} onChange={set('category_id')} placeholder="Todas"
              options={opts(meta.categories, (c) => c.id, (c) => c.name)} />
            <SelectField label="Prioridad" value={f.priority} onChange={set('priority')} placeholder="Todas" options={meta.priorities} />
            <SelectField label="Estado" value={f.status} onChange={set('status')} placeholder="Todos" options={meta.statuses} />
            <SelectField label="Responsable" value={f.responsible_id} onChange={set('responsible_id')} placeholder="Todos"
              options={opts(meta.users, (u) => u.id, (u) => u.full_name)} />
            <SelectField label="Proveedor" value={f.supplier_id} onChange={set('supplier_id')} placeholder="Todos"
              options={opts(meta.suppliers, (s) => s.id, (s) => s.name)} />
            <TextField label="Desde" type="date" value={f.date_from} onChange={set('date_from')} hint="Fecha de la novedad" />
            <TextField label="Hasta" type="date" value={f.date_to} onChange={set('date_to')} min={f.date_from || undefined} />
            <SelectField label="Ordenar por" value={sort} onChange={(v) => { setSort(v); setPage(1); }} options={SORTS} />
          </div>
          {filtered && (
            <div><Button size="sm" variant="ghost" icon={<RotateCcw size={16} />} onClick={() => { setF(EMPTY); clearProduct(); }}>
              Limpiar filtros</Button></div>
          )}
        </div>
        {list.loading && !list.data ? <Loading /> : list.error ? <ErrorState error={list.error} onRetry={list.reload} /> :
          list.data.items.length === 0 ? (
            <EmptyState title={filtered || quick !== 'todas' ? 'Ninguna observación coincide' : 'Aún no hay observaciones'}
              icon={<ClipboardList size={40} aria-hidden />}>
              {!filtered && quick === 'todas' && can('observaciones.crear') &&
                <p>Registre novedades como faltantes, productos defectuosos o diferencias de conteo con «Nueva observación».</p>}
            </EmptyState>
          ) : (
            <>
              <DataTable caption="Observaciones de inventario" columns={columns} rows={list.data.items as Observation[]}
                rowKey={(o) => o.id} onSelect={(o) => navigate(String(o.id))} />
              <Pagination page={list.data.page} pages={list.data.pages} total={list.data.total} onPage={setPage} />
            </>
          )}
      </Card>
      {form && (
        <ObservationForm meta={meta} observation={form === 'new' ? null : form} productId={productId ? Number(productId) : null}
          onClose={() => setForm(null)} onSaved={(o) => {
            setForm(null);
            if (form === 'new') navigate(String(o.id));
            else list.reload();
          }} />
      )}
      <ConfirmDialog open={Boolean(deleting)} title={`Eliminar ${deleting?.code ?? ''}`} danger requireReason busy={busy}
        confirmLabel="Eliminar observación" onClose={() => setDeleting(null)} onConfirm={remove}
        message={<p>La observación dejará de aparecer en los listados e indicadores. El registro, su historial y el motivo
          se conservan para auditoría. No se modifica el inventario.</p>} />
    </div>
  );
}

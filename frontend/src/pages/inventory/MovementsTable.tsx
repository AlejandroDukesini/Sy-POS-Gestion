import { CheckCircle2, XCircle } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ApiError, post, qs } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { Dialog } from '../../components/ui/Dialog';
import { Badge, EmptyState, ErrorAlert, ErrorState, Loading } from '../../components/ui/Feedback';
import { SelectField, TextField } from '../../components/ui/Form';
import { Card, Metric, Tabs } from '../../components/ui/Layout';
import { DataTable, Pagination } from '../../components/ui/Table';
import { useAuth } from '../../context/Auth';
import { useInventory } from '../../context/Inventory';
import { useToast } from '../../context/Toast';
import { dateTime, money, qty } from '../../lib/format';
import { useApi, useDebounced, useOnline } from '../../lib/hooks';
import { KIND_LABELS } from './InventoryPage';
import { CONDITION_KIND, CONDITION_LABELS } from './returnLabels';

type View = 'todos' | 'entradas' | 'salidas' | 'devoluciones';
type Filters = { date_from: string; date_to: string; product_id: string; user_id: string };


/**
 * Movimientos de inventario del inventario elegido: indicadores, entradas, salidas y devoluciones,
 * con filtros por fechas, producto y persona. Todo sale de la base del servidor y se recarga solo
 * cuando otra persona vende, anula, devuelve o mueve existencias.
 */
export function MovementsTable() {
  const { current } = useInventory();
  const [view, setView] = useState<View>('todos');
  const [f, setF] = useState<Filters>({ date_from: '', date_to: '', product_id: '', user_id: '' });
  const [page, setPage] = useState(1);
  const change = (patch: Partial<Filters>) => { setF((old) => ({ ...old, ...patch })); setPage(1); };
  const dash = useApi(`/inventory/dashboard${qs(f)}`);
  const d = dash.data;
  return (
    <div className="stack">
      <Card>
        <div className="card-body row">
          <div><TextField label="Desde" type="date" value={f.date_from} onChange={(v) => change({ date_from: v })} /></div>
          <div><TextField label="Hasta" type="date" value={f.date_to} onChange={(v) => change({ date_to: v })} /></div>
          <ProductFilter value={f.product_id} onChange={(v) => change({ product_id: v })} />
          <div style={{ minWidth: 200 }}>
            <SelectField label="Persona" value={f.user_id} onChange={(v) => change({ user_id: v })} placeholder="Todas"
              options={(d?.people ?? []).map((p: any) => ({ value: p.id, label: p.full_name }))} />
          </div>
        </div>
      </Card>
      {dash.error ? <ErrorState error={dash.error} onRetry={dash.reload} /> : d && (
        <>
          <div className="metrics">
            <Metric label="Entradas" value={d.counts.entradas.count} hint={`${qty(d.counts.entradas.qty)} unidades`} />
            <Metric label="Salidas" value={d.counts.salidas.count} hint={`${qty(d.counts.salidas.qty)} unidades`} />
            <Metric label="Devoluciones" value={d.counts.devoluciones.count}
              hint={`${qty(d.counts.devoluciones.restocked)} de ${qty(d.counts.devoluciones.qty)} volvieron`
                + (d.counts.devoluciones.pending_review ? ` · ${d.counts.devoluciones.pending_review} por revisar` : '')} />
            <Metric label="Ventas realizadas" value={d.sales.completed}
              hint={[d.sales.total !== undefined ? money(d.sales.total) : '', d.sales.voided ? `${d.sales.voided} anuladas` : '']
                .filter(Boolean).join(' · ') || undefined} />
            <Metric label="Existencias bajas" value={d.low_stock}
              hint={d.low_stock ? <Link to="/inventario">Ver productos</Link> : 'Sin alertas'} />
          </div>
          {d.people.length > 0 && (
            <Card title="Personas que realizaron operaciones">
              <ul className="result-list card-body">
                {d.people.map((p: any) => (
                  <li key={p.id} className="result-item" style={{ cursor: 'default' }}>
                    <span><strong>{p.full_name}</strong><br /><small className="muted">Última: {dateTime(p.last_at)}</small></span>
                    <span className="num">{p.movements} movimiento{p.movements === 1 ? '' : 's'}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </>
      )}
      <Card title={`Movimientos · ${current?.name ?? ''}`}>
        <div className="card-body" style={{ paddingBottom: 0 }}>
          <Tabs label="Tipo de movimiento" value={view} onChange={(v) => { setView(v); setPage(1); }} tabs={[
            { value: 'todos', label: 'Todos' }, { value: 'entradas', label: 'Entradas' },
            { value: 'salidas', label: 'Salidas' }, { value: 'devoluciones', label: 'Devoluciones' },
          ]} />
        </div>
        {view === 'devoluciones'
          ? <ReturnsList filters={f} page={page} onPage={setPage} />
          : <MovementList filters={f} category={view === 'todos' ? '' : view} page={page} onPage={setPage} />}
      </Card>
    </div>
  );
}

function ProductFilter({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [q, setQ] = useState('');
  const term = useDebounced(q.trim(), 300);
  const found = useApi<any[]>(term ? `/products/lookup${qs({ q: term, limit: 20 })}` : null);
  const [picked, setPicked] = useState<{ value: string; label: string } | null>(null);
  const options = [...(picked ? [picked] : []),
    ...(found.data ?? []).filter((p) => String(p.id) !== picked?.value).map((p) => ({ value: String(p.id), label: `${p.code} · ${p.description}` }))];
  return (
    <>
      <div style={{ minWidth: 180 }}>
        <TextField label="Buscar producto" type="search" value={q} onChange={setQ} placeholder="Código o nombre" autoComplete="off" />
      </div>
      <div style={{ minWidth: 220 }}>
        <SelectField label="Producto" value={value} placeholder="Todos" options={options} onChange={(v) => {
          setPicked(options.find((o) => o.value === v) ?? null);
          onChange(v);
        }} />
      </div>
    </>
  );
}

function MovementList({ filters, category, page, onPage }: { filters: Filters; category: string; page: number; onPage: (p: number) => void }) {
  const [kind, setKind] = useState('');
  const list = useApi(`/movements${qs({ ...filters, category, kind, page, page_size: 25 })}`);
  return (
    <>
      <div className="card-body row">
        <div style={{ minWidth: 200 }}>
          <SelectField label="Detalle del tipo" value={kind} onChange={(v) => { setKind(v); onPage(1); }} placeholder="Todos"
            options={Object.entries(KIND_LABELS).map(([value, label]) => ({ value, label }))} />
        </div>
      </div>
      {list.loading && !list.data ? <Loading /> : list.error ? <ErrorState error={list.error} onRetry={list.reload} /> :
        !list.data.items.length ? <EmptyState title="No hay movimientos en este filtro" /> : (
          <>
            <DataTable caption="Movimientos de inventario" rows={list.data.items} rowKey={(m: any) => m.id} columns={[
              { key: 'date', header: 'Fecha', render: (m: any) => <span className="nowrap">{dateTime(m.created_at)}</span> },
              { key: 'product', header: 'Producto', render: (m: any) => <><strong>{m.code}</strong> {m.description}</> },
              { key: 'kind', header: 'Tipo', render: (m: any) => KIND_LABELS[m.kind] ?? m.kind },
              { key: 'ref', header: 'Referencia', render: (m: any) => (m.reference_number
                ? (m.reference_type === 'venta' ? <Link to={`/vender/historial/${m.reference_id}`}>{m.reference_number}</Link> : m.reference_number)
                : <span className="muted">—</span>) },
              { key: 'reason', header: 'Motivo', render: (m: any) => m.reason },
              { key: 'qty', header: 'Cantidad', numeric: true, render: (m: any) => <strong>{Number(m.qty) > 0 ? '+' : ''}{qty(m.qty)}</strong> },
              { key: 'before', header: 'Antes', numeric: true, render: (m: any) => qty(m.stock_before) },
              { key: 'after', header: 'Después', numeric: true, render: (m: any) => qty(m.stock_after) },
              ...(list.data.items[0]?.unit_cost !== undefined
                ? [{ key: 'cost', header: 'Costo unit.', numeric: true, render: (m: any) => money(m.unit_cost) }] : []),
              { key: 'user', header: 'Responsable', render: (m: any) => m.full_name ?? m.username ?? 'sistema' },
            ]} />
            <Pagination page={list.data.page} pages={list.data.pages} total={list.data.total} onPage={onPage} />
          </>
        )}
    </>
  );
}

function ReturnsList({ filters, page, onPage }: { filters: Filters; page: number; onPage: (p: number) => void }) {
  const { can } = useAuth();
  const [condition, setCondition] = useState('');
  const [reviewing, setReviewing] = useState<any>(null);
  const list = useApi(`/inventory/returns${qs({ ...filters, condition, page, page_size: 25 })}`);
  return (
    <>
      <div className="card-body row">
        <div style={{ minWidth: 220 }}>
          <SelectField label="Estado del producto" value={condition} onChange={(v) => { setCondition(v); onPage(1); }} placeholder="Todos"
            options={Object.entries(CONDITION_LABELS).map(([value, label]) => ({ value, label }))} />
        </div>
      </div>
      {list.loading && !list.data ? <Loading /> : list.error ? <ErrorState error={list.error} onRetry={list.reload} /> :
        !list.data.items.length ? <EmptyState title="No hay devoluciones en este filtro" /> : (
          <>
            <DataTable caption="Devoluciones de clientes" rows={list.data.items} rowKey={(r: any) => r.id} columns={[
              { key: 'date', header: 'Fecha', render: (r: any) => <span className="nowrap">{dateTime(r.created_at)}</span> },
              { key: 'product', header: 'Producto', render: (r: any) => <><strong>{r.code}</strong> {r.description}</> },
              { key: 'sale', header: 'Venta original', render: (r: any) => <Link to={`/vender/historial/${r.sale_id}`}>{r.sale_number}</Link> },
              { key: 'num', header: 'Devolución', render: (r: any) => r.return_number },
              { key: 'reason', header: 'Motivo', render: (r: any) => r.reason },
              { key: 'cond', header: 'Estado', render: (r: any) => (
                <span><Badge kind={CONDITION_KIND[r.condition]}>{CONDITION_LABELS[r.condition] ?? r.condition}</Badge>
                  {r.resolved_at && <><br /><small className="muted">Revisado {dateTime(r.resolved_at)} · {r.resolved_by_name}</small></>}</span>) },
              { key: 'qty', header: 'Devuelto', numeric: true, render: (r: any) => qty(r.qty) },
              { key: 'back', header: 'Volvió', numeric: true, render: (r: any) => <strong>{qty(r.restocked)}</strong> },
              { key: 'user', header: 'Responsable', render: (r: any) => r.user_name },
              ...(can('ventas.anular') ? [{ key: 'act', header: 'Revisión', render: (r: any) => (r.condition === 'revision'
                ? <Button size="sm" variant="outline" onClick={() => setReviewing(r)}>Revisar</Button> : null) }] : []),
            ]} />
            <Pagination page={list.data.page} pages={list.data.pages} total={list.data.total} onPage={onPage} />
          </>
        )}
      {reviewing && <ReviewDialog row={reviewing} onClose={() => setReviewing(null)} onDone={() => { setReviewing(null); list.reload(); }} />}
    </>
  );
}

function ReviewDialog({ row, onClose, onDone }: { row: any; onClose: () => void; onDone: () => void }) {
  const { notify } = useToast();
  const online = useOnline();
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState<'' | 'apto' | 'no_apto'>('');
  const [error, setError] = useState<ApiError | null>(null);
  const decide = async (condition: 'apto' | 'no_apto') => {
    setBusy(condition);
    setError(null);
    try {
      await post(`/sales/returns/lines/${row.id}/resolve`, { condition, note: note.trim() });
      notify('success', condition === 'apto' ? 'Producto reingresado al inventario' : 'Producto marcado como no apto',
        `${row.code} · ${qty(row.qty)} unidades`);
      onDone();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy('');
    }
  };
  return (
    <Dialog open title={`Revisar devolución ${row.return_number}`} onClose={onClose} footer={
      <>
        <Button onClick={onClose}>Cancelar</Button>
        <Button variant="danger" disabled={!online || Boolean(busy)} busy={busy === 'no_apto'} icon={<XCircle size={20} />}
          onClick={() => decide('no_apto')}>No apto</Button>
        <Button variant="primary" disabled={!online || Boolean(busy)} busy={busy === 'apto'} icon={<CheckCircle2 size={20} />}
          onClick={() => decide('apto')}>Apto: reingresar</Button>
      </>
    }>
      <ErrorAlert error={error} />
      <p><strong>{row.code}</strong> {row.description} · {qty(row.qty)} unidades devueltas de la venta {row.sale_number}.</p>
      <p className="muted">«Apto» devuelve las unidades al inventario. «No apto» las deja fuera y registra su costo como pérdida.</p>
      <TextField label="Nota de la revisión (opcional)" value={note} onChange={setNote} maxLength={200} />
    </Dialog>
  );
}

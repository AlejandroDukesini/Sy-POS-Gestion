import { ArrowDownToLine, ArrowUpFromLine, ClipboardCheck, ClipboardList, History, Pencil, Plus, Power, Search, X } from 'lucide-react';
import { Fragment, useState } from 'react';
import { Link, Route, Routes, useSearchParams } from 'react-router-dom';
import { put, qs } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { ConfirmDialog } from '../../components/ui/Dialog';
import { Alert, Badge, EmptyState, ErrorState, Loading } from '../../components/ui/Feedback';
import { Checkbox, SelectField, TextField } from '../../components/ui/Form';
import { Card, LinkTabs, Metric, PageHeader } from '../../components/ui/Layout';
import { DataTable, Pagination, type Column } from '../../components/ui/Table';
import { useAuth } from '../../context/Auth';
import { useToast } from '../../context/Toast';
import { dateTime, money, pct, qty } from '../../lib/format';
import { useApi, useDebounced, useOnline } from '../../lib/hooks';
import { ColumnsAdmin, CustomValue, useInventoryColumns, type InventoryColumn } from './Columns';
import { ImportExport } from './ImportExport';
import { MovementDialog, type MovementKind } from './MovementDialog';
import { MovementsTable } from './MovementsTable';
import { ProductForm } from './ProductForm';
import ObservationsRoutes from './observations/ObservationsPage';
import { PriorityBadge, StatusBadge } from './observations/labels';

export interface Product {
  id: number; code: string; description: string; category_id: number | null; category_name: string | null; unit: string;
  price: string; discount_price: string | null; cost?: string; tax_rate: string; stock: string; min_stock: string;
  active: number; low_stock: boolean; version: number; external_ref: string | null; updated_at: string;
  created_by_name?: string; updated_by_name?: string; custom?: Record<string, string>;
}

export default function InventoryPage() {
  const { can } = useAuth();
  return (
    <>
      <PageHeader title="Inventario" description="Consulte existencias y registre entradas, salidas y ajustes." />
      <LinkTabs label="Secciones de inventario" tabs={[
        { to: '/inventario', label: 'Productos', end: true },
        { to: '/inventario/movimientos', label: 'Movimientos' },
        ...(can('observaciones.ver') ? [{ to: '/inventario/observaciones', label: 'Observaciones' }] : []),
        ...(can('inventario.importar') ? [{ to: '/inventario/importar', label: 'Importar y exportar' }] : []),
        ...(can('inventario.columnas') ? [{ to: '/inventario/columnas', label: 'Administrar columnas' }] : []),
      ]} />
      <Routes>
        <Route index element={<Products />} />
        <Route path="movimientos" element={<Card><MovementsTable /></Card>} />
        {can('observaciones.ver') && <Route path="observaciones/*" element={<ObservationsRoutes />} />}
        <Route path="importar" element={<ImportExport />} />
        {can('inventario.columnas') && <Route path="columnas" element={<ColumnsAdmin />} />}
      </Routes>
    </>
  );
}

function Products() {
  const { can } = useAuth();
  const [q, setQ] = useState('');
  const [category, setCategory] = useState('');
  const [status, setStatus] = useState('activos');
  const [lowStock, setLowStock] = useState(false);
  const [sort, setSort] = useState('code');
  const [direction, setDirection] = useState<'asc' | 'desc'>('asc');
  const [page, setPage] = useState(1);
  const [params] = useSearchParams();
  const [selected, setSelected] = useState<number | null>(Number(params.get('producto')) || null);
  const [editing, setEditing] = useState<Product | 'new' | null>(null);
  const [saved, setSaved] = useState(0);   // vuelve a cargar la ficha tras editar el producto
  const search = useDebounced(q.trim(), 300);
  const list = useApi(`/products${qs({ q: search, category_id: category, status, low_stock: lowStock, sort, direction, page, page_size: 25 })}`);
  const categories = useApi<any[]>('/categories');
  const meta = useApi('/products/meta');
  const extra = useInventoryColumns();
  const showCost = can('inventario.costos');
  const pageIds = (list.data?.items ?? []).map((p: Product) => p.id).join(',');
  const flags = useApi<Record<string, { open: number; critical: number }>>(
    can('observaciones.ver') && pageIds ? `/observations/flags?ids=${pageIds}` : null);

  const onSort = (key: string) => {
    if (sort === key) setDirection(direction === 'asc' ? 'desc' : 'asc');
    else {
      setSort(key);
      setDirection('asc');
    }
    setPage(1);
  };
  const refresh = () => {
    list.reload();
    meta.reload();
    flags.reload();
  };

  const columns: Column<Product>[] = [
    { key: 'code', header: 'Código', sortable: true, render: (p) => <strong className="nowrap">{p.code}</strong> },
    { key: 'description', header: 'Descripción', sortable: true, render: (p) => (
      <span>{p.description}{!p.active && <> <Badge>Inactivo</Badge></>}<ObservationFlag flag={flags.data?.[p.id]} /></span>) },
    { key: 'discount_price', header: 'Precio con descuento', numeric: true, sortable: true,
      render: (p) => (p.discount_price ? money(p.discount_price) : <span className="muted">—</span>) },
    { key: 'price', header: 'Precio sin descuento', numeric: true, sortable: true, render: (p) => money(p.price) },
    ...(showCost ? [{ key: 'cost', header: 'Costo', numeric: true, sortable: true, render: (p: Product) => money(p.cost) }] : []),
    { key: 'stock', header: 'Disponible', numeric: true, sortable: true, render: (p) => (
      <span className="row" style={{ justifyContent: 'flex-end', gap: 8 }}>
        {p.low_stock && <Badge kind="warning">Bajo</Badge>}
        <strong>{qty(p.stock)}</strong> <span className="muted">{p.unit}</span>
      </span>) },
    ...(extra.data?.columns ?? []).map((c) => ({
      key: `custom-${c.id}`, header: c.name, numeric: c.data_type === 'entero' || c.data_type === 'decimal',
      render: (p: Product) => <CustomValue column={c} value={p.custom?.[String(c.id)]} clip />,
    })),
  ];

  const summary = meta.data?.summary;
  return (
    <>
      {summary && (
        <div className="metrics">
          <Metric label="Productos activos" value={summary.products} />
          <Metric label="Existencias bajas" value={summary.low_stock} hint={summary.low_stock ? 'Revise el reabastecimiento' : 'Sin alertas'} />
          <Metric label="Sin existencias" value={summary.out_of_stock} />
          {summary.value !== undefined && <Metric label="Valor del inventario (costo)" value={money(summary.value)} />}
        </div>
      )}
      <div className={`split${selected ? '' : ' no-panel'}`}>
        <Card title={
          <div className="row grow">
            <div className="grow" style={{ minWidth: 220 }}>
              <TextField label="Buscar por código o descripción" value={q} onChange={(v) => { setQ(v); setPage(1); }}
                type="search" placeholder="Ej.: MART-01 o martillo" autoComplete="off" />
            </div>
          </div>
        } actions={can('inventario.editar') && (
          <Button variant="primary" icon={<Plus size={20} />} onClick={() => setEditing('new')}>Nuevo producto</Button>)}>
          <div className="card-body" style={{ paddingBottom: 0 }}>
            <div className="row">
              <div style={{ minWidth: 200 }}>
                <SelectField label="Categoría" value={category} onChange={(v) => { setCategory(v); setPage(1); }} placeholder="Todas"
                  options={(categories.data ?? []).map((c) => ({ value: c.id, label: c.name }))} />
              </div>
              <div style={{ minWidth: 180 }}>
                <SelectField label="Estado" value={status} onChange={(v) => { setStatus(v); setPage(1); }} options={[
                  { value: 'activos', label: 'Activos' }, { value: 'inactivos', label: 'Inactivos' }, { value: 'todos', label: 'Todos' }]} />
              </div>
              <div style={{ alignSelf: 'flex-end' }}>
                <Checkbox label="Solo existencias bajas" checked={lowStock} onChange={(v) => { setLowStock(v); setPage(1); }} />
              </div>
            </div>
          </div>
          {list.loading && !list.data ? <Loading /> : list.error ? <ErrorState error={list.error} onRetry={list.reload} /> :
            list.data.items.length === 0 ? (
              <EmptyState title={search || lowStock ? 'Ningún producto coincide' : 'Aún no hay productos'}
                icon={<Search size={40} aria-hidden />}>
                {!search && can('inventario.editar') && <p>Cree el primero con «Nuevo producto» o impórtelos desde Excel.</p>}
              </EmptyState>
            ) : (
              <>
                <DataTable caption="Productos del inventario" columns={columns} rows={list.data.items as Product[]} rowKey={(p) => p.id}
                  selectedKey={selected} onSelect={(p) => setSelected(p.id)} sort={sort} direction={direction} onSort={onSort} />
                <Pagination page={list.data.page} pages={list.data.pages} total={list.data.total} onPage={setPage} />
              </>
            )}
        </Card>
        {selected && (
          <ProductPanel key={`${selected}-${saved}`} id={selected} onClose={() => setSelected(null)} onChanged={refresh}
            onEdit={(p) => setEditing(p)} columns={extra.data?.columns ?? []} />
        )}
      </div>
      {editing && (
        <ProductForm product={editing === 'new' ? null : editing} categories={categories.data ?? []} units={meta.data?.units ?? ['und']}
          columns={extra.data?.columns ?? []}
          onClose={() => setEditing(null)} onSaved={(p) => { setEditing(null); setSelected(p.id); setSaved((n) => n + 1); refresh(); categories.reload(); }} />
      )}
    </>
  );
}

function ProductPanel({ id, onClose, onChanged, onEdit, columns }: {
  id: number; onClose: () => void; onChanged: () => void; onEdit: (p: Product) => void; columns: InventoryColumn[];
}) {
  const { can } = useAuth();
  const { notify } = useToast();
  const online = useOnline();
  const product = useApi<Product>(`/products/${id}`);
  const history = useApi(`/movements${qs({ product_id: id, page_size: 8 })}`);
  const [movement, setMovement] = useState<MovementKind | null>(null);
  const [confirmToggle, setConfirmToggle] = useState(false);
  const [busy, setBusy] = useState(false);
  const p = product.data;

  const toggle = async () => {
    if (!p) return;
    setBusy(true);
    try {
      await put(`/products/${p.id}`, { active: !p.active, version: p.version });
      notify('success', p.active ? 'Producto desactivado' : 'Producto activado', `${p.code} · ${p.description}`);
      product.reload();
      onChanged();
    } catch (err) {
      notify('danger', 'No se pudo cambiar el estado', (err as Error).message);
    } finally {
      setBusy(false);
      setConfirmToggle(false);
    }
  };
  const afterMovement = () => {
    setMovement(null);
    product.reload();
    history.reload();
    onChanged();
  };

  return (
    <aside className="panel" aria-label="Detalle del producto">
      <Card title={p ? p.code : 'Producto'} actions={<Button variant="ghost" iconOnly icon={<X size={22} />} onClick={onClose}>Cerrar detalle</Button>}>
        {product.loading && !p ? <Loading /> : product.error ? <ErrorState error={product.error} onRetry={product.reload} /> : p && (
          <div className="card-body stack">
            <div>
              <h3>{p.description}</h3>
              <div className="row" style={{ marginTop: 8 }}>
                {p.active ? <Badge kind="success">Activo</Badge> : <Badge kind="danger">Inactivo</Badge>}
                {p.low_stock && p.active ? <Badge kind="warning">Existencia baja</Badge> : null}
                {p.category_name && <Badge>{p.category_name}</Badge>}
              </div>
            </div>
            <div className="metrics" style={{ gridTemplateColumns: '1fr 1fr' }}>
              <div><div className="metric-label">Disponible</div><div className="metric-value">{qty(p.stock)} <small className="muted">{p.unit}</small></div></div>
              <div><div className="metric-label">Mínimo</div><div className="metric-value">{qty(p.min_stock)}</div></div>
            </div>
            <dl className="dl">
              <dt>Precio sin descuento</dt><dd className="num" style={{ textAlign: 'left' }}>{money(p.price)}</dd>
              <dt>Precio con descuento</dt><dd>{p.discount_price ? money(p.discount_price) : 'Sin descuento'}</dd>
              {p.cost !== undefined && <><dt>Costo promedio</dt><dd>{money(p.cost)}</dd></>}
              <dt>IVA</dt><dd>{pct(p.tax_rate)}</dd>
              <dt>Actualizado</dt><dd>{dateTime(p.updated_at)}{p.updated_by_name ? ` · ${p.updated_by_name}` : ''}</dd>
              {columns.map((c) => <Fragment key={c.id}><dt>{c.name}</dt><dd><CustomValue column={c} value={p.custom?.[String(c.id)]} /></dd></Fragment>)}
            </dl>
            {!online && <Alert kind="warning">Sin conexión: las operaciones están deshabilitadas.</Alert>}
            {can('inventario.movimientos') && p.active ? (
              <div className="grid-3" style={{ gap: 8 }}>
                <Button variant="primary" disabled={!online} icon={<ArrowDownToLine size={20} />} onClick={() => setMovement('entrada')}>Entrada</Button>
                <Button variant="outline" disabled={!online} icon={<ArrowUpFromLine size={20} />} onClick={() => setMovement('salida')}>Salida</Button>
                <Button variant="outline" disabled={!online} icon={<ClipboardCheck size={20} />} onClick={() => setMovement('ajuste')}>Ajuste</Button>
              </div>
            ) : null}
            {can('inventario.editar') && (
              <div className="row">
                <Button disabled={!online} icon={<Pencil size={20} />} onClick={() => onEdit(p)}>Editar</Button>
                <Button variant="ghost" disabled={!online} icon={<Power size={20} />} onClick={() => setConfirmToggle(true)}>
                  {p.active ? 'Desactivar' : 'Activar'}
                </Button>
              </div>
            )}
            <div>
              <h3 className="row" style={{ marginBottom: 8 }}><History size={20} aria-hidden /> Últimos movimientos</h3>
              {history.loading && !history.data ? <Loading /> : history.data?.items.length ? (
                <ul className="result-list">
                  {history.data.items.map((m: any) => (
                    <li key={m.id} className="result-item" style={{ cursor: 'default' }}>
                      <span>
                        <strong>{KIND_LABELS[m.kind] ?? m.kind}</strong> · {m.reason}
                        <br /><small className="muted">{dateTime(m.created_at)} · {m.username ?? 'sistema'}</small>
                      </span>
                      <span className="num"><strong>{Number(m.qty) > 0 ? '+' : ''}{qty(m.qty)}</strong><br />
                        <small className="muted">queda {qty(m.stock_after)}</small></span>
                    </li>
                  ))}
                </ul>
              ) : <p className="muted">Sin movimientos.</p>}
            </div>
            {can('observaciones.ver') && <ProductObservations productId={p.id} />}
            <p className="muted" style={{ fontSize: '0.875rem' }}>La existencia solo cambia mediante movimientos registrados.</p>
          </div>
        )}
      </Card>
      {movement && p && <MovementDialog kind={movement} product={p} onClose={() => setMovement(null)} onDone={afterMovement} />}
      {p && (
        <ConfirmDialog open={confirmToggle} title={p.active ? 'Desactivar producto' : 'Activar producto'} busy={busy}
          danger={Boolean(p.active)} confirmLabel={p.active ? 'Desactivar' : 'Activar'} onClose={() => setConfirmToggle(false)}
          onConfirm={toggle} message={p.active
            ? `«${p.description}» dejará de aparecer para vender y cotizar. Su historial se conserva y puede activarlo de nuevo.`
            : `«${p.description}» volverá a estar disponible para vender y cotizar.`} />
      )}
    </aside>
  );
}

/** Indicador discreto en el listado: solo aparece si hay observaciones abiertas. */
function ObservationFlag({ flag }: { flag?: { open: number; critical: number } }) {
  if (!flag) return null;
  const text = flag.critical
    ? `${flag.critical} observación${flag.critical > 1 ? 'es' : ''} crítica${flag.critical > 1 ? 's' : ''}`
    : `${flag.open} observación${flag.open > 1 ? 'es' : ''} pendiente${flag.open > 1 ? 's' : ''}`;
  return <> <span className={`badge obs-flag${flag.critical ? ' obs-flag-critical' : ''}`} title={text}>
    <ClipboardList size={14} aria-hidden /> <span className="sr-only">{text}</span><span aria-hidden>{flag.critical || flag.open}</span></span></>;
}

/** Observaciones del producto dentro de su ficha, con acceso al módulo completo. */
function ProductObservations({ productId }: { productId: number }) {
  const { can } = useAuth();
  const data = useApi(`/observations${qs({ product_id: productId, page_size: 5 })}`);
  const context = useApi<any>(`/observations/products/${productId}`);
  const c = context.data;
  return (
    <div>
      <h3 className="row" style={{ marginBottom: 8 }}><ClipboardList size={20} aria-hidden /> Observaciones</h3>
      {c && (
        <p style={{ margin: '0 0 8px' }}>
          {c.open_observations === 0 ? <span className="muted">Sin observaciones pendientes.</span> : <>
            <strong>{c.open_observations}</strong> {c.open_observations === 1 ? 'observación abierta' : 'observaciones abiertas'}
            {c.critical_observations > 0 && <> · <span className="badge obs-priority obs-priority-critica">{c.critical_observations} crítica{c.critical_observations > 1 ? 's' : ''}</span></>}
          </>}
        </p>
      )}
      {data.loading && !data.data ? <Loading /> : data.data?.items.length ? (
        <ul className="result-list">
          {data.data.items.map((o: any) => (
            <li key={o.id}>
              <Link className="result-item" to={`/inventario/observaciones/${o.id}`}>
                <span><strong>{o.code}</strong> · {o.category_name}<br /><small className="muted">{dateTime(o.created_at)}</small></span>
                <span className="row" style={{ gap: 4, flexWrap: 'nowrap' }}><PriorityBadge priority={o.priority} /><StatusBadge status={o.status} /></span>
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
      <div className="row" style={{ marginTop: 8 }}>
        {(c?.total_observations ?? 0) > 0 && <Link className="btn btn-ghost btn-sm" to={`/inventario/observaciones?producto=${productId}`}>Ver todas ({c.total_observations})</Link>}
        {can('observaciones.crear') && <Link className="btn btn-outline btn-sm" to={`/inventario/observaciones?producto=${productId}&nueva=1`}>
          <Plus size={16} aria-hidden /> Registrar observación</Link>}
      </div>
    </div>
  );
}

export const KIND_LABELS: Record<string, string> = {
  inicial: 'Existencia inicial', entrada: 'Entrada', salida: 'Salida', ajuste: 'Ajuste', venta: 'Venta',
  devolucion: 'Devolución', anulacion_venta: 'Anulación de venta', conciliacion: 'Conciliación',
};

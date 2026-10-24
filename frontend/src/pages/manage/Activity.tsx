import { useState } from 'react';
import { qs } from '../../api/client';
import { EmptyState, ErrorState, Loading } from '../../components/ui/Feedback';
import { SelectField, TextField } from '../../components/ui/Form';
import { Card, Metric } from '../../components/ui/Layout';
import { DataTable, Pagination } from '../../components/ui/Table';
import { dateTime, date, money, qty, today, daysFromToday } from '../../lib/format';
import { useApi, useDebounced } from '../../lib/hooks';
import { ManageBack } from './ManageRoutes';

function details(raw: string | null): string {
  if (!raw) return '';
  try {
    const data = JSON.parse(raw);
    return Object.entries(data).map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' · ').slice(0, 300);
  } catch {
    return raw.slice(0, 300);
  }
}

export function ActivityPage() {
  const users = useApi<any[]>('/users');
  const [q, setQ] = useState('');
  const [userId, setUserId] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [page, setPage] = useState(1);
  const term = useDebounced(q, 300);
  const list = useApi(`/activity${qs({ q: term, user_id: userId, date_from: from, date_to: to, page, page_size: 50 })}`);
  return (
    <div className="stack">
      <ManageBack title="Historial de actividad" description="Registro inalterable de las operaciones. Nunca contiene contraseñas ni credenciales." />
      <Card>
        <div className="card-body row">
          <div className="grow"><TextField label="Buscar" type="search" value={q} onChange={(v) => { setQ(v); setPage(1); }} placeholder="Ej.: venta, producto, sesion" /></div>
          <div style={{ minWidth: 200 }}><SelectField label="Usuario" value={userId} onChange={(v) => { setUserId(v); setPage(1); }} placeholder="Todos"
            options={(users.data ?? []).map((u) => ({ value: u.id, label: u.username }))} /></div>
          <TextField label="Desde" type="date" value={from} onChange={(v) => { setFrom(v); setPage(1); }} />
          <TextField label="Hasta" type="date" value={to} onChange={(v) => { setTo(v); setPage(1); }} />
        </div>
        {list.loading && !list.data ? <Loading /> : list.error ? <ErrorState error={list.error} /> : !list.data.items.length ? <EmptyState title="Sin registros" /> : (
          <>
            <DataTable caption="Actividad" rows={list.data.items} rowKey={(a: any) => a.id} columns={[
              { key: 'd', header: 'Fecha', render: (a: any) => <span className="nowrap">{dateTime(a.created_at)}</span> },
              { key: 'u', header: 'Usuario', render: (a: any) => a.username },
              { key: 'a', header: 'Acción', render: (a: any) => <strong>{a.action}</strong> },
              { key: 'e', header: 'Registro', render: (a: any) => (a.entity ? `${a.entity} ${a.entity_id ?? ''}` : '') },
              { key: 'x', header: 'Detalle', render: (a: any) => <small>{details(a.details)}</small> },
            ]} />
            <Pagination page={list.data.page} pages={list.data.pages} total={list.data.total} onPage={setPage} />
          </>
        )}
      </Card>
    </div>
  );
}

export function ReportsPage() {
  const [from, setFrom] = useState(daysFromToday(-29));
  const [to, setTo] = useState(today());
  const sales = useApi(`/reports/sales${qs({ date_from: from, date_to: to })}`);
  const moves = useApi(`/reports/movements${qs({ date_from: from, date_to: to })}`);
  const s = sales.data;
  const max = Math.max(1, ...(s?.by_day ?? []).map((d: any) => Number(d.total)));
  return (
    <div className="stack">
      <ManageBack title="Reportes operativos" />
      <Card><div className="card-body row">
        <TextField label="Desde" type="date" value={from} onChange={setFrom} />
        <TextField label="Hasta" type="date" value={to} onChange={setTo} />
      </div></Card>
      {sales.loading && !s ? <Loading /> : sales.error ? <ErrorState error={sales.error} /> : s && (
        <>
          <div className="metrics">
            <Metric label="Ventas" value={s.sales} />
            <Metric label="Total vendido" value={money(s.total)} />
            <Metric label="Ticket promedio" value={money(s.average_ticket)} />
            <Metric label="Devoluciones" value={money(s.returns)} hint={`${s.returns_count} devoluciones`} />
          </div>
          <Card title="Ventas por día">
            <div className="card-body stack">
              {s.by_day.length ? s.by_day.map((d: any) => (
                <div key={d.day} className="row" style={{ flexWrap: 'nowrap' }}>
                  <span style={{ width: 110 }}>{date(d.day)}</span>
                  <div className="grow" aria-hidden style={{ height: 14, background: 'var(--surface-2)', borderRadius: 6, overflow: 'hidden' }}>
                    <div style={{ width: `${(Number(d.total) / max) * 100}%`, height: '100%', background: 'var(--primary)' }} />
                  </div>
                  <span className="num" style={{ width: 160 }}>{money(d.total)} ({d.sales})</span>
                </div>
              )) : <p className="muted">Sin ventas en el periodo.</p>}
            </div>
          </Card>
          <div className="grid-2">
            <Card title="Productos más vendidos">
              <DataTable caption="Productos más vendidos" rows={s.top_products} rowKey={(p: any) => p.code} columns={[
                { key: 'p', header: 'Producto', render: (p: any) => <><strong>{p.code}</strong> {p.description}</> },
                { key: 'q', header: 'Cantidad', numeric: true, render: (p: any) => qty(p.qty) },
                { key: 'n', header: 'Ventas', numeric: true, render: (p: any) => money(p.net) },
              ]} />
            </Card>
            <Card title="Ventas por usuario">
              <DataTable caption="Ventas por usuario" rows={s.by_user} rowKey={(u: any) => u.username} columns={[
                { key: 'u', header: 'Usuario', render: (u: any) => u.full_name },
                { key: 'c', header: 'Ventas', numeric: true, render: (u: any) => u.sales },
                { key: 't', header: 'Total', numeric: true, render: (u: any) => money(u.total) },
              ]} />
            </Card>
          </div>
        </>
      )}
      {moves.data && (
        <Card title="Movimientos de inventario por tipo">
          <DataTable caption="Movimientos por tipo" rows={moves.data.by_kind} rowKey={(m: any) => m.kind} columns={[
            { key: 'k', header: 'Tipo', render: (m: any) => m.kind },
            { key: 'n', header: 'Movimientos', numeric: true, render: (m: any) => m.movements },
            { key: 'i', header: 'Unidades que entraron', numeric: true, render: (m: any) => qty(m.in) },
            { key: 'o', header: 'Unidades que salieron', numeric: true, render: (m: any) => qty(m.out) },
          ]} />
        </Card>
      )}
    </div>
  );
}

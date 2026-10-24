import { useState } from 'react';
import { qs } from '../../api/client';
import { EmptyState, ErrorState, Loading } from '../../components/ui/Feedback';
import { SelectField, TextField } from '../../components/ui/Form';
import { DataTable, Pagination } from '../../components/ui/Table';
import { dateTime, money, qty } from '../../lib/format';
import { useApi } from '../../lib/hooks';
import { KIND_LABELS } from './InventoryPage';

/** Historial completo de movimientos: fecha, usuario, motivo y cantidades. */
export function MovementsTable() {
  const [kind, setKind] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [page, setPage] = useState(1);
  const list = useApi(`/movements${qs({ kind, date_from: from, date_to: to, page, page_size: 25 })}`);
  return (
    <>
      <div className="card-body row">
        <div style={{ minWidth: 200 }}>
          <SelectField label="Tipo" value={kind} onChange={(v) => { setKind(v); setPage(1); }} placeholder="Todos"
            options={Object.entries(KIND_LABELS).map(([value, label]) => ({ value, label }))} />
        </div>
        <div><TextField label="Desde" type="date" value={from} onChange={(v) => { setFrom(v); setPage(1); }} /></div>
        <div><TextField label="Hasta" type="date" value={to} onChange={(v) => { setTo(v); setPage(1); }} /></div>
      </div>
      {list.loading && !list.data ? <Loading /> : list.error ? <ErrorState error={list.error} onRetry={list.reload} /> :
        !list.data.items.length ? <EmptyState title="No hay movimientos en este filtro" /> : (
          <>
            <DataTable caption="Movimientos de inventario" rows={list.data.items} rowKey={(m: any) => m.id} columns={[
              { key: 'date', header: 'Fecha', render: (m: any) => <span className="nowrap">{dateTime(m.created_at)}</span> },
              { key: 'product', header: 'Producto', render: (m: any) => <><strong>{m.code}</strong> {m.description}</> },
              { key: 'kind', header: 'Tipo', render: (m: any) => KIND_LABELS[m.kind] ?? m.kind },
              { key: 'reason', header: 'Motivo', render: (m: any) => m.reason },
              { key: 'qty', header: 'Cantidad', numeric: true, render: (m: any) => <strong>{Number(m.qty) > 0 ? '+' : ''}{qty(m.qty)}</strong> },
              { key: 'after', header: 'Saldo', numeric: true, render: (m: any) => qty(m.stock_after) },
              ...(list.data.items[0]?.unit_cost !== undefined
                ? [{ key: 'cost', header: 'Costo unit.', numeric: true, render: (m: any) => money(m.unit_cost) }] : []),
              { key: 'user', header: 'Usuario', render: (m: any) => m.username ?? 'sistema' },
            ]} />
            <Pagination page={list.data.page} pages={list.data.pages} total={list.data.total} onPage={setPage} />
          </>
        )}
    </>
  );
}

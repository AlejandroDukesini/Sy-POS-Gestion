import { Plus, Star } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from '../../components/ui/Button';
import { Badge, EmptyState, ErrorState, Loading } from '../../components/ui/Feedback';
import { TextField } from '../../components/ui/Form';
import { Card, Metric, Tabs } from '../../components/ui/Layout';
import { DataTable } from '../../components/ui/Table';
import { qs } from '../../api/client';
import { date } from '../../lib/format';
import { useApi, useDebounced } from '../../lib/hooks';
import { ManageBack } from '../manage/ManageRoutes';
import { SupplierInfoDialog } from './SupplierDialogs';

type Status = 'activos' | 'inactivos' | 'todos';

/** Vista general: indicadores, búsqueda, filtro por estado y acceso al expediente de cada proveedor. */
export function SuppliersPage() {
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const [status, setStatus] = useState<Status>('activos');
  const [creating, setCreating] = useState(false);
  const term = useDebounced(q, 300);
  const list = useApi<any>(`/suppliers${qs({ q: term, status })}`);
  const m = list.data?.metrics;

  return (
    <div className="stack">
      <ManageBack title="Proveedores" description="Expediente comercial de cada proveedor: contacto, asesor, pendientes, visitas, cotizaciones y lista de productos."
        actions={<Button variant="primary" icon={<Plus size={20} />} onClick={() => setCreating(true)}>Nuevo proveedor</Button>} />
      {m && (
        <div className="metrics">
          <Metric label="Proveedores" value={m.total} />
          <Metric label="Activos" value={m.active} />
          <Metric label="Con pendientes" value={m.with_pending} />
          <Metric label="Con visitas recientes" value={m.recent_visits} hint={`Últimos ${list.data.recent_visit_days} días`} />
          <Metric label="Con cotizaciones" value={m.with_quotes} />
        </div>
      )}
      <Card>
        <div className="card-body row" style={{ flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div className="grow"><TextField label="Buscar por nombre o NIT" type="search" value={q} onChange={setQ} /></div>
          <Tabs label="Estado" value={status} onChange={setStatus}
            tabs={[{ value: 'activos', label: 'Activos' }, { value: 'inactivos', label: 'Inactivos' }, { value: 'todos', label: 'Todos' }]} />
        </div>
        {list.loading && !list.data ? <Loading /> : list.error ? <ErrorState error={list.error} onRetry={list.reload} />
          : !list.data.items.length ? <EmptyState title={q ? 'Ningún proveedor coincide con la búsqueda' : 'No hay proveedores en este estado'} /> : (
            <DataTable caption="Proveedores" rows={list.data.items} rowKey={(s: any) => s.id} onSelect={(s: any) => navigate(String(s.id))} columns={[
              { key: 'n', header: 'Proveedor', render: (s: any) => (
                <span><strong>{s.name}</strong>{s.identification && <><br /><small className="muted">NIT {s.identification}</small></>}</span>) },
              { key: 'c', header: 'Contacto', render: (s: any) => [s.phone, s.whatsapp && `WhatsApp ${s.whatsapp}`, s.city].filter(Boolean).join(' · ') || '—' },
              { key: 'a', header: 'Asesor', render: (s: any) => s.advisor_name || '—' },
              { key: 'p', header: 'Pendientes', render: (s: any) => (s.pending_notes ? (
                <Badge kind={s.important_notes ? 'danger' : 'warning'}>
                  {s.important_notes ? <Star size={12} aria-label="importante" /> : null} {s.pending_notes}</Badge>) : '—') },
              { key: 'v', header: 'Última visita', render: (s: any) => (s.last_visit
                ? <>{date(s.last_visit)}{s.recent_visit && <> <Badge kind="success">Reciente</Badge></>}</> : '—') },
              { key: 'q', header: 'Cotizaciones', numeric: true, render: (s: any) => s.quotes },
              { key: 's', header: 'Estado', render: (s: any) => (s.active ? <Badge kind="success">Activo</Badge> : <Badge>Inactivo</Badge>) },
            ]} />
          )}
      </Card>
      {creating && <SupplierInfoDialog supplier={{}} onClose={() => setCreating(false)}
        onSaved={(s) => { setCreating(false); navigate(String(s.id)); }} />}
    </div>
  );
}

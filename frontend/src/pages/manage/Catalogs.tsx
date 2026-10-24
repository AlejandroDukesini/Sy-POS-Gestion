import { Plus, Save } from 'lucide-react';
import { useState } from 'react';
import { ApiError, post, put, qs } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { Dialog } from '../../components/ui/Dialog';
import { Badge, EmptyState, ErrorAlert, ErrorState, Loading } from '../../components/ui/Feedback';
import { Checkbox, NumberField, SelectField, TextField } from '../../components/ui/Form';
import { Card } from '../../components/ui/Layout';
import { DataTable, Pagination } from '../../components/ui/Table';
import { useToast } from '../../context/Toast';
import { useApi, useDebounced } from '../../lib/hooks';
import { ManageBack } from './ManageRoutes';

// ------------------------------------------------------------------ clientes y proveedores
export function PartiesPage({ kind }: { kind: 'clientes' | 'proveedores' }) {
  const label = kind === 'clientes' ? 'Clientes' : 'Proveedores';
  const [q, setQ] = useState('');
  const [inactive, setInactive] = useState(false);
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<any>(null);
  const term = useDebounced(q, 300);
  const list = useApi(`/parties/${kind}${qs({ q: term, include_inactive: inactive, page, page_size: 25 })}`);
  return (
    <div className="stack">
      <ManageBack title={label} actions={<Button variant="primary" icon={<Plus size={20} />} onClick={() => setEditing({})}>
        {kind === 'clientes' ? 'Nuevo cliente' : 'Nuevo proveedor'}</Button>} />
      <Card>
        <div className="card-body row">
          <div className="grow"><TextField label="Buscar por nombre, identificación o teléfono" type="search" value={q} onChange={(v) => { setQ(v); setPage(1); }} /></div>
          <div style={{ alignSelf: 'flex-end' }}><Checkbox label="Incluir inactivos" checked={inactive} onChange={setInactive} /></div>
        </div>
        {list.loading && !list.data ? <Loading /> : list.error ? <ErrorState error={list.error} /> : !list.data.items.length
          ? <EmptyState title={`No hay ${label.toLowerCase()} registrados`} /> : (
            <>
              <DataTable caption={label} rows={list.data.items} rowKey={(p: any) => p.id} onSelect={setEditing} columns={[
                { key: 'n', header: 'Nombre', render: (p: any) => <strong>{p.name}</strong> },
                { key: 'i', header: 'Identificación', render: (p: any) => p.identification ?? '—' },
                { key: 't', header: 'Teléfono', render: (p: any) => p.phone || '—' },
                { key: 'e', header: 'Correo', render: (p: any) => p.email || '—' },
                { key: 'd', header: kind === 'clientes' ? 'Días de crédito' : 'Días de pago', numeric: true,
                  render: (p: any) => (kind === 'clientes' ? p.credit_days : p.payment_days) },
                { key: 's', header: 'Estado', render: (p: any) => (p.active ? <Badge kind="success">Activo</Badge> : <Badge>Inactivo</Badge>) },
              ]} />
              <Pagination page={list.data.page} pages={list.data.pages} total={list.data.total} onPage={setPage} />
            </>
          )}
      </Card>
      {editing && <PartyDialog kind={kind} party={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); list.reload(); }} />}
    </div>
  );
}

function PartyDialog({ kind, party, onClose, onSaved }: { kind: string; party: any; onClose: () => void; onSaved: () => void }) {
  const { notify } = useToast();
  const daysKey = kind === 'clientes' ? 'credit_days' : 'payment_days';
  const [form, setForm] = useState({ name: party.name ?? '', identification: party.identification ?? '', phone: party.phone ?? '',
    email: party.email ?? '', address: party.address ?? '', days: String(party[daysKey] ?? 30), active: party.active ?? 1 });
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (v: any) => setForm((f) => ({ ...f, [k]: v }));
  const save = async () => {
    setBusy(true);
    setError(null);
    const body = { name: form.name, identification: form.identification || null, phone: form.phone, email: form.email,
      address: form.address, [daysKey]: Number(form.days) || 0, active: Boolean(form.active), version: party.version };
    try {
      if (party.id) await put(`/parties/${kind}/${party.id}`, body);
      else await post(`/parties/${kind}`, body);
      notify('success', 'Guardado', form.name);
      onSaved();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  const fe = error?.fields ?? {};
  return (
    <Dialog open title={party.id ? party.name : kind === 'clientes' ? 'Nuevo cliente' : 'Nuevo proveedor'} onClose={onClose} size="wide"
      footer={<><Button onClick={onClose}>Cancelar</Button><Button variant="primary" busy={busy} icon={<Save size={20} />} onClick={save}>Guardar</Button></>}>
      <ErrorAlert error={error} />
      <div className="form-grid">
        <TextField label="Nombre o razón social" value={form.name} onChange={set('name')} error={fe.name} required />
        <TextField label="NIT o cédula" value={form.identification} onChange={set('identification')} error={fe.identification} />
        <TextField label="Teléfono" type="tel" value={form.phone} onChange={set('phone')} error={fe.phone} />
        <TextField label="Correo" type="email" value={form.email} onChange={set('email')} error={fe.email} />
        <TextField label="Dirección" value={form.address} onChange={set('address')} error={fe.address} />
        <NumberField label={kind === 'clientes' ? 'Días de crédito' : 'Días de pago'} value={form.days} onChange={set('days')} error={fe[daysKey]} />
      </div>
      {party.id && <Checkbox label="Activo" checked={Boolean(form.active)} onChange={(v) => set('active')(v ? 1 : 0)} />}
    </Dialog>
  );
}

// ------------------------------------------------------------------ categorías
export function CategoriesPage() {
  const list = useApi<any[]>('/categories?include_inactive=true');
  const [editing, setEditing] = useState<any>(null);
  const [name, setName] = useState('');
  const [active, setActive] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const open = (c: any) => { setEditing(c); setName(c.name ?? ''); setActive(c.active === undefined ? true : Boolean(c.active)); setError(null); };
  const save = async () => {
    try {
      if (editing.id) await put(`/categories/${editing.id}`, { name, active });
      else await post('/categories', { name, active });
      setEditing(null);
      list.reload();
    } catch (err) {
      setError(err as ApiError);
    }
  };
  return (
    <div className="stack">
      <ManageBack title="Categorías de productos" actions={<Button variant="primary" icon={<Plus size={20} />} onClick={() => open({})}>Nueva categoría</Button>} />
      <Card>
        {list.loading && !list.data ? <Loading /> : !list.data?.length ? <EmptyState title="Sin categorías" /> : (
          <DataTable caption="Categorías" rows={list.data} rowKey={(c: any) => c.id} onSelect={open} columns={[
            { key: 'n', header: 'Nombre', render: (c: any) => <strong>{c.name}</strong> },
            { key: 'p', header: 'Productos', numeric: true, render: (c: any) => c.products },
            { key: 's', header: 'Estado', render: (c: any) => (c.active ? <Badge kind="success">Activa</Badge> : <Badge>Inactiva</Badge>) },
          ]} />
        )}
      </Card>
      <Dialog open={Boolean(editing)} title={editing?.id ? 'Editar categoría' : 'Nueva categoría'} onClose={() => setEditing(null)}
        footer={<><Button onClick={() => setEditing(null)}>Cancelar</Button><Button variant="primary" onClick={save}>Guardar</Button></>}>
        <ErrorAlert error={error} />
        <TextField label="Nombre" value={name} onChange={setName} error={error?.fields.name} required autoFocus />
        <Checkbox label="Activa" checked={active} onChange={setActive} />
      </Dialog>
    </div>
  );
}

// ------------------------------------------------------------------ métodos de pago
const KINDS = { efectivo: 'Efectivo', tarjeta: 'Tarjeta', transferencia: 'Transferencia', credito: 'Crédito (cuenta por cobrar)', otro: 'Otro' };

export function PaymentMethodsPage() {
  const list = useApi<any[]>('/payment-methods?include_inactive=true');
  const accounts = useApi<any[]>('/finance/accounts');
  const [editing, setEditing] = useState<any>(null);
  const [form, setForm] = useState({ name: '', kind: 'efectivo', account_code: '1105', active: true });
  const [error, setError] = useState<ApiError | null>(null);
  const open = (m: any) => {
    setEditing(m);
    setForm({ name: m.name ?? '', kind: m.kind ?? 'efectivo', account_code: m.account_code ?? '1105', active: m.active === undefined ? true : Boolean(m.active) });
    setError(null);
  };
  const save = async () => {
    try {
      const body = { ...form, account_code: form.kind === 'credito' ? null : form.account_code };
      if (editing.id) await put(`/payment-methods/${editing.id}`, body);
      else await post('/payment-methods', body);
      setEditing(null);
      list.reload();
    } catch (err) {
      setError(err as ApiError);
    }
  };
  return (
    <div className="stack">
      <ManageBack title="Métodos de pago" description="Cada método (salvo crédito) registra el dinero en una cuenta de caja o bancos."
        actions={<Button variant="primary" icon={<Plus size={20} />} onClick={() => open({})}>Nuevo método</Button>} />
      <Card>
        {list.loading && !list.data ? <Loading /> : (
          <DataTable caption="Métodos de pago" rows={list.data ?? []} rowKey={(m: any) => m.id} onSelect={open} columns={[
            { key: 'n', header: 'Nombre', render: (m: any) => <strong>{m.name}</strong> },
            { key: 'k', header: 'Tipo', render: (m: any) => (KINDS as any)[m.kind] },
            { key: 'a', header: 'Cuenta', render: (m: any) => (m.account_code ? `${m.account_code} ${m.account_name}` : 'Cuentas por cobrar') },
            { key: 's', header: 'Estado', render: (m: any) => (m.active ? <Badge kind="success">Activo</Badge> : <Badge>Inactivo</Badge>) },
          ]} />
        )}
      </Card>
      <Dialog open={Boolean(editing)} title={editing?.id ? 'Editar método de pago' : 'Nuevo método de pago'} onClose={() => setEditing(null)}
        footer={<><Button onClick={() => setEditing(null)}>Cancelar</Button><Button variant="primary" onClick={save}>Guardar</Button></>}>
        <ErrorAlert error={error} />
        <TextField label="Nombre" value={form.name} onChange={(v) => setForm({ ...form, name: v })} error={error?.fields.name} required />
        <SelectField label="Tipo" value={form.kind} onChange={(v) => setForm({ ...form, kind: v })}
          options={Object.entries(KINDS).map(([value, label]) => ({ value, label }))} />
        {form.kind !== 'credito' && (
          <SelectField label="Cuenta de caja o bancos" value={form.account_code} onChange={(v) => setForm({ ...form, account_code: v })}
            error={error?.fields.account_code} options={(accounts.data ?? []).filter((a) => a.is_cash).map((a) => ({ value: a.code, label: `${a.code} ${a.name}` }))} />
        )}
        <Checkbox label="Activo" checked={form.active} onChange={(v) => setForm({ ...form, active: v })} />
      </Dialog>
    </div>
  );
}

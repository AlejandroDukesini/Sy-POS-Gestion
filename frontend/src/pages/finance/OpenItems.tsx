import { Ban, HandCoins, Plus } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Route, Routes } from 'react-router-dom';
import { ApiError, newKey, post, qs } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { ConfirmDialog, Dialog } from '../../components/ui/Dialog';
import { Alert, EmptyState, ErrorAlert, ErrorState, Loading, StatusBadge } from '../../components/ui/Feedback';
import { NumberField, SelectField, TextField } from '../../components/ui/Form';
import { Card, LinkTabs, Metric } from '../../components/ui/Layout';
import { DataTable } from '../../components/ui/Table';
import { useAuth } from '../../context/Auth';
import { useToast } from '../../context/Toast';
import { date, daysFromToday, money, today, toApiNumber } from '../../lib/format';
import { useApi, useDebounced } from '../../lib/hooks';
import { FinanceBack } from './FinanceRoutes';

type Kind = 'ar' | 'ap';
const TEXT = {
  ar: { abbr: 'AR', title: 'Cuentas por cobrar', party: 'Cliente', parties: 'clientes', partyKey: 'customer_id', pay: 'Registrar cobro',
    paid: 'Cobro registrado', accountTypes: ['ingreso'] },
  ap: { abbr: 'AP', title: 'Cuentas por pagar', party: 'Proveedor', parties: 'proveedores', partyKey: 'supplier_id', pay: 'Registrar pago',
    paid: 'Pago registrado', accountTypes: ['activo', 'gasto', 'costo'] },
};
const BUCKET_LABELS: Record<string, string> = { corriente: 'Al día', '1_30': '1 a 30 días', '31_60': '31 a 60', '61_90': '61 a 90', mas_90: 'Más de 90' };

export function OpenItemsPage({ kind }: { kind: Kind }) {
  const t = TEXT[kind];
  const { can } = useAuth();
  const base = `/finanzas/${kind}`;
  return (
    <div className="stack">
      <FinanceBack abbr={t.abbr} title={t.title} />
      <LinkTabs label={t.title} tabs={[
        { to: base, label: 'Documentos', end: true },
        { to: `${base}/antiguedad`, label: kind === 'ar' ? 'Antigüedad de cartera' : 'Antigüedad' },
        ...(can('finanzas.registrar') ? [{ to: `${base}/nuevo`, label: kind === 'ar' ? 'Nueva cuenta por cobrar' : 'Nueva factura de proveedor' }] : []),
      ]} />
      <Routes>
        <Route index element={<ItemList kind={kind} />} />
        <Route path="antiguedad" element={<Aging kind={kind} />} />
        <Route path="nuevo" element={<NewItem kind={kind} />} />
      </Routes>
    </div>
  );
}

function ItemList({ kind }: { kind: Kind }) {
  const t = TEXT[kind];
  const [status, setStatus] = useState('pendientes');
  const [q, setQ] = useState('');
  const [selected, setSelected] = useState<number | null>(null);
  const term = useDebounced(q, 300);
  const list = useApi<any[]>(`/finance/${kind}${qs({ status, q: term })}`);
  const alerts = useApi(`/finance/${kind}/alerts`);
  const items = list.data ?? [];
  const pending = items.reduce((s, i) => s + Number(i.balance), 0);
  return (
    <>
      {alerts.data && (alerts.data.vencidas.length > 0 || alerts.data.por_vencer.length > 0) && (
        <Alert kind={alerts.data.vencidas.length ? 'danger' : 'warning'} title="Vencimientos">
          {alerts.data.vencidas.length} vencidas · {alerts.data.por_vencer.length} vencen en los próximos 7 días.
        </Alert>
      )}
      <Card>
        <div className="card-body row">
          <div style={{ minWidth: 200 }}>
            <SelectField label="Estado" value={status} onChange={setStatus} options={[
              { value: 'pendientes', label: 'Pendientes' }, { value: 'vencidas', label: 'Vencidas' },
              { value: 'pagadas', label: 'Pagadas' }, { value: 'todas', label: 'Todas' }]} />
          </div>
          <div className="grow" style={{ minWidth: 220 }}>
            <TextField label={`Buscar por ${t.party.toLowerCase()} o número`} type="search" value={q} onChange={setQ} />
          </div>
          {status !== 'pagadas' && <Metric label="Saldo de la lista" value={money(pending.toFixed(2))} />}
        </div>
        {list.loading && !list.data ? <Loading /> : list.error ? <ErrorState error={list.error} onRetry={list.reload} /> :
          !items.length ? <EmptyState title="No hay documentos en este estado" /> : (
            <DataTable caption={t.title} rows={items} rowKey={(i) => i.id} onSelect={(i) => setSelected(i.id)} columns={[
              { key: 'n', header: 'Número', render: (i: any) => <strong>{i.number}</strong> },
              { key: 'p', header: t.party, render: (i: any) => i.party_name },
              { key: 'e', header: 'Emisión', render: (i: any) => date(i.issue_date) },
              { key: 'v', header: 'Vence', render: (i: any) => <>{date(i.due_date)}{i.days_overdue > 0 && <small className="muted"> ({i.days_overdue} días)</small>}</> },
              { key: 's', header: 'Estado', render: (i: any) => <StatusBadge status={i.state} /> },
              { key: 'a', header: 'Importe', numeric: true, render: (i: any) => money(i.amount) },
              { key: 'b', header: 'Saldo', numeric: true, render: (i: any) => <strong>{money(i.balance)}</strong> },
            ]} />
          )}
      </Card>
      {selected && <ItemDetail kind={kind} id={selected} onClose={() => setSelected(null)} onChanged={() => { list.reload(); alerts.reload(); }} />}
    </>
  );
}

function ItemDetail({ kind, id, onClose, onChanged }: { kind: Kind; id: number; onClose: () => void; onChanged: () => void }) {
  const t = TEXT[kind];
  const { can } = useAuth();
  const { notify } = useToast();
  const item = useApi(`/finance/${kind}/${id}`);
  const methods = useApi<any[]>('/payment-methods');
  const key = useMemo(newKey, [id]);
  const [form, setForm] = useState({ amount: '', method_id: '', payment_date: today(), reference: '' });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [voidPayment, setVoidPayment] = useState<any>(null);
  const [voidItem, setVoidItem] = useState(false);
  const [payKey, setPayKey] = useState(key);
  const d = item.data;

  const pay = async () => {
    const e: Record<string, string> = {};
    if (!(Number(toApiNumber(form.amount)) > 0)) e.amount = 'Escriba el importe.';
    if (!form.method_id) e.method_id = 'Elija el medio.';
    setErrors(e);
    if (Object.keys(e).length) return;
    setBusy(true);
    setError(null);
    try {
      await post(`/finance/${kind}/${id}/payments`, { ...form, amount: toApiNumber(form.amount), method_id: Number(form.method_id) }, payKey);
      notify('success', t.paid);
      setForm({ ...form, amount: '', reference: '' });
      setPayKey(newKey());
      item.reload();
      onChanged();
    } catch (err) {
      setError(err as ApiError);
      setErrors((err as ApiError).fields ?? {});
    } finally {
      setBusy(false);
    }
  };
  const doVoidPayment = async (reason: string) => {
    try {
      await post(`/finance/${kind}/payments/${voidPayment.id}/void`, { reason });
      notify('success', 'Pago anulado', 'Se registró el reverso contable.');
      item.reload();
      onChanged();
    } catch (err) {
      notify('danger', 'No se pudo anular', (err as Error).message);
    } finally {
      setVoidPayment(null);
    }
  };
  const doVoidItem = async (reason: string) => {
    try {
      await post(`/finance/${kind}/${id}/void`, { reason });
      notify('success', 'Documento anulado');
      item.reload();
      onChanged();
    } catch (err) {
      notify('danger', 'No se pudo anular', (err as Error).message);
    } finally {
      setVoidItem(false);
    }
  };
  return (
    <Dialog open title={d ? `${d.number} · ${d.party_name}` : 'Detalle'} onClose={onClose} size="wide">
      {item.loading && !d ? <Loading /> : item.error ? <ErrorState error={item.error} /> : d && (
        <>
          <div className="metrics">
            <Metric label="Importe" value={money(d.amount)} />
            <Metric label="Saldo" value={money(d.balance)} />
            <Metric label="Vence" value={date(d.due_date)} />
          </div>
          {d.description && <p>{d.description}</p>}
          {d.status === 'anulada' && <Alert kind="danger">Documento anulado.</Alert>}
          <h3>Movimientos</h3>
          {d.payments.length || d.credits.length ? (
            <ul className="result-list">
              {d.payments.map((p: any) => (
                <li key={p.id} className="result-item" style={{ cursor: 'default' }}>
                  <span>{date(p.payment_date)} · {p.method_name}{p.reference ? ` · ${p.reference}` : ''} · {p.username}
                    {p.voided_at && <><br /><small>Anulado: {p.void_reason}</small></>}</span>
                  <span className="row"><strong style={{ textDecoration: p.voided_at ? 'line-through' : undefined }}>{money(p.amount)}</strong>
                    {!p.voided_at && can('finanzas.registrar') && <Button size="sm" variant="ghost" onClick={() => setVoidPayment(p)}>Anular</Button>}</span>
                </li>
              ))}
              {d.credits.map((c: any) => (
                <li key={`c${c.id}`} className="result-item" style={{ cursor: 'default' }}>
                  <span>Abono por devolución</span><strong>{money(c.amount)}</strong>
                </li>
              ))}
            </ul>
          ) : <p className="muted">Sin pagos todavía.</p>}
          {can('finanzas.registrar') && d.status !== 'anulada' && Number(d.balance) > 0 && (
            <fieldset>
              <legend>{t.pay}</legend>
              <ErrorAlert error={error} />
              <div className="form-grid">
                <NumberField label="Importe" value={form.amount} onChange={(v) => setForm({ ...form, amount: v })} error={errors.amount}
                  hint={`Saldo: ${money(d.balance)}`} required />
                <SelectField label="Medio" value={form.method_id} onChange={(v) => setForm({ ...form, method_id: v })} placeholder="Elija…"
                  error={errors.method_id} required options={(methods.data ?? []).filter((m) => m.kind !== 'credito').map((m) => ({ value: m.id, label: m.name }))} />
                <TextField label="Fecha" type="date" value={form.payment_date} onChange={(v) => setForm({ ...form, payment_date: v })} />
                <TextField label="Referencia" value={form.reference} onChange={(v) => setForm({ ...form, reference: v })} />
              </div>
              <div className="form-actions" style={{ marginTop: 12 }}>
                <Button onClick={() => setForm({ ...form, amount: d.balance })}>Saldo completo</Button>
                <Button variant="primary" busy={busy} icon={<HandCoins size={20} />} onClick={pay}>{t.pay}</Button>
              </div>
            </fieldset>
          )}
          {can('finanzas.registrar') && d.status !== 'anulada' && d.source_type === 'manual' && (
            <div><Button variant="ghost" icon={<Ban size={20} />} onClick={() => setVoidItem(true)}>Anular documento</Button></div>
          )}
        </>
      )}
      <ConfirmDialog open={Boolean(voidPayment)} title="Anular pago" danger requireReason confirmLabel="Anular pago"
        onClose={() => setVoidPayment(null)} onConfirm={doVoidPayment} message="El saldo vuelve a quedar pendiente y se registra el reverso contable." />
      <ConfirmDialog open={voidItem} title="Anular documento" danger requireReason confirmLabel="Anular"
        onClose={() => setVoidItem(false)} onConfirm={doVoidItem} message="Se reversa su asiento contable. Debe no tener pagos vigentes." />
    </Dialog>
  );
}

function Aging({ kind }: { kind: Kind }) {
  const [asOf, setAsOf] = useState(today());
  const a = useApi(`/finance/${kind}/aging${qs({ as_of: asOf })}`);
  return (
    <Card>
      <div className="card-body"><TextField label="Fecha de corte" type="date" value={asOf} onChange={setAsOf} /></div>
      {a.loading && !a.data ? <Loading /> : a.error ? <ErrorState error={a.error} /> : a.data && (
        a.data.rows.length ? (
          <DataTable caption="Antigüedad" rows={a.data.rows} rowKey={(r: any) => r.party_id} columns={[
            { key: 'p', header: TEXT[kind].party, render: (r: any) => r.party_name },
            ...a.data.buckets.map((b: string) => ({ key: b, header: BUCKET_LABELS[b], numeric: true, render: (r: any) => (Number(r[b]) ? money(r[b]) : '—') })),
            { key: 't', header: 'Total', numeric: true, render: (r: any) => <strong>{money(r.total)}</strong> },
          ]} footer={<tr><td>Total</td>{a.data.buckets.map((b: string) => <td key={b} className="num">{money(a.data.totals[b])}</td>)}
            <td className="num">{money(a.data.totals.total)}</td></tr>} />
        ) : <EmptyState title="No hay saldos pendientes" />
      )}
    </Card>
  );
}

function NewItem({ kind }: { kind: Kind }) {
  const t = TEXT[kind];
  const { notify } = useToast();
  const parties = useApi(`/parties/${t.parties}?page_size=200`);
  const accounts = useApi<any[]>('/finance/accounts');
  const [form, setForm] = useState({ party: '', number: '', amount: '', issue_date: today(), due_date: daysFromToday(30), description: '',
    account_code: kind === 'ap' ? '1435' : '4135' });
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (v: string) => setForm((f) => ({ ...f, [k]: v }));
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await post(`/finance/${kind}`, { [t.partyKey]: form.party ? Number(form.party) : null, number: form.number || null,
        amount: toApiNumber(form.amount), issue_date: form.issue_date, due_date: form.due_date, description: form.description,
        account_code: form.account_code });
      notify('success', 'Documento registrado', r.number);
      setForm({ ...form, number: '', amount: '', description: '' });
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  const fe = error?.fields ?? {};
  return (
    <Card>
      <div className="card-body stack">
        <ErrorAlert error={error} />
        {parties.data?.items?.length === 0 && <Alert kind="info">Registre primero {t.parties} en Gestión.</Alert>}
        <div className="form-grid">
          <SelectField label={t.party} value={form.party} onChange={set('party')} placeholder="Elija…" error={fe[t.partyKey]} required
            options={(parties.data?.items ?? []).map((p: any) => ({ value: p.id, label: p.name }))} />
          <TextField label={kind === 'ap' ? 'Número de la factura del proveedor' : 'Número (opcional, se asigna automáticamente)'}
            value={form.number} onChange={set('number')} error={fe.number} required={kind === 'ap'} />
          <NumberField label="Importe" value={form.amount} onChange={set('amount')} error={fe.amount} required />
          <TextField label="Fecha de emisión" type="date" value={form.issue_date} onChange={set('issue_date')} />
          <TextField label="Vencimiento" type="date" value={form.due_date} onChange={set('due_date')} error={fe.due_date} />
          <SelectField label={kind === 'ap' ? 'Se registra en (débito)' : 'Ingreso (crédito)'} value={form.account_code} onChange={set('account_code')}
            error={fe.account_code} options={(accounts.data ?? []).filter((a) => t.accountTypes.includes(a.type) && !a.is_cash)
              .map((a) => ({ value: a.code, label: `${a.code} ${a.name}` }))} />
        </div>
        <TextField label="Descripción" value={form.description} onChange={set('description')} />
        <div className="form-actions"><Button variant="primary" busy={busy} icon={<Plus size={20} />} onClick={save}>Registrar</Button></div>
      </div>
    </Card>
  );
}

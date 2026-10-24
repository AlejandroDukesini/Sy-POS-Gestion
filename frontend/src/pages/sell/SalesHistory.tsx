import { ArrowLeft, Ban, Printer, Undo2 } from 'lucide-react';
import { Fragment, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ApiError, newKey, post, qs } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { ConfirmDialog, Dialog } from '../../components/ui/Dialog';
import { Alert, EmptyState, ErrorAlert, ErrorState, Loading, StatusBadge } from '../../components/ui/Feedback';
import { SelectField, TextField } from '../../components/ui/Form';
import { Card, Metric, PageHeader } from '../../components/ui/Layout';
import { DataTable, Pagination } from '../../components/ui/Table';
import { useAuth } from '../../context/Auth';
import { useToast } from '../../context/Toast';
import { date, dateTime, money, qty, toApiNumber } from '../../lib/format';
import { useApi, useDebounced } from '../../lib/hooks';
import { printReceipt } from './receipt';

export function SalesHistory() {
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [page, setPage] = useState(1);
  const term = useDebounced(q, 300);
  const list = useApi(`/sales${qs({ q: term, status, date_from: from, date_to: to, page, page_size: 25 })}`);
  const day = useApi('/sales/summary');
  return (
    <div className="stack">
      {day.data && (
        <div className="metrics">
          <Metric label="Ventas de hoy" value={day.data.sales} />
          <Metric label="Total vendido hoy" value={money(day.data.total)} />
          {day.data.by_method.map((m: any) => <Metric key={m.name} label={m.name} value={money(m.amount)} hint={`${m.count} pagos`} />)}
        </div>
      )}
      <Card>
        <div className="card-body row">
          <div className="grow" style={{ minWidth: 220 }}>
            <TextField label="Buscar por número o cliente" type="search" value={q} onChange={(v) => { setQ(v); setPage(1); }} />
          </div>
          <div style={{ minWidth: 170 }}>
            <SelectField label="Estado" value={status} onChange={(v) => { setStatus(v); setPage(1); }} placeholder="Todos"
              options={[{ value: 'completada', label: 'Completadas' }, { value: 'anulada', label: 'Anuladas' }]} />
          </div>
          <div><TextField label="Desde" type="date" value={from} onChange={(v) => { setFrom(v); setPage(1); }} /></div>
          <div><TextField label="Hasta" type="date" value={to} onChange={(v) => { setTo(v); setPage(1); }} /></div>
        </div>
        {list.loading && !list.data ? <Loading /> : list.error ? <ErrorState error={list.error} onRetry={list.reload} /> :
          !list.data.items.length ? <EmptyState title="No hay ventas con estos filtros" /> : (
            <>
              <DataTable caption="Historial de ventas" rows={list.data.items} rowKey={(s: any) => s.id}
                onSelect={(s: any) => navigate(`/vender/historial/${s.id}`)} columns={[
                  { key: 'number', header: 'Número', render: (s: any) => <strong>{s.number}</strong> },
                  { key: 'date', header: 'Fecha', render: (s: any) => dateTime(s.created_at) },
                  { key: 'customer', header: 'Cliente', render: (s: any) => s.customer_name || <span className="muted">Consumidor final</span> },
                  { key: 'user', header: 'Vendedor', render: (s: any) => s.username },
                  { key: 'status', header: 'Estado', render: (s: any) => (
                    <span className="row" style={{ gap: 6 }}><StatusBadge status={s.status} />
                      {Number(s.returned) > 0 && <span className="badge badge-info">Con devolución</span>}
                      {Number(s.credit) > 0 && <span className="badge">Crédito</span>}</span>) },
                  { key: 'total', header: 'Total', numeric: true, render: (s: any) => <strong>{money(s.total)}</strong> },
                ]} />
              <Pagination page={list.data.page} pages={list.data.pages} total={list.data.total} onPage={setPage} />
            </>
          )}
      </Card>
    </div>
  );
}

export function SaleDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const { notify } = useToast();
  const sale = useApi(`/sales/${id}`);
  const methods = useApi<any[]>('/payment-methods');
  const [voiding, setVoiding] = useState(false);
  const [returning, setReturning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const s = sale.data;

  const reprint = async () => {
    setBusy(true);
    try {
      await printReceipt(Number(id));
      notify('success', 'Comprobante enviado a imprimir');
      sale.reload();
    } catch (err) {
      notify('danger', 'No se pudo imprimir', (err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const doVoid = async (reason: string) => {
    setBusy(true);
    setError(null);
    try {
      await post(`/sales/${id}/void`, { reason });
      notify('success', 'Venta anulada', 'Las existencias y la contabilidad se revirtieron.');
      sale.reload();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
      setVoiding(false);
    }
  };

  if (sale.loading && !s) return <Loading />;
  if (sale.error) return <ErrorState error={sale.error} onRetry={sale.reload} />;
  const returnable = s.lines.some((l: any) => Number(l.qty) > Number(l.returned));
  return (
    <div className="stack">
      <Link to="/vender/historial" className="btn btn-ghost" style={{ alignSelf: 'flex-start' }}><ArrowLeft size={20} aria-hidden /> Volver al historial</Link>
      <PageHeader title={`Venta ${s.number}`} description={`${dateTime(s.created_at)} · ${s.seller_name || s.username}`} actions={
        <>
          <StatusBadge status={s.status} />
          <Button variant="primary" busy={busy} icon={<Printer size={20} />} onClick={reprint}>
            {s.prints ? 'Reimprimir' : 'Imprimir'} comprobante
          </Button>
          {can('ventas.anular') && s.status === 'completada' && returnable && (
            <Button variant="outline" icon={<Undo2 size={20} />} onClick={() => setReturning(true)}>Devolución</Button>
          )}
          {can('ventas.anular') && s.status === 'completada' && !s.returns.length && (
            <Button variant="danger" icon={<Ban size={20} />} onClick={() => setVoiding(true)}>Anular</Button>
          )}
        </>
      } />
      <ErrorAlert error={error} />
      {s.status === 'anulada' && <Alert kind="danger" title="Venta anulada">{s.void_reason} · {dateTime(s.voided_at)}</Alert>}
      <Card title="Productos">
        <DataTable caption="Productos de la venta" rows={s.lines} rowKey={(l: any) => l.id} columns={[
          { key: 'p', header: 'Producto', render: (l: any) => <><strong>{l.code}</strong> {l.description}</> },
          { key: 'q', header: 'Cantidad', numeric: true, render: (l: any) => qty(l.qty) },
          { key: 'r', header: 'Devuelto', numeric: true, render: (l: any) => (Number(l.returned) ? qty(l.returned) : '—') },
          { key: 'u', header: 'Precio', numeric: true, render: (l: any) => money(l.unit_price) },
          { key: 'd', header: 'Descuento', numeric: true, render: (l: any) => (Number(l.discount) ? money(l.discount) : '—') },
          { key: 'n', header: 'Total', numeric: true, render: (l: any) => <strong>{money(l.net)}</strong> },
        ]} />
      </Card>
      <div className="grid-2">
        <Card title="Totales y pagos">
          <div className="card-body">
            <dl className="dl" style={{ gridTemplateColumns: '1fr auto' }}>
              <dt>Subtotal</dt><dd className="num">{money(s.gross)}</dd>
              <dt>Descuentos</dt><dd className="num">-{money(s.discount)}</dd>
              <dt>IVA incluido</dt><dd className="num">{money(s.tax)}</dd>
              <dt>Total</dt><dd className="num"><strong>{money(s.total)}</strong></dd>
              {s.payments.map((p: any) => (
                <Fragment key={p.id}>
                  <dt>{p.method_name}{p.reference ? ` (${p.reference})` : ''}</dt>
                  <dd className="num">{money(p.amount)}</dd>
                </Fragment>
              ))}
              {Number(s.change) > 0 && <><dt>Cambio entregado</dt><dd className="num">{money(s.change)}</dd></>}
            </dl>
          </div>
        </Card>
        <Card title="Cliente y crédito">
          <div className="card-body stack">
            <p>{s.customer_name || 'Consumidor final'}{s.customer_identification && ` · ${s.customer_identification}`}</p>
            {s.receivable && <p>Cuenta por cobrar <strong>{s.receivable.number}</strong> por {money(s.receivable.amount)} · vence {date(s.receivable.due_date)}</p>}
            {s.notes && <p className="muted">{s.notes}</p>}
          </div>
        </Card>
      </div>
      {s.returns.length > 0 && (
        <Card title="Devoluciones">
          <DataTable caption="Devoluciones" rows={s.returns} rowKey={(r: any) => r.id} columns={[
            { key: 'n', header: 'Número', render: (r: any) => r.number },
            { key: 'd', header: 'Fecha', render: (r: any) => dateTime(r.created_at) },
            { key: 'm', header: 'Motivo', render: (r: any) => r.reason },
            { key: 'f', header: 'Reembolso', render: (r: any) => (Number(r.refund) ? `${money(r.refund)} (${r.refund_method_name})` : '—') },
            { key: 'c', header: 'Abono a cartera', numeric: true, render: (r: any) => (Number(r.credit_applied) ? money(r.credit_applied) : '—') },
            { key: 't', header: 'Total', numeric: true, render: (r: any) => money(r.total) },
          ]} />
        </Card>
      )}
      <ConfirmDialog open={voiding} title={`Anular venta ${s.number}`} danger requireReason busy={busy} confirmLabel="Anular venta"
        onClose={() => setVoiding(false)} onConfirm={doVoid}
        message="Las unidades vuelven al inventario y se registra el reverso contable. La venta se conserva marcada como anulada." />
      {returning && <ReturnDialog sale={s} methods={methods.data ?? []} onClose={() => setReturning(false)}
        onDone={() => { setReturning(false); sale.reload(); }} />}
    </div>
  );
}

function ReturnDialog({ sale, methods, onClose, onDone }: { sale: any; methods: any[]; onClose: () => void; onDone: () => void }) {
  const { notify } = useToast();
  const key = useMemo(newKey, []);
  const [qtys, setQtys] = useState<Record<number, string>>({});
  const [reason, setReason] = useState('');
  const [method, setMethod] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    const e: Record<string, string> = {};
    if (!reason.trim()) e.reason = 'Escriba el motivo.';
    const lines = Object.entries(qtys).filter(([, v]) => Number(toApiNumber(v)) > 0)
      .map(([id, v]) => ({ sale_line_id: Number(id), qty: toApiNumber(v) }));
    if (!lines.length) e.lines = 'Indique al menos una cantidad.';
    setErrors(e);
    if (Object.keys(e).length) return;
    setBusy(true);
    setError(null);
    try {
      await post(`/sales/${sale.id}/returns`, { reason: reason.trim(), lines, refund_method_id: method ? Number(method) : null }, key);
      notify('success', 'Devolución registrada', 'Las unidades volvieron al inventario.');
      onDone();
    } catch (err) {
      setError(err as ApiError);
      setErrors((err as ApiError).fields ?? {});
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open title={`Devolución de la venta ${sale.number}`} onClose={onClose} size="wide" footer={
      <><Button onClick={onClose}>Cancelar</Button><Button variant="primary" busy={busy} onClick={submit}>Registrar devolución</Button></>
    }>
      <ErrorAlert error={error} />
      {errors.lines && <Alert kind="danger">{errors.lines}</Alert>}
      <div className="table-wrap">
        <table className="table">
          <caption className="sr-only">Cantidades a devolver</caption>
          <thead><tr><th>Producto</th><th className="num">Vendido</th><th className="num">Ya devuelto</th><th className="num">Devolver</th></tr></thead>
          <tbody>
            {sale.lines.map((l: any) => {
              const available = Number(l.qty) - Number(l.returned);
              return (
                <tr key={l.id}>
                  <td><strong>{l.code}</strong> {l.description}</td>
                  <td className="num">{qty(l.qty)}</td>
                  <td className="num">{qty(l.returned)}</td>
                  <td className="num">
                    <input className="input num" style={{ width: 100 }} inputMode="decimal" disabled={available <= 0}
                      aria-label={`Cantidad a devolver de ${l.code} (máximo ${available})`} value={qtys[l.id] ?? ''}
                      onChange={(e) => setQtys((q) => ({ ...q, [l.id]: e.target.value }))} placeholder="0" />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <TextField label="Motivo" value={reason} onChange={setReason} error={errors.reason} required />
      <SelectField label="Reembolsar con" value={method} onChange={setMethod} error={errors.refund_method_id} placeholder="Elija…"
        options={methods.filter((m) => m.kind !== 'credito').map((m) => ({ value: m.id, label: m.name }))}
        hint={sale.receivable ? 'Si la venta tiene saldo a crédito, primero se descuenta de la cuenta por cobrar.' : undefined} />
    </Dialog>
  );
}

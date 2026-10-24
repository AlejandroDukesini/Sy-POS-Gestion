import { Banknote, CheckCircle2, CreditCard, Printer, ShoppingCart, Trash2, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ApiError, newKey, post } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { ConfirmDialog, Dialog } from '../../components/ui/Dialog';
import { Alert, EmptyState, ErrorAlert } from '../../components/ui/Feedback';
import { NumberField, TextField } from '../../components/ui/Form';
import { Card } from '../../components/ui/Layout';
import { useAuth } from '../../context/Auth';
import { useToast } from '../../context/Toast';
import { daysFromToday, money, toApiNumber } from '../../lib/format';
import { useApi, useOnline } from '../../lib/hooks';
import { addToCart, CartTable, CustomerPicker, ProductSearch, StockWarnings, TotalsBox, useQuote, type CartLine, type Customer } from './Cart';
import { printReceipt } from './receipt';

interface PaymentRow { method_id: number; amount: string; tendered: string; reference: string }
const STORAGE = 'pospy.cart';

function loadCart(): { lines: CartLine[]; customer: Customer | null } {
  try {
    return JSON.parse(sessionStorage.getItem(STORAGE) ?? '') ?? { lines: [], customer: null };
  } catch {
    return { lines: [], customer: null };
  }
}

export default function PosPage() {
  const { can } = useAuth();
  const { notify } = useToast();
  const online = useOnline();
  const location = useLocation();
  const navigate = useNavigate();
  const methods = useApi<any[]>('/payment-methods');
  const [lines, setLines] = useState<CartLine[]>(() => loadCart().lines);
  const [customer, setCustomer] = useState<Customer | null>(() => loadCart().customer);
  const [payments, setPayments] = useState<PaymentRow[]>([]);
  const [notes, setNotes] = useState('');
  const [dueDate, setDueDate] = useState('');
  const [sourceDoc, setSourceDoc] = useState<number | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [done, setDone] = useState<any>(null);
  const attemptKey = useRef<string | null>(null);   // misma clave en reintentos del mismo cobro

  const apiPayments = useMemo(() => payments.map((p) => ({ method_id: p.method_id, amount: toApiNumber(p.amount) || '0',
    tendered: p.tendered ? toApiNumber(p.tendered) : undefined })), [payments]);
  const { quote, error: quoteError } = useQuote(lines, apiPayments);
  const summary = quote?.payment_summary;
  const methodList = methods.data ?? [];
  const methodById = new Map(methodList.map((m) => [m.id, m]));
  const hasCredit = payments.some((p) => methodById.get(p.method_id)?.kind === 'credito');

  useEffect(() => {
    sessionStorage.setItem(STORAGE, JSON.stringify({ lines, customer }));
    attemptKey.current = null;            // el carrito cambió: el próximo cobro es otra operación
  }, [lines, customer, payments]);

  useEffect(() => {
    // Venta desde una cotización u orden: carga sus líneas (los precios se recalculan con los vigentes).
    const state = location.state as { fromDocument?: any } | null;
    if (state?.fromDocument) {
      const doc = state.fromDocument;
      setLines(doc.lines.map((l: any) => ({ product_id: l.product_id, code: l.code, description: l.description, unit: '',
        qty: l.qty, discount_pct: Number(l.manual_discount) ? l.manual_discount : '' })));
      if (doc.customer_id) setCustomer({ id: doc.customer_id, name: doc.customer_name, identification: doc.customer_identification,
        phone: doc.customer_phone, email: doc.customer_email, address: doc.customer_address });
      setSourceDoc(doc.id);
      setNotes(`Según ${doc.type_name} ${doc.number}`);
      navigate(location.pathname, { replace: true, state: null });
    }
  }, [location, navigate]);

  const addPayment = (methodId: number) => {
    const remaining = summary ? summary.remaining : quote?.totals.total ?? '0';
    setPayments((ps) => [...ps, { method_id: methodId, amount: Number(remaining) > 0 ? remaining : '', tendered: '', reference: '' }]);
    if (methodById.get(methodId)?.kind === 'credito' && !dueDate) setDueDate(daysFromToday(30));
  };
  const updatePayment = (i: number, changes: Partial<PaymentRow>) =>
    setPayments((ps) => ps.map((p, j) => (j === i ? { ...p, ...changes } : p)));

  const clear = () => {
    setLines([]);
    setCustomer(null);
    setPayments([]);
    setNotes('');
    setSourceDoc(null);
    setDueDate('');
    setError(null);
  };

  const readyIssues: string[] = [];
  if (!lines.length) readyIssues.push('Agregue productos.');
  if (quote && !quote.can_sell) readyIssues.push('Hay productos sin existencias suficientes.');
  if (!payments.length) readyIssues.push('Elija el método de pago.');
  else if (summary && !summary.complete) {
    readyIssues.push(Number(summary.remaining) > 0 ? `Falta registrar ${money(summary.remaining)}.` : `Los pagos superan el total en ${money(summary.excess)}.`);
  }
  if (hasCredit && !customer) readyIssues.push('Una venta a crédito necesita cliente.');

  const checkout = async () => {
    if (!attemptKey.current) attemptKey.current = newKey();
    setBusy(true);
    setError(null);
    try {
      const sale = await post('/sales', {
        lines: lines.map((l) => ({ product_id: l.product_id, qty: toApiNumber(l.qty), discount_pct: toApiNumber(l.discount_pct) || '0' })),
        payments: payments.map((p) => ({ method_id: p.method_id, amount: toApiNumber(p.amount),
          tendered: p.tendered ? toApiNumber(p.tendered) : null, reference: p.reference })),
        customer_id: customer?.id ?? null, notes, due_date: hasCredit && dueDate ? dueDate : null, source_document_id: sourceDoc,
      }, attemptKey.current);
      setConfirming(false);
      setDone(sale);
      clear();
      if (sale.duplicate) notify('info', 'Venta ya registrada', `La venta ${sale.number} ya estaba guardada; no se duplicó.`);
    } catch (err) {
      setError(err as ApiError);
      setConfirming(false);
      if (!(err as ApiError).offline && (err as ApiError).status !== 0) attemptKey.current = null;
    } finally {
      setBusy(false);
    }
  };

  if (!can('ventas.vender')) {
    return <EmptyState title="No tiene permiso para registrar ventas" />;
  }

  return (
    <div className="pos">
      <Card title="Productos" actions={lines.length > 0 && (
        <Button variant="ghost" icon={<Trash2 size={20} />} onClick={clear}>Vaciar</Button>)}>
        <div className="card-body stack">
          <ProductSearch autoFocus onPick={(p) => setLines((ls) => addToCart(ls, p))} />
          <StockWarnings quote={quote} />
          <ErrorAlert error={quoteError} />
          {lines.length ? <CartTable lines={lines} setLines={setLines} quote={quote} />
            : <EmptyState title="El carrito está vacío" icon={<ShoppingCart size={40} aria-hidden />}><p>Busque un producto para comenzar.</p></EmptyState>}
        </div>
      </Card>
      <div className="stack">
        <Card title="Cliente">
          <div className="card-body"><CustomerPicker value={customer} onChange={setCustomer} /></div>
        </Card>
        <Card title="Total y pago">
          <div className="card-body stack">
            {quote ? <TotalsBox quote={quote} /> : <p className="muted">Agregue productos para ver el total.</p>}
            <div>
              <span className="field-label">Agregar pago</span>
              <div className="grid-2" style={{ gap: 8, marginTop: 8 }}>
                {methodList.map((m) => (
                  <Button key={m.id} variant="outline" className="btn-wrap" disabled={!lines.length} onClick={() => addPayment(m.id)}
                    icon={m.kind === 'efectivo' ? <Banknote size={20} /> : <CreditCard size={20} />}>{m.name}</Button>
                ))}
              </div>
            </div>
            {payments.map((p, i) => {
              const m = methodById.get(p.method_id);
              return (
                <fieldset key={i}>
                  <legend>{m?.name}</legend>
                  <div className="grid-2">
                    <NumberField label="Importe" value={p.amount} onChange={(v) => updatePayment(i, { amount: v })} />
                    {m?.kind === 'efectivo' ? (
                      <NumberField label="Recibido" value={p.tendered} onChange={(v) => updatePayment(i, { tendered: v })}
                        hint="Para calcular el cambio." />
                    ) : m?.kind !== 'credito' ? (
                      <TextField label="Referencia" value={p.reference} onChange={(v) => updatePayment(i, { reference: v })} />
                    ) : (
                      <TextField label="Vence" type="date" value={dueDate} onChange={setDueDate} />
                    )}
                  </div>
                  <Button size="sm" variant="ghost" icon={<X size={18} />} onClick={() => setPayments((ps) => ps.filter((_, j) => j !== i))}>
                    Quitar pago
                  </Button>
                </fieldset>
              );
            })}
            {summary && payments.length > 0 && (
              <dl className="dl" style={{ gridTemplateColumns: '1fr auto' }}>
                <dt>Pagado</dt><dd className="num">{money(summary.paid)}</dd>
                {Number(summary.remaining) > 0 && <><dt>Falta</dt><dd className="num"><strong>{money(summary.remaining)}</strong></dd></>}
                {Number(summary.change) > 0 && <><dt style={{ fontSize: '1.125rem' }}>Cambio</dt><dd className="num pos-total">{money(summary.change)}</dd></>}
              </dl>
            )}
            {hasCredit && <Alert kind="info">La parte a crédito queda como cuenta por cobrar; no es un ingreso de caja hasta que se cobre.</Alert>}
            <TextField label="Observaciones" value={notes} onChange={setNotes} maxLength={500} />
            <ErrorAlert error={error} title="No se registró la venta" />
            {!online && <Alert kind="warning">Sin conexión con el servidor: no se puede registrar la venta.</Alert>}
            <Button variant="primary" size="lg" block disabled={readyIssues.length > 0 || !online} icon={<CheckCircle2 size={24} />}
              onClick={() => setConfirming(true)}>Cobrar {quote ? money(quote.totals.total) : ''}</Button>
            {readyIssues.length > 0 && lines.length > 0 && <p className="muted">{readyIssues.join(' ')}</p>}
          </div>
        </Card>
      </div>
      <ConfirmDialog open={confirming} title="Confirmar venta" confirmLabel="Registrar venta" busy={busy}
        onClose={() => setConfirming(false)} onConfirm={checkout} message={quote && (
          <div className="stack">
            <p>{lines.length} {lines.length === 1 ? 'producto' : 'productos'}{customer ? ` · ${customer.name}` : ''}</p>
            <TotalsBox quote={quote} />
            <ul>{payments.map((p, i) => <li key={i}>{methodById.get(p.method_id)?.name}: {money(toApiNumber(p.amount))}</li>)}</ul>
            {summary && Number(summary.change) > 0 && <p><strong>Cambio: {money(summary.change)}</strong></p>}
          </div>
        )} />
      {done && <SaleDone sale={done} onClose={() => setDone(null)} />}
    </div>
  );
}

function SaleDone({ sale, onClose }: { sale: any; onClose: () => void }) {
  const { notify } = useToast();
  const [busy, setBusy] = useState(false);
  const print = async () => {
    setBusy(true);
    try {
      await printReceipt(sale.id);
      notify('success', 'Comprobante enviado a imprimir');
    } catch (err) {
      notify('danger', 'No se pudo imprimir', (err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open title={`Venta ${sale.number} registrada`} onClose={onClose} footer={
      <>
        <Button size="lg" onClick={onClose}>Nueva venta</Button>
        <Button size="lg" variant="primary" busy={busy} icon={<Printer size={22} />} onClick={print}>Imprimir comprobante</Button>
      </>
    }>
      <Alert kind="success" title="Venta guardada">Total {money(sale.total)}{Number(sale.credit) > 0 ? ` · a crédito ${money(sale.credit)}` : ''}</Alert>
      {Number(sale.change) > 0 && <p className="pos-total">Cambio: {money(sale.change)}</p>}
      {sale.print?.error && <Alert kind="warning" title="La impresión automática falló">{sale.print.error}</Alert>}
      <p className="muted">El comprobante es un documento interno de venta, no una factura electrónica.</p>
    </Dialog>
  );
}

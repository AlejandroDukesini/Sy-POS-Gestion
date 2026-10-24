import { Minus, Plus, Search, Trash2, UserPlus, X } from 'lucide-react';
import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { ApiError, get, post, qs } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { Dialog } from '../../components/ui/Dialog';
import { Alert, Badge, ErrorAlert } from '../../components/ui/Feedback';
import { NumberField, TextField } from '../../components/ui/Form';
import { useAuth } from '../../context/Auth';
import { money, qty, toApiNumber } from '../../lib/format';
import { useDebounced } from '../../lib/hooks';

export interface CartLine {
  product_id: number;
  code: string;
  description: string;
  unit: string;
  qty: string;
  discount_pct: string;
}

export interface Quote {
  lines: any[];
  totals: { gross: string; discount: string; tax: string; base: string; total: string; items: string };
  stock_warnings: { product_id: number; code: string; message: string }[];
  can_sell: boolean;
  payment_summary?: { paid: string; remaining: string; excess: string; change: string; complete: boolean };
}

/** Los totales los calcula el servidor (misma lógica que al registrar la venta); aquí solo se muestran. */
export function useQuote(lines: CartLine[], payments?: { method_id: number; amount: string; tendered?: string }[]) {
  const [quote, setQuote] = useState<Quote | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const payload = useDebounced(JSON.stringify({
    lines: lines.map((l) => ({ product_id: l.product_id, qty: toApiNumber(l.qty) || '0', discount_pct: toApiNumber(l.discount_pct) || '0' })),
    payments,
  }), 200);
  useEffect(() => {
    const body = JSON.parse(payload);
    if (!body.lines.length) {
      setQuote(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    post<Quote>('/sales/quote', body)
      .then((q) => { if (!cancelled) { setQuote(q); setError(null); } })
      .catch((err) => { if (!cancelled) { setError(err); } })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [payload]);
  return { quote, error, loading, fresh: payload === JSON.stringify({
    lines: lines.map((l) => ({ product_id: l.product_id, qty: toApiNumber(l.qty) || '0', discount_pct: toApiNumber(l.discount_pct) || '0' })),
    payments,
  }) };
}

export function ProductSearch({ onPick, autoFocus }: { onPick: (p: any) => void; autoFocus?: boolean }) {
  const [q, setQ] = useState('');
  const [results, setResults] = useState<any[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const term = useDebounced(q.trim(), 200);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!term) {
      setResults([]);
      return;
    }
    let cancelled = false;
    get(`/products/lookup${qs({ q: term, limit: 12 })}`)
      .then((r) => { if (!cancelled) { setResults(r); setError(null); } })
      .catch((err) => { if (!cancelled) setError(err); });
    return () => { cancelled = true; };
  }, [term]);
  const pick = (p: any) => {
    onPick(p);
    setQ('');
    setResults([]);
    input.current?.focus();
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && results.length) {
      e.preventDefault();
      const exact = results.find((r) => r.code.toLowerCase() === q.trim().toLowerCase());
      pick(exact ?? results[0]);
    }
  };
  return (
    <div className="stack" style={{ gap: 8 }}>
      <label className="field-label" htmlFor="product-search">Buscar producto por código o descripción</label>
      <div className="row" style={{ flexWrap: 'nowrap' }}>
        <Search size={22} aria-hidden className="muted" />
        <input id="product-search" ref={input} className="input" type="search" value={q} onChange={(e) => setQ(e.target.value)}
          onKeyDown={onKey} autoComplete="off" autoFocus={autoFocus} placeholder="Escriba o escanee el código y presione Enter"
          aria-controls="product-results" />
      </div>
      <ErrorAlert error={error} />
      {results.length > 0 && (
        <ul id="product-results" className="result-list card" aria-label="Resultados">
          {results.map((p) => (
            <li key={p.id}>
              <button type="button" className="result-item" onClick={() => pick(p)}>
                <span>
                  <strong>{p.code}</strong> · {p.description}
                  <br /><small className="muted">Disponible: {qty(p.stock)} {p.unit}</small>
                </span>
                <span className="num">
                  <strong>{money(p.discount_price ?? p.price)}</strong>
                  {p.discount_price && <><br /><small className="muted"><s>{money(p.price)}</s></small></>}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {term && !results.length && !error && <p className="muted">Ningún producto activo coincide con «{term}».</p>}
    </div>
  );
}

export function addToCart(lines: CartLine[], p: any): CartLine[] {
  const existing = lines.find((l) => l.product_id === p.id);
  if (existing) {
    return lines.map((l) => (l === existing ? { ...l, qty: String(Number(toApiNumber(l.qty) || 0) + 1) } : l));
  }
  return [...lines, { product_id: p.id, code: p.code, description: p.description, unit: p.unit, qty: '1', discount_pct: '' }];
}

export function CartTable({ lines, setLines, quote }: { lines: CartLine[]; setLines: (l: CartLine[]) => void; quote: Quote | null }) {
  const { can } = useAuth();
  const allowDiscount = can('ventas.descuento');
  const priced = new Map((quote?.lines ?? []).map((l, i) => [i, l]));
  const update = (i: number, changes: Partial<CartLine>) => setLines(lines.map((l, j) => (j === i ? { ...l, ...changes } : l)));
  const step = (i: number, delta: number) => {
    const next = Math.max(1, Number(toApiNumber(lines[i].qty) || 0) + delta);
    update(i, { qty: String(next) });
  };
  const warnings = new Set((quote?.stock_warnings ?? []).map((w) => w.product_id));
  return (
    <div className="table-wrap">
      <table className="table">
        <caption className="sr-only">Productos agregados</caption>
        <thead>
          <tr>
            <th scope="col">Producto</th>
            <th scope="col">Cantidad</th>
            {allowDiscount && <th scope="col" className="num">Desc. %</th>}
            <th scope="col" className="num">Precio</th>
            <th scope="col" className="num">Total</th>
            <th scope="col"><span className="sr-only">Quitar</span></th>
          </tr>
        </thead>
        <tbody>
          {lines.map((l, i) => {
            const p = priced.get(i);
            return (
              <tr key={l.product_id}>
                <td>
                  <strong>{l.code}</strong> {l.description}
                  {warnings.has(l.product_id) && <div><Badge kind="danger">Existencias insuficientes</Badge></div>}
                </td>
                <td>
                  <div className="qty-control">
                    <Button size="sm" variant="outline" iconOnly icon={<Minus size={18} />} onClick={() => step(i, -1)}>Restar uno</Button>
                    <input className="input" inputMode="decimal" aria-label={`Cantidad de ${l.code}`} value={l.qty}
                      onChange={(e) => update(i, { qty: e.target.value })} />
                    <Button size="sm" variant="outline" iconOnly icon={<Plus size={18} />} onClick={() => step(i, 1)}>Sumar uno</Button>
                  </div>
                </td>
                {allowDiscount && (
                  <td className="num">
                    <input className="input num" style={{ width: 80, minHeight: 'var(--control-h-sm)' }} inputMode="decimal"
                      aria-label={`Descuento de ${l.code} en porcentaje`} value={l.discount_pct} placeholder="0"
                      onChange={(e) => update(i, { discount_pct: e.target.value })} />
                  </td>
                )}
                <td className="num">
                  {p ? money(p.unit_price) : '…'}
                  {p && p.unit_price !== p.list_price && <><br /><small className="muted"><s>{money(p.list_price)}</s></small></>}
                </td>
                <td className="num"><strong>{p ? money(p.net) : '…'}</strong></td>
                <td>
                  <Button variant="ghost" size="sm" iconOnly icon={<Trash2 size={18} />}
                    onClick={() => setLines(lines.filter((_, j) => j !== i))}>Quitar {l.code}</Button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function TotalsBox({ quote }: { quote: Quote | null }) {
  if (!quote) return null;
  const t = quote.totals;
  return (
    <dl className="dl" style={{ gridTemplateColumns: '1fr auto' }}>
      <dt>Subtotal (precio de lista)</dt><dd className="num">{money(t.gross)}</dd>
      {Number(t.discount) > 0 && <><dt>Descuentos</dt><dd className="num">-{money(t.discount)}</dd></>}
      {Number(t.tax) > 0 && <><dt>IVA incluido</dt><dd className="num">{money(t.tax)}</dd></>}
      <dt style={{ fontSize: '1.25rem', color: 'var(--text)' }}>Total</dt>
      <dd className="num pos-total">{money(t.total)}</dd>
    </dl>
  );
}

// ------------------------------------------------------------------ clientes
export interface Customer { id: number; name: string; identification: string | null; phone: string; email: string; address: string }

export function CustomerPicker({ value, onChange, label = 'Cliente' }: {
  value: Customer | null; onChange: (c: Customer | null) => void; label?: string;
}) {
  const [q, setQ] = useState('');
  const [results, setResults] = useState<Customer[]>([]);
  const [creating, setCreating] = useState(false);
  const term = useDebounced(q.trim(), 250);
  useEffect(() => {
    if (!term) {
      setResults([]);
      return;
    }
    get(`/parties/clientes${qs({ q: term, page_size: 8 })}`).then((r) => setResults(r.items)).catch(() => setResults([]));
  }, [term]);
  if (value) {
    return (
      <div className="field">
        <span className="field-label">{label}</span>
        <div className="row-between card" style={{ padding: '10px 14px' }}>
          <span><strong>{value.name}</strong>{value.identification && <span className="muted"> · {value.identification}</span>}</span>
          <Button size="sm" variant="ghost" icon={<X size={18} />} onClick={() => onChange(null)}>Quitar</Button>
        </div>
      </div>
    );
  }
  return (
    <div className="stack" style={{ gap: 8 }}>
      <TextField label={label} type="search" value={q} onChange={setQ} placeholder="Nombre, identificación o teléfono"
        hint="Opcional en ventas de contado; obligatorio en ventas a crédito." autoComplete="off" />
      {results.length > 0 && (
        <ul className="result-list card">
          {results.map((c) => (
            <li key={c.id}>
              <button type="button" className="result-item" onClick={() => { onChange(c); setQ(''); }}>
                <span><strong>{c.name}</strong>{c.identification && <span className="muted"> · {c.identification}</span>}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <div><Button size="sm" variant="outline" icon={<UserPlus size={18} />} onClick={() => setCreating(true)}>Nuevo cliente</Button></div>
      {creating && <QuickCustomer initialName={q} onClose={() => setCreating(false)} onCreated={(c) => { onChange(c); setCreating(false); setQ(''); }} />}
    </div>
  );
}

function QuickCustomer({ initialName, onClose, onCreated }: { initialName: string; onClose: () => void; onCreated: (c: Customer) => void }) {
  const [form, setForm] = useState({ name: initialName, identification: '', phone: '', email: '', address: '', credit_days: '30' });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (v: string) => setForm((f) => ({ ...f, [k]: v }));
  const save = async () => {
    if (!form.name.trim()) {
      setErrors({ name: 'El nombre es obligatorio.' });
      return;
    }
    setBusy(true);
    try {
      const c = await post<Customer>('/parties/clientes', { ...form, identification: form.identification || null,
        credit_days: Number(form.credit_days) || 30 });
      onCreated(c);
    } catch (err) {
      setError(err as ApiError);
      setErrors((err as ApiError).fields ?? {});
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open title="Nuevo cliente" onClose={onClose} footer={
      <><Button onClick={onClose}>Cancelar</Button><Button variant="primary" busy={busy} onClick={save}>Guardar cliente</Button></>
    }>
      <ErrorAlert error={error} />
      <div className="form-grid">
        <TextField label="Nombre o razón social" value={form.name} onChange={set('name')} error={errors.name} required autoFocus />
        <TextField label="NIT o cédula" value={form.identification} onChange={set('identification')} error={errors.identification} />
        <TextField label="Teléfono" type="tel" value={form.phone} onChange={set('phone')} error={errors.phone} />
        <TextField label="Correo" type="email" value={form.email} onChange={set('email')} error={errors.email} />
        <TextField label="Dirección" value={form.address} onChange={set('address')} error={errors.address} />
        <NumberField label="Días de crédito" value={form.credit_days} onChange={set('credit_days')} error={errors.credit_days} />
      </div>
    </Dialog>
  );
}

// ------------------------------------------------------------------ impresión por navegador
/** Abre una ventana con el contenido y el diálogo de impresión del navegador (la persona elige la impresora). */
export function printInBrowser(title: string, bodyHtml: string, css = '') {
  const w = window.open('', '_blank', 'width=480,height=720');
  if (!w) {
    alert('El navegador bloqueó la ventana de impresión. Permita las ventanas emergentes para este sitio.');
    return false;
  }
  w.document.write(`<!doctype html><html lang="es"><head><meta charset="utf-8"><title>${title}</title><style>
    body{font-family:Arial,sans-serif;margin:12px;color:#000} pre{font-family:"Courier New",monospace;font-size:13px;white-space:pre}
    ${css}</style></head><body>${bodyHtml}</body></html>`);
  w.document.close();
  w.focus();
  w.print();
  setTimeout(() => w.close(), 500);
  return true;
}

export function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
}

export function StockWarnings({ quote }: { quote: Quote | null }) {
  if (!quote?.stock_warnings.length) return null;
  return (
    <Alert kind={quote.can_sell ? 'warning' : 'danger'} title="Existencias insuficientes">
      <ul>{quote.stock_warnings.map((w) => <li key={w.product_id}>{w.message}</li>)}</ul>
    </Alert>
  );
}

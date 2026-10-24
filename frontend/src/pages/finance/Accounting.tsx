import { CheckCircle2, Plus, Save, Trash2, Undo2, XCircle } from 'lucide-react';
import { Fragment, useState } from 'react';
import { Route, Routes } from 'react-router-dom';
import { ApiError, newKey, post, put, qs } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { ConfirmDialog, Dialog } from '../../components/ui/Dialog';
import { Alert, Badge, EmptyState, ErrorAlert, ErrorState, Loading } from '../../components/ui/Feedback';
import { Checkbox, NumberField, SelectField, TextField } from '../../components/ui/Form';
import { Card, LinkTabs } from '../../components/ui/Layout';
import { DataTable, Pagination } from '../../components/ui/Table';
import { useAuth } from '../../context/Auth';
import { useToast } from '../../context/Toast';
import { date, money, monthStart, today, toApiNumber } from '../../lib/format';
import { useApi } from '../../lib/hooks';
import { FinanceBack } from './FinanceRoutes';

const SOURCES: Record<string, string> = {
  venta: 'Venta', devolucion: 'Devolución', cobro: 'Cobro', pago: 'Pago', cxc: 'Cuenta por cobrar', cxp: 'Cuenta por pagar',
  movimiento: 'Inventario', gasto: 'Gasto', manual: 'Manual',
};
const TYPES = { activo: 'Activo', pasivo: 'Pasivo', patrimonio: 'Patrimonio', ingreso: 'Ingreso', costo: 'Costo', gasto: 'Gasto' };

export function AccountingPage() {
  const { can } = useAuth();
  return (
    <div className="stack">
      <FinanceBack abbr="ACC" title="Contabilidad" />
      <LinkTabs label="Secciones de contabilidad" tabs={[
        { to: '/finanzas/acc', label: 'Libro diario', end: true },
        { to: '/finanzas/acc/mayor', label: 'Libro mayor' },
        { to: '/finanzas/acc/balance-prueba', label: 'Balance de prueba' },
        ...(can('finanzas.registrar') ? [{ to: '/finanzas/acc/registrar', label: 'Registrar' }, { to: '/finanzas/acc/conciliacion', label: 'Conciliación' }] : []),
        { to: '/finanzas/acc/cuentas', label: 'Plan de cuentas' },
        { to: '/finanzas/acc/verificaciones', label: 'Verificaciones' },
      ]} />
      <Routes>
        <Route index element={<Journal />} />
        <Route path="mayor" element={<Ledger />} />
        <Route path="balance-prueba" element={<TrialBalance />} />
        <Route path="registrar" element={<Register />} />
        <Route path="conciliacion" element={<Reconciliation />} />
        <Route path="cuentas" element={<Accounts />} />
        <Route path="verificaciones" element={<Integrity />} />
      </Routes>
    </div>
  );
}

function useAccounts() {
  return useApi<any[]>('/finance/accounts');
}

function Journal() {
  const { can } = useAuth();
  const { notify } = useToast();
  const [from, setFrom] = useState(monthStart());
  const [to, setTo] = useState(today());
  const [source, setSource] = useState('');
  const [page, setPage] = useState(1);
  const [reversing, setReversing] = useState<any>(null);
  const j = useApi(`/finance/journal${qs({ date_from: from, date_to: to, source, page, page_size: 20 })}`);
  const reverse = async (reason: string) => {
    try {
      await post(`/finance/entries/${reversing.id}/reverse`, { reason });
      notify('success', 'Asiento reversado');
      j.reload();
    } catch (err) {
      notify('danger', 'No se pudo reversar', (err as Error).message);
    } finally {
      setReversing(null);
    }
  };
  return (
    <Card>
      <div className="card-body row">
        <TextField label="Desde" type="date" value={from} onChange={(v) => { setFrom(v); setPage(1); }} />
        <TextField label="Hasta" type="date" value={to} onChange={(v) => { setTo(v); setPage(1); }} />
        <div style={{ minWidth: 200 }}>
          <SelectField label="Origen" value={source} onChange={(v) => { setSource(v); setPage(1); }} placeholder="Todos"
            options={Object.entries(SOURCES).map(([value, label]) => ({ value, label }))} />
        </div>
      </div>
      {j.loading && !j.data ? <Loading /> : j.error ? <ErrorState error={j.error} onRetry={j.reload} /> :
        !j.data.items.length ? <EmptyState title="Sin asientos en el periodo" /> : (
          <>
            <div className="table-wrap">
              <table className="table">
                <caption className="sr-only">Libro diario</caption>
                <thead><tr><th>Fecha</th><th>Cuenta</th><th>Detalle</th><th className="num">Débito</th><th className="num">Crédito</th></tr></thead>
                <tbody>
                  {j.data.items.map((e: any) => (
                    <Fragment key={e.id}>
                      <tr style={{ background: 'var(--surface-2)' }}>
                        <td className="nowrap"><strong>{date(e.entry_date)}</strong></td>
                        <td colSpan={2}>
                          <strong>#{e.id} {e.description}</strong> <Badge>{SOURCES[e.source_type] ?? e.source_type}</Badge>
                          {e.reversed_by_id && <> <Badge kind="warning">Reversado</Badge></>}
                          {e.reverses_id && <> <Badge kind="info">Reverso de #{e.reverses_id}</Badge></>}
                          <span className="muted"> · {e.username ?? 'sistema'}</span>
                        </td>
                        <td colSpan={2} style={{ textAlign: 'right' }}>
                          {can('finanzas.registrar') && ['manual', 'gasto'].includes(e.source_type) && !e.reversed_by_id && !e.reverses_id && (
                            <Button size="sm" variant="ghost" icon={<Undo2 size={16} />} onClick={() => setReversing(e)}>Reversar</Button>
                          )}
                        </td>
                      </tr>
                      {e.lines.map((l: any) => (
                        <tr key={l.id}>
                          <td />
                          <td style={{ paddingLeft: Number(l.credit) ? 40 : 14 }}>{l.code} {l.name}</td>
                          <td className="muted">{l.memo}</td>
                          <td className="num">{Number(l.debit) ? money(l.debit) : ''}</td>
                          <td className="num">{Number(l.credit) ? money(l.credit) : ''}</td>
                        </tr>
                      ))}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination page={j.data.page} pages={j.data.pages} total={j.data.total} onPage={setPage} />
          </>
        )}
      <ConfirmDialog open={Boolean(reversing)} title="Reversar asiento" requireReason danger confirmLabel="Reversar"
        onClose={() => setReversing(null)} onConfirm={reverse}
        message="Se registrará un asiento contrario enlazado al original. Ningún registro se elimina." />
    </Card>
  );
}

function Ledger() {
  const accounts = useAccounts();
  const [code, setCode] = useState('1105');
  const [from, setFrom] = useState(monthStart());
  const [to, setTo] = useState(today());
  const l = useApi(code ? `/finance/ledger/${code}${qs({ date_from: from, date_to: to })}` : null);
  return (
    <Card>
      <div className="card-body row">
        <div style={{ minWidth: 280 }}>
          <SelectField label="Cuenta" value={code} onChange={setCode}
            options={(accounts.data ?? []).map((a) => ({ value: a.code, label: `${a.code} ${a.name}` }))} />
        </div>
        <TextField label="Desde" type="date" value={from} onChange={setFrom} />
        <TextField label="Hasta" type="date" value={to} onChange={setTo} />
      </div>
      {l.loading && !l.data ? <Loading /> : l.error ? <ErrorState error={l.error} /> : l.data && (
        <DataTable caption="Libro mayor" rows={l.data.lines} rowKey={(r: any) => r.id} columns={[
          { key: 'd', header: 'Fecha', render: (r: any) => date(r.entry_date) },
          { key: 'x', header: 'Descripción', render: (r: any) => <>{r.description}{r.reconciled ? <> <Badge kind="success">Conciliado</Badge></> : null}</> },
          { key: 'db', header: 'Débito', numeric: true, render: (r: any) => (Number(r.debit) ? money(r.debit) : '') },
          { key: 'cr', header: 'Crédito', numeric: true, render: (r: any) => (Number(r.credit) ? money(r.credit) : '') },
          { key: 'b', header: 'Saldo', numeric: true, render: (r: any) => <strong>{money(r.balance)}</strong> },
        ]} footer={<tr><td colSpan={2}>Saldo inicial {money(l.data.opening)} · saldo final</td><td /><td /><td className="num">{money(l.data.closing)}</td></tr>} />
      )}
    </Card>
  );
}

function TrialBalance() {
  const [asOf, setAsOf] = useState(today());
  const t = useApi(`/finance/trial-balance${qs({ as_of: asOf })}`);
  return (
    <Card>
      <div className="card-body"><TextField label="Fecha de corte" type="date" value={asOf} onChange={setAsOf} /></div>
      {t.loading && !t.data ? <Loading /> : t.error ? <ErrorState error={t.error} /> : t.data && (
        <>
          <div className="card-body" style={{ paddingTop: 0 }}>
            {t.data.balanced ? <Alert kind="success">Débitos y créditos son iguales.</Alert> : <Alert kind="danger">Débitos y créditos no coinciden.</Alert>}
          </div>
          <DataTable caption="Balance de prueba" rows={t.data.rows} rowKey={(r: any) => r.code} columns={[
            { key: 'c', header: 'Cuenta', render: (r: any) => `${r.code} ${r.name}` },
            { key: 't', header: 'Tipo', render: (r: any) => (TYPES as any)[r.type] },
            { key: 'd', header: 'Débitos', numeric: true, render: (r: any) => money(r.debit) },
            { key: 'cr', header: 'Créditos', numeric: true, render: (r: any) => money(r.credit) },
            { key: 'b', header: 'Saldo', numeric: true, render: (r: any) => <strong>{money(r.balance)}</strong> },
          ]} footer={<tr><td colSpan={2}>Totales</td><td className="num">{money(t.data.total_debit)}</td><td className="num">{money(t.data.total_credit)}</td><td /></tr>} />
        </>
      )}
    </Card>
  );
}

function Register() {
  const accounts = useAccounts();
  const methods = useApi<any[]>('/payment-methods');
  const { notify } = useToast();
  const [kind, setKind] = useState<'gasto' | 'asiento'>('gasto');
  const [expense, setExpense] = useState({ entry_date: today(), description: '', account_code: '', amount: '', method_id: '' });
  const [entry, setEntry] = useState({ entry_date: today(), description: '', lines: [{ account_code: '', debit: '', credit: '', memo: '' },
    { account_code: '', debit: '', credit: '', memo: '' }] });
  const [error, setError] = useState<ApiError | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [key, setKey] = useState(newKey());
  const acc = accounts.data ?? [];
  const expenseAccounts = acc.filter((a) => a.type === 'gasto' || a.type === 'costo');
  const totals = entry.lines.reduce((t, l) => ({ d: t.d + (Number(toApiNumber(l.debit)) || 0), c: t.c + (Number(toApiNumber(l.credit)) || 0) }), { d: 0, c: 0 });

  const saveExpense = async () => {
    const e: Record<string, string> = {};
    if (!expense.description.trim()) e.description = 'Describa el gasto.';
    if (!expense.account_code) e.account_code = 'Elija la cuenta de gasto.';
    if (!(Number(toApiNumber(expense.amount)) > 0)) e.amount = 'Escriba un importe mayor que cero.';
    if (!expense.method_id) e.method_id = 'Elija cómo se pagó.';
    setErrors(e);
    if (Object.keys(e).length) return;
    setBusy(true);
    setError(null);
    try {
      await post('/finance/expenses', { ...expense, amount: toApiNumber(expense.amount), method_id: Number(expense.method_id) }, key);
      notify('success', 'Gasto registrado');
      setExpense({ ...expense, description: '', amount: '' });
      setKey(newKey());
    } catch (err) {
      setError(err as ApiError);
      setErrors((err as ApiError).fields ?? {});
    } finally {
      setBusy(false);
    }
  };
  const saveEntry = async () => {
    setBusy(true);
    setError(null);
    try {
      await post('/finance/entries', { entry_date: entry.entry_date, description: entry.description,
        lines: entry.lines.filter((l) => l.account_code).map((l) => ({ account_code: l.account_code, debit: toApiNumber(l.debit) || null,
          credit: toApiNumber(l.credit) || null, memo: l.memo })) }, key);
      notify('success', 'Asiento registrado');
      setEntry({ entry_date: today(), description: '', lines: entry.lines.map(() => ({ account_code: '', debit: '', credit: '', memo: '' })) });
      setKey(newKey());
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  const setLine = (i: number, changes: Record<string, string>) =>
    setEntry((en) => ({ ...en, lines: en.lines.map((l, j) => (j === i ? { ...l, ...changes } : l)) }));

  return (
    <Card>
      <div className="card-body stack">
        <div className="row">
          <Button variant={kind === 'gasto' ? 'primary' : 'outline'} onClick={() => setKind('gasto')}>Gasto pagado</Button>
          <Button variant={kind === 'asiento' ? 'primary' : 'outline'} onClick={() => setKind('asiento')}>Asiento manual</Button>
        </div>
        <ErrorAlert error={error} />
        {kind === 'gasto' ? (
          <>
            <p className="muted">Para gastos que se pagaron de inmediato (arriendo, servicios, nómina…). Si se pagarán después, regístrelos en Cuentas por pagar.</p>
            <div className="form-grid">
              <TextField label="Fecha" type="date" value={expense.entry_date} onChange={(v) => setExpense({ ...expense, entry_date: v })} />
              <TextField label="Descripción" value={expense.description} onChange={(v) => setExpense({ ...expense, description: v })} error={errors.description} required />
              <SelectField label="Cuenta de gasto" value={expense.account_code} onChange={(v) => setExpense({ ...expense, account_code: v })}
                placeholder="Elija…" error={errors.account_code} required
                options={expenseAccounts.map((a) => ({ value: a.code, label: `${a.code} ${a.name}${a.cost_behavior ? ` (${a.cost_behavior})` : ''}` }))} />
              <NumberField label="Importe" value={expense.amount} onChange={(v) => setExpense({ ...expense, amount: v })} error={errors.amount} required />
              <SelectField label="Pagado con" value={expense.method_id} onChange={(v) => setExpense({ ...expense, method_id: v })} placeholder="Elija…"
                error={errors.method_id} required options={(methods.data ?? []).filter((m) => m.kind !== 'credito').map((m) => ({ value: m.id, label: m.name }))} />
            </div>
            <div className="form-actions"><Button variant="primary" busy={busy} icon={<Save size={20} />} onClick={saveExpense}>Registrar gasto</Button></div>
          </>
        ) : (
          <>
            <p className="muted">Para operaciones sin módulo propio: aportes de capital, préstamos, depreciaciones, ajustes. Débitos y créditos deben ser iguales.</p>
            <div className="form-grid">
              <TextField label="Fecha" type="date" value={entry.entry_date} onChange={(v) => setEntry({ ...entry, entry_date: v })} />
              <TextField label="Descripción" value={entry.description} onChange={(v) => setEntry({ ...entry, description: v })} required />
            </div>
            {entry.lines.map((l, i) => (
              <div key={i} className="row" style={{ alignItems: 'flex-end' }}>
                <div style={{ minWidth: 260, flex: 2 }}>
                  <SelectField label={`Cuenta ${i + 1}`} value={l.account_code} onChange={(v) => setLine(i, { account_code: v })} placeholder="Elija…"
                    options={acc.map((a) => ({ value: a.code, label: `${a.code} ${a.name}` }))} />
                </div>
                <div style={{ flex: 1, minWidth: 130 }}><NumberField label="Débito" value={l.debit} onChange={(v) => setLine(i, { debit: v, credit: v ? '' : l.credit })} /></div>
                <div style={{ flex: 1, minWidth: 130 }}><NumberField label="Crédito" value={l.credit} onChange={(v) => setLine(i, { credit: v, debit: v ? '' : l.debit })} /></div>
                <Button variant="ghost" iconOnly icon={<Trash2 size={18} />} disabled={entry.lines.length <= 2}
                  onClick={() => setEntry({ ...entry, lines: entry.lines.filter((_, j) => j !== i) })}>Quitar línea {i + 1}</Button>
              </div>
            ))}
            <div className="row-between">
              <Button variant="outline" icon={<Plus size={18} />} onClick={() => setEntry({ ...entry, lines: [...entry.lines, { account_code: '', debit: '', credit: '', memo: '' }] })}>
                Agregar línea
              </Button>
              <span className="row">
                {Math.abs(totals.d - totals.c) < 0.005 && totals.d > 0
                  ? <Badge kind="success">Cuadrado</Badge>
                  : <Badge kind="danger">Diferencia {money((totals.d - totals.c).toFixed(2))}</Badge>}
              </span>
            </div>
            <div className="form-actions"><Button variant="primary" busy={busy} icon={<Save size={20} />} onClick={saveEntry}>Registrar asiento</Button></div>
          </>
        )}
      </div>
    </Card>
  );
}

function Reconciliation() {
  const { notify } = useToast();
  const accounts = useAccounts();
  const [code, setCode] = useState('1110');
  const [statementDate, setStatementDate] = useState(today());
  const [statement, setStatement] = useState('');
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const data = useApi(`/finance/reconciliation/${code}${qs({ until: statementDate })}`);
  const cash = (accounts.data ?? []).filter((a) => a.is_cash);
  const toggle = (id: number) => setPicked((p) => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await post('/finance/reconciliation', { account_code: code, statement_date: statementDate,
        statement_balance: toApiNumber(statement), line_ids: [...picked] });
      notify(Number(r.difference) === 0 ? 'success' : 'warning', 'Conciliación guardada', `Diferencia: ${money(r.difference)}`);
      setPicked(new Set());
      data.reload();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card>
      <div className="card-body stack">
        <p className="muted">Marque los movimientos que aparecen en el extracto del banco (o en el arqueo de caja) y escriba su saldo.</p>
        <div className="form-grid">
          <SelectField label="Cuenta" value={code} onChange={(v) => { setCode(v); setPicked(new Set()); }} options={cash.map((a) => ({ value: a.code, label: `${a.code} ${a.name}` }))} />
          <TextField label="Fecha del extracto" type="date" value={statementDate} onChange={setStatementDate} />
          <NumberField label="Saldo según extracto" value={statement} onChange={setStatement} required />
        </div>
        <ErrorAlert error={error} />
        {data.loading && !data.data ? <Loading /> : data.data && (
          <>
            {data.data.lines.length ? data.data.lines.map((l: any) => (
              <Checkbox key={l.id} checked={picked.has(l.id)} onChange={() => toggle(l.id)}
                label={`${date(l.entry_date)} · ${l.description} · ${Number(l.debit) ? `+${money(l.debit)}` : `-${money(l.credit)}`}`} />
            )) : <p className="muted">No hay movimientos pendientes de conciliar.</p>}
            <p>Saldo conciliado anterior: <strong>{money(data.data.reconciled_balance)}</strong></p>
            <div className="form-actions"><Button variant="primary" busy={busy} disabled={!statement} onClick={save}>Guardar conciliación</Button></div>
            {data.data.history.length > 0 && (
              <DataTable caption="Conciliaciones anteriores" rows={data.data.history} rowKey={(r: any) => r.id} columns={[
                { key: 'd', header: 'Extracto', render: (r: any) => date(r.statement_date) },
                { key: 's', header: 'Saldo extracto', numeric: true, render: (r: any) => money(r.statement_balance) },
                { key: 'c', header: 'Conciliado', numeric: true, render: (r: any) => money(r.reconciled_balance) },
                { key: 'b', header: 'Libros', numeric: true, render: (r: any) => money(r.book_balance) },
                { key: 'x', header: 'Diferencia', numeric: true, render: (r: any) => (Number(r.difference)
                  ? <Badge kind="warning">{money(r.difference)}</Badge> : <Badge kind="success">Sin diferencia</Badge>) },
              ]} />
            )}
          </>
        )}
      </div>
    </Card>
  );
}

function Accounts() {
  const { can } = useAuth();
  const accounts = useApi<any[]>('/finance/accounts?include_inactive=true');
  const [editing, setEditing] = useState<any>(null);
  return (
    <Card title="Plan de cuentas" actions={can('finanzas.registrar') && (
      <Button variant="primary" icon={<Plus size={20} />} onClick={() => setEditing({})}>Nueva cuenta</Button>)}>
      {accounts.loading && !accounts.data ? <Loading /> : (
        <DataTable caption="Plan de cuentas" rows={accounts.data ?? []} rowKey={(a: any) => a.id}
          onSelect={can('finanzas.registrar') ? setEditing : undefined} columns={[
            { key: 'c', header: 'Código', render: (a: any) => <strong>{a.code}</strong> },
            { key: 'n', header: 'Nombre', render: (a: any) => a.name },
            { key: 't', header: 'Tipo', render: (a: any) => (TYPES as any)[a.type] },
            { key: 'b', header: 'Comportamiento', render: (a: any) => a.cost_behavior ?? (a.is_cash ? 'Caja o bancos' : '—') },
            { key: 's', header: 'Estado', render: (a: any) => (a.active ? <Badge kind="success">Activa</Badge> : <Badge>Inactiva</Badge>) },
          ]} />
      )}
      {editing && <AccountForm account={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); accounts.reload(); }} />}
    </Card>
  );
}

function AccountForm({ account, onClose, onSaved }: { account: any; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({ code: account.code ?? '', name: account.name ?? '', type: account.type ?? 'gasto',
    is_cash: Boolean(account.is_cash), cost_behavior: account.cost_behavior ?? '', active: account.active ?? 1 });
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      const body = { ...form, active: Boolean(form.active), cost_behavior: form.cost_behavior || null };
      if (account.id) await put(`/finance/accounts/${account.id}`, body);
      else await post('/finance/accounts', body);
      onSaved();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open title={account.id ? `Cuenta ${account.code}` : 'Nueva cuenta'} onClose={onClose} footer={
      <><Button onClick={onClose}>Cancelar</Button><Button variant="primary" busy={busy} onClick={save}>Guardar</Button></>}>
      <ErrorAlert error={error} />
      <TextField label="Código" value={form.code} onChange={(v) => setForm({ ...form, code: v })} error={error?.fields.code} required />
      <TextField label="Nombre" value={form.name} onChange={(v) => setForm({ ...form, name: v })} error={error?.fields.name} required />
      <SelectField label="Tipo" value={form.type} onChange={(v) => setForm({ ...form, type: v })} options={Object.entries(TYPES).map(([value, label]) => ({ value, label }))} />
      {(form.type === 'gasto' || form.type === 'costo') && (
        <SelectField label="Comportamiento (para punto de equilibrio)" value={form.cost_behavior} onChange={(v) => setForm({ ...form, cost_behavior: v })}
          placeholder="Sin clasificar" options={[{ value: 'fijo', label: 'Fijo' }, { value: 'variable', label: 'Variable' }]} />
      )}
      {form.type === 'activo' && <Checkbox label="Es una cuenta de caja o bancos" checked={form.is_cash} onChange={(v) => setForm({ ...form, is_cash: v })} />}
      {account.id && <Checkbox label="Activa" checked={Boolean(form.active)} onChange={(v) => setForm({ ...form, active: v ? 1 : 0 })} />}
    </Dialog>
  );
}

function Integrity() {
  const r = useApi('/finance/integrity');
  if (r.loading && !r.data) return <Loading />;
  if (r.error) return <ErrorState error={r.error} />;
  return (
    <Card title="Verificaciones cruzadas" actions={<Button onClick={r.reload}>Volver a verificar</Button>}>
      <ul className="result-list">
        {r.data.checks.map((c: any) => (
          <li key={c.name} className="result-item" style={{ cursor: 'default' }}>
            <span className="row" style={{ flexWrap: 'nowrap' }}>
              {c.ok ? <CheckCircle2 size={24} color="var(--on-success-soft)" aria-hidden /> : <XCircle size={24} color="var(--danger)" aria-hidden />}
              <span><strong>{c.name}</strong> — {c.ok ? 'correcto' : 'con diferencias'}
                {c.ledger !== undefined && <><br /><small className="muted">Contabilidad {money(c.ledger)} · detalle {money(c.items)} · diferencia {money(c.difference)}</small></>}
                {!c.ok && c.detail && <><br /><small>{c.detail}</small></>}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

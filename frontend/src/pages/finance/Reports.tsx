import { Calculator } from 'lucide-react';
import { useEffect, useState } from 'react';
import { ApiError, post, qs } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { Alert, ErrorAlert, ErrorState, Loading } from '../../components/ui/Feedback';
import { NumberField, TextField } from '../../components/ui/Form';
import { Card, Metric } from '../../components/ui/Layout';
import { date, money, monthStart, qty, today, toApiNumber } from '../../lib/format';
import { useApi } from '../../lib/hooks';
import { FinanceBack } from './FinanceRoutes';

function Missing({ items }: { items: string[] }) {
  if (!items?.length) return null;
  return <Alert kind="info" title="Información faltante"><ul>{items.map((m) => <li key={m}>{m}</li>)}</ul></Alert>;
}

function Bar({ value, max, label }: { value: number; max: number; label: string }) {
  const width = max > 0 ? Math.max(2, Math.round((Math.abs(value) / max) * 100)) : 0;
  return (
    <div aria-hidden title={label} style={{ height: 10, background: 'var(--surface-2)', borderRadius: 6, overflow: 'hidden' }}>
      <div style={{ width: `${width}%`, height: '100%', background: value < 0 ? 'var(--danger)' : 'var(--primary)',
        transition: 'width var(--dur-slow) var(--ease)' }} />
    </div>
  );
}

// ------------------------------------------------------------------ BS
export function BalanceSheet() {
  const [asOf, setAsOf] = useState(today());
  const [compare, setCompare] = useState('');
  const bs = useApi(`/finance/balance-sheet${qs({ as_of: asOf, compare_to: compare })}`);
  const d = bs.data;
  const prevMap = (section: string) => new Map<string, string>((d?.previous?.[section] ?? []).map((a: any) => [a.code + a.name, a.balance]));
  const Section = ({ title, k, total }: { title: string; k: string; total: string }) => {
    const prev = prevMap(k);
    return (
      <Card title={title}>
        <div className="table-wrap">
          <table className="table">
            <caption className="sr-only">{title}</caption>
            <thead><tr><th>Cuenta</th><th className="num">{date(d.as_of)}</th>{d.previous && <th className="num">{date(d.compare_to)}</th>}</tr></thead>
            <tbody>
              {d.current[k].map((a: any) => (
                <tr key={a.code + a.name}><td>{a.code} {a.name}</td><td className="num">{money(a.balance)}</td>
                  {d.previous && <td className="num">{money(prev.get(a.code + a.name) ?? '0')}</td>}</tr>
              ))}
              {!d.current[k].length && <tr><td colSpan={3} className="muted">Sin saldos.</td></tr>}
            </tbody>
            <tfoot><tr><td>Total</td><td className="num">{money(d.current[total])}</td>{d.previous && <td className="num">{money(d.previous[total])}</td>}</tr></tfoot>
          </table>
        </div>
      </Card>
    );
  };
  return (
    <div className="stack">
      <FinanceBack abbr="BS" title="Balance general" />
      <Card><div className="card-body row">
        <TextField label="Fecha de corte" type="date" value={asOf} onChange={setAsOf} />
        <TextField label="Comparar con (opcional)" type="date" value={compare} onChange={setCompare} />
      </div></Card>
      {bs.loading && !d ? <Loading /> : bs.error ? <ErrorState error={bs.error} onRetry={bs.reload} /> : d && (
        <>
          <Missing items={d.missing} />
          <div className="metrics">
            <Metric label="Activos" value={money(d.current.total_assets)} />
            <Metric label="Pasivos" value={money(d.current.total_liabilities)} />
            <Metric label="Patrimonio" value={money(d.current.total_equity)} />
          </div>
          {d.current.balanced
            ? <Alert kind="success">Activos = Pasivos + Patrimonio. El balance cuadra.</Alert>
            : <Alert kind="danger" title="El balance no cuadra">Diferencia: {money(d.current.difference)}. Revise Contabilidad › Verificaciones.</Alert>}
          <div className="grid-3">
            <Section title="Activos" k="assets" total="total_assets" />
            <Section title="Pasivos" k="liabilities" total="total_liabilities" />
            <Section title="Patrimonio" k="equity" total="total_equity" />
          </div>
        </>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ BEP
export function BreakEven() {
  const [from, setFrom] = useState(monthStart());
  const [to, setTo] = useState(today());
  const [manual, setManual] = useState({ fixed_costs: '', price: '', variable_cost: '' });
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async (overrides = manual) => {
    setBusy(true);
    setError(null);
    try {
      setData(await post('/finance/break-even', {
        date_from: from, date_to: to,
        ...Object.fromEntries(Object.entries(overrides).filter(([, v]) => v.trim()).map(([k, v]) => [k, toApiNumber(v)])),
      }));
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    void run({ fixed_costs: '', price: '', variable_cost: '' });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- recalcula solo al cambiar el periodo
  }, [from, to]);
  const set = (k: keyof typeof manual) => (v: string) => setManual((m) => ({ ...m, [k]: v }));
  return (
    <div className="stack">
      <FinanceBack abbr="BEP" title="Punto de equilibrio" />
      <Card title="Datos">
        <div className="card-body stack">
          <div className="row">
            <TextField label="Desde" type="date" value={from} onChange={setFrom} />
            <TextField label="Hasta" type="date" value={to} onChange={setTo} />
          </div>
          <p className="muted">Por defecto se usan las ventas, el costo de ventas y los gastos fijos y variables registrados en el periodo.
            Puede reemplazar cualquiera de estos valores para simular escenarios:</p>
          <div className="form-grid">
            <NumberField label="Costos fijos del periodo" value={manual.fixed_costs} onChange={set('fixed_costs')} placeholder="Según contabilidad" />
            <NumberField label="Precio de venta por unidad (sin IVA)" value={manual.price} onChange={set('price')} placeholder="Promedio del periodo" />
            <NumberField label="Costo variable por unidad" value={manual.variable_cost} onChange={set('variable_cost')} placeholder="Promedio del periodo" />
          </div>
          <div className="form-actions"><Button variant="primary" busy={busy} icon={<Calculator size={20} />} onClick={() => run()}>Calcular</Button></div>
        </div>
      </Card>
      <ErrorAlert error={error} />
      {data && (
        <>
          <Missing items={data.missing} />
          <div className="metrics">
            <Metric label="Costos fijos" value={money(data.fixed_costs)} />
            <Metric label="Precio por unidad" value={money(data.price_unit)} />
            <Metric label="Costo variable por unidad" value={money(data.variable_unit)} />
            <Metric label="Margen de contribución" value={data.contribution_margin_unit ? money(data.contribution_margin_unit) : '—'}
              hint={data.contribution_margin_ratio ? `${data.contribution_margin_ratio.replace('.', ',')} % del precio` : undefined} />
          </div>
          {data.break_even_units && (
            <div className="metrics">
              <Metric label="Unidades necesarias" value={qty(data.break_even_units)} />
              <Metric label="Ventas necesarias (sin IVA)" value={money(data.break_even_sales)} />
              {data.safety_margin_pct && <Metric label="Margen de seguridad" value={`${data.safety_margin_pct.replace('.', ',')} %`}
                hint={`Vendidas en el periodo: ${qty(data.units_sold)} unidades`} />}
            </div>
          )}
          <p className="muted">Fuente: {data.source === 'contabilidad' ? 'operaciones registradas' : data.source === 'manual' ? 'valores escritos' : 'combinación de ambos'}.
            Fórmulas: unidades = costos fijos ÷ (precio − costo variable); ventas = unidades × precio.</p>
        </>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ CF
export function CashFlow() {
  const [from, setFrom] = useState(monthStart());
  const [to, setTo] = useState(today());
  const cf = useApi(`/finance/cash-flow${qs({ date_from: from, date_to: to, projection_weeks: 8 })}`);
  const d = cf.data;
  const List = ({ title, items }: { title: string; items: any[] }) => {
    const max = Math.max(1, ...items.map((i) => Number(i.amount)));
    return (
      <Card title={title}>
        <div className="card-body stack">
          {items.length ? items.map((i) => (
            <div key={i.label} className="stack" style={{ gap: 4 }}>
              <div className="row-between"><span>{i.label}</span><strong className="num">{money(i.amount)}</strong></div>
              <Bar value={Number(i.amount)} max={max} label={i.label} />
            </div>
          )) : <p className="muted">Sin movimientos.</p>}
        </div>
      </Card>
    );
  };
  return (
    <div className="stack">
      <FinanceBack abbr="CF" title="Flujo de efectivo" />
      <Card><div className="card-body row">
        <TextField label="Desde" type="date" value={from} onChange={setFrom} />
        <TextField label="Hasta" type="date" value={to} onChange={setTo} />
      </div></Card>
      {cf.loading && !d ? <Loading /> : cf.error ? <ErrorState error={cf.error} onRetry={cf.reload} /> : d && (
        <>
          <Missing items={d.missing} />
          <div className="metrics">
            <Metric label="Saldo inicial" value={money(d.current.opening)} />
            <Metric label="Entradas" value={money(d.current.total_in)} hint={`Periodo anterior: ${money(d.previous.total_in)}`} />
            <Metric label="Salidas" value={money(d.current.total_out)} hint={`Periodo anterior: ${money(d.previous.total_out)}`} />
            <Metric label="Flujo neto" value={money(d.current.net)} hint={`Periodo anterior: ${money(d.previous.net)}`} />
            <Metric label="Saldo final" value={money(d.current.closing)} />
          </div>
          <div className="grid-2">
            <List title="Entradas por concepto" items={d.current.inflows} />
            <List title="Salidas por concepto" items={d.current.outflows} />
          </div>
          <Card title="Proyección semanal (8 semanas)">
            <div className="table-wrap">
              <table className="table">
                <caption className="sr-only">Proyección de caja</caption>
                <thead><tr><th>Semana desde</th><th className="num">Cobros esperados</th><th className="num">Pagos esperados</th>
                  <th className="num">Neto</th><th className="num">Saldo proyectado</th></tr></thead>
                <tbody>
                  {d.projection.weeks.map((w: any) => (
                    <tr key={w.week_start}><td>{date(w.week_start)}</td><td className="num">{money(w.in)}</td><td className="num">{money(w.out)}</td>
                      <td className="num">{money(w.net)}</td><td className="num"><strong>{money(w.balance)}</strong></td></tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="card-body"><p className="muted">{d.projection.note} Lo vencido se asume en la primera semana.</p></div>
          </Card>
        </>
      )}
    </div>
  );
}

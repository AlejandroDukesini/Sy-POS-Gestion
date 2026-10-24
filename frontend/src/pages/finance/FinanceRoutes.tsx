import { ArrowLeft } from 'lucide-react';
import type { CSSProperties, ReactNode } from 'react';
import { Link, Route, Routes } from 'react-router-dom';
import { PageHeader } from '../../components/ui/Layout';
import { AccountingPage } from './Accounting';
import { BalanceSheet, BreakEven, CashFlow } from './Reports';
import { OpenItemsPage } from './OpenItems';

const TILES = [
  { to: 'bs', abbr: 'BS', name: 'Balance general', desc: 'Activos, pasivos y patrimonio a una fecha de corte, con comparación.', tone: 'primary' },
  { to: 'bep', abbr: 'BEP', name: 'Punto de equilibrio', desc: 'Ventas y unidades necesarias para cubrir los costos.', tone: 'success' },
  { to: 'cf', abbr: 'CF', name: 'Flujo de efectivo', desc: 'Entradas, salidas, saldos y proyección de caja.', tone: 'info' },
  { to: 'acc', abbr: 'ACC', name: 'Contabilidad', desc: 'Libro diario, mayor, asientos, gastos y conciliaciones.', tone: 'neutral' },
  { to: 'ap', abbr: 'AP', name: 'Cuentas por pagar', desc: 'Facturas de proveedores, vencimientos y pagos.', tone: 'warning' },
  { to: 'ar', abbr: 'AR', name: 'Cuentas por cobrar', desc: 'Cartera de clientes, cobros y antigüedad.', tone: 'danger' },
];
const TONES: Record<string, CSSProperties> = {
  primary: { ['--tile-bg' as string]: 'var(--primary-soft)', ['--tile-fg' as string]: 'var(--on-primary-soft)' },
  success: { ['--tile-bg' as string]: 'var(--success-soft)', ['--tile-fg' as string]: 'var(--on-success-soft)' },
  info: { ['--tile-bg' as string]: 'var(--info-soft)', ['--tile-fg' as string]: 'var(--on-info-soft)' },
  neutral: { ['--tile-bg' as string]: 'var(--surface-2)', ['--tile-fg' as string]: 'var(--text)' },
  warning: { ['--tile-bg' as string]: 'var(--warning-soft)', ['--tile-fg' as string]: 'var(--on-warning-soft)' },
  danger: { ['--tile-bg' as string]: 'var(--danger-soft)', ['--tile-fg' as string]: 'var(--on-danger-soft)' },
};

function FinanceHub() {
  return (
    <>
      <PageHeader title="Finanzas" description="Informes calculados con las operaciones registradas en POS-PY (contabilidad de gestión)." />
      <div className="tiles">
        {TILES.map((t) => (
          <Link key={t.to} to={t.to} className="tile" style={TONES[t.tone]}>
            <span className="tile-abbr" aria-hidden>{t.abbr}</span>
            <span>
              <span className="tile-name">{t.name} <span className="sr-only">({t.abbr})</span></span>
              <p className="tile-desc">{t.desc}</p>
            </span>
          </Link>
        ))}
      </div>
      <p className="muted">
        Esta contabilidad es de gestión y usa un plan de cuentas de ejemplo basado en el PUC. No reemplaza la contabilidad oficial,
        la información exógena ni la facturación electrónica ante la DIAN; revísela con su contador.
      </p>
    </>
  );
}

export function FinanceBack({ title, abbr, children }: { title: string; abbr: string; children?: ReactNode }) {
  return (
    <>
      <Link to="/finanzas" className="btn btn-ghost" style={{ alignSelf: 'flex-start' }}><ArrowLeft size={20} aria-hidden /> Finanzas</Link>
      <PageHeader title={`${abbr} · ${title}`} actions={children} />
    </>
  );
}

export default function FinanceRoutes() {
  return (
    <Routes>
      <Route index element={<FinanceHub />} />
      <Route path="bs" element={<BalanceSheet />} />
      <Route path="bep" element={<BreakEven />} />
      <Route path="cf" element={<CashFlow />} />
      <Route path="acc/*" element={<AccountingPage />} />
      <Route path="ap/*" element={<OpenItemsPage kind="ap" />} />
      <Route path="ar/*" element={<OpenItemsPage kind="ar" />} />
    </Routes>
  );
}

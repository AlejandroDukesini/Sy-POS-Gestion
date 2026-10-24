import type { ReactNode } from 'react';
import { NavLink } from 'react-router-dom';

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </div>
  );
}

export function Card({ title, actions, children, className }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className ?? ''}`}>
      {(title || actions) && (
        <div className="card-head">
          {typeof title === 'string' ? <h2>{title}</h2> : title}
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function Metric({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="card metric">
      <span className="metric-label">{label}</span>
      <span className="metric-value">{value}</span>
      {hint && <span className="muted">{hint}</span>}
    </div>
  );
}

/** Pestañas como enlaces: cada pestaña tiene su propia dirección y el historial del navegador funciona. */
export function LinkTabs({ tabs, label }: { tabs: { to: string; label: string; end?: boolean; icon?: ReactNode }[]; label: string }) {
  return (
    <nav className="tabs" aria-label={label}>
      {tabs.map((t) => (
        <NavLink key={t.to} to={t.to} end={t.end} className={({ isActive }) => `tab${isActive ? ' active' : ''}`}>
          {t.icon}
          {t.label}
        </NavLink>
      ))}
    </nav>
  );
}

export function Tabs<T extends string>({ value, onChange, tabs, label }: {
  value: T; onChange: (v: T) => void; tabs: { value: T; label: string }[]; label: string;
}) {
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {tabs.map((t) => (
        <button key={t.value} type="button" role="tab" className="tab" aria-selected={value === t.value}
          onClick={() => onChange(t.value)}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

import { AlertTriangle, CheckCircle2, Info, Inbox, RefreshCw, XCircle } from 'lucide-react';
import type { ReactNode } from 'react';
import type { ApiError } from '../../api/client';
import { Button } from './Button';

type Kind = 'success' | 'danger' | 'info' | 'warning';
const ICONS = { success: CheckCircle2, danger: XCircle, info: Info, warning: AlertTriangle };

/** Aviso con icono y texto: el estado nunca depende solo del color. */
export function Alert({ kind = 'info', title, children }: { kind?: Kind; title?: string; children?: ReactNode }) {
  const Icon = ICONS[kind];
  return (
    <div className={`alert alert-${kind}`}>
      <Icon size={22} aria-hidden />
      <div>
        {title && <div className="alert-title">{title}</div>}
        {children && <div>{children}</div>}
      </div>
    </div>
  );
}

export function ErrorAlert({ error, title }: { error: ApiError | null | undefined; title?: string }) {
  if (!error) return null;
  const fieldMessages = Object.values(error.fields ?? {}).filter((m) => m && m !== error.message);
  return (
    <div role="alert">
      <Alert kind={error.offline ? 'warning' : 'danger'} title={title ?? error.title}>
        {error.message}
        {fieldMessages.length > 1 && <ul>{fieldMessages.slice(0, 6).map((m) => <li key={m}>{m}</li>)}</ul>}
      </Alert>
    </div>
  );
}

export function Loading({ label = 'Cargando…' }: { label?: string }) {
  return (
    <div className="loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden />
      <span>{label}</span>
    </div>
  );
}

export function EmptyState({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="state">
      {icon ?? <Inbox size={40} aria-hidden />}
      <div className="state-title">{title}</div>
      {children}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  return (
    <div className="state" role="alert">
      <XCircle size={40} aria-hidden />
      <div className="state-title">{error.offline ? 'Sin conexión con el servidor' : 'No se pudo cargar la información'}</div>
      <p>{error.message}</p>
      {onRetry && <Button onClick={onRetry} icon={<RefreshCw size={18} />}>Intentar de nuevo</Button>}
    </div>
  );
}

const BADGE: Record<string, Kind | undefined> = {
  completada: 'success', vigente: 'success', ok: 'success', pagada: 'success', aplicada: 'success', activo: 'success',
  anulada: 'danger', anulado: 'danger', error: 'danger', vencida: 'danger', inactivo: 'danger',
  por_vencer: 'warning', vista_previa: 'info', con_errores: 'warning', descartada: undefined,
};
const LABELS: Record<string, string> = {
  completada: 'Completada', anulada: 'Anulada', anulado: 'Anulado', vigente: 'Vigente', pagada: 'Pagada',
  vencida: 'Vencida', por_vencer: 'Por vencer', vista_previa: 'Vista previa', aplicada: 'Aplicada', descartada: 'Descartada',
  error: 'Error', ok: 'Correcto', con_errores: 'Con errores', activo: 'Activo', inactivo: 'Inactivo',
};

export function StatusBadge({ status }: { status: string }) {
  const kind = BADGE[status];
  return <span className={`badge${kind ? ` badge-${kind}` : ''}`}>{LABELS[status] ?? status}</span>;
}

export function Badge({ kind, children }: { kind?: Kind; children: ReactNode }) {
  return <span className={`badge${kind ? ` badge-${kind}` : ''}`}>{children}</span>;
}

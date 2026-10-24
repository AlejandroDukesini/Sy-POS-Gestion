import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import { Alert } from '../components/ui/Feedback';

type Kind = 'success' | 'danger' | 'info' | 'warning';
interface Toast { id: number; kind: Kind; title: string; text?: string }

interface ToastState { notify: (kind: Kind, title: string, text?: string) => void }

const ToastContext = createContext<ToastState | null>(null);
let counter = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const notify = useCallback((kind: Kind, title: string, text?: string) => {
    const id = ++counter;
    setToasts((t) => [...t.slice(-3), { id, kind, title, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === 'danger' ? 9000 : 5000);
  }, []);
  const value = useMemo(() => ({ notify }), [notify]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toasts" aria-live="polite" aria-atomic="false">
        {toasts.map((t) => (
          <div className="toast" key={t.id} role={t.kind === 'danger' ? 'alert' : 'status'}>
            <Alert kind={t.kind} title={t.title}>{t.text}</Alert>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastState {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast fuera de ToastProvider');
  return ctx;
}

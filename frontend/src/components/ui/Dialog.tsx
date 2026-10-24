import { X } from 'lucide-react';
import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { Button } from './Button';
import { TextField } from './Form';

interface DialogProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  size?: 'normal' | 'wide' | 'xl';
}

/** Diálogo modal nativo: atrapa el foco, se cierra con Esc y devuelve el foco al cerrar. */
export function Dialog({ open, title, onClose, children, footer, size = 'normal' }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      if (typeof dialog.showModal === 'function') dialog.showModal();
      else dialog.setAttribute('open', '');
    } else if (!open && dialog.open) {
      if (typeof dialog.close === 'function') dialog.close();
      else dialog.removeAttribute('open');
    }
  }, [open]);
  return (
    <dialog ref={ref} className={`dialog${size !== 'normal' ? ` dialog-${size}` : ''}`} aria-labelledby={titleId}
      onCancel={(e) => { e.preventDefault(); onClose(); }}>
      {open && (
        <>
          <div className="dialog-head">
            <h2 id={titleId}>{title}</h2>
            <Button variant="ghost" iconOnly icon={<X size={22} />} onClick={onClose}>Cerrar</Button>
          </div>
          <div className="dialog-body">{children}</div>
          {footer && <div className="dialog-foot">{footer}</div>}
        </>
      )}
    </dialog>
  );
}

interface ConfirmProps {
  open: boolean;
  title: string;
  message: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  requireReason?: boolean;
  busy?: boolean;
  onConfirm: (reason: string) => void;
  onClose: () => void;
}

/** Confirmación antes de operaciones destructivas; puede exigir el motivo (queda en la auditoría). */
export function ConfirmDialog({ open, title, message, confirmLabel, danger, requireReason, busy, onConfirm, onClose }: ConfirmProps) {
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');
  useEffect(() => {
    if (open) {
      setReason('');
      setError('');
    }
  }, [open]);
  const confirm = () => {
    if (requireReason && !reason.trim()) {
      setError('Escriba el motivo.');
      return;
    }
    onConfirm(reason.trim());
  };
  return (
    <Dialog open={open} title={title} onClose={onClose} footer={
      <>
        <Button onClick={onClose}>Volver</Button>
        <Button variant={danger ? 'danger' : 'primary'} busy={busy} onClick={confirm}>{confirmLabel}</Button>
      </>
    }>
      <div>{message}</div>
      {requireReason && (
        <TextField label="Motivo" required value={reason} onChange={setReason} error={error} maxLength={300} autoFocus />
      )}
    </Dialog>
  );
}

import { AlertCircle } from 'lucide-react';
import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react';

interface FieldProps {
  label: string;
  error?: string;
  hint?: string;
  required?: boolean;
  children: (ids: { id: string; describedBy?: string; invalid: boolean }) => ReactNode;
}

/** Etiqueta visible, ayuda y error junto al campo (enlazados con aria-describedby). */
export function Field({ label, error, hint, required, children }: FieldProps) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined;
  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>
        {label}
        {required && <span className="req" aria-hidden>*</span>}
        {required && <span className="sr-only"> (obligatorio)</span>}
      </label>
      {children({ id, describedBy, invalid: Boolean(error) })}
      {hint && <span className="field-hint" id={hintId}>{hint}</span>}
      {error && (
        <span className="field-error" id={errorId}>
          <AlertCircle size={18} aria-hidden /> {error}
        </span>
      )}
    </div>
  );
}

type InputProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'onChange'> & {
  label: string;
  error?: string;
  hint?: string;
  onChange: (value: string) => void;
};

export function TextField({ label, error, hint, required, onChange, className, ...rest }: InputProps) {
  return (
    <Field label={label} error={error} hint={hint} required={required}>
      {({ id, describedBy, invalid }) => (
        <input id={id} className={`input ${className ?? ''}`} aria-describedby={describedBy} aria-invalid={invalid || undefined}
          required={required} onChange={(e) => onChange(e.target.value)} {...rest} />
      )}
    </Field>
  );
}

/** Importes y cantidades: teclado numérico y alineación a la derecha; acepta "12.500" o "12500,5". */
export function NumberField(props: InputProps) {
  return <TextField inputMode="decimal" autoComplete="off" className="num" {...props} />;
}

type SelectProps = Omit<SelectHTMLAttributes<HTMLSelectElement>, 'onChange'> & {
  label: string;
  error?: string;
  hint?: string;
  options: { value: string | number; label: string }[];
  placeholder?: string;
  onChange: (value: string) => void;
};

export function SelectField({ label, error, hint, required, options, placeholder, onChange, ...rest }: SelectProps) {
  return (
    <Field label={label} error={error} hint={hint} required={required}>
      {({ id, describedBy, invalid }) => (
        <select id={id} className="select" aria-describedby={describedBy} aria-invalid={invalid || undefined}
          required={required} onChange={(e) => onChange(e.target.value)} {...rest}>
          {placeholder !== undefined && <option value="">{placeholder}</option>}
          {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      )}
    </Field>
  );
}

type AreaProps = Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'onChange'> & {
  label: string;
  error?: string;
  hint?: string;
  onChange: (value: string) => void;
};

export function TextArea({ label, error, hint, required, onChange, ...rest }: AreaProps) {
  return (
    <Field label={label} error={error} hint={hint} required={required}>
      {({ id, describedBy, invalid }) => (
        <textarea id={id} className="textarea" aria-describedby={describedBy} aria-invalid={invalid || undefined}
          onChange={(e) => onChange(e.target.value)} {...rest} />
      )}
    </Field>
  );
}

export function Checkbox({ label, checked, onChange, hint, disabled }: {
  label: string; checked: boolean; onChange: (v: boolean) => void; hint?: string; disabled?: boolean;
}) {
  return (
    <label className="check">
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span>
        <span>{label}</span>
        {hint && <span className="field-hint" style={{ display: 'block' }}>{hint}</span>}
      </span>
    </label>
  );
}

/** Estado de formulario con errores por campo devueltos por la API. */
export function fieldError(errors: Record<string, string> | undefined, name: string): string | undefined {
  return errors?.[name];
}

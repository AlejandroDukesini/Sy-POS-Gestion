import { SelectField, TextField } from './ui/Form';
import { useApi } from '../lib/hooks';

interface PrintersInfo { available: boolean; printers: { name: string; driver: string }[]; default: string; reason: string }

/**
 * Elige cualquier impresora instalada en Windows en el equipo del servidor (térmica, láser, tinta, PDF…).
 * emptyLabel: texto de la opción vacía (usar la predeterminada). Si la lista no está disponible se escribe el nombre.
 */
export function PrinterSelect({ label, value, onChange, emptyLabel, hint, error }: {
  label: string; value: string; onChange: (v: string) => void; emptyLabel?: string; hint?: string; error?: string;
}) {
  const info = useApi<PrintersInfo>('/printing/printers');
  if (!info.data && !info.error) {             // cargando: lista provisional con el valor actual
    return <SelectField label={label} value={value} onChange={onChange} hint={hint} error={error}
      options={[...(emptyLabel !== undefined ? [{ value: '', label: emptyLabel }] : []), ...(value ? [{ value, label: value }] : [])]} />;
  }
  if (!info.data?.available) {
    return <TextField label={label} value={value} onChange={onChange} maxLength={200} error={error}
      hint={info.data?.reason ?? hint ?? 'Nombre exacto de la impresora en Windows.'} />;
  }
  const names = info.data.printers.map((p) => p.name);
  const options = [
    ...(emptyLabel !== undefined ? [{ value: '', label: emptyLabel }] : []),
    ...info.data.printers.map((p) => ({ value: p.name, label: `${p.name}${p.name === info.data!.default ? ' (predeterminada de Windows)' : ''}` })),
    ...(value && !names.includes(value) ? [{ value, label: `${value} (no instalada en este equipo)` }] : []),
  ];
  return <SelectField label={label} value={value} onChange={onChange} options={options} hint={hint} error={error} />;
}

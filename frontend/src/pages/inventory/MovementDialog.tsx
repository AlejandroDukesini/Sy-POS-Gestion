import { Check } from 'lucide-react';
import { useMemo, useState } from 'react';
import { ApiError, newKey, post } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { Dialog } from '../../components/ui/Dialog';
import { ErrorAlert } from '../../components/ui/Feedback';
import { NumberField, SelectField, TextField } from '../../components/ui/Form';
import { useAuth } from '../../context/Auth';
import { useToast } from '../../context/Toast';
import { daysFromToday, qty, toApiNumber } from '../../lib/format';
import { useApi } from '../../lib/hooks';
import type { Product } from './InventoryPage';

export type MovementKind = 'entrada' | 'salida' | 'ajuste';
const TITLES = { entrada: 'Registrar entrada', salida: 'Registrar salida', ajuste: 'Ajuste por conteo físico' };

export function MovementDialog({ kind, product, onClose, onDone }: {
  kind: MovementKind; product: Product; onClose: () => void; onDone: () => void;
}) {
  const { can } = useAuth();
  const { notify } = useToast();
  const meta = useApi('/products/meta');
  const methods = useApi<any[]>('/payment-methods');
  const suppliers = useApi(kind === 'entrada' ? '/parties/proveedores?page_size=200' : null);
  const idempotencyKey = useMemo(newKey, []);   // una clave por intento: reintentar no duplica el movimiento
  const [form, setForm] = useState({
    qty: '', counted_qty: '', unit_cost: product.cost ?? '', reason: '',
    counterpart: kind === 'entrada' ? 'compra_contado' : 'merma', method_id: '', supplier_id: '', invoice_number: '',
    due_date: daysFromToday(30),
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (key: keyof typeof form) => (value: string) => setForm((f) => ({ ...f, [key]: value }));
  const counterparts: Record<string, string> = kind === 'entrada' ? meta.data?.entry_counterparts ?? {} : meta.data?.exit_counterparts ?? {};
  const cashMethods = (methods.data ?? []).filter((m) => m.kind !== 'credito');

  const submit = async () => {
    const e: Record<string, string> = {};
    if (kind === 'ajuste') {
      if (form.counted_qty.trim() === '' || Number(toApiNumber(form.counted_qty)) < 0) e.counted_qty = 'Escriba la cantidad contada.';
    } else if (!(Number(toApiNumber(form.qty)) > 0)) e.qty = 'La cantidad debe ser mayor que cero.';
    if (!form.reason.trim()) e.reason = 'Escriba el motivo.';
    if (kind === 'entrada' && form.counterpart === 'compra_contado' && !form.method_id) e.method_id = 'Elija cómo se pagó.';
    if (kind === 'entrada' && form.counterpart === 'compra_credito') {
      if (!form.supplier_id) e.supplier_id = 'Seleccione el proveedor.';
      if (!form.invoice_number.trim()) e.invoice_number = 'Escriba el número de la factura.';
    }
    setErrors(e);
    if (Object.keys(e).length) return;
    const body: Record<string, unknown> = { kind, reason: form.reason.trim() };
    if (kind === 'ajuste') body.counted_qty = toApiNumber(form.counted_qty);
    else body.qty = toApiNumber(form.qty);
    if (kind !== 'ajuste') body.counterpart = form.counterpart;
    if (kind === 'entrada') {
      if (form.unit_cost.trim()) body.unit_cost = toApiNumber(form.unit_cost);
      if (form.counterpart === 'compra_contado') body.method_id = Number(form.method_id);
      if (form.counterpart === 'compra_credito') {
        Object.assign(body, { supplier_id: Number(form.supplier_id), invoice_number: form.invoice_number.trim(), due_date: form.due_date });
      }
    }
    setBusy(true);
    setError(null);
    try {
      const result = await post(`/products/${product.id}/movements`, body, idempotencyKey);
      notify('success', 'Movimiento registrado', `${product.code}: ahora hay ${qty(result.product.stock)} ${product.unit}.`);
      onDone();
    } catch (err) {
      setError(err as ApiError);
      setErrors((err as ApiError).fields ?? {});
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open title={`${TITLES[kind]} · ${product.code}`} onClose={onClose} size="wide" footer={
      <>
        <Button onClick={onClose}>Cancelar</Button>
        <Button variant="primary" busy={busy} icon={<Check size={20} />} onClick={submit}>Confirmar {kind}</Button>
      </>
    }>
      <p><strong>{product.description}</strong> · disponible ahora: <strong>{qty(product.stock)} {product.unit}</strong></p>
      <ErrorAlert error={error} />
      <div className="form-grid">
        {kind === 'ajuste' ? (
          <NumberField label="Cantidad contada" value={form.counted_qty} onChange={set('counted_qty')} error={errors.counted_qty}
            hint="Se registra la diferencia con la existencia actual." required autoFocus />
        ) : (
          <NumberField label="Cantidad" value={form.qty} onChange={set('qty')} error={errors.qty} required autoFocus />
        )}
        {kind !== 'ajuste' && (
          <SelectField label={kind === 'entrada' ? 'Origen' : 'Destino'} value={form.counterpart} onChange={set('counterpart')}
            options={Object.entries(counterparts).map(([value, label]) => ({ value, label }))} error={errors.counterpart} />
        )}
        {kind === 'entrada' && can('inventario.costos') && (
          <NumberField label="Costo unitario" value={form.unit_cost} onChange={set('unit_cost')} error={errors.unit_cost}
            hint="Actualiza el costo promedio del producto." />
        )}
        {kind === 'entrada' && form.counterpart === 'compra_contado' && (
          <SelectField label="Pagado con" value={form.method_id} onChange={set('method_id')} placeholder="Elija…" required
            options={cashMethods.map((m) => ({ value: m.id, label: m.name }))} error={errors.method_id} />
        )}
        {kind === 'entrada' && form.counterpart === 'compra_credito' && (
          <>
            <SelectField label="Proveedor" value={form.supplier_id} onChange={set('supplier_id')} placeholder="Elija…" required
              options={(suppliers.data?.items ?? []).map((s: any) => ({ value: s.id, label: s.name }))} error={errors.supplier_id}
              hint={suppliers.data?.items?.length === 0 ? 'Registre proveedores en Gestión › Proveedores.' : undefined} />
            <TextField label="Factura del proveedor" value={form.invoice_number} onChange={set('invoice_number')}
              error={errors.invoice_number} required />
            <TextField label="Vence" type="date" value={form.due_date} onChange={set('due_date')} error={errors.due_date} />
          </>
        )}
      </div>
      <TextField label="Motivo" value={form.reason} onChange={set('reason')} error={errors.reason} required maxLength={300}
        placeholder={kind === 'ajuste' ? 'Ej.: Conteo mensual' : kind === 'entrada' ? 'Ej.: Factura 123 de Ferretería X' : 'Ej.: Producto dañado'} />
    </Dialog>
  );
}

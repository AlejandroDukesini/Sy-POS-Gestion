import { Save } from 'lucide-react';
import { useState } from 'react';
import { ApiError, post, put } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { Dialog } from '../../components/ui/Dialog';
import { ErrorAlert } from '../../components/ui/Feedback';
import { NumberField, SelectField, TextField } from '../../components/ui/Form';
import { useAuth } from '../../context/Auth';
import { useToast } from '../../context/Toast';
import { toApiNumber } from '../../lib/format';
import type { Product } from './InventoryPage';

const UNIT_LABELS: Record<string, string> = {
  und: 'Unidad', kg: 'Kilogramo', g: 'Gramo', l: 'Litro', ml: 'Mililitro', m: 'Metro', cm: 'Centímetro',
  caja: 'Caja', paquete: 'Paquete', servicio: 'Servicio',
};

export function ProductForm({ product, categories, units, onClose, onSaved }: {
  product: Product | null; categories: { id: number; name: string }[]; units: string[];
  onClose: () => void; onSaved: (p: Product) => void;
}) {
  const { can } = useAuth();
  const { notify } = useToast();
  const [form, setForm] = useState({
    code: product?.code ?? '', description: product?.description ?? '', category_id: product?.category_id ? String(product.category_id) : '',
    unit: product?.unit ?? 'und', price: product?.price ?? '', discount_price: product?.discount_price ?? '',
    cost: product?.cost ?? '', tax_rate: product?.tax_rate ?? '0', min_stock: product?.min_stock ?? '', initial_stock: '',
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (key: keyof typeof form) => (value: string) => setForm((f) => ({ ...f, [key]: value }));

  const validate = () => {
    const e: Record<string, string> = {};
    if (!form.code.trim()) e.code = 'El código es obligatorio.';
    if (!form.description.trim()) e.description = 'La descripción es obligatoria.';
    const num = (v: string) => (v.trim() === '' ? null : Number(toApiNumber(v)));
    const price = num(form.price);
    if (price === null || Number.isNaN(price) || price < 0) e.price = 'Escriba un precio válido (cero o más).';
    const disc = num(form.discount_price);
    if (disc !== null && (Number.isNaN(disc) || disc < 0)) e.discount_price = 'Valor no válido.';
    else if (disc !== null && price !== null && disc > price) e.discount_price = 'No puede ser mayor que el precio sin descuento.';
    for (const key of ['cost', 'tax_rate', 'min_stock', 'initial_stock'] as const) {
      const v = num(form[key]);
      if (v !== null && (Number.isNaN(v) || v < 0)) e[key] = 'Escriba un número mayor o igual a cero.';
    }
    return e;
  };

  const submit = async () => {
    const local = validate();
    setErrors(local);
    if (Object.keys(local).length) return;
    const body: Record<string, unknown> = {
      code: form.code.trim(), description: form.description.trim(), category_id: form.category_id ? Number(form.category_id) : null,
      unit: form.unit, price: toApiNumber(form.price), discount_price: form.discount_price.trim() ? toApiNumber(form.discount_price) : null,
      tax_rate: toApiNumber(form.tax_rate || '0'), min_stock: toApiNumber(form.min_stock || '0'),
    };
    if (can('inventario.costos')) body.cost = toApiNumber(form.cost || '0');
    if (!product && form.initial_stock.trim()) body.initial_stock = toApiNumber(form.initial_stock);
    if (product) body.version = product.version;
    setBusy(true);
    setError(null);
    try {
      const saved = product ? await put<Product>(`/products/${product.id}`, body) : await post<Product>('/products', body);
      notify('success', product ? 'Producto actualizado' : 'Producto creado', `${saved.code} · ${saved.description}`);
      onSaved(saved);
    } catch (err) {
      setError(err as ApiError);
      setErrors((err as ApiError).fields ?? {});
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open title={product ? `Editar ${product.code}` : 'Nuevo producto'} onClose={onClose} size="wide" footer={
      <>
        <Button onClick={onClose}>Cancelar</Button>
        <Button variant="primary" busy={busy} icon={<Save size={20} />} onClick={submit}>Guardar</Button>
      </>
    }>
      <ErrorAlert error={error} />
      <div className="form-grid">
        <TextField label="Código" value={form.code} onChange={set('code')} error={errors.code} required maxLength={40} autoFocus />
        <TextField label="Descripción" value={form.description} onChange={set('description')} error={errors.description} required maxLength={200} />
        <SelectField label="Categoría" value={form.category_id} onChange={set('category_id')} placeholder="Sin categoría"
          options={categories.map((c) => ({ value: c.id, label: c.name }))} error={errors.category_id} />
        <SelectField label="Unidad" value={form.unit} onChange={set('unit')} error={errors.unit}
          options={units.map((u) => ({ value: u, label: UNIT_LABELS[u] ?? u }))} />
        <NumberField label="Precio sin descuento" value={form.price} onChange={set('price')} error={errors.price} required />
        <NumberField label="Precio con descuento" value={form.discount_price} onChange={set('discount_price')} error={errors.discount_price}
          hint="Déjelo vacío si no tiene descuento." />
        {can('inventario.costos') && (
          <NumberField label="Costo unitario" value={form.cost} onChange={set('cost')} error={errors.cost}
            hint={product ? 'Las entradas con costo recalculan el costo promedio.' : undefined} />
        )}
        <NumberField label="IVA (%)" value={form.tax_rate} onChange={set('tax_rate')} error={errors.tax_rate} />
        <NumberField label="Existencia mínima" value={form.min_stock} onChange={set('min_stock')} error={errors.min_stock}
          hint="Por debajo de esta cantidad se muestra la alerta." />
        {!product && can('inventario.movimientos') && (
          <NumberField label="Existencia inicial" value={form.initial_stock} onChange={set('initial_stock')} error={errors.initial_stock}
            hint="Se registra como movimiento de existencia inicial." />
        )}
      </div>
      {product && <p className="muted">La existencia no se edita aquí: use Entrada, Salida o Ajuste para conservar el historial.</p>}
    </Dialog>
  );
}

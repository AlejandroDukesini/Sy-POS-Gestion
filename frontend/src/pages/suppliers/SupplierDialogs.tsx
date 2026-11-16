import { Paperclip, Save } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { ApiError, post, put, upload } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { Dialog } from '../../components/ui/Dialog';
import { ErrorAlert } from '../../components/ui/Feedback';
import { Checkbox, NumberField, SelectField, TextArea, TextField } from '../../components/ui/Form';
import { useToast } from '../../context/Toast';
import { today } from '../../lib/format';

export const NOTE_CATEGORIES: Record<string, string> = {
  deuda: 'Deuda', pago: 'Pago', entrega: 'Entrega', acuerdo: 'Acuerdo', reclamacion: 'Reclamación',
  seguimiento: 'Seguimiento', general: 'General',
};
export const QUOTE_STATUS: Record<string, string> = {
  pendiente: 'Pendiente', aceptada: 'Aceptada', rechazada: 'Rechazada', vencida: 'Vencida',
};
const options = (map: Record<string, string>) => Object.entries(map).map(([value, label]) => ({ value, label }));

/** Diálogo con guardado, errores del servidor junto a cada campo y botón «Guardar». */
function FormDialog({ title, onClose, onSave, children, error, busy }: {
  title: string; onClose: () => void; onSave: () => void; children: ReactNode; error: ApiError | null; busy: boolean;
}) {
  return (
    <Dialog open title={title} onClose={onClose} size="wide"
      footer={<><Button onClick={onClose}>Cancelar</Button><Button variant="primary" busy={busy} icon={<Save size={20} />} onClick={onSave}>Guardar</Button></>}>
      <ErrorAlert error={error} />
      {children}
    </Dialog>
  );
}

function useSave<T>(fn: () => Promise<T>, done: (value: T) => void, message: string) {
  const { notify } = useToast();
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const value = await fn();
      notify('success', message);
      done(value);
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  return { save, error, busy, fe: error?.fields ?? {} };
}

// ------------------------------------------------------------------ información general y contacto
export function SupplierInfoDialog({ supplier, onClose, onSaved }: { supplier: any; onClose: () => void; onSaved: (s: any) => void }) {
  const [f, setF] = useState({
    name: supplier.name ?? '', identification: supplier.identification ?? '', phone: supplier.phone ?? '',
    whatsapp: supplier.whatsapp ?? '', email: supplier.email ?? '', address: supplier.address ?? '', city: supplier.city ?? '',
    contact_notes: supplier.contact_notes ?? '', payment_days: String(supplier.payment_days ?? 30), active: supplier.active ?? 1,
  });
  const set = (k: keyof typeof f) => (v: any) => setF((x) => ({ ...x, [k]: v }));
  const body = () => ({ ...f, identification: f.identification || null, payment_days: Number(f.payment_days) || 0,
    active: Boolean(f.active), version: supplier.version });
  const { save, error, busy, fe } = useSave(
    () => (supplier.id ? put(`/parties/proveedores/${supplier.id}`, body()) : post('/parties/proveedores', body())),
    onSaved, supplier.id ? 'Proveedor actualizado' : 'Proveedor registrado');
  return (
    <FormDialog title={supplier.id ? 'Información general y contacto' : 'Nuevo proveedor'} onClose={onClose} onSave={save} error={error} busy={busy}>
      <div className="form-grid">
        <TextField label="Nombre o razón social" value={f.name} onChange={set('name')} error={fe.name} required maxLength={160} />
        <TextField label="NIT o cédula" value={f.identification} onChange={set('identification')} error={fe.identification} maxLength={40} />
        <TextField label="Teléfono" type="tel" value={f.phone} onChange={set('phone')} error={fe.phone} maxLength={60} />
        <TextField label="WhatsApp" type="tel" value={f.whatsapp} onChange={set('whatsapp')} error={fe.whatsapp} maxLength={60} />
        <TextField label="Correo" type="email" value={f.email} onChange={set('email')} error={fe.email} maxLength={120} />
        <TextField label="Ciudad" value={f.city} onChange={set('city')} error={fe.city} maxLength={80} />
        <TextField label="Dirección" value={f.address} onChange={set('address')} error={fe.address} maxLength={200} />
        <NumberField label="Días de pago" value={f.payment_days} onChange={set('payment_days')} error={fe.payment_days} />
      </div>
      <TextArea label="Información adicional de contacto" value={f.contact_notes} onChange={set('contact_notes')} error={fe.contact_notes}
        maxLength={1000} hint="Horarios, otras personas de contacto, cómo hacer pedidos…" />
      {supplier.id && <Checkbox label="Activo" checked={Boolean(f.active)} onChange={(v) => set('active')(v ? 1 : 0)}
        hint="Un proveedor inactivo conserva todo su expediente." />}
    </FormDialog>
  );
}

// ------------------------------------------------------------------ asesor comercial
export function AdvisorDialog({ supplier, onClose, onSaved }: { supplier: any; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ advisor_name: supplier.advisor_name ?? '', advisor_phone: supplier.advisor_phone ?? '',
    advisor_email: supplier.advisor_email ?? '', advisor_notes: supplier.advisor_notes ?? '' });
  const set = (k: keyof typeof f) => (v: string) => setF((x) => ({ ...x, [k]: v }));
  const { save, error, busy, fe } = useSave(() => put(`/suppliers/${supplier.id}/advisor`, f), onSaved, 'Asesor actualizado');
  return (
    <FormDialog title="Asesor comercial" onClose={onClose} onSave={save} error={error} busy={busy}>
      <div className="form-grid">
        <TextField label="Nombre del asesor" value={f.advisor_name} onChange={set('advisor_name')} error={fe.advisor_name} maxLength={120} />
        <TextField label="Teléfono" type="tel" value={f.advisor_phone} onChange={set('advisor_phone')} error={fe.advisor_phone} maxLength={60} />
        <TextField label="Correo" type="email" value={f.advisor_email} onChange={set('advisor_email')} error={fe.advisor_email} maxLength={120} />
      </div>
      <TextArea label="Observaciones" value={f.advisor_notes} onChange={set('advisor_notes')} error={fe.advisor_notes} maxLength={1000} />
      <p className="muted">Si el proveedor cambia de asesor, actualícelo aquí: las visitas y cotizaciones anteriores conservan el nombre con que se registraron.</p>
    </FormDialog>
  );
}

// ------------------------------------------------------------------ notas
export function NoteDialog({ supplierId, note, onClose, onSaved }: { supplierId: number; note: any; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ category: note.category ?? 'general', title: note.title ?? '', body: note.body ?? '',
    status: note.status ?? 'pendiente', important: Boolean(note.important), due_date: note.due_date ?? '' });
  const set = (k: keyof typeof f) => (v: any) => setF((x) => ({ ...x, [k]: v }));
  const body = { ...f, due_date: f.due_date || null, ...(note.id ? { version: note.version } : {}) };
  const { save, error, busy, fe } = useSave(
    () => (note.id ? put(`/suppliers/${supplierId}/notes/${note.id}`, body) : post(`/suppliers/${supplierId}/notes`, body)),
    onSaved, note.id ? 'Nota actualizada' : 'Nota registrada');
  return (
    <FormDialog title={note.id ? 'Editar nota' : 'Nueva nota o pendiente'} onClose={onClose} onSave={save} error={error} busy={busy}>
      <div className="form-grid">
        <SelectField label="Categoría" value={f.category} onChange={set('category')} options={options(NOTE_CATEGORIES)} error={fe.category} />
        <SelectField label="Estado" value={f.status} onChange={set('status')} error={fe.status}
          options={[{ value: 'pendiente', label: 'Pendiente' }, { value: 'resuelta', label: 'Resuelta' }]} />
        <TextField label="Vence" type="date" value={f.due_date} onChange={set('due_date')} error={fe.due_date} hint="Opcional." />
      </div>
      <TextField label="Título" value={f.title} onChange={set('title')} error={fe.title} required maxLength={200}
        hint="Ej.: «Debemos la factura 123 por $ 1.200.000»." />
      <TextArea label="Detalle" value={f.body} onChange={set('body')} error={fe.body} maxLength={4000} />
      <Checkbox label="Importante" checked={f.important} onChange={set('important')} />
      <p className="muted">Las notas son informativas: no modifican inventario, compras, ventas ni cuentas por pagar.</p>
    </FormDialog>
  );
}

// ------------------------------------------------------------------ visitas
export function VisitDialog({ supplier, visit, onClose, onSaved }: { supplier: any; visit: any; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ visit_date: visit.visit_date ?? today(), advisor_name: visit.advisor_name ?? supplier.advisor_name ?? '',
    reason: visit.reason ?? '', summary: visit.summary ?? '', agreements: visit.agreements ?? '', next_visit_date: visit.next_visit_date ?? '' });
  const set = (k: keyof typeof f) => (v: string) => setF((x) => ({ ...x, [k]: v }));
  const body = { ...f, next_visit_date: f.next_visit_date || null, ...(visit.id ? { version: visit.version } : {}) };
  const { save, error, busy, fe } = useSave(
    () => (visit.id ? put(`/suppliers/${supplier.id}/visits/${visit.id}`, body) : post(`/suppliers/${supplier.id}/visits`, body)),
    onSaved, visit.id ? 'Visita actualizada' : 'Visita registrada');
  return (
    <FormDialog title={visit.id ? 'Editar visita' : 'Registrar visita'} onClose={onClose} onSave={save} error={error} busy={busy}>
      <div className="form-grid">
        <TextField label="Fecha de la visita" type="date" value={f.visit_date} onChange={set('visit_date')} error={fe.visit_date} required />
        <TextField label="Asesor que visitó" value={f.advisor_name} onChange={set('advisor_name')} error={fe.advisor_name} maxLength={120} />
        <TextField label="Próxima visita" type="date" value={f.next_visit_date} onChange={set('next_visit_date')} error={fe.next_visit_date} hint="Opcional." />
      </div>
      <TextField label="Motivo" value={f.reason} onChange={set('reason')} error={fe.reason} required maxLength={200} />
      <TextArea label="Descripción o resumen" value={f.summary} onChange={set('summary')} error={fe.summary} maxLength={4000} />
      <TextArea label="Acuerdos alcanzados" value={f.agreements} onChange={set('agreements')} error={fe.agreements} maxLength={4000} />
    </FormDialog>
  );
}

// ------------------------------------------------------------------ cotizaciones
export function QuoteDialog({ supplier, quote, onClose, onSaved }: { supplier: any; quote: any; onClose: () => void; onSaved: () => void }) {
  const { notify } = useToast();
  const [f, setF] = useState({ number: quote.number ?? '', issue_date: quote.issue_date ?? today(), due_date: quote.due_date ?? '',
    advisor_name: quote.advisor_name ?? supplier.advisor_name ?? '', description: quote.description ?? '', total: quote.total ?? '',
    status: quote.status ?? 'pendiente', notes: quote.notes ?? '' });
  const [file, setFile] = useState<File | null>(null);
  const set = (k: keyof typeof f) => (v: string) => setF((x) => ({ ...x, [k]: v }));
  const body = { ...f, due_date: f.due_date || null, total: f.total === '' ? null : f.total, ...(quote.id ? { version: quote.version } : {}) };
  const { save, error, busy, fe } = useSave(async () => {
    const saved = quote.id ? await put(`/suppliers/${supplier.id}/quotes/${quote.id}`, body) : await post(`/suppliers/${supplier.id}/quotes`, body);
    if (file) {
      const form = new FormData();
      form.append('file', file);
      try {
        await upload(`/suppliers/${supplier.id}/quotes/${saved.id}/file`, form);
      } catch (err) {
        notify('danger', 'La cotización se guardó, pero el adjunto no', (err as ApiError).message);
      }
    }
    return saved;
  }, onSaved, quote.id ? 'Cotización actualizada' : 'Cotización registrada');
  return (
    <FormDialog title={quote.id ? `Cotización ${quote.number}` : 'Registrar cotización'} onClose={onClose} onSave={save} error={error} busy={busy}>
      <div className="form-grid">
        <TextField label="Número o identificador" value={f.number} onChange={set('number')} error={fe.number} required maxLength={60} />
        <TextField label="Fecha de emisión" type="date" value={f.issue_date} onChange={set('issue_date')} error={fe.issue_date} required />
        <TextField label="Vence" type="date" value={f.due_date} onChange={set('due_date')} error={fe.due_date} hint="Opcional." />
        <TextField label="Asesor" value={f.advisor_name} onChange={set('advisor_name')} error={fe.advisor_name} maxLength={120} />
        <NumberField label="Valor total" value={f.total} onChange={set('total')} error={fe.total} hint="Opcional, si se conoce." />
        <SelectField label="Estado" value={f.status} onChange={set('status')} options={options(QUOTE_STATUS)} error={fe.status} />
      </div>
      <TextArea label="Descripción" value={f.description} onChange={set('description')} error={fe.description} maxLength={4000} />
      <TextArea label="Observaciones" value={f.notes} onChange={set('notes')} error={fe.notes} maxLength={4000} />
      <label className="field-label" htmlFor="quote-file"><Paperclip size={16} aria-hidden /> Archivo adjunto (opcional)</label>
      <input id="quote-file" type="file" accept=".pdf,.xlsx,.xls,.png,.jpg,.jpeg" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      <p className="muted">{quote.file_name ? `Adjunto actual: ${quote.file_name}. Si elige otro, lo reemplaza. ` : ''}
        PDF, Excel o imagen. Registrar una cotización no crea una compra ni modifica el inventario.</p>
    </FormDialog>
  );
}

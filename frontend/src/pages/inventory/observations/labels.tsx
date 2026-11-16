/** Etiquetas y distintivos de observaciones de inventario: el color acompaña siempre a un texto. */

export const PRIORITY_LABELS: Record<string, string> = { baja: 'Baja', media: 'Media', alta: 'Alta', critica: 'Crítica' };
export const STATUS_LABELS: Record<string, string> = {
  pendiente: 'Pendiente', en_proceso: 'En proceso', resuelta: 'Resuelta', cerrada: 'Cerrada',
};
export const EVENT_LABELS: Record<string, string> = {
  creada: 'Observación registrada', comentario: 'Comentario', estado: 'Cambio de estado', prioridad: 'Cambio de prioridad',
  edicion: 'Datos editados', adjunto: 'Archivo adjuntado', adjunto_eliminado: 'Archivo eliminado', eliminada: 'Observación eliminada',
};
export const FIELD_LABELS: Record<string, string> = {
  category_id: 'Categoría', description: 'Descripción', qty_milli: 'Cantidad afectada', supplier_id: 'Proveedor',
  reference_doc: 'Documento de referencia', detected_on: 'Fecha de la novedad', follow_up_date: 'Fecha límite de seguimiento',
  notes: 'Comentarios adicionales', assigned_to: 'Responsable',
};

export interface Observation {
  id: number; code: string; product_id: number; product_code: string; product_description: string; product_unit: string;
  product_active: number; category_id: number; category_name: string; priority: string; status: string; description: string;
  qty: string | null; supplier_id: number | null; supplier_name: string | null; reference_doc: string; detected_on: string;
  follow_up_date: string | null; notes?: string; assigned_to: number | null; responsible_name: string | null;
  created_by_name: string | null; created_at: string; updated_at: string; resolved_at: string | null; closed_at: string | null;
  version: number; is_open: boolean; follow_up_overdue: boolean;
}

export function PriorityBadge({ priority }: { priority: string }) {
  return <span className={`badge obs-priority obs-priority-${priority}`}>{PRIORITY_LABELS[priority] ?? priority}</span>;
}

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge obs-status obs-status-${status}`}>{STATUS_LABELS[status] ?? status}</span>;
}

export const obsCode = (id: number) => `OBS-${String(id).padStart(5, '0')}`;

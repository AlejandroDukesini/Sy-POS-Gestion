import { FileText } from 'lucide-react';
import { useEffect, useState } from 'react';
import { ApiError, qs } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { Dialog } from '../../components/ui/Dialog';
import { ErrorAlert, Loading } from '../../components/ui/Feedback';
import { SelectField } from '../../components/ui/Form';
import { useApi } from '../../lib/hooks';

/**
 * PDF de una operación real con una plantilla de impresión (Gestión › Plantillas de impresión).
 * El servidor genera el PDF con los datos reales y la hora real, y lo guarda en el historial con la
 * versión de la plantilla usada. Solo aparece si hay plantillas activas para este tipo.
 */
export function TemplatePdfButton({ target, id, kind, documentTypeId, label }: {
  target: 'documento' | 'venta'; id: number; kind: 'documento' | 'venta' | 'recibo'; documentTypeId?: number; label?: string;
}) {
  const templates = useApi<any[]>(`/print-templates${qs({ kind, document_type_id: documentTypeId, active: true })}`);
  const [open, setOpen] = useState(false);
  const list = templates.data ?? [];
  if (!list.length) return null;
  return (
    <>
      <Button variant="outline" icon={<FileText size={20} />} onClick={() => setOpen(true)}>{label ?? 'PDF con plantilla'}</Button>
      {open && <PdfDialog target={target} id={id} kind={kind} templates={list} onClose={() => setOpen(false)} />}
    </>
  );
}

function PdfDialog({ target, id, kind, templates, onClose }: {
  target: 'documento' | 'venta'; id: number; kind: string; templates: any[]; onClose: () => void;
}) {
  const initial = templates.find((t) => t.is_default) ?? templates[0];
  const [template, setTemplate] = useState<string>(initial.public_id);
  const [url, setUrl] = useState<string | null>(null);
  const [pages, setPages] = useState<string>('');
  const [error, setError] = useState<ApiError | null>(null);
  useEffect(() => {
    let alive = true;
    let current: string | null = null;
    setUrl(null);
    setError(null);
    const path = target === 'documento' ? `/documents/${id}/template-pdf${qs({ template })}`
      : `/sales/${id}/template-pdf${qs({ template, kind })}`;
    fetch(`/api${path}`, { credentials: 'same-origin', headers: { 'X-Requested-With': 'pos-py' } })
      .then(async (r) => {
        if (!r.ok) {
          const data = await r.json().catch(() => ({}));
          throw new ApiError(r.status, data.error ?? 'Error', data.detail ?? 'No se pudo generar el PDF.');
        }
        setPages(r.headers.get('X-Pages') ?? '');
        return r.blob();
      })
      .then((blob) => { if (!alive) return; current = URL.createObjectURL(blob); setUrl(current); })
      .catch((err) => { if (alive) setError(err as ApiError); });
    return () => { alive = false; if (current) URL.revokeObjectURL(current); };
  }, [target, id, kind, template]);
  return (
    <Dialog open size="xl" title="PDF con plantilla" onClose={onClose} footer={<>
      {url && <a className="btn btn-outline" href={url} download={`${target}-${id}.pdf`}>Descargar PDF</a>}
      <Button onClick={onClose}>Cerrar</Button>
    </>}>
      <div className="row">
        {templates.length > 1 && (
          <div style={{ minWidth: 260 }}>
            <SelectField label="Plantilla" value={template} onChange={setTemplate}
              options={templates.map((t) => ({ value: t.public_id, label: `${t.name}${t.is_default ? ' (predeterminada)' : ''}` }))} />
          </div>
        )}
        <p className="muted grow">
          Datos reales de la operación y hora de esta generación{pages ? ` · ${pages} página(s)` : ''}. Queda guardado en el historial
          con la versión de la plantilla. Imprímalo desde el visor del PDF.
        </p>
      </div>
      <ErrorAlert error={error} />
      {!url && !error ? <Loading label="Generando PDF…" /> : url ? <iframe className="tpl-preview" title="PDF generado" src={url} /> : null}
    </Dialog>
  );
}

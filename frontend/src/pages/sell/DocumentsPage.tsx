import { ArrowLeft, Ban, Download, FileDown, FilePlus2, Pencil, Printer, Save, ShoppingCart } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Link, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { ApiError, download, get, newKey, post, put, qs } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { ConfirmDialog } from '../../components/ui/Dialog';
import { Alert, EmptyState, ErrorAlert, ErrorState, Loading, StatusBadge } from '../../components/ui/Feedback';
import { SelectField, TextArea, TextField } from '../../components/ui/Form';
import { Card, PageHeader } from '../../components/ui/Layout';
import { DataTable, Pagination } from '../../components/ui/Table';
import { useAuth } from '../../context/Auth';
import { useToast } from '../../context/Toast';
import { date, dateTime, money, toApiNumber } from '../../lib/format';
import { useApi, useDebounced, useOnline } from '../../lib/hooks';
import { addToCart, CartTable, CustomerPicker, printInBrowser, ProductSearch, StockWarnings, TotalsBox, useQuote, type CartLine, type Customer } from './Cart';

export default function DocumentsPage() {
  return (
    <Routes>
      <Route index element={<DocumentList />} />
      <Route path="nuevo" element={<DocumentEditor />} />
      <Route path=":id" element={<DocumentDetail />} />
      <Route path=":id/editar" element={<DocumentEditor />} />
    </Routes>
  );
}

function DocumentList() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const types = useApi<any[]>('/document-types');
  const [typeId, setTypeId] = useState('');
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  const term = useDebounced(q, 300);
  const list = useApi(`/documents${qs({ type_id: typeId, q: term, page, page_size: 25 })}`);
  if (!can('documentos.ver')) return <EmptyState title="No tiene permiso para consultar documentos" />;
  return (
    <div className="stack">
      <PageHeader title="Cotizaciones y órdenes" description="Documentos comerciales generados con las plantillas de la empresa."
        actions={can('documentos.crear') && (
          <Button variant="primary" icon={<FilePlus2 size={20} />} onClick={() => navigate('/vender/documentos/nuevo')}>Nuevo documento</Button>)} />
      <Card>
        <div className="card-body row">
          <div style={{ minWidth: 220 }}>
            <SelectField label="Tipo" value={typeId} onChange={(v) => { setTypeId(v); setPage(1); }} placeholder="Todos"
              options={(types.data ?? []).map((t) => ({ value: t.id, label: t.name }))} />
          </div>
          <div className="grow" style={{ minWidth: 220 }}>
            <TextField label="Buscar por número o cliente" type="search" value={q} onChange={(v) => { setQ(v); setPage(1); }} />
          </div>
        </div>
        {list.loading && !list.data ? <Loading /> : list.error ? <ErrorState error={list.error} onRetry={list.reload} /> :
          !list.data.items.length ? <EmptyState title="No hay documentos todavía" /> : (
            <>
              <DataTable caption="Documentos comerciales" rows={list.data.items} rowKey={(d: any) => d.id}
                onSelect={(d: any) => navigate(`/vender/documentos/${d.id}`)} columns={[
                  { key: 't', header: 'Tipo', render: (d: any) => d.type_name },
                  { key: 'n', header: 'Número', render: (d: any) => <strong>{d.number}</strong> },
                  { key: 'f', header: 'Fecha', render: (d: any) => date(d.doc_date) },
                  { key: 'c', header: 'Cliente', render: (d: any) => d.customer_name },
                  { key: 's', header: 'Estado', render: (d: any) => <StatusBadge status={d.status} /> },
                  { key: 'p', header: 'Impreso', render: (d: any) => (d.prints ? `${d.prints} ${d.prints === 1 ? 'vez' : 'veces'}` : 'No') },
                  { key: 'v', header: 'Total', numeric: true, render: (d: any) => <strong>{money(d.total)}</strong> },
                ]} />
              <Pagination page={list.data.page} pages={list.data.pages} total={list.data.total} onPage={setPage} />
            </>
          )}
      </Card>
    </div>
  );
}

function DocumentEditor() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { notify } = useToast();
  const online = useOnline();
  const types = useApi<any[]>('/document-types');
  const existing = useApi(id ? `/documents/${id}` : null);
  const idempotencyKey = useMemo(newKey, []);
  const [typeId, setTypeId] = useState('');
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [manual, setManual] = useState({ customer_name: '', customer_identification: '', customer_phone: '', customer_email: '', customer_address: '' });
  const [extra, setExtra] = useState<Record<string, string>>({});
  const [number, setNumber] = useState('');
  const [notes, setNotes] = useState('');
  const [lines, setLines] = useState<CartLine[]>([]);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const { quote, error: quoteError } = useQuote(lines);

  useEffect(() => {
    const d = existing.data;
    if (!d) return;
    setTypeId(String(d.type_id));
    setManual({ customer_name: d.customer_name, customer_identification: d.customer_identification, customer_phone: d.customer_phone,
      customer_email: d.customer_email, customer_address: d.customer_address });
    if (d.customer_id) setCustomer({ id: d.customer_id, name: d.customer_name, identification: d.customer_identification,
      phone: d.customer_phone, email: d.customer_email, address: d.customer_address });
    setExtra(d.extra ?? {});
    setNotes(d.notes);
    setLines(d.lines.map((l: any) => ({ product_id: l.product_id, code: l.code, description: l.description, unit: '', qty: l.qty,
      discount_pct: Number(l.manual_discount) ? l.manual_discount : '' })));
  }, [existing.data]);

  useEffect(() => {
    if (!typeId && types.data?.length && !id) setTypeId(String(types.data[0].id));
  }, [types.data, typeId, id]);

  const type = (types.data ?? []).find((t) => String(t.id) === typeId);
  const setM = (k: keyof typeof manual) => (v: string) => setManual((m) => ({ ...m, [k]: v }));

  const save = async () => {
    const e: Record<string, string> = {};
    if (!typeId) e.type_id = 'Seleccione el tipo de documento.';
    if (!customer && !manual.customer_name.trim()) e.customer_name = 'Seleccione o escriba el cliente.';
    if (!lines.length) e.lines = 'Agregue al menos un producto.';
    for (const f of type?.fields ?? []) if (f.required && !extra[f.key]?.trim()) e[`extra.${f.key}`] = `${f.label} es obligatorio.`;
    if (type && !type.numbering && !id && !number.trim()) e.number = 'Escriba el número del documento.';
    setErrors(e);
    if (Object.keys(e).length) return;
    const body: Record<string, unknown> = {
      type_id: Number(typeId), customer_id: customer?.id ?? null, ...(customer ? {} : manual), extra, notes,
      lines: lines.map((l) => ({ product_id: l.product_id, qty: toApiNumber(l.qty), discount_pct: toApiNumber(l.discount_pct) || '0' })),
    };
    if (type && !type.numbering && !id) body.number = number.trim();
    setBusy(true);
    setError(null);
    try {
      const doc = id ? await put(`/documents/${id}`, { ...body, version: existing.data.version })
        : await post('/documents', body, idempotencyKey);
      notify('success', id ? 'Documento actualizado' : 'Documento creado', `${doc.type_name} ${doc.number}`);
      navigate(`/vender/documentos/${doc.id}`);
    } catch (err) {
      setError(err as ApiError);
      setErrors((err as ApiError).fields ?? {});
    } finally {
      setBusy(false);
    }
  };

  if (id && existing.loading && !existing.data) return <Loading />;
  return (
    <div className="stack">
      <Link to={id ? `/vender/documentos/${id}` : '/vender/documentos'} className="btn btn-ghost" style={{ alignSelf: 'flex-start' }}>
        <ArrowLeft size={20} aria-hidden /> Volver
      </Link>
      <PageHeader title={id ? `Editar ${existing.data?.type_name} ${existing.data?.number}` : 'Nuevo documento'} />
      <ErrorAlert error={error} />
      <div className="pos">
        <Card title="1. Productos">
          <div className="card-body stack">
            <ProductSearch onPick={(p) => setLines((ls) => addToCart(ls, p))} />
            {errors.lines && <Alert kind="danger">{errors.lines}</Alert>}
            <StockWarnings quote={quote} />
            <ErrorAlert error={quoteError} />
            {lines.length ? <CartTable lines={lines} setLines={setLines} quote={quote} /> : <EmptyState title="Sin productos todavía" />}
            <TotalsBox quote={quote} />
          </div>
        </Card>
        <div className="stack">
          <Card title="2. Documento">
            <div className="card-body stack">
              <SelectField label="Tipo de documento" value={typeId} onChange={setTypeId} disabled={Boolean(id)} error={errors.type_id}
                options={(types.data ?? []).map((t) => ({ value: t.id, label: t.name }))} required />
              {type && !type.has_template && <Alert kind="warning">Este tipo aún no tiene plantilla: podrá guardarlo, pero para imprimir un administrador debe subirla en Gestión › Tipos de documento.</Alert>}
              {type && !type.numbering && !id && <TextField label="Número" value={number} onChange={setNumber} error={errors.number} required />}
              {(type?.fields ?? []).map((f: any) => (
                <TextField key={f.key} label={f.label} required={f.required} value={extra[f.key] ?? ''}
                  onChange={(v) => setExtra((x) => ({ ...x, [f.key]: v }))} error={errors[`extra.${f.key}`]} />
              ))}
            </div>
          </Card>
          <Card title="3. Cliente">
            <div className="card-body stack">
              <CustomerPicker value={customer} onChange={setCustomer} label="Cliente registrado" />
              {!customer && (
                <>
                  <p className="muted">O escriba los datos sin registrarlo:</p>
                  <TextField label="Nombre" value={manual.customer_name} onChange={setM('customer_name')} error={errors.customer_name} required />
                  <TextField label="NIT o cédula" value={manual.customer_identification} onChange={setM('customer_identification')} />
                  <TextField label="Teléfono" value={manual.customer_phone} onChange={setM('customer_phone')} />
                  <TextField label="Correo" value={manual.customer_email} onChange={setM('customer_email')} error={errors.customer_email} />
                  <TextField label="Dirección" value={manual.customer_address} onChange={setM('customer_address')} />
                </>
              )}
              <TextArea label="Observaciones" value={notes} onChange={setNotes} maxLength={1000} />
            </div>
          </Card>
          <Button variant="primary" size="lg" block busy={busy} disabled={!online} icon={<Save size={22} />} onClick={save}>
            Guardar documento
          </Button>
        </div>
      </div>
    </div>
  );
}

function DocumentDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { can } = useAuth();
  const { notify } = useToast();
  const doc = useApi(`/documents/${id}`);
  const [preview, setPreview] = useState<any>(null);
  const [previewError, setPreviewError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState('');
  const [voiding, setVoiding] = useState(false);
  const [printError, setPrintError] = useState<ApiError | null>(null);
  const d = doc.data;

  useEffect(() => {
    if (!d) return;
    setPreviewError(null);
    get(`/documents/${id}/preview`).then(setPreview).catch((err) => { setPreview(null); setPreviewError(err); });
  }, [d, id]);

  const print = async () => {
    setBusy('print');
    setPrintError(null);
    try {
      if (preview?.direct_print) {
        const r = await post(`/documents/${id}/print`, {});
        notify('success', 'Documento enviado a imprimir', `Impresora: ${r.printer}`);
      } else {
        printInBrowser(`${d.type_name} ${d.number}`, preview?.html ?? '',
          `table{border-collapse:collapse;font-size:12px} td{padding:2px 4px} @page{size:${preview?.page_setup?.paper ?? 'letter'} ${preview?.page_setup?.orientation ?? 'portrait'};margin:${preview?.page_setup?.margins_cm ?? 1.5}cm}`);
        await post('/printing/browser-log', { target_type: 'documento', target_id: Number(id), label: `${d.type_name} ${d.number}` });
      }
      doc.reload();
    } catch (err) {
      setPrintError(err as ApiError);
      doc.reload();
    } finally {
      setBusy('');
    }
  };
  const fetchFile = async (kind: 'file' | 'pdf') => {
    setBusy(kind);
    try {
      await download(`/documents/${id}/${kind}`, `${d.number}.${kind === 'pdf' ? 'pdf' : 'xlsx'}`);
    } catch (err) {
      notify('danger', 'No se pudo descargar', (err as Error).message);
    } finally {
      setBusy('');
    }
  };
  const doVoid = async (reason: string) => {
    try {
      await post(`/documents/${id}/void`, { reason });
      notify('success', 'Documento anulado');
      doc.reload();
    } catch (err) {
      notify('danger', 'No se pudo anular', (err as Error).message);
    } finally {
      setVoiding(false);
    }
  };

  if (doc.loading && !d) return <Loading />;
  if (doc.error) return <ErrorState error={doc.error} onRetry={doc.reload} />;
  const active = d.status === 'vigente';
  return (
    <div className="stack">
      <Link to="/vender/documentos" className="btn btn-ghost" style={{ alignSelf: 'flex-start' }}><ArrowLeft size={20} aria-hidden /> Volver a documentos</Link>
      <PageHeader title={`${d.type_name} ${d.number}`} description={`${d.customer_name} · ${date(d.doc_date)}${d.valid_until ? ` · válida hasta ${date(d.valid_until)}` : ''}`}
        actions={<StatusBadge status={d.status} />} />
      <Card>
        <div className="card-body row">
          {can('documentos.imprimir') && active && (
            <Button variant="primary" size="lg" busy={busy === 'print'} icon={<Printer size={22} />} onClick={print}
              disabled={!preview}>{d.prints.length ? 'Reimprimir' : 'Imprimir'}</Button>
          )}
          <Button variant="outline" busy={busy === 'file'} icon={<Download size={20} />} onClick={() => fetchFile('file')}>Excel</Button>
          {preview?.direct_print && <Button variant="outline" busy={busy === 'pdf'} icon={<FileDown size={20} />} onClick={() => fetchFile('pdf')}>PDF</Button>}
          {can('documentos.crear') && active && (
            <Button variant="outline" icon={<Pencil size={20} />} onClick={() => navigate(`/vender/documentos/${id}/editar`)}>Editar</Button>
          )}
          {can('ventas.vender') && active && (
            <Button variant="outline" icon={<ShoppingCart size={20} />} onClick={() => navigate('/vender', { state: { fromDocument: d } })}>Vender</Button>
          )}
          {can('documentos.anular') && active && (
            <Button variant="ghost" icon={<Ban size={20} />} onClick={() => setVoiding(true)}>Anular</Button>
          )}
        </div>
        {preview && (
          <div className="card-body" style={{ paddingTop: 0 }}>
            <p className="muted">
              {preview.direct_print
                ? `Se imprime directamente en «${preview.printer || 'la impresora predeterminada del tipo'}» con la configuración de página del tipo de documento.`
                : 'Este equipo no tiene Microsoft Excel para imprimir la plantilla directamente: se usará el diálogo de impresión del navegador.'}
            </p>
          </div>
        )}
      </Card>
      <ErrorAlert error={printError} title="No se pudo imprimir" />
      <Card title="Vista previa">
        <div className="card-body">
          {previewError ? <Alert kind="warning" title="Vista previa no disponible">{previewError.message}</Alert>
            : !preview ? <Loading label="Generando con la plantilla…" />
            : <div className="preview-sheet" dangerouslySetInnerHTML={{ __html: preview.html }} />}
          <p className="muted" style={{ marginTop: 8 }}>La vista previa muestra el contenido; el archivo Excel conserva el formato exacto de la plantilla.</p>
        </div>
      </Card>
      <div className="grid-2">
        <Card title="Totales">
          <div className="card-body">
            <dl className="dl" style={{ gridTemplateColumns: '1fr auto' }}>
              <dt>Subtotal</dt><dd className="num">{money(d.gross)}</dd>
              <dt>Descuentos</dt><dd className="num">-{money(d.discount)}</dd>
              <dt>IVA incluido</dt><dd className="num">{money(d.tax)}</dd>
              <dt>Total</dt><dd className="num"><strong>{money(d.total)}</strong></dd>
            </dl>
          </div>
        </Card>
        <Card title="Impresiones y generación">
          <div className="card-body">
            {d.prints.length ? (
              <ul>{d.prints.map((p: any) => (
                <li key={p.id}>{dateTime(p.created_at)} · {p.username} · {p.printer} · {p.status === 'ok' ? 'correcta' : `error: ${p.error}`}</li>
              ))}</ul>
            ) : <p className="muted">Aún no se ha impreso.</p>}
            <p className="muted">Generado {d.outputs.length} {d.outputs.length === 1 ? 'vez' : 'veces'}.</p>
          </div>
        </Card>
      </div>
      <ConfirmDialog open={voiding} title={`Anular ${d.number}`} danger requireReason confirmLabel="Anular documento"
        onClose={() => setVoiding(false)} onConfirm={doVoid} message="El documento quedará marcado como anulado y no podrá imprimirse ni editarse." />
    </div>
  );
}

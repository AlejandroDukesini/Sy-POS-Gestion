import { CheckCircle2, Download, FileSpreadsheet, Plus, Trash2, Upload, X } from 'lucide-react';
import { useState } from 'react';
import { ApiError, download, post, upload } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { ConfirmDialog } from '../../components/ui/Dialog';
import { Alert, ErrorAlert, Loading, StatusBadge } from '../../components/ui/Feedback';
import { Checkbox, Field, SelectField, TextField } from '../../components/ui/Form';
import { Card } from '../../components/ui/Layout';
import { DataTable } from '../../components/ui/Table';
import { useAuth } from '../../context/Auth';
import { useToast } from '../../context/Toast';
import { dateTime } from '../../lib/format';
import { useApi } from '../../lib/hooks';
import { COLUMN_TYPES } from './Columns';

interface NewColumn { header: string; name: string; data_type: string; options: string }

export function ImportExport() {
  const { notify } = useToast();
  const runs = useApi<any[]>('/imports');
  const [busy, setBusy] = useState('');
  const exportAs = async (fmt: 'xlsx' | 'csv') => {
    setBusy(fmt);
    try {
      await download(`/products/export?fmt=${fmt}`, `inventario.${fmt}`);
    } catch (err) {
      notify('danger', 'No se pudo exportar', (err as Error).message);
    } finally {
      setBusy('');
    }
  };
  return (
    <div className="stack">
      <Card title="Exportar inventario">
        <div className="card-body row">
          <Button variant="outline" busy={busy === 'xlsx'} icon={<FileSpreadsheet size={20} />} onClick={() => exportAs('xlsx')}>Descargar Excel</Button>
          <Button variant="outline" busy={busy === 'csv'} icon={<Download size={20} />} onClick={() => exportAs('csv')}>Descargar CSV</Button>
        </div>
      </Card>
      <ImportWizard onApplied={runs.reload} />
      <Card title="Importaciones recientes">
        {runs.loading && !runs.data ? <Loading /> : (
          <DataTable caption="Importaciones recientes" rows={runs.data ?? []} rowKey={(r: any) => r.id} columns={[
            { key: 'date', header: 'Fecha', render: (r: any) => dateTime(r.started_at) },
            { key: 'source', header: 'Fuente', render: (r: any) => r.source_label },
            { key: 'trigger', header: 'Origen', render: (r: any) => ({ archivo: 'Archivo subido', manual: 'Conexión (manual)', automatica: 'Conexión (automática)' } as any)[r.trigger] },
            { key: 'status', header: 'Estado', render: (r: any) => <StatusBadge status={r.status} /> },
            { key: 'user', header: 'Usuario', render: (r: any) => r.username ?? 'sistema' },
          ]} />
        )}
      </Card>
    </div>
  );
}

function ImportWizard({ onApplied }: { onApplied: () => void }) {
  const { can } = useAuth();
  const [file, setFile] = useState<File | null>(null);
  const [info, setInfo] = useState<any>(null);
  const [sheet, setSheet] = useState('');
  const [columns, setColumns] = useState<Record<string, string>>({});
  const [custom, setCustom] = useState<Record<string, string>>({});
  const [newCols, setNewCols] = useState<NewColumn[]>([]);
  const [options, setOptions] = useState({ create_missing: true, update_catalog: true, adjust_stock: false });
  const [run, setRun] = useState<any>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  const inspect = async (f: File, sheetName = '') => {
    setBusy(true);
    setError(null);
    setRun(null);
    try {
      const form = new FormData();
      form.append('file', f);
      form.append('sheet', sheetName);
      const data = await upload('/imports/inspect', form);
      setInfo(data);
      setSheet(data.sheet);
      setColumns(data.suggested_columns);
      setCustom(data.suggested_custom ?? {});
      setNewCols([]);
    } catch (err) {
      setError(err as ApiError);
      setInfo(null);
    } finally {
      setBusy(false);
    }
  };

  const preview = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append('file', file);
      const extra = [
        ...Object.entries(custom).filter(([, h]) => h).map(([id, header]) => ({ column_id: Number(id), header })),
        ...newCols.map((n) => ({ header: n.header, new: { name: n.name.trim(), data_type: n.data_type,
          options: n.data_type === 'lista' ? n.options.split(',').map((o) => o.trim()).filter(Boolean) : undefined } })),
      ];
      form.append('options', JSON.stringify({ sheet, header_row: info.header_row, columns, custom: extra, ...options }));
      setRun(await upload('/imports/preview', form));
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };

  const reset = () => {
    setFile(null);
    setInfo(null);
    setRun(null);
    setError(null);
    onApplied();
  };
  // Cada columna del archivo se puede usar una sola vez.
  const used = [...Object.values(columns), ...Object.values(custom), ...newCols.map((n) => n.header)].filter(Boolean);
  const twice = [...new Set(used.filter((h, i) => used.indexOf(h) !== i))];
  const free: string[] = (info?.headers ?? []).filter((h: string) => h && !used.includes(h) && !(info?.duplicate_headers ?? []).includes(h));
  const incomplete = newCols.some((n) => !n.header || !n.name.trim() || (n.data_type === 'lista' && !n.options.trim()));
  const headerOptions = (info?.headers ?? []).filter(Boolean).map((h: string) => ({ value: h, label: h }));
  const addColumn = (header = '') => setNewCols((c) => [...c, { header, name: header, data_type: 'texto', options: '' }]);
  const setNew = (i: number, patch: Partial<NewColumn>) => setNewCols((c) => c.map((n, j) => (j === i ? { ...n, ...patch } : n)));

  return (
    <Card title="Importar desde Excel o CSV">
      <div className="card-body stack">
        <Alert kind="info">
          Importar un archivo es una operación única: no deja una sincronización automática. Para sincronizar con una fuente
          permanente (Excel, carpeta de red, OneDrive o Google Drive) configure una conexión en Gestión › Integraciones.
        </Alert>
        <ErrorAlert error={error} />
        <Field label="Archivo (.xlsx, .xlsm o .csv)">
          {({ id }) => (
            <input id={id} className="input" type="file" accept=".xlsx,.xlsm,.csv"
              onChange={(e) => { const f = e.target.files?.[0] ?? null; setFile(f); if (f) void inspect(f); }} />
          )}
        </Field>
        {busy && <Loading label="Leyendo el archivo…" />}
        {info && !run && (
          <>
            <p><strong>{info.rows}</strong> filas · encabezados en la fila <strong>{info.header_row}</strong></p>
            {info.sheets.length > 1 && (
              <SelectField label="Hoja" value={sheet} onChange={(v) => { setSheet(v); if (file) void inspect(file, v); }}
                options={info.sheets.map((s: string) => ({ value: s, label: s }))} />
            )}
            {info.sample?.length > 0 && (
              <details open>
                <summary style={{ cursor: 'pointer', fontWeight: 700, minHeight: 44, display: 'flex', alignItems: 'center' }}>
                  Primeras filas del archivo</summary>
                <div className="table-wrap" style={{ maxHeight: 280, overflow: 'auto' }}>
                  <table className="table">
                    <caption className="sr-only">Primeras filas del archivo</caption>
                    <thead><tr>{info.headers.map((h: string, i: number) => <th key={i} scope="col">{h || <span className="muted">(sin nombre)</span>}</th>)}</tr></thead>
                    <tbody>{info.sample.map((row: any[], i: number) => (
                      <tr key={i}>{info.headers.map((_: string, j: number) => <td key={j}><span className="cell-clip">{String(row[j] ?? '')}</span></td>)}</tr>))}
                    </tbody>
                  </table>
                </div>
              </details>
            )}
            {info.duplicate_headers?.length > 0 && (
              <Alert kind="warning" title="Encabezados repetidos">
                {info.duplicate_headers.join(', ')}: aparece(n) más de una vez. Esas columnas no se pueden importar; renómbrelas en el archivo.
              </Alert>
            )}
            <fieldset>
              <legend>Correspondencia de columnas</legend>
              <div className="form-grid">
                {Object.entries(info.fields as Record<string, string>).map(([key, label]) => (
                  <SelectField key={key} label={label} required={info.required.includes(key)} value={columns[key] ?? ''}
                    onChange={(v) => setColumns((c) => ({ ...c, [key]: v }))} placeholder="(no importar)"
                    options={info.headers.filter(Boolean).map((h: string) => ({ value: h, label: h }))} />
                ))}
              </div>
            </fieldset>
            {info.custom_columns?.length > 0 && (
              <fieldset>
                <legend>Columnas adicionales del inventario</legend>
                <div className="custom-map">
                  {info.custom_columns.map((c: any) => (
                    <SelectField key={c.id} label={c.name} value={custom[c.id] ?? ''} placeholder="(no importar)" options={headerOptions}
                      onChange={(v) => setCustom((x) => ({ ...x, [c.id]: v }))}
                      hint={`${COLUMN_TYPES[c.data_type]}${c.required ? ` · obligatoria (si no se importa: «${c.default_value}»)` : ''}`} />
                  ))}
                </div>
              </fieldset>
            )}
            {info.can_create_columns && (
              <fieldset className="stack">
                <legend>Agregar columnas nuevas</legend>
                <p className="muted" style={{ margin: 0 }}>Puede agregar al inventario columnas que vienen en el archivo (por ejemplo, Marca o
                  Ubicación). Se crean solo al aplicar la importación: si la cancela, no queda nada.</p>
                {newCols.map((n, i) => (
                  <div key={i} className="new-column-row">
                    <SelectField label="Columna del archivo" value={n.header} placeholder="Elija…" options={headerOptions}
                      onChange={(v) => setNew(i, { header: v, name: n.name || v })} required />
                    <TextField label="Nombre en el inventario" value={n.name} maxLength={60} required onChange={(v) => setNew(i, { name: v })} />
                    <SelectField label="Tipo de dato" value={n.data_type} onChange={(v) => setNew(i, { data_type: v })}
                      options={Object.entries(COLUMN_TYPES).map(([value, label]) => ({ value, label }))} />
                    {n.data_type === 'lista' && <TextField label="Opciones (separadas por coma)" value={n.options} required
                      onChange={(v) => setNew(i, { options: v })} />}
                    <Button variant="ghost" icon={<X size={18} />} onClick={() => setNewCols((c) => c.filter((_, j) => j !== i))}>Quitar</Button>
                  </div>
                ))}
                <div className="row" style={{ gap: 8 }}>
                  {free.slice(0, 12).map((h) => (
                    <Button key={h} size="sm" variant="outline" icon={<Plus size={16} />} onClick={() => addColumn(h)}>{h}</Button>))}
                  <Button size="sm" icon={<Plus size={16} />} onClick={() => addColumn()}>Agregar columna</Button>
                </div>
              </fieldset>
            )}
            {twice.length > 0 && <Alert kind="danger">Cada columna del archivo se puede usar una sola vez. Repetida(s): {twice.join(', ')}.</Alert>}
            <fieldset>
              <legend>Qué hacer</legend>
              <Checkbox label="Crear los productos que no existen" checked={options.create_missing}
                onChange={(v) => setOptions((o) => ({ ...o, create_missing: v }))} />
              <Checkbox label="Actualizar descripción, precios y datos del catálogo" checked={options.update_catalog}
                onChange={(v) => setOptions((o) => ({ ...o, update_catalog: v }))} />
              {can('inventario.movimientos') && (
                <Checkbox label="Ajustar existencias a las del archivo" checked={options.adjust_stock}
                  onChange={(v) => setOptions((o) => ({ ...o, adjust_stock: v }))}
                  hint="Cada diferencia se registra como movimiento de conciliación. Si no lo marca, las diferencias solo se informan." />
              )}
            </fieldset>
            <div className="form-actions">
              <Button onClick={reset}>Cancelar</Button>
              <Button variant="primary" busy={busy} icon={<Upload size={20} />} onClick={preview} disabled={twice.length > 0 || incomplete}>
                Ver vista previa</Button>
            </div>
          </>
        )}
        {run && <ImportPreview run={run} onDone={reset} />}
      </div>
    </Card>
  );
}

const SECTION_LABELS: Record<string, string> = {
  new: 'Productos nuevos', changes: 'Cambios en el catálogo', stock_differences: 'Diferencias de existencias',
  cost_differences: 'Diferencias de costo (solo informativas)', invalid: 'Filas con errores', duplicates: 'Códigos repetidos en el archivo',
};

/** Vista previa común (archivo subido o conexión): conteos, detalle por fila y aplicar / descartar. */
export function ImportPreview({ run, onDone }: { run: any; onDone: () => void }) {
  const { notify } = useToast();
  const [current, setCurrent] = useState(run);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const s = current.summary;
  const counts = s.counts ?? {};
  const pending = current.status === 'vista_previa';

  const apply = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await post(`/imports/${current.id}/apply`);
      setCurrent(result);
      const a = result.summary.applied;
      notify('success', 'Importación aplicada', `${a.created} nuevos, ${a.updated} actualizados, ${a.stock_adjusted} ajustes.`);
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
      setConfirm(false);
    }
  };
  const discard = async () => {
    await post(`/imports/${current.id}/discard`).catch(() => undefined);
    onDone();
  };

  return (
    <div className="stack">
      <div className="row-between">
        <h3>Vista previa · {s.file}</h3>
        <StatusBadge status={current.status} />
      </div>
      <ErrorAlert error={error} />
      <div className="metrics">
        {Object.entries({ new: 'Nuevos', changes: 'Con cambios', stock_differences: 'Existencias distintas', invalid: 'Con errores',
          duplicates: 'Repetidos', unchanged: 'Sin cambios' }).map(([k, label]) => (
          <div key={k} className="card metric"><span className="metric-label">{label}</span><span className="metric-value">{counts[k] ?? 0}</span></div>
        ))}
      </div>
      {(s.warnings ?? []).map((w: string) => <Alert key={w} kind="warning">{w}</Alert>)}
      {s.will?.new_columns?.length > 0 && pending && (
        <Alert kind="info" title="Columnas nuevas">Al aplicar se agregarán al inventario: {s.will.new_columns.join(', ')}.</Alert>)}
      {counts.stock_differences > 0 && (
        <Alert kind={s.will.adjust_stock ? 'warning' : 'info'} title="Existencias">
          {s.will.adjust_stock
            ? 'Las diferencias se aplicarán como movimientos de conciliación (con fecha, usuario y asiento contable).'
            : 'Las diferencias solo se informan: las existencias de POS-PY no cambian.'}
        </Alert>
      )}
      {Object.keys(SECTION_LABELS).map((key) => (s[key]?.length ? (
        <details key={key}>
          <summary style={{ cursor: 'pointer', fontWeight: 700, minHeight: 44, display: 'flex', alignItems: 'center' }}>
            {SECTION_LABELS[key]} ({counts[key === 'changes' ? 'changes' : key] ?? s[key].length})
          </summary>
          <div className="table-wrap" style={{ maxHeight: 320, overflowY: 'auto' }}>
            <table className="table">
              <tbody>
                {s[key].slice(0, 200).map((r: any, i: number) => (
                  <tr key={i}>
                    <td className="nowrap">Fila {r.row}</td>
                    <td><strong>{r.code || '(sin código)'}</strong></td>
                    <td>{describe(key, r)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ) : null))}
      {s.applied && (
        <Alert kind={s.applied.errors.length ? 'warning' : 'success'} title="Resultado">
          {s.applied.columns_created?.length > 0 && <>Columnas agregadas: {s.applied.columns_created.join(', ')} · </>}
          {s.applied.created} creados · {s.applied.updated} actualizados · {s.applied.stock_adjusted} existencias ajustadas ·
          {' '}{s.applied.stock_reported} diferencias informadas · {s.applied.skipped} omitidos · {s.applied.errors.length} errores
          {s.applied.errors.length > 0 && <ul>{s.applied.errors.slice(0, 10).map((e: any) => <li key={e.row}>Fila {e.row} ({e.code}): {e.error}</li>)}</ul>}
        </Alert>
      )}
      <div className="form-actions">
        {pending ? (
          <>
            <Button icon={<Trash2 size={20} />} onClick={discard}>Descartar</Button>
            <Button variant="primary" icon={<CheckCircle2 size={20} />} busy={busy} onClick={() => setConfirm(true)}
              disabled={!counts.new && !counts.changes && !(counts.stock_differences && s.will.adjust_stock)}>
              Aplicar cambios
            </Button>
          </>
        ) : <Button variant="primary" onClick={onDone}>Terminar</Button>}
      </div>
      <ConfirmDialog open={confirm} title="Aplicar importación" confirmLabel="Aplicar" busy={busy} onClose={() => setConfirm(false)}
        onConfirm={apply} message={`Se aplicarán ${s.will.create ? counts.new : 0} productos nuevos, ${s.will.update_catalog ? counts.changes : 0} cambios de catálogo`
          + `${s.will.adjust_stock ? ` y ${counts.stock_differences} ajustes de existencias` : ''}. Las filas con errores se omiten.`} />
    </div>
  );
}

function describe(key: string, r: any): string {
  if (key === 'new') return [`${r.description} · precio ${r.price} · cantidad ${r.stock}`,
    ...Object.entries(r.custom ?? {}).map(([k, v]) => `${k}: ${v}`)].join(' · ');
  if (key === 'changes') return Object.entries(r.fields).map(([f, v]: [string, any]) => `${f}: ${v.antes ?? '—'} → ${v.despues}`).join(' · ');
  if (key === 'stock_differences') return `POS-PY ${r.local} · fuente ${r.external} (diferencia ${r.difference})`;
  if (key === 'cost_differences') return `POS-PY ${r.local} · fuente ${r.external}`;
  if (key === 'invalid') return r.errors.join(' ');
  return 'El código aparece más de una vez en el archivo.';
}

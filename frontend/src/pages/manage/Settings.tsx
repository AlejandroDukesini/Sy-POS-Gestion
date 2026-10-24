import { ImageUp, Printer, Save, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { ApiError, del, get, post, put, upload } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { ConfirmDialog } from '../../components/ui/Dialog';
import { Alert, ErrorAlert, Loading } from '../../components/ui/Feedback';
import { Checkbox, Field, NumberField, SelectField, TextField } from '../../components/ui/Form';
import { Card } from '../../components/ui/Layout';
import { DataTable } from '../../components/ui/Table';
import { useAuth } from '../../context/Auth';
import { useToast } from '../../context/Toast';
import { useApi } from '../../lib/hooks';
import { ManageBack } from './ManageRoutes';

const CHOICE_LABELS: Record<string, string> = {
  escpos: 'Directa a la impresora (ESC/POS)', navegador: 'Diálogo del navegador', '32': '58 mm (32 caracteres)',
  '42': '76 mm (42 caracteres)', '48': '80 mm (48 caracteres)',
};

/** Formulario generado desde el esquema de configuración del backend (mismos límites y validación). */
export function SettingsSection({ section, title, exclude = [] }: { section: string; title?: string; exclude?: string[] }) {
  const { notify } = useToast();
  const { refresh } = useAuth();
  const data = useApi('/settings');
  const [values, setValues] = useState<Record<string, any> | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (data.data) setValues(data.data.values[section]);
  }, [data.data, section]);
  if (data.loading || !values) return <Loading />;
  const schema = data.data.schema[section];
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const saved = await put(`/settings/${section}`, values);
      setValues(saved);
      notify('success', 'Configuración guardada', schema.label);
      if (section === 'empresa') await refresh();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  const fe = error?.fields ?? {};
  return (
    <Card title={title ?? schema.label}>
      <div className="card-body stack">
        <ErrorAlert error={error} />
        <div className="form-grid">
          {Object.entries(schema.fields as Record<string, any>).filter(([k]) => !exclude.includes(k)).map(([key, f]) => {
            const set = (v: any) => setValues((s) => ({ ...s!, [key]: v }));
            if (f.kind === 'bool') return <Checkbox key={key} label={f.label} checked={Boolean(values[key])} onChange={set} />;
            if (f.kind === 'choice') {
              return <SelectField key={key} label={f.label} value={String(values[key])} error={fe[key]}
                onChange={(v) => set(typeof f.default === 'number' ? Number(v) : v)}
                options={f.choices.map((c: any) => ({ value: String(c), label: CHOICE_LABELS[String(c)] ?? String(c) }))} />;
            }
            if (f.kind === 'int') {
              return <NumberField key={key} label={f.label} value={String(values[key])} error={fe[key]} hint={`Entre ${f.min} y ${f.max}.`}
                onChange={(v) => set(v === '' ? '' : Number(v))} />;
            }
            if (f.kind === 'color') {
              return (
                <Field key={key} label={f.label} error={fe[key]}>
                  {({ id }) => <input id={id} type="color" className="input" style={{ padding: 4 }} value={values[key]} onChange={(e) => set(e.target.value)} />}
                </Field>
              );
            }
            return <TextField key={key} label={f.label} value={values[key] ?? ''} onChange={set} error={fe[key]} maxLength={f.max_len} />;
          })}
        </div>
        <div className="form-actions"><Button variant="primary" busy={busy} icon={<Save size={20} />} onClick={save}>Guardar</Button></div>
      </div>
    </Card>
  );
}

export function CompanyPage() {
  const { notify } = useToast();
  const [version, setVersion] = useState(0);
  const [hasLogo, setHasLogo] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  useEffect(() => {
    get('/company/public').then((c) => setHasLogo(c.has_logo)).catch(() => undefined);
  }, [version]);
  const onFile = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    try {
      const form = new FormData();
      form.append('file', file);
      await upload('/company/logo', form);
      notify('success', 'Logotipo actualizado', 'Se muestra en la pantalla de ingreso y en la barra lateral.');
      setVersion((v) => v + 1);
    } catch (err) {
      notify('danger', 'No se pudo subir el logotipo', (err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    await del('/company/logo');
    setConfirm(false);
    setVersion((v) => v + 1);
  };
  return (
    <div className="stack">
      <ManageBack title="Empresa" description="Estos datos aparecen en los documentos y comprobantes." />
      <Card title="Logotipo">
        <div className="card-body row">
          <div className="logo-slot" style={{ width: 220, fontSize: '1rem', aspectRatio: '4 / 3', color: 'var(--text-muted)' }}>
            {hasLogo ? <img src={`/api/company/logo?v=${version}`} alt="Logotipo actual" /> : <span>Aquí tu logo</span>}
          </div>
          <div className="stack">
            <Field label="Subir logotipo (PNG, JPG o WEBP, máximo 2 MB)">
              {({ id }) => <input id={id} className="input" type="file" accept="image/png,image/jpeg,image/webp" disabled={busy}
                onChange={(e) => void onFile(e.target.files?.[0])} />}
            </Field>
            {hasLogo && <Button variant="ghost" icon={<Trash2 size={20} />} onClick={() => setConfirm(true)}>Quitar logotipo</Button>}
            <p className="muted"><ImageUp size={16} aria-hidden /> Para el icono de la aplicación de escritorio vea el README (Escritorio › Icono).</p>
          </div>
        </div>
      </Card>
      <SettingsSection section="empresa" title="Datos de la empresa" />
      <ConfirmDialog open={confirm} title="Quitar logotipo" danger confirmLabel="Quitar" onClose={() => setConfirm(false)} onConfirm={remove}
        message="La pantalla de ingreso volverá a mostrar «Aquí tu logo»." />
    </div>
  );
}

export function PrintingPage() {
  const { notify } = useToast();
  const printers = useApi('/printing/printers');
  const jobs = useApi<any[]>('/printing/jobs');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const test = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await post('/printing/test', {});
      notify('success', 'Prueba enviada', `Impresora: ${r.printer}`);
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
      jobs.reload();
    }
  };
  return (
    <div className="stack">
      <ManageBack title="Impresión" description="Comprobantes de venta en la impresora térmica DIGITALPOS (u otra compatible ESC/POS)." />
      <Card title="Impresoras de este equipo">
        <div className="card-body stack">
          {printers.loading ? <Loading /> : printers.data?.available ? (
            <>
              <ul>{printers.data.printers.map((p: any) => (
                <li key={p.name}><strong>{p.name}</strong> · {p.driver} · {p.port}{p.name === printers.data.default ? ' (predeterminada)' : ''}</li>
              ))}</ul>
              {!printers.data.printers.some((p: any) => /digitalpos/i.test(p.name)) && (
                <Alert kind="warning" title="DIGITALPOS no está instalada">
                  Instale el controlador de la impresora en Windows y escriba su nombre exacto abajo. Mientras tanto puede usar el modo
                  «Diálogo del navegador».
                </Alert>
              )}
            </>
          ) : <Alert kind="info">{printers.data?.reason}</Alert>}
          <ErrorAlert error={error} title="La prueba falló" />
          <div><Button busy={busy} icon={<Printer size={20} />} onClick={test}>Imprimir página de prueba</Button></div>
        </div>
      </Card>
      <SettingsSection section="impresion" title="Comprobante de venta" />
      <Alert kind="info">
        La impresora, el papel, la orientación, los márgenes y la escala de cotizaciones y órdenes se configuran en cada tipo de
        documento (Gestión › Tipos de documento).
      </Alert>
      <Card title="Últimas impresiones">
        <DataTable caption="Trabajos de impresión" rows={jobs.data ?? []} rowKey={(j: any) => j.id} columns={[
          { key: 'd', header: 'Fecha', render: (j: any) => new Date(j.created_at).toLocaleString('es-CO') },
          { key: 't', header: 'Documento', render: (j: any) => j.target_label || j.target_type },
          { key: 'p', header: 'Impresora', render: (j: any) => j.printer },
          { key: 'u', header: 'Usuario', render: (j: any) => j.username },
          { key: 's', header: 'Resultado', render: (j: any) => (j.status === 'ok' ? 'Correcto' : `Error: ${j.error}`) },
        ]} />
      </Card>
    </div>
  );
}

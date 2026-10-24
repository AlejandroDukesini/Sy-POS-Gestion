import { RotateCcw, Save } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '../components/ui/Button';
import { ConfirmDialog } from '../components/ui/Dialog';
import { Alert } from '../components/ui/Feedback';
import { Checkbox, SelectField } from '../components/ui/Form';
import { Card, PageHeader } from '../components/ui/Layout';
import { useAuth } from '../context/Auth';
import { usePrefs } from '../context/Prefs';
import { useToast } from '../context/Toast';
import { useApi } from '../lib/hooks';
import { DEFAULT_PREFS, type Prefs } from '../lib/prefs';
import { MANAGE_ITEMS } from './manage/ManageRoutes';
import { PasswordForm } from './ChangePassword';

/** Configuración personal (de cada usuario) separada de la configuración global de la empresa. */
export default function SettingsPage() {
  const { prefs, preview, save, reset } = usePrefs();
  const { canAny, can } = useAuth();
  const { notify } = useToast();
  const printers = useApi(can('documentos.imprimir') || can('ventas.vender') ? '/printing/printers' : null);
  const [busy, setBusy] = useState(false);
  const [confirmDefaults, setConfirmDefaults] = useState(false);
  const resetRef = useRef(reset);
  resetRef.current = reset;
  useEffect(() => () => resetRef.current(), []);   // salir sin guardar descarta la vista previa

  const update = <K extends keyof Prefs>(key: K) => (value: Prefs[K]) => preview({ [key]: value } as Partial<Prefs>);
  const persist = async (values: Partial<Prefs> = prefs) => {
    setBusy(true);
    try {
      await save(values);
      notify('success', 'Preferencias guardadas', 'Se aplican en todos los equipos donde inicie sesión.');
    } catch (err) {
      notify('danger', 'No se pudieron guardar', (err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const adminLinks = MANAGE_ITEMS.filter((i) => ['empresa', 'parametros', 'integraciones', 'documentos', 'impresion', 'usuarios', 'seguridad', 'respaldos', 'actividad']
    .includes(i.to) && canAny(...i.perms));

  return (
    <div className="stack">
      <PageHeader title="Configuración" description="Sus preferencias personales. Solo afectan su cuenta." />
      <Card title="Apariencia y accesibilidad">
        <div className="card-body stack">
          <div className="form-grid">
            <SelectField label="Tema" value={prefs.theme} onChange={(v) => update('theme')(v as Prefs['theme'])} options={[
              { value: 'light', label: 'Claro' }, { value: 'dark', label: 'Oscuro' }, { value: 'system', label: 'Según el sistema' }]} />
            <SelectField label="Tamaño del texto" value={String(prefs.font_size)} onChange={(v) => update('font_size')(Number(v) as Prefs['font_size'])} options={[
              { value: 16, label: 'Normal (16 px)' }, { value: 18, label: 'Grande (18 px)' }, { value: 20, label: 'Muy grande (20 px)' },
              { value: 22, label: 'Extra grande (22 px)' }]} />
            <SelectField label="Densidad" value={prefs.density} onChange={(v) => update('density')(v as Prefs['density'])} options={[
              { value: 'comoda', label: 'Cómoda (más espacio)' }, { value: 'compacta', label: 'Compacta' }]} />
            <SelectField label="Animaciones" value={prefs.motion} onChange={(v) => update('motion')(v as Prefs['motion'])} options={[
              { value: 'system', label: 'Según el sistema' }, { value: 'reduced', label: 'Reducidas' }]} />
            <SelectField label="Menú lateral" value={prefs.sidebar} onChange={(v) => update('sidebar')(v as Prefs['sidebar'])} options={[
              { value: 'expanded', label: 'Con nombres' }, { value: 'collapsed', label: 'Solo iconos' }]} />
            {printers.data?.available && (
              <SelectField label="Impresora preferida" value={prefs.preferred_printer} onChange={update('preferred_printer')} placeholder="La del tipo de documento"
                options={printers.data.printers.map((p: any) => ({ value: p.name, label: p.name }))} />
            )}
          </div>
          <Checkbox label="Alto contraste (bordes y textos más marcados)" checked={prefs.high_contrast} onChange={update('high_contrast')} />
          <Checkbox label="Subrayar los enlaces" checked={prefs.underline_links} onChange={update('underline_links')} />
          <Alert kind="info">Los cambios se ven de inmediato como vista previa. Pulse «Guardar» para conservarlos.</Alert>
          <div className="form-actions">
            <Button icon={<RotateCcw size={20} />} onClick={() => setConfirmDefaults(true)}>Restaurar predeterminados</Button>
            <Button variant="primary" busy={busy} icon={<Save size={20} />} onClick={() => persist()}>Guardar</Button>
          </div>
        </div>
      </Card>
      <Card title="Contraseña"><div className="card-body"><PasswordForm /></div></Card>
      {adminLinks.length > 0 && (
        <Card title="Configuración de la empresa">
          <div className="card-body">
            <p className="muted" style={{ marginBottom: 12 }}>Estas opciones afectan a todos los usuarios:</p>
            <ul>{adminLinks.map((i) => <li key={i.to} style={{ margin: '8px 0' }}><Link to={`/gestion/${i.to}`}>{i.title}</Link> — {i.desc}</li>)}</ul>
          </div>
        </Card>
      )}
      <ConfirmDialog open={confirmDefaults} title="Restaurar predeterminados" confirmLabel="Restaurar" onClose={() => setConfirmDefaults(false)}
        onConfirm={() => { setConfirmDefaults(false); void persist(DEFAULT_PREFS); }} message="Se volverá al tema claro, texto de 16 px y demás valores iniciales." />
    </div>
  );
}

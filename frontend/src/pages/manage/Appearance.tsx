import { Check, ImagePlus, Monitor, RotateCcw, Save, Smartphone, Tablet, Trash2, X } from 'lucide-react';
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { ApiError, del, put, upload } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { ConfirmDialog } from '../../components/ui/Dialog';
import { Alert, Badge, ErrorAlert } from '../../components/ui/Feedback';
import { Checkbox, Field, SelectField } from '../../components/ui/Form';
import { Card, Tabs } from '../../components/ui/Layout';
import { useApi } from '../../lib/hooks';
import { useToast } from '../../context/Toast';
import { useTheme, type LoginLook } from '../../context/Theme';
import {
  COLOR_FIELDS, contrastIssues, isHex, PRESETS, previewCss, type ColorKey, type Mode, type ThemeConfig,
} from '../../lib/theme';
import { LoginVisual } from '../Login';
import { ManageBack } from './ManageRoutes';
import '../../styles/appearance.css';

/** Gestión › Apariencia del sistema: colores de toda la aplicación y pantalla de ingreso. */
export function AppearancePage() {
  const [tab, setTab] = useState<'colores' | 'ingreso'>('colores');
  return (
    <div className="stack">
      <ManageBack title="Apariencia del sistema"
        description="Colores de todo el POS y pantalla de ingreso del negocio. Los cambios se ven al instante y se guardan para todos los equipos." />
      <Tabs label="Apariencia" value={tab} onChange={setTab}
        tabs={[{ value: 'colores', label: 'Colores del sistema' }, { value: 'ingreso', label: 'Pantalla de ingreso' }]} />
      {tab === 'colores' ? <ThemeEditor /> : <LoginEditor />}
    </div>
  );
}

// ================================================================== colores
const same = (a: ThemeConfig, b: ThemeConfig) => JSON.stringify(a) === JSON.stringify(b);

function ThemeEditor() {
  const { appearance, preview, reload } = useTheme();
  const { notify } = useToast();
  const saved = appearance.theme;
  const [draft, setDraft] = useState<ThemeConfig>(saved);
  const [mode, setMode] = useState<Mode>(() => (document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [confirming, setConfirming] = useState(false);
  const dirty = !same(draft, saved);
  const issues = useMemo(() => contrastIssues(draft), [draft]);
  const critical = issues.filter((i) => i.level === 'critico');

  useEffect(() => { setDraft(saved); }, [saved]);
  // Vista previa en TODA la aplicación mientras se edita; al salir sin guardar se vuelve al tema guardado.
  useEffect(() => { preview(dirty ? draft : null); }, [draft, dirty, preview]);
  useEffect(() => () => preview(null), [preview]);

  const setColor = (key: ColorKey, value: string) =>
    setDraft((d) => ({ ...d, enabled: true, [mode]: { ...d[mode], [key]: value.toLowerCase() } }));
  const choose = (key: string) => setDraft({ enabled: true, palette: key, light: { ...PRESETS[key].light }, dark: { ...PRESETS[key].dark } });
  const base = PRESETS[draft.palette] ?? PRESETS.corporate;
  const modified = draft.enabled && (!same({ ...draft, light: base.light, dark: base.dark }, draft));

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await put('/appearance/theme', draft);
      await reload();
      notify('success', 'Apariencia guardada', draft.enabled ? 'Todos los equipos verán estos colores.' : 'Se usan los colores de fábrica.');
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  };

  return (
    <div className="stack">
      <style>{previewCss(draft)}</style>
      <Card>
        <div className="card-body stack">
          <Checkbox label="Usar el tema personalizado del negocio" checked={draft.enabled}
            onChange={(v) => setDraft((d) => ({ ...d, enabled: v }))} />
          {!draft.enabled && <p className="muted">Se usan los colores de fábrica del POS. Elija una paleta o un color para empezar.</p>}
          <div>
            <h3 className="appearance-h">Paletas predefinidas <span className="muted">(puntos de partida: luego puede cambiar cualquier color)</span></h3>
            <div className="palette-grid" role="group" aria-label="Paletas predefinidas">
              {Object.entries(PRESETS).map(([key, p]) => (
                <button key={key} type="button" className="preset palette-card" aria-pressed={draft.enabled && draft.palette === key}
                  onClick={() => choose(key)}>
                  <span className="swatches" aria-hidden>
                    {(['primary', 'secondary', 'accent', 'nav', 'background'] as ColorKey[]).map((k) => (
                      <span key={k} className="swatch" style={{ background: p[mode][k] }} />))}
                  </span>
                  <span>{p.label}</span>
                </button>
              ))}
            </div>
            {modified && <p className="muted">Basado en «{base.label}», con colores modificados.</p>}
          </div>
        </div>
      </Card>

      <div className="appearance-layout">
        <Card title="Colores">
          <div className="card-body stack">
            <div className="segmented" role="radiogroup" aria-label="Modo que se edita">
              {(['light', 'dark'] as Mode[]).map((m) => (
                <button key={m} type="button" role="radio" aria-checked={mode === m} className={`seg${mode === m ? ' on' : ''}`}
                  onClick={() => setMode(m)}>{m === 'light' ? 'Modo claro' : 'Modo oscuro'}</button>
              ))}
            </div>
            <p className="muted">Cada persona elige claro u oscuro en sus preferencias; aquí se definen los colores de los dos modos.
              Cambiar de modo no borra los colores del otro.</p>
            <div className="color-list">
              {COLOR_FIELDS.map((f) => (
                <ColorRow key={`${mode}-${f.key}`} label={f.label} hint={f.hint} value={draft[mode][f.key]}
                  onChange={(v) => setColor(f.key, v)} />
              ))}
            </div>
          </div>
        </Card>
        <div className="stack">
          <Card title="Vista previa">
            <div className="card-body stack">
              <ThemePreview mode={mode} />
              <p className="muted">Toda la aplicación (también el menú de la izquierda) ya muestra estos colores mientras edita. Nada se guarda
                hasta pulsar «Aplicar cambios».</p>
            </div>
          </Card>
          <Card title="Contraste y legibilidad">
            <div className="card-body stack">
              {issues.length === 0 ? <Alert kind="success">Todas las combinaciones cumplen el contraste recomendado (WCAG 2.1 AA).</Alert> : (
                <ul className="issue-list" aria-label="Combinaciones con poco contraste">
                  {issues.map((i) => (
                    <li key={`${i.mode}-${i.message}`}>
                      <Badge kind={i.level === 'critico' ? 'danger' : 'warning'}>{i.level === 'critico' ? 'Ilegible' : 'Bajo'}</Badge>{' '}
                      {i.mode === 'light' ? 'Claro' : 'Oscuro'} · {i.message}: {String(i.ratio).replace('.', ',')}:1
                      (recomendado {i.message.startsWith('Bordes') ? '3' : '4,5'}:1)
                    </li>
                  ))}
                </ul>
              )}
              <p className="muted">El texto sobre botones, menú y avisos se elige automáticamente para que siempre se lea.
                Si algo quedara ilegible, abra el POS con <code>?tema=original</code> al final de la dirección para ver los colores de fábrica.</p>
            </div>
          </Card>
        </div>
      </div>

      <ErrorAlert error={error} />
      <div className="appearance-actions">
        {dirty && <span className="muted">Cambios sin guardar</span>}
        <Button icon={<RotateCcw size={18} />} onClick={() => setDraft((d) => ({ ...d, enabled: true, light: { ...base.light }, dark: { ...base.dark } }))}>
          Restablecer paleta
        </Button>
        <Button icon={<X size={18} />} disabled={!dirty} onClick={() => setDraft(saved)}>Cancelar</Button>
        <Button variant="primary" busy={busy} icon={<Check size={18} />} disabled={!dirty}
          onClick={() => (critical.length ? setConfirming(true) : save())}>Aplicar cambios</Button>
      </div>
      <ConfirmDialog open={confirming} title="Hay textos que no se leen bien" confirmLabel="Guardar de todos modos" busy={busy}
        message={`${critical.length} combinación(es) quedan casi ilegibles (por ejemplo: ${critical[0]?.message.toLowerCase()}). ¿Guardar igualmente?`}
        onClose={() => setConfirming(false)} onConfirm={save} />
    </div>
  );
}

function ColorRow({ label, hint, value, onChange }: { label: string; hint: string; value: string; onChange: (v: string) => void }) {
  const [text, setText] = useState(value.toUpperCase());
  useEffect(() => setText(value.toUpperCase()), [value]);
  const valid = isHex(text);
  return (
    <div className="color-row">
      <input type="color" value={value} aria-label={`${label}: selector`} onChange={(e) => onChange(e.target.value)} />
      <Field label={label} hint={hint} error={valid ? undefined : 'Use el formato #RRGGBB.'}>
        {({ id, describedBy, invalid }) => (
          <input id={id} className="input color-hex" value={text} maxLength={7} aria-describedby={describedBy} aria-invalid={invalid || undefined}
            spellCheck={false} onChange={(e) => {
              const v = e.target.value.startsWith('#') ? e.target.value : `#${e.target.value}`;
              setText(v.toUpperCase());
              if (isHex(v)) onChange(v);
            }} />
        )}
      </Field>
    </div>
  );
}

/** Componentes representativos con los colores del modo elegido (sin depender del modo de quien edita). */
function ThemePreview({ mode }: { mode: Mode }) {
  return (
    <div className="theme-preview" data-mode={mode} data-testid="theme-preview">
      <nav className="tp-nav" aria-label="Menú de ejemplo">
        <span className="tp-nav-item active">Vender</span><span className="tp-nav-item">Inventario</span><span className="tp-nav-item">Finanzas</span>
      </nav>
      <div className="tp-body">
        <div className="tp-card">
          <strong>Venta V-000128</strong>
          <span className="tp-muted">Cliente: Taller Ruiz · hoy 10:42</span>
          <input className="input" readOnly value="Filtro de aceite" aria-label="Campo de ejemplo" />
          <div className="row" style={{ gap: 6 }}>
            <span className="btn btn-primary btn-sm">Cobrar</span>
            <span className="btn btn-secondary btn-sm">Secundario</span>
            <span className="btn btn-outline btn-sm">Cancelar</span>
          </div>
        </div>
        <div className="alert alert-success">Venta registrada.</div>
        <div className="alert alert-warning">Existencias bajas.</div>
        <div className="alert alert-danger">No se pudo imprimir.</div>
        <table className="table tp-table">
          <thead><tr><th>Producto</th><th>Estado</th></tr></thead>
          <tbody>
            <tr><td>Martillo</td><td><span className="badge badge-success">Activo</span></td></tr>
            <tr className="is-selected"><td>Taladro</td><td><span className="badge badge-info">Nuevo</span></td></tr>
          </tbody>
        </table>
        <a href="#preview" onClick={(e) => e.preventDefault()}>Enlace de ejemplo</a>
      </div>
    </div>
  );
}

// ================================================================== pantalla de ingreso
const POSITIONS: [string, string][] = [['top-left', 'Arriba a la izquierda'], ['top-center', 'Arriba al centro'], ['top-right', 'Arriba a la derecha'],
  ['center-left', 'Centro a la izquierda'], ['center', 'Centro'], ['center-right', 'Centro a la derecha'],
  ['bottom-left', 'Abajo a la izquierda'], ['bottom-center', 'Abajo al centro'], ['bottom-right', 'Abajo a la derecha']];
const FILE_LIMITS = { fondo: 6, logotipo: 2 };

function LoginEditor() {
  const { appearance, reload } = useTheme();
  const { notify } = useToast();
  const company = useApi<{ name: string; has_logo: boolean }>('/company/public');
  const saved = appearance.login;
  const [draft, setDraft] = useState<LoginLook>(saved);
  const [device, setDevice] = useState<'desktop' | 'tablet' | 'phone'>('desktop');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState<ApiError | null>(null);
  const [removing, setRemoving] = useState<'fondo' | 'logotipo' | null>(null);
  const bgInput = useRef<HTMLInputElement>(null);
  const logoInput = useRef<HTMLInputElement>(null);
  const settings = (l: LoginLook) => JSON.stringify({ background: l.background, logo: l.logo });
  const dirty = settings(draft) !== settings(saved);

  useEffect(() => {
    setDraft((d) => ({ ...saved, background: dirty ? d.background : saved.background, logo: dirty ? d.logo : saved.logo }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [saved]);

  const setBg = (patch: Partial<LoginLook['background']>) => setDraft((d) => ({ ...d, background: { ...d.background, ...patch } }));
  const setLogo = (patch: Partial<LoginLook['logo']>) => setDraft((d) => ({ ...d, logo: { ...d.logo, ...patch } }));

  const sendFile = async (kind: 'fondo' | 'logotipo', file: File | undefined) => {
    if (!file) return;
    setError(null);
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
      setError(new ApiError(422, 'Formato no admitido', 'Use una imagen PNG, JPG o WEBP (no se admite SVG).'));
      return;
    }
    if (file.size > FILE_LIMITS[kind] * 1024 * 1024) {
      setError(new ApiError(422, 'Imagen demasiado grande', `Máximo ${FILE_LIMITS[kind]} MB.`));
      return;
    }
    setBusy(kind);
    try {
      const form = new FormData();
      form.append('file', file);
      await upload(`/appearance/login/${kind}`, form);
      await reload();
      notify('success', kind === 'fondo' ? 'Imagen de fondo actualizada' : 'Logotipo actualizado');
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy('');
    }
  };
  const remove = async () => {
    const kind = removing!;
    setRemoving(null);
    setBusy(kind);
    try {
      await del(`/appearance/login/${kind}`);
      await reload();
      notify('success', kind === 'fondo' ? 'Imagen de fondo eliminada' : 'Logotipo eliminado');
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy('');
    }
  };
  const save = async () => {
    setBusy('save');
    setError(null);
    try {
      await put('/appearance/login', { background: draft.background, logo: draft.logo });
      await reload();
      notify('success', 'Pantalla de ingreso guardada');
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy('');
    }
  };
  const bg = draft.background;
  const lg = draft.logo;
  return (
    <div className="stack">
      <div className="appearance-layout">
        <div className="stack">
          <Card title="Imagen de fondo">
            <div className="card-body stack">
              <div className="row" style={{ gap: 8 }}>
                <Button icon={<ImagePlus size={18} />} busy={busy === 'fondo'} onClick={() => bgInput.current?.click()}>
                  {draft.has_background ? 'Reemplazar imagen' : 'Seleccionar imagen'}</Button>
                {draft.has_background && <Button variant="ghost" icon={<Trash2 size={18} />} onClick={() => setRemoving('fondo')}>Eliminar imagen</Button>}
              </div>
              <input ref={bgInput} type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" aria-label="Archivo de imagen de fondo"
                onChange={(e) => { void sendFile('fondo', e.target.files?.[0]); e.target.value = ''; }} />
              <p className="muted">PNG, JPG o WEBP, hasta 6 MB y 8000 × 8000 px. Llena el panel sin deformarse.</p>
              <SelectField label="Ajuste" value={bg.fit} onChange={(v) => setBg({ fit: v as 'cover' })}
                options={[{ value: 'cover', label: 'Cubrir todo el panel (recorta los bordes)' }, { value: 'contain', label: 'Mostrar la imagen completa' }]} />
              <Range label="Posición horizontal" value={bg.pos_x} min={0} max={100} unit="%" onChange={(v) => setBg({ pos_x: v })} />
              <Range label="Posición vertical" value={bg.pos_y} min={0} max={100} unit="%" onChange={(v) => setBg({ pos_y: v })} />
              <Range label="Zoom" value={bg.zoom} min={100} max={300} unit="%" onChange={(v) => setBg({ zoom: v })} />
              <Range label="Oscurecimiento" value={bg.darken} min={0} max={80} unit="%" onChange={(v) => setBg({ darken: v })} />
              <div className="row" style={{ gap: 12, alignItems: 'flex-end' }}>
                <label className="color-inline">Color de superposición
                  <input type="color" value={bg.overlay_color} onChange={(e) => setBg({ overlay_color: e.target.value })} />
                </label>
                <div className="grow"><Range label="Opacidad de la superposición" value={bg.overlay_opacity} min={0} max={90} unit="%"
                  onChange={(v) => setBg({ overlay_opacity: v })} /></div>
              </div>
            </div>
          </Card>
          <Card title="Logotipo del establecimiento">
            <div className="card-body stack">
              <div className="row" style={{ gap: 8 }}>
                <Button icon={<ImagePlus size={18} />} busy={busy === 'logotipo'} onClick={() => logoInput.current?.click()}>
                  {draft.has_logo ? 'Reemplazar logotipo' : 'Seleccionar logotipo'}</Button>
                {draft.has_logo && <Button variant="ghost" icon={<Trash2 size={18} />} onClick={() => setRemoving('logotipo')}>Eliminar logotipo</Button>}
              </div>
              <input ref={logoInput} type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" aria-label="Archivo del logotipo"
                onChange={(e) => { void sendFile('logotipo', e.target.files?.[0]); e.target.value = ''; }} />
              <p className="muted">Se muestra solo la imagen, sin marcos ni fondos, y respeta la transparencia (use PNG o WEBP transparente).
                Es independiente de la imagen de fondo.</p>
              <Checkbox label="Si no hay logotipo propio, usar el de la empresa (Gestión › Empresa)" checked={lg.use_company}
                onChange={(v) => setLogo({ use_company: v })} />
              <Range label="Tamaño (ancho)" value={lg.size} min={40} max={520} unit=" px" onChange={(v) => setLogo({ size: v })} />
              <Range label="Separación del borde" value={lg.offset} min={0} max={160} unit=" px" onChange={(v) => setLogo({ offset: v })} />
              <fieldset className="pos-grid">
                <legend>Posición del logotipo</legend>
                {POSITIONS.map(([value, label]) => (
                  <label key={value} className={`pos-cell${lg.position === value ? ' on' : ''}`} title={label}>
                    <input type="radio" name="logo-pos" value={value} checked={lg.position === value} onChange={() => setLogo({ position: value })}
                      aria-label={label} />
                    <span aria-hidden />
                  </label>
                ))}
              </fieldset>
            </div>
          </Card>
        </div>
        <Card title="Vista previa">
          <div className="card-body stack">
            <div className="segmented" role="radiogroup" aria-label="Tamaño de pantalla">
              {([['desktop', 'Escritorio', <Monitor key="m" size={16} />], ['tablet', 'Tableta', <Tablet key="t" size={16} />],
                ['phone', 'Teléfono', <Smartphone key="p" size={16} />]] as const).map(([d, label, icon]) => (
                <button key={d} type="button" role="radio" aria-checked={device === d} className={`seg${device === d ? ' on' : ''}`}
                  onClick={() => setDevice(d)}>{icon} {label}</button>
              ))}
            </div>
            <DeviceFrame device={device}>
              <div className={`login login-mock${device === 'phone' ? ' login-narrow' : ''}`} data-testid="login-preview">
                <div className="login-form">
                  <div className="stack">
                    <h2 style={{ margin: 0 }}>Iniciar sesión</h2>
                    <span className="muted">Escriba el usuario y la contraseña que le asignó el administrador.</span>
                    <span className="field-label">Usuario</span><span className="input" />
                    <span className="field-label">Contraseña</span><span className="input" />
                    <span className="btn btn-primary btn-lg btn-block">Ingresar</span>
                  </div>
                </div>
                <LoginVisual look={draft} company={company.data ?? null} />
              </div>
            </DeviceFrame>
            <p className="muted">Así se verá la pantalla de ingreso. Los ajustes se aplican al guardar; las imágenes se guardan al subirlas.</p>
          </div>
        </Card>
      </div>
      <ErrorAlert error={error} />
      <div className="appearance-actions">
        {dirty && <span className="muted">Cambios sin guardar</span>}
        <Button icon={<X size={18} />} disabled={!dirty} onClick={() => setDraft(saved)}>Cancelar</Button>
        <Button variant="primary" icon={<Save size={18} />} busy={busy === 'save'} disabled={!dirty} onClick={save}>Guardar pantalla de ingreso</Button>
      </div>
      <ConfirmDialog open={Boolean(removing)} danger title={removing === 'fondo' ? 'Eliminar imagen de fondo' : 'Eliminar logotipo'}
        confirmLabel="Eliminar" message={removing === 'fondo' ? 'El panel mostrará el color del tema. El logotipo no cambia.'
          : 'El logotipo propio se elimina. La imagen de fondo no cambia.'}
        onClose={() => setRemoving(null)} onConfirm={remove} />
    </div>
  );
}

function Range({ label, value, min, max, unit, onChange }: { label: string; value: number; min: number; max: number; unit: string;
  onChange: (v: number) => void }) {
  return (
    <label className="range-field">
      <span className="field-label">{label} <span className="muted">{value}{unit}</span></span>
      <input type="range" min={min} max={max} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

const DEVICES = { desktop: [1280, 760], tablet: [820, 1000], phone: [390, 760] } as const;

/** Muestra la pantalla al tamaño real del dispositivo, reducida para caber en la página (misma composición). */
function DeviceFrame({ device, children }: { device: keyof typeof DEVICES; children: ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0.5);
  const [w, h] = DEVICES[device];
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const update = () => setScale(Math.min(1, el.clientWidth / w));
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [w]);
  return (
    <div ref={box} className="device-frame" style={{ height: h * scale }}>
      <div className="device-screen" style={{ width: w, height: h, transform: `scale(${scale})` }}>{children}</div>
    </div>
  );
}

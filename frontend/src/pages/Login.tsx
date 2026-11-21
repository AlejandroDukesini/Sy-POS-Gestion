import { LogIn } from 'lucide-react';
import { useEffect, useState, type CSSProperties, type FormEvent } from 'react';
import { ApiError, get } from '../api/client';
import { Button } from '../components/ui/Button';
import { Alert, ErrorAlert } from '../components/ui/Feedback';
import { TextField } from '../components/ui/Form';
import { useAuth } from '../context/Auth';
import { DEFAULT_LOGIN, useOptionalTheme, type LoginLook } from '../context/Theme';

interface PublicCompany { name: string; has_logo: boolean }

/**
 * Panel visual de la pantalla de ingreso: imagen de fondo y logotipo INDEPENDIENTES, configurados en
 * Gestión › Apariencia. El logotipo se muestra solo (sin marcos, tarjetas ni fondos) y sin deformarse.
 * Sin logotipo propio puede usarse el de la empresa; sin ninguno, el panel queda limpio con el color del tema.
 */
export function LoginVisual({ look, company, backgroundUrl, logoUrl, className = '' }: {
  look: LoginLook; company: PublicCompany | null; backgroundUrl?: string | null; logoUrl?: string | null; className?: string;
}) {
  const bg = look.background;
  const lg = look.logo;
  const background = backgroundUrl !== undefined ? backgroundUrl
    : look.has_background ? `/api/appearance/login/fondo?v=${look.version}` : null;
  const logo = logoUrl !== undefined ? logoUrl
    : look.has_logo ? `/api/appearance/login/logotipo?v=${look.version}`
      : lg.use_company && company?.has_logo ? '/api/company/logo' : null;
  const vars = {
    '--bg-fit': bg.fit, '--bg-x': `${bg.pos_x}%`, '--bg-y': `${bg.pos_y}%`, '--bg-zoom': String(bg.zoom / 100),
    '--bg-bright': String(1 - bg.darken / 100), '--ov-color': bg.overlay_color, '--ov-opacity': String(bg.overlay_opacity / 100),
    '--logo-size': `${lg.size}px`, '--logo-offset': `${lg.offset}px`,
  } as CSSProperties;
  return (
    <section className={`login-brand ${className}`} aria-label="Identidad de la empresa" style={vars}>
      {background && <img className="login-bg" src={background} alt="" aria-hidden="true" draggable={false} />}
      {background && bg.overlay_opacity > 0 && <div className="login-overlay" aria-hidden="true" />}
      {logo && (
        <div className="login-logo-layer" data-pos={lg.position}>
          <img className="login-logo" src={logo} alt={`Logotipo de ${company?.name ?? 'la empresa'}`} draggable={false} />
        </div>
      )}
    </section>
  );
}

export function LogoPanel() {
  const theme = useOptionalTheme();
  const [company, setCompany] = useState<PublicCompany | null>(null);
  const [own, setOwn] = useState<LoginLook | null>(null);
  useEffect(() => {
    get<PublicCompany>('/company/public').then(setCompany).catch(() => setCompany(null));
    if (!theme) get<any>('/appearance').then((a) => setOwn({ ...DEFAULT_LOGIN, ...a.login })).catch(() => setOwn(null));
  }, [theme]);
  return <LoginVisual look={theme?.appearance.login ?? own ?? DEFAULT_LOGIN} company={company} />;
}

export function LoginPage({ initialUsername = '', onBack, notice }: { initialUsername?: string; onBack?: () => void; notice?: string } = {}) {
  const { login, expiredMessage } = useAuth();
  const [username, setUsername] = useState(initialUsername);
  const [password, setPassword] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const local: Record<string, string> = {};
    if (!username.trim()) local.username = 'Escriba su usuario.';
    if (!password) local.password = 'Escriba su contraseña.';
    setErrors(local);
    if (Object.keys(local).length) return;
    setBusy(true);
    setError(null);
    try {
      await login(username.trim(), password);
    } catch (err) {
      setError(err as ApiError);
      setPassword('');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <main className="login-form">
        <div className="stack">
          <div>
            <h1>Iniciar sesión</h1>
            <p className="muted" style={{ marginTop: 6 }}>Escriba el usuario y la contraseña que le asignó el administrador.</p>
          </div>
          {notice && <Alert kind="info">{notice}</Alert>}
          {expiredMessage && <Alert kind="info">{expiredMessage}</Alert>}
          <ErrorAlert error={error} title="No se pudo iniciar sesión" />
          <form className="stack" onSubmit={submit} noValidate>
            <TextField label="Usuario" value={username} onChange={setUsername} error={errors.username} autoComplete="username"
              autoCapitalize="none" spellCheck={false} required autoFocus={!initialUsername} />
            <TextField label="Contraseña" type="password" value={password} onChange={setPassword} error={errors.password}
              autoComplete="current-password" required autoFocus={Boolean(initialUsername)} />
            <Button type="submit" variant="primary" size="lg" block busy={busy} icon={<LogIn size={22} />}>Ingresar</Button>
          </form>
          <p className="muted">¿Olvidó su contraseña? Pida a un administrador que la restablezca.</p>
          {onBack && <Button variant="ghost" onClick={onBack}>Volver a la lista de perfiles</Button>}
        </div>
      </main>
      <LogoPanel />
    </div>
  );
}

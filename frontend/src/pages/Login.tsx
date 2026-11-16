import { LogIn } from 'lucide-react';
import { useEffect, useState, type FormEvent } from 'react';
import { ApiError, get } from '../api/client';
import { Button } from '../components/ui/Button';
import { Alert, ErrorAlert } from '../components/ui/Feedback';
import { TextField } from '../components/ui/Form';
import { useAuth } from '../context/Auth';

interface PublicCompany { name: string; has_logo: boolean }

export function LogoPanel() {
  const [company, setCompany] = useState<PublicCompany | null>(null);
  useEffect(() => {
    get<PublicCompany>('/company/public').then(setCompany).catch(() => setCompany(null));
  }, []);
  return (
    <section className="login-brand" aria-label="Identidad de la empresa">
      <div className="logo-slot">
        {company?.has_logo ? <img src="/api/company/logo" alt={`Logotipo de ${company.name}`} /> : <span>Aquí tu logo</span>}
      </div>
    </section>
  );
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

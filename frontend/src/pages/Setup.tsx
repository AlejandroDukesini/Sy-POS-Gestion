import { ShieldCheck } from 'lucide-react';
import { useEffect, useState, type FormEvent } from 'react';
import { ApiError, post } from '../api/client';
import { Button } from '../components/ui/Button';
import { Alert, ErrorAlert } from '../components/ui/Feedback';
import { TextField } from '../components/ui/Form';
import { LogoPanel } from './Login';

interface Status { needs_setup: boolean; local: boolean; code_file: string | null; code_injected: boolean }

/** Primera instalación: crea el administrador inicial con el código de un solo uso del servidor. */
export function SetupPage({ status, onDone }: { status: Status; onDone: () => void }) {
  const [code, setCode] = useState('');
  const [username, setUsername] = useState('');
  const [fullName, setFullName] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // La aplicación de escritorio entrega el código en el fragmento (#setup=…), que nunca viaja al servidor.
    const match = /setup=([A-Z0-9-]+)/i.exec(window.location.hash);
    if (match) {
      setCode(match[1]);
      history.replaceState(null, '', window.location.pathname);
    }
  }, []);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const local: Record<string, string> = {};
    if (!code.trim()) local.code = 'Escriba el código de instalación.';
    if (!/^[a-z0-9._-]{3,40}$/.test(username.trim().toLowerCase())) local.username = 'De 3 a 40 letras, números, punto o guion.';
    if (!fullName.trim()) local.full_name = 'Escriba el nombre.';
    if (password.length < 10) local.password = 'Al menos 10 caracteres, con letras y números.';
    if (password !== confirm) local.confirm = 'Las contraseñas no coinciden.';
    setErrors(local);
    if (Object.keys(local).length) return;
    setBusy(true);
    setError(null);
    try {
      await post('/setup', { code: code.trim(), username: username.trim().toLowerCase(), full_name: fullName.trim(), password });
      onDone();
    } catch (err) {
      const apiErr = err as ApiError;
      setError(apiErr);
      setErrors(apiErr.fields ?? {});
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <main className="login-form">
        <div className="stack">
          <div>
            <h1>Instalación de POS-PY</h1>
            <p className="muted" style={{ marginTop: 6 }}>Cree la cuenta del primer administrador. Después podrá crear las demás cuentas desde Gestión.</p>
          </div>
          {!status.local && (
            <Alert kind="warning" title="Debe hacerse en el equipo del servidor">
              Por seguridad, la instalación inicial solo se acepta desde el propio equipo donde está instalado POS-PY.
            </Alert>
          )}
          {status.code_file && (
            <Alert kind="info" title="Código de instalación">
              Ábralo en el archivo <code>{status.code_file}</code> (también se puede usar
              <code> python -m pospy.cli create-admin</code>).
            </Alert>
          )}
          <ErrorAlert error={error} />
          <form className="stack" onSubmit={submit} noValidate>
            <TextField label="Código de instalación" value={code} onChange={setCode} error={errors.code} autoComplete="off" required />
            <TextField label="Usuario del administrador" value={username} onChange={setUsername} error={errors.username}
              autoComplete="username" autoCapitalize="none" required />
            <TextField label="Nombre completo" value={fullName} onChange={setFullName} error={errors.full_name} required />
            <TextField label="Contraseña" type="password" value={password} onChange={setPassword} error={errors.password}
              hint="Mínimo 10 caracteres, con letras y números, sin incluir el usuario." autoComplete="new-password" required />
            <TextField label="Repita la contraseña" type="password" value={confirm} onChange={setConfirm} error={errors.confirm}
              autoComplete="new-password" required />
            <Button type="submit" variant="primary" size="lg" block busy={busy} icon={<ShieldCheck size={22} />}>
              Crear administrador
            </Button>
          </form>
        </div>
      </main>
      <LogoPanel />
    </div>
  );
}

import { KeyRound } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { ApiError, post } from '../api/client';
import { Button } from '../components/ui/Button';
import { Alert, ErrorAlert } from '../components/ui/Feedback';
import { TextField } from '../components/ui/Form';
import { useAuth } from '../context/Auth';
import { useToast } from '../context/Toast';

export function PasswordForm({ onDone }: { onDone?: () => void }) {
  const { refresh, user } = useAuth();
  const { notify } = useToast();
  const [current, setCurrent] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const local: Record<string, string> = {};
    if (!current) local.current = 'Escriba su contraseña actual.';
    if (password.length < 10) local.password = 'Al menos 10 caracteres, con letras y números.';
    if (user && password.toLowerCase().includes(user.username.toLowerCase())) local.password = 'No puede contener su usuario.';
    if (password !== confirm) local.confirm = 'Las contraseñas no coinciden.';
    setErrors(local);
    if (Object.keys(local).length) return;
    setBusy(true);
    setError(null);
    try {
      await post('/auth/password', { current, password });
      notify('success', 'Contraseña actualizada', 'Las demás sesiones abiertas se cerraron.');
      setCurrent('');
      setPassword('');
      setConfirm('');
      await refresh();
      onDone?.();
    } catch (err) {
      setError(err as ApiError);
      setErrors((err as ApiError).fields ?? {});
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="stack" onSubmit={submit} noValidate>
      <ErrorAlert error={error} />
      <TextField label="Contraseña actual" type="password" value={current} onChange={setCurrent} error={errors.current}
        autoComplete="current-password" required />
      <TextField label="Nueva contraseña" type="password" value={password} onChange={setPassword} error={errors.password}
        hint="Mínimo 10 caracteres, con letras y números." autoComplete="new-password" required />
      <TextField label="Repita la nueva contraseña" type="password" value={confirm} onChange={setConfirm} error={errors.confirm}
        autoComplete="new-password" required />
      <div className="form-actions">
        <Button type="submit" variant="primary" busy={busy} icon={<KeyRound size={20} />}>Guardar contraseña</Button>
      </div>
    </form>
  );
}

export function ChangePasswordPage() {
  const { logout } = useAuth();
  return (
    <div className="login">
      <main className="login-form">
        <div className="stack">
          <h1>Cambie su contraseña</h1>
          <Alert kind="info">Su contraseña es temporal. Elija una nueva para continuar.</Alert>
          <PasswordForm />
          <Button variant="ghost" onClick={() => void logout()}>Salir</Button>
        </div>
      </main>
      <section className="login-brand" aria-hidden><div className="logo-slot"><span>POS-PY</span></div></section>
    </div>
  );
}

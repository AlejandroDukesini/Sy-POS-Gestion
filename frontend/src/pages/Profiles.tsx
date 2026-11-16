import { KeyRound, LogIn, ShieldCheck, User } from 'lucide-react';
import { useState } from 'react';
import { ApiError, post } from '../api/client';
import { Button } from '../components/ui/Button';
import { ErrorAlert, ErrorState, Loading } from '../components/ui/Feedback';
import { useAuth } from '../context/Auth';
import { useApi } from '../lib/hooks';
import { LoginPage, LogoPanel } from './Login';

interface Profile { id: number; username: string; full_name: string; role: 'admin' | 'employee'; requires_password: boolean }

/** Acceso directo (inicio de sesión desactivado): cada persona elige su perfil y trabaja con sus permisos. */
export function ProfilesPage() {
  const { refresh, expiredMessage } = useAuth();
  const profiles = useApi<Profile[]>('/auth/profiles');
  const [withPassword, setWithPassword] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  if (withPassword !== null) return <LoginPage initialUsername={withPassword} onBack={() => setWithPassword(null)} />;

  const choose = async (p: Profile) => {
    if (p.requires_password) {
      setWithPassword(p.username);
      return;
    }
    setBusy(p.id);
    setError(null);
    try {
      await post('/auth/open', { user_id: p.id });
      await refresh();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="login">
      <main className="login-form">
        <div className="stack">
          <div>
            <h1>¿Quién está trabajando?</h1>
            <p className="muted" style={{ marginTop: 6 }}>Elija su perfil. Cada persona trabaja con los permisos que le asignó el administrador.</p>
          </div>
          {expiredMessage && <p className="muted">{expiredMessage}</p>}
          <ErrorAlert error={error} />
          {profiles.loading && !profiles.data ? <Loading /> : profiles.error ? <ErrorState error={profiles.error} onRetry={profiles.reload} /> : (
            <div className="stack" role="list">
              {(profiles.data ?? []).map((p) => (
                <Button key={p.id} block size="lg" busy={busy === p.id} onClick={() => void choose(p)}
                  icon={p.role === 'admin' ? <ShieldCheck size={22} /> : <User size={22} />}>
                  <span role="listitem">{p.full_name} <small className="muted">· {p.role === 'admin' ? 'Administrador' : 'Empleado'}</small>
                    {p.requires_password && <KeyRound size={16} aria-label="pide contraseña" style={{ marginLeft: 6 }} />}</span>
                </Button>
              ))}
            </div>
          )}
          <Button variant="ghost" icon={<LogIn size={20} />} onClick={() => setWithPassword('')}>Ingresar con usuario y contraseña</Button>
        </div>
      </main>
      <LogoPanel />
    </div>
  );
}

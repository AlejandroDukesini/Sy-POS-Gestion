import { Rocket } from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ApiError, post } from '../api/client';
import { Button } from '../components/ui/Button';
import { Alert, ErrorAlert, Loading } from '../components/ui/Feedback';
import { TextField } from '../components/ui/Form';
import { useAuth } from '../context/Auth';
import { LoginPage, LogoPanel } from './Login';

export interface SetupStatus {
  needs_setup: boolean; setup_step: string; login_enabled: boolean; direct_access: boolean;
  local: boolean; code_file: string | null; code_injected: boolean;
}

/**
 * Primera ejecución: abre el asistente de configuración sin pedir cuenta ni contraseña.
 * Solo exige el código de instalación (la aplicación de escritorio lo entrega automáticamente).
 */
export function SetupPage({ status }: { status: SetupStatus }) {
  const { refresh } = useAuth();
  const [code, setCode] = useState('');
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [needsPassword, setNeedsPassword] = useState(false);
  const autoTried = useRef(false);

  const start = async (value: string) => {
    setBusy(true);
    setError(null);
    try {
      await post('/setup/start', { code: value.trim() });
      await refresh();
    } catch (err) {
      const apiErr = err as ApiError;
      if (apiErr.status === 401) setNeedsPassword(true);   // el administrador ya tiene contraseña
      else setError(apiErr);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    // La aplicación de escritorio entrega el código en el fragmento (#setup=…), que nunca viaja al servidor.
    const match = /setup=([A-Z0-9-]+)/i.exec(window.location.hash);
    if (match && !autoTried.current) {
      autoTried.current = true;
      setCode(match[1]);
      history.replaceState(null, '', window.location.pathname);
      void start(match[1]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (needsPassword) {
    return <LoginPage notice="La configuración inicial quedó a medias. Ingrese con la contraseña del administrador para continuarla." />;
  }
  if (busy && !error && autoTried.current) return <Loading label="Preparando la configuración inicial…" />;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (code.trim()) void start(code);
  };

  return (
    <div className="login">
      <main className="login-form">
        <div className="stack">
          <div>
            <h1>Bienvenido a POS-PY</h1>
            <p className="muted" style={{ marginTop: 6 }}>
              {status.setup_step !== 'empresa' ? 'Continúe la configuración inicial donde la dejó.'
                : 'Configure su empresa antes de empezar. No necesita una cuenta: el inicio de sesión se activa después, si lo desea.'}
            </p>
          </div>
          {!status.local && (
            <Alert kind="warning" title="Debe hacerse en el equipo del servidor">
              Por seguridad, la configuración inicial solo se acepta desde el propio equipo donde está instalado POS-PY.
            </Alert>
          )}
          {status.code_file && (
            <Alert kind="info" title="Código de instalación">
              Por seguridad se pide un código de un solo uso. Ábralo en el archivo <code>{status.code_file}</code>.
            </Alert>
          )}
          <ErrorAlert error={error} />
          <form className="stack" onSubmit={submit} noValidate>
            <TextField label="Código de instalación" value={code} onChange={setCode} autoComplete="off" required error={error?.fields?.code} />
            <Button type="submit" variant="primary" size="lg" block busy={busy} icon={<Rocket size={22} />} disabled={!code.trim()}>
              {status.setup_step !== 'empresa' ? 'Continuar configuración' : 'Comenzar configuración'}
            </Button>
          </form>
        </div>
      </main>
      <LogoPanel />
    </div>
  );
}

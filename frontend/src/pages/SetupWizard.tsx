import { ArrowLeft, ArrowRight, CheckCircle2, Plus } from 'lucide-react';
import { useState } from 'react';
import { ApiError, post, put } from '../api/client';
import { Button } from '../components/ui/Button';
import { Alert, ErrorAlert } from '../components/ui/Feedback';
import { Card, PageHeader } from '../components/ui/Layout';
import { useAuth } from '../context/Auth';
import { SecurityPanel } from './manage/Security';
import { SettingsSection } from './manage/Settings';
import { UsersPanel } from './manage/Users';

const STEPS = [
  { key: 'empresa', label: 'Empresa' },
  { key: 'preferencias', label: 'Preferencias' },
  { key: 'seguridad', label: 'Seguridad' },
  { key: 'empleados', label: 'Empleados' },
  { key: 'listo', label: 'Finalizar' },
] as const;

/** Asistente de configuración inicial. Retoma el último paso guardado en el servidor. */
export function SetupWizard({ initialStep, onDone }: { initialStep: string; onDone: () => void }) {
  const { refresh, access } = useAuth();
  const start = Math.max(0, STEPS.findIndex((s) => s.key === initialStep));
  const [index, setIndex] = useState(start);
  const [editing, setEditing] = useState<any>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const step = STEPS[index].key;

  const go = async (next: number) => {
    setError(null);
    try {
      await put('/setup/step', { step: STEPS[next].key });
      setIndex(next);
      window.scrollTo({ top: 0 });
    } catch (err) {
      setError(err as ApiError);
    }
  };
  const finish = async () => {
    setBusy(true);
    setError(null);
    try {
      await post('/setup/complete');
      await refresh();
      onDone();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="content" style={{ maxWidth: 1000, margin: '0 auto' }}>
      <div className="stack">
        <PageHeader title="Configuración inicial" description="Configure la empresa antes de empezar. Puede cambiar todo después desde Gestión y Configuración." />
        <ol className="row" style={{ gap: 8, flexWrap: 'wrap', listStyle: 'none', padding: 0 }} aria-label="Pasos">
          {STEPS.map((s, i) => (
            <li key={s.key} aria-current={i === index ? 'step' : undefined}
              className={`badge${i === index ? ' badge-info' : i < index ? ' badge-success' : ''}`}>
              {i + 1}. {s.label}
            </li>
          ))}
        </ol>
        <ErrorAlert error={error} />

        {step === 'empresa' && (
          <SettingsSection section="empresa" title="Datos de la empresa" saveLabel="Guardar y continuar" onSaved={() => void go(1)} />
        )}
        {step === 'preferencias' && (
          <>
            <Alert kind="info">Los valores predeterminados sirven para empezar. Si cambia alguno, pulse «Guardar» en su sección.</Alert>
            <SettingsSection section="ventas" />
            <SettingsSection section="inventario" />
          </>
        )}
        {step === 'seguridad' && (
          <>
            <Alert kind="info">El inicio de sesión es opcional. Si lo activa, primero asigne una contraseña a la cuenta administrativa.
              Puede activarlo o desactivarlo más adelante en Gestión › Sesiones y seguridad.</Alert>
            <SecurityPanel onChanged={() => void refresh()} />
            <SettingsSection section="seguridad" title="Cierre de sesión automático y bloqueos" />
          </>
        )}
        {step === 'empleados' && (
          <>
            <div className="row" style={{ justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
              <p className="muted">Registre a sus empleados y sus permisos. No necesitan cuenta si el inicio de sesión está desactivado.</p>
              <Button variant="primary" icon={<Plus size={20} />} onClick={() => setEditing({})}>Nuevo empleado</Button>
            </div>
            <UsersPanel editing={editing} setEditing={setEditing} />
          </>
        )}
        {step === 'listo' && (
          <Card title="Todo listo">
            <div className="card-body stack">
              <p>Inicio de sesión: <strong>{access?.login_enabled ? 'activado' : 'desactivado'}</strong>.</p>
              {access?.login_enabled
                ? <Alert kind="info">Al finalizar se le pedirá ingresar con su usuario y contraseña.</Alert>
                : <Alert kind="info">Al finalizar entrará directamente. En este equipo, cada persona elegirá su perfil.</Alert>}
            </div>
          </Card>
        )}

        <div className="form-actions">
          {index > 0 && <Button icon={<ArrowLeft size={20} />} onClick={() => void go(index - 1)}>Anterior</Button>}
          {step !== 'listo' && step !== 'empresa' && (
            <Button variant="primary" icon={<ArrowRight size={20} />} onClick={() => void go(index + 1)}>Continuar</Button>)}
          {step === 'empresa' && <Button onClick={() => void go(1)}>Omitir por ahora</Button>}
          {step === 'listo' && (
            <Button variant="primary" size="lg" busy={busy} icon={<CheckCircle2 size={22} />} onClick={finish}>Finalizar y entrar</Button>)}
        </div>
      </div>
    </div>
  );
}

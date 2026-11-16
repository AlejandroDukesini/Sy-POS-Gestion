import { Lock, LockOpen, Save } from 'lucide-react';
import { useEffect, useState } from 'react';
import { ApiError, put } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { ConfirmDialog } from '../../components/ui/Dialog';
import { Alert, Badge, ErrorAlert, Loading } from '../../components/ui/Feedback';
import { TextField } from '../../components/ui/Form';
import { Card } from '../../components/ui/Layout';
import { useAuth } from '../../context/Auth';
import { useToast } from '../../context/Toast';
import { useApi } from '../../lib/hooks';
import { PasswordForm } from '../ChangePassword';

/**
 * Seguridad: activar o desactivar el inicio de sesión y configurar la cuenta administrativa.
 * Las reglas (exigir un administrador con contraseña, solo administradores…) las aplica el servidor.
 */
export function SecurityPanel({ onChanged }: { onChanged?: () => void }) {
  const { user, refresh } = useAuth();
  const { notify } = useToast();
  const sec = useApi<any>('/security');
  const [confirm, setConfirm] = useState<null | boolean>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [account, setAccount] = useState({ username: user?.username ?? '', full_name: user?.full_name ?? '' });
  useEffect(() => setAccount({ username: user?.username ?? '', full_name: user?.full_name ?? '' }), [user]);

  if (sec.loading && !sec.data) return <Loading />;
  const s = sec.data;
  if (!s) return <ErrorAlert error={sec.error} />;

  const toggle = async (enabled: boolean) => {
    setConfirm(null);
    setBusy(true);
    setError(null);
    try {
      await put('/security/login', { enabled });
      notify('success', enabled ? 'Inicio de sesión activado' : 'Inicio de sesión desactivado',
        enabled ? 'Todas las personas deberán ingresar con usuario y contraseña.' : 'No se eliminó ninguna cuenta, contraseña ni permiso.');
      sec.reload();
      onChanged?.();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  const saveAccount = async () => {
    setBusy(true);
    setError(null);
    try {
      await put(`/users/${user!.id}`, { username: account.username.trim().toLowerCase(), full_name: account.full_name });
      await refresh();
      notify('success', 'Cuenta administrativa actualizada');
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  const fe = error?.fields ?? {};
  const canEnable = s.admins_with_password > 0;

  return (
    <div className="stack">
      <Card title={<span className="row" style={{ gap: 8 }}>Inicio de sesión {s.login_enabled
        ? <Badge kind="success">Activado</Badge> : <Badge kind="warning">Desactivado</Badge>}</span>}>
        <div className="card-body stack">
          <ErrorAlert error={error} />
          {s.login_enabled ? (
            <p>Cada persona ingresa con su usuario y contraseña. Los empleados sin cuenta siguen existiendo y recibiendo tareas,
              pero no pueden ingresar hasta que se les asigne una contraseña.</p>
          ) : (
            <p>Acceso directo: en este equipo cada persona elige su perfil y trabaja con <strong>sus</strong> permisos. Los
              administradores con contraseña la siguen necesitando. Desde otros equipos de la red siempre se pide contraseña.</p>
          )}
          {!s.login_enabled && s.admins_without_password > 0 && (
            <Alert kind="warning" title="Hay administradores sin contraseña">
              Mientras un administrador no tenga contraseña, cualquier persona que use este equipo puede entrar con su perfil y
              cambiar la configuración. Asígnele una contraseña abajo.
            </Alert>
          )}
          {!s.login_enabled && !canEnable && (
            <Alert kind="info">Para activar el inicio de sesión primero asigne una contraseña a la cuenta administrativa.</Alert>
          )}
          <Alert kind="info">Es una protección local: impide el uso no autorizado de la aplicación, pero no protege los archivos
            de datos frente a quien tenga acceso administrativo a Windows. Use además una cuenta de Windows con contraseña.</Alert>
          <div className="form-actions">
            {s.login_enabled
              ? <Button icon={<LockOpen size={20} />} busy={busy} onClick={() => setConfirm(false)}>Desactivar inicio de sesión</Button>
              : <Button variant="primary" icon={<Lock size={20} />} busy={busy} disabled={!canEnable} onClick={() => setConfirm(true)}>
                  Activar inicio de sesión</Button>}
          </div>
        </div>
      </Card>

      <Card title="Cuenta administrativa (la suya)">
        <div className="card-body stack">
          <div className="form-grid">
            <TextField label="Usuario" value={account.username} onChange={(v) => setAccount({ ...account, username: v })}
              error={fe.username} autoCapitalize="none" hint="Con este usuario iniciará sesión." />
            <TextField label="Nombre completo" value={account.full_name} onChange={(v) => setAccount({ ...account, full_name: v })}
              error={fe.full_name} />
          </div>
          <div className="form-actions"><Button busy={busy} icon={<Save size={20} />} onClick={saveAccount}>Guardar datos</Button></div>
          <h3 style={{ fontSize: '1.05rem' }}>{s.current_user_has_password ? 'Cambiar contraseña' : 'Asignar contraseña'}</h3>
          <PasswordForm onDone={() => { sec.reload(); onChanged?.(); }} />
        </div>
      </Card>

      <ConfirmDialog open={confirm !== null} title={confirm ? 'Activar inicio de sesión' : 'Desactivar inicio de sesión'}
        confirmLabel={confirm ? 'Activar' : 'Desactivar'} onClose={() => setConfirm(null)} onConfirm={() => void toggle(Boolean(confirm))}
        message={confirm
          ? 'Desde ahora todas las personas deberán ingresar con usuario y contraseña. Las sesiones de acceso directo se cerrarán.'
          : 'Las personas podrán entrar en este equipo eligiendo su perfil. No se borra ninguna cuenta, contraseña, empleado ni permiso.'} />
    </div>
  );
}

import { KeyRound, LockOpen, Plus, Save } from 'lucide-react';
import { useState } from 'react';
import { ApiError, post, put } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { Dialog } from '../../components/ui/Dialog';
import { Badge, ErrorAlert, ErrorState, Loading } from '../../components/ui/Feedback';
import { Checkbox, SelectField, TextField } from '../../components/ui/Form';
import { Card } from '../../components/ui/Layout';
import { DataTable } from '../../components/ui/Table';
import { useAuth } from '../../context/Auth';
import { useToast } from '../../context/Toast';
import { dateTime } from '../../lib/format';
import { useApi } from '../../lib/hooks';
import { ManageBack } from './ManageRoutes';

export function UsersPage() {
  const users = useApi<any[]>('/users');
  const catalog = useApi<any[]>('/permissions/catalog');
  const [editing, setEditing] = useState<any>(null);
  return (
    <div className="stack">
      <ManageBack title="Usuarios y permisos" description="Los administradores tienen acceso completo; cada empleado, solo a lo que usted le permita."
        actions={<Button variant="primary" icon={<Plus size={20} />} onClick={() => setEditing({})}>Nuevo usuario</Button>} />
      <Card>
        {users.loading && !users.data ? <Loading /> : users.error ? <ErrorState error={users.error} /> : (
          <DataTable caption="Usuarios" rows={users.data ?? []} rowKey={(u: any) => u.id} onSelect={setEditing} columns={[
            { key: 'u', header: 'Usuario', render: (u: any) => <strong>{u.username}</strong> },
            { key: 'n', header: 'Nombre', render: (u: any) => u.full_name },
            { key: 'r', header: 'Rol', render: (u: any) => (u.role === 'admin' ? <Badge kind="info">Administrador</Badge> : <Badge>Empleado</Badge>) },
            { key: 's', header: 'Estado', render: (u: any) => (
              <span className="row" style={{ gap: 6 }}>
                {u.active ? <Badge kind="success">Activo</Badge> : <Badge kind="danger">Inactivo</Badge>}
                {u.locked_until && new Date(u.locked_until) > new Date() && <Badge kind="warning">Bloqueado</Badge>}
                {u.must_change_password ? <Badge>Clave temporal</Badge> : null}
              </span>) },
            { key: 'p', header: 'Permisos', render: (u: any) => (u.role === 'admin' ? 'Todos' : `${u.permissions.length}`) },
            { key: 'l', header: 'Último ingreso', render: (u: any) => dateTime(u.last_login_at) },
          ]} />
        )}
      </Card>
      {editing && catalog.data && (
        <UserDialog user={editing} catalog={catalog.data} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); users.reload(); }} />
      )}
    </div>
  );
}

function UserDialog({ user, catalog, onClose, onSaved }: { user: any; catalog: any[]; onClose: () => void; onSaved: () => void }) {
  const { user: me } = useAuth();
  const { notify } = useToast();
  const isNew = !user.id;
  const [form, setForm] = useState({
    username: user.username ?? '', full_name: user.full_name ?? '', role: user.role ?? 'employee', active: user.active ?? 1,
    password: '', permissions: new Set<string>(user.permissions ?? ['inventario.ver', 'ventas.vender', 'ventas.historial',
      'documentos.ver', 'documentos.crear', 'documentos.imprimir']),
  });
  const [newPassword, setNewPassword] = useState('');
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const groups = [...new Set(catalog.map((p) => p.group))];
  const toggle = (code: string, on: boolean) => setForm((f) => {
    const next = new Set(f.permissions);
    if (on) next.add(code); else next.delete(code);
    return { ...f, permissions: next };
  });

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const permissions = form.role === 'employee' ? [...form.permissions].filter((p) => !catalog.find((c) => c.code === p)?.admin_only) : undefined;
      if (isNew) {
        await post('/users', { username: form.username.trim().toLowerCase(), full_name: form.full_name, role: form.role,
          password: form.password, permissions });
        notify('success', 'Usuario creado', 'Deberá cambiar la contraseña temporal en su primer ingreso.');
      } else {
        await put(`/users/${user.id}`, { full_name: form.full_name, role: form.role, active: Boolean(form.active), permissions,
          version: user.version });
        notify('success', 'Usuario actualizado', 'Si cambió el rol o los permisos, sus sesiones abiertas se cerraron.');
      }
      onSaved();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  const reset = async () => {
    setBusy(true);
    setError(null);
    try {
      await post(`/users/${user.id}/password`, { password: newPassword });
      notify('success', 'Contraseña temporal asignada', 'Comuníquela de forma privada; se pedirá cambiarla al ingresar.');
      setNewPassword('');
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  const unlock = async () => {
    await post(`/users/${user.id}/unlock`);
    notify('success', 'Cuenta desbloqueada');
    onSaved();
  };
  const fe = error?.fields ?? {};
  const self = me?.id === user.id;
  return (
    <Dialog open title={isNew ? 'Nuevo usuario' : `Usuario ${user.username}`} onClose={onClose} size="wide" footer={
      <><Button onClick={onClose}>Cancelar</Button><Button variant="primary" busy={busy} icon={<Save size={20} />} onClick={save}>Guardar</Button></>}>
      <ErrorAlert error={error} />
      <div className="form-grid">
        <TextField label="Usuario" value={form.username} onChange={(v) => setForm({ ...form, username: v })} disabled={!isNew}
          error={fe.username} required autoCapitalize="none" />
        <TextField label="Nombre completo" value={form.full_name} onChange={(v) => setForm({ ...form, full_name: v })} error={fe.full_name} required />
        <SelectField label="Rol" value={form.role} onChange={(v) => setForm({ ...form, role: v })} disabled={self}
          options={[{ value: 'employee', label: 'Empleado' }, { value: 'admin', label: 'Administrador' }]}
          hint={self ? 'No puede cambiar su propio rol.' : undefined} />
        {isNew && <TextField label="Contraseña temporal" type="password" value={form.password} onChange={(v) => setForm({ ...form, password: v })}
          error={fe.password} hint="Mínimo 10 caracteres con letras y números." autoComplete="new-password" required />}
      </div>
      {!isNew && !self && <Checkbox label="Cuenta activa" checked={Boolean(form.active)} onChange={(v) => setForm({ ...form, active: v ? 1 : 0 })} />}
      {form.role === 'employee' ? (
        <fieldset>
          <legend>Permisos del empleado</legend>
          <div className="grid-2">
            {groups.map((g) => (
              <div key={g}>
                <h3 style={{ fontSize: '1rem', margin: '8px 0' }}>{g}</h3>
                {catalog.filter((p) => p.group === g).map((p) => (
                  <Checkbox key={p.code} label={p.label} checked={!p.admin_only && form.permissions.has(p.code)} disabled={p.admin_only}
                    hint={p.admin_only ? 'Exclusivo de administradores' : undefined} onChange={(on) => toggle(p.code, on)} />
                ))}
              </div>
            ))}
          </div>
        </fieldset>
      ) : <p className="muted">Los administradores tienen todos los permisos.</p>}
      {!isNew && (
        <fieldset>
          <legend>Acceso</legend>
          <div className="row" style={{ alignItems: 'flex-end' }}>
            <div className="grow"><TextField label="Nueva contraseña temporal" type="password" value={newPassword} onChange={setNewPassword}
              autoComplete="new-password" /></div>
            <Button disabled={!newPassword} busy={busy} icon={<KeyRound size={20} />} onClick={reset}>Restablecer contraseña</Button>
            {user.locked_until && <Button icon={<LockOpen size={20} />} onClick={unlock}>Desbloquear</Button>}
          </div>
        </fieldset>
      )}
    </Dialog>
  );
}

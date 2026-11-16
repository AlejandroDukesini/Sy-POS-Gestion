import { KeyRound, LockOpen, Plus, Save } from 'lucide-react';
import { useState } from 'react';
import { ApiError, post, put } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { Dialog } from '../../components/ui/Dialog';
import { Alert, Badge, ErrorAlert, ErrorState, Loading } from '../../components/ui/Feedback';
import { Checkbox, SelectField, TextField } from '../../components/ui/Form';
import { Card } from '../../components/ui/Layout';
import { DataTable } from '../../components/ui/Table';
import { useAuth } from '../../context/Auth';
import { useToast } from '../../context/Toast';
import { dateTime } from '../../lib/format';
import { useApi } from '../../lib/hooks';
import { TASK_STATUS } from '../tasks/TasksPage';
import { ManageBack } from './ManageRoutes';

const DEFAULT_PERMS = ['inventario.ver', 'ventas.vender', 'ventas.historial', 'documentos.ver', 'documentos.crear', 'documentos.imprimir',
  'observaciones.ver', 'observaciones.crear', 'observaciones.comentar'];

export function UsersPage() {
  const [editing, setEditing] = useState<any>(null);
  return (
    <div className="stack">
      <ManageBack title="Empleados, usuarios y permisos"
        description="Los administradores tienen acceso completo; cada empleado, solo a lo que usted le permita. Un empleado puede existir sin cuenta de acceso."
        actions={<Button variant="primary" icon={<Plus size={20} />} onClick={() => setEditing({})}>Nuevo empleado</Button>} />
      <UsersPanel editing={editing} setEditing={setEditing} />
    </div>
  );
}

/** Lista de empleados y usuarios con su diálogo de edición (se usa también en el asistente inicial). */
export function UsersPanel({ editing, setEditing }: { editing: any; setEditing: (u: any) => void }) {
  const users = useApi<any[]>('/users');
  const catalog = useApi<any[]>('/permissions/catalog');
  return (
    <>
      <Card>
        {users.loading && !users.data ? <Loading /> : users.error ? <ErrorState error={users.error} /> : (
          <DataTable caption="Empleados y usuarios" rows={users.data ?? []} rowKey={(u: any) => u.id} onSelect={setEditing} columns={[
            { key: 'n', header: 'Nombre', render: (u: any) => <strong>{u.full_name}</strong> },
            { key: 'u', header: 'Usuario', render: (u: any) => u.username },
            { key: 'r', header: 'Rol', render: (u: any) => (u.role === 'admin' ? <Badge kind="info">Administrador</Badge> : <Badge>Empleado</Badge>) },
            { key: 'c', header: 'Cuenta', render: (u: any) => (u.has_password ? 'Con contraseña' : <Badge>Sin cuenta</Badge>) },
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
    </>
  );
}

function UserDialog({ user, catalog, onClose, onSaved }: { user: any; catalog: any[]; onClose: () => void; onSaved: () => void }) {
  const { user: me, refresh } = useAuth();
  const { notify } = useToast();
  const isNew = !user.id;
  const [form, setForm] = useState({
    username: user.username ?? '', full_name: user.full_name ?? '', role: user.role ?? 'employee', active: user.active ?? 1,
    password: '', withAccount: false, permissions: new Set<string>(user.permissions ?? DEFAULT_PERMS),
  });
  const tasks = useApi<any[]>(isNew ? null : `/tasks?assignee_id=${user.id}`);
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
        await post('/users', { username: form.username.trim().toLowerCase() || undefined, full_name: form.full_name, role: form.role,
          password: form.withAccount ? form.password : undefined, permissions });
        notify('success', form.role === 'admin' ? 'Administrador registrado' : 'Empleado registrado',
          form.withAccount ? 'Deberá cambiar la contraseña temporal en su primer ingreso.' : 'Sin cuenta de acceso: puede recibir tareas y usar el acceso directo.');
      } else {
        await put(`/users/${user.id}`, { username: form.username.trim().toLowerCase(), full_name: form.full_name, role: form.role,
          active: Boolean(form.active), permissions, version: user.version });
        notify('success', 'Datos actualizados', 'Si cambió el rol o los permisos, sus sesiones abiertas se cerraron.');
        if (me?.id === user.id) await refresh();
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
      onSaved();
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
    <Dialog open title={isNew ? 'Nuevo empleado o usuario' : user.full_name} onClose={onClose} size="wide" footer={
      <><Button onClick={onClose}>Cancelar</Button><Button variant="primary" busy={busy} icon={<Save size={20} />} onClick={save}>Guardar</Button></>}>
      <ErrorAlert error={error} />
      <div className="form-grid">
        <TextField label="Nombre completo" value={form.full_name} onChange={(v) => setForm({ ...form, full_name: v })} error={fe.full_name} required />
        <SelectField label="Rol" value={form.role} onChange={(v) => setForm({ ...form, role: v })} disabled={self}
          options={[{ value: 'employee', label: 'Empleado' }, { value: 'admin', label: 'Administrador' }]}
          hint={self ? 'No puede cambiar su propio rol.' : undefined} />
        <TextField label="Usuario" value={form.username} onChange={(v) => setForm({ ...form, username: v })} error={fe.username}
          required={!isNew || form.withAccount} autoCapitalize="none"
          hint={isNew && !form.withAccount ? 'Opcional: si lo deja vacío se genera a partir del nombre.' : 'De 3 a 40 letras, números, punto o guion.'} />
        {isNew && form.withAccount && <TextField label="Contraseña temporal" type="password" value={form.password}
          onChange={(v) => setForm({ ...form, password: v })} error={fe.password} hint="Mínimo 10 caracteres con letras y números."
          autoComplete="new-password" required />}
      </div>
      {isNew && <Checkbox label="Crear cuenta de acceso (usuario y contraseña)" checked={form.withAccount}
        onChange={(v) => setForm({ ...form, withAccount: v })}
        hint="Solo es necesaria si el inicio de sesión está activado. Puede asignarla después." />}
      {!isNew && !self && <Checkbox label="Activo" checked={Boolean(form.active)} onChange={(v) => setForm({ ...form, active: v ? 1 : 0 })}
        hint="Desactivar no borra su historial ni sus tareas." />}
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
          <legend>Tareas asignadas</legend>
          {tasks.loading ? <Loading /> : !tasks.data?.length ? <p className="muted">Sin tareas asignadas.</p> : (
            <ul>{tasks.data.map((t) => (
              <li key={t.id} style={{ margin: '6px 0' }}><strong>{t.title}</strong> — {TASK_STATUS[t.status] ?? t.status}
                {t.due_date ? ` · vence ${t.due_date}` : ''}</li>))}</ul>
          )}
        </fieldset>
      )}
      {!isNew && (
        <fieldset>
          <legend>Acceso</legend>
          {!user.has_password && <Alert kind="info">Sin cuenta de acceso. Asigne una contraseña temporal para crearla.</Alert>}
          <div className="row" style={{ alignItems: 'flex-end' }}>
            <div className="grow"><TextField label={user.has_password ? 'Nueva contraseña temporal' : 'Contraseña temporal'} type="password"
              value={newPassword} onChange={setNewPassword} autoComplete="new-password" /></div>
            <Button disabled={!newPassword} busy={busy} icon={<KeyRound size={20} />} onClick={reset}>
              {user.has_password ? 'Restablecer contraseña' : 'Crear cuenta'}</Button>
            {user.locked_until && <Button icon={<LockOpen size={20} />} onClick={unlock}>Desbloquear</Button>}
          </div>
        </fieldset>
      )}
    </Dialog>
  );
}

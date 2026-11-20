import { Archive, ArrowRight, Boxes, Plus, Power, Save, Trash2 } from 'lucide-react';
import { Fragment, useEffect, useMemo, useState } from 'react';
import { Link, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { ApiError, del, post, put } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { ConfirmDialog } from '../../components/ui/Dialog';
import { Alert, Badge, EmptyState, ErrorAlert, ErrorState, Loading } from '../../components/ui/Feedback';
import { Checkbox, SelectField, TextArea, TextField } from '../../components/ui/Form';
import { Card } from '../../components/ui/Layout';
import { DataTable } from '../../components/ui/Table';
import { useInventory } from '../../context/Inventory';
import { useToast } from '../../context/Toast';
import { dateTime, qty } from '../../lib/format';
import { useApi } from '../../lib/hooks';
import { ManageBack } from './ManageRoutes';

interface Perm { code: string; label: string; group: string }
interface GroupOpt { key: string; name: string; status: string; inventory_name: string | null; inventory_key: string | null;
  members: { id: number; full_name: string; username: string }[] }
const DEFAULT_MEMBER = ['inventario.ver', 'ventas.vender', 'ventas.historial', 'documentos.ver', 'documentos.crear', 'documentos.imprimir',
  'observaciones.ver', 'observaciones.crear', 'observaciones.comentar'];
const STATUS_LABEL: Record<string, string> = { activo: 'Activo', inactivo: 'Inactivo', archivado: 'Archivado' };
const STATUS_KIND: Record<string, 'success' | 'warning' | undefined> = { activo: 'success', inactivo: 'warning' };

export function InventoriesPage() {
  return (
    <Routes>
      <Route index element={<InventoryList />} />
      <Route path="nuevo" element={<InventoryCreate />} />
      <Route path=":key" element={<InventoryDetail />} />
    </Routes>
  );
}

function InventoryList() {
  const navigate = useNavigate();
  const { options } = useInventory();
  const mine = options.filter((o) => o.owner);
  return (
    <div className="stack">
      <ManageBack title="Administrar inventarios"
        description="Cada inventario pertenece a un grupo. Sus integrantes autorizados trabajan sobre el mismo inventario según los permisos que usted les dé."
        actions={<Button variant="primary" icon={<Plus size={20} />} onClick={() => navigate('nuevo')}>Nuevo inventario</Button>} />
      {mine.some((o) => !o.group) && (
        <Alert kind="warning" title="Hay inventarios sin grupo">
          Asócielos a un grupo para que los integrantes de ese grupo trabajen sobre ellos (por ejemplo, el «Inventario general» que ya existía).
        </Alert>
      )}
      <Card>
        {!mine.length ? <EmptyState title="Aún no tiene inventarios" icon={<Boxes size={40} aria-hidden />} /> : (
          <DataTable caption="Mis inventarios" rows={mine} rowKey={(o) => o.key} onSelect={(o) => navigate(o.key)} columns={[
            { key: 'n', header: 'Inventario', render: (o) => <strong>{o.name}</strong> },
            { key: 'g', header: 'Grupo', render: (o) => (o.group ? o.group.name : <Badge kind="warning">Sin grupo</Badge>) },
            { key: 's', header: 'Estado', render: (o) => <Badge kind={STATUS_KIND[o.status]}>{STATUS_LABEL[o.status]}</Badge> },
            { key: 'p', header: 'Productos', numeric: true, render: (o) => o.products },
            { key: 'e', header: 'Existencias', numeric: true, render: (o) => qty(o.stock) },
            { key: 'u', header: 'Última actualización', render: (o) => (o.last_update ? dateTime(o.last_update) : '—') },
          ]} />
        )}
      </Card>
    </div>
  );
}

function PermissionChecklist({ perms, value, onChange, idPrefix }: {
  perms: Perm[]; value: string[]; onChange: (v: string[]) => void; idPrefix: string;
}) {
  const groups = [...new Set(perms.map((p) => p.group))];
  const set = new Set(value);
  return (
    <div className="perm-grid">
      {groups.map((g) => (
        <fieldset key={g} className="perm-group">
          <legend>{g}</legend>
          {perms.filter((p) => p.group === g).map((p) => (
            <Checkbox key={`${idPrefix}-${p.code}`} label={p.label} checked={set.has(p.code)}
              onChange={(on) => onChange(on ? [...set, p.code] : value.filter((c) => c !== p.code))} />
          ))}
        </fieldset>
      ))}
    </div>
  );
}

function SettingsFields({ settings, setSettings, perms }: { settings: any; setSettings: (s: any) => void; perms: Perm[] }) {
  return (
    <div className="stack">
      <Checkbox label="Autorizar automáticamente a los integrantes del grupo con los permisos iniciales"
        hint="Si lo desactiva, cada integrante necesita que usted lo autorice." checked={settings.auto_authorize}
        onChange={(v) => setSettings({ ...settings, auto_authorize: v })} />
      <SelectField label="Qué pueden hacer los integrantes en este inventario"
        value={settings.member_permissions === null ? 'usuario' : 'restringir'}
        onChange={(v) => setSettings({ ...settings, member_permissions: v === 'usuario' ? null : DEFAULT_MEMBER })}
        hint="Por defecto cada integrante conserva los permisos de su usuario (Gestión › Usuarios). Puede restringirlos aquí."
        options={[{ value: 'usuario', label: 'Lo que permite su usuario (sin restricción)' },
          { value: 'restringir', label: 'Restringir a los permisos elegidos' }]} />
      {settings.member_permissions !== null && (
        <PermissionChecklist idPrefix="default" perms={perms} value={settings.member_permissions}
          onChange={(v) => setSettings({ ...settings, member_permissions: v })} />
      )}
      <SelectField label="Ventas sin existencias suficientes" value={settings.allow_negative_stock === null ? 'global' : settings.allow_negative_stock ? 'si' : 'no'}
        onChange={(v) => setSettings({ ...settings, allow_negative_stock: v === 'global' ? null : v === 'si' })}
        options={[{ value: 'global', label: 'Usar la configuración general' }, { value: 'no', label: 'No permitir existencias negativas' },
          { value: 'si', label: 'Permitir existencias negativas' }]} />
      <Checkbox label="Alertas de existencias bajas" checked={settings.low_stock_alerts}
        onChange={(v) => setSettings({ ...settings, low_stock_alerts: v })} />
    </div>
  );
}

function InventoryCreate() {
  const navigate = useNavigate();
  const { notify } = useToast();
  const { reload } = useInventory();
  const groups = useApi<GroupOpt[]>('/inventories/groups');
  const perms = useApi<Perm[]>('/inventories/permissions');
  const [form, setForm] = useState({ name: '', description: '', group: '' });
  const [settings, setSettings] = useState<any>({ auto_authorize: true, member_permissions: null, allow_negative_stock: null, low_stock_alerts: true });
  const [authorized, setAuthorized] = useState<Record<number, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const group = groups.data?.find((g) => g.key === form.group);
  useEffect(() => { setAuthorized(Object.fromEntries((group?.members ?? []).map((m) => [m.id, true]))); }, [group]);

  const submit = async () => {
    const e: Record<string, string> = {};
    if (!form.group) e.group = 'Elija el grupo al que pertenece el inventario.';
    if (!form.name.trim()) e.name = 'Escriba el nombre.';
    setErrors(e);
    if (Object.keys(e).length) return;
    setBusy(true);
    setError(null);
    try {
      const members = (group?.members ?? []).map((m) => ({ user_id: m.id,
        permissions: authorized[m.id] ? null : [] }));      // autorizado: según la configuración; no: sin acceso
      const inv = await post('/inventories', { ...form, name: form.name.trim(), settings, members });
      notify('success', 'Inventario creado', `${inv.name} · grupo ${inv.group?.name}`);
      reload();
      navigate(`/gestion/inventarios/${inv.key}`);
    } catch (err) {
      setError(err as ApiError);
      setErrors((err as ApiError).fields ?? {});
    } finally {
      setBusy(false);
    }
  };

  if (groups.loading && !groups.data) return <Loading />;
  const free = (groups.data ?? []).filter((g) => !g.inventory_key);
  return (
    <div className="stack">
      <ManageBack title="Nuevo inventario" description="Se crea vacío (sin productos de ejemplo) y asociado al grupo que elija." />
      <ErrorAlert error={error} />
      {!free.length && (
        <Alert kind="info" title="No tiene grupos sin inventario">
          Cada grupo tiene un solo inventario. <Link to="/grupos">Cree un grupo</Link> e invite a sus integrantes; luego cree aquí su inventario.
        </Alert>
      )}
      <Card title="Datos del inventario">
        <div className="card-body stack">
          <SelectField label="Grupo al que pertenece" required value={form.group} error={errors.group} placeholder="Elija un grupo…"
            onChange={(v) => setForm({ ...form, group: v })}
            options={(groups.data ?? []).map((g) => ({ value: g.key, label: g.inventory_key ? `${g.name} (ya tiene «${g.inventory_name}»)` : g.name,
              disabled: Boolean(g.inventory_key) }))} />
          <TextField label="Nombre del inventario" required value={form.name} error={errors.name} maxLength={80}
            onChange={(v) => setForm({ ...form, name: v })} placeholder="Ej.: Inventario Sucursal Armenia" />
          <TextArea label="Descripción (opcional)" value={form.description} maxLength={300} error={errors.description}
            onChange={(v) => setForm({ ...form, description: v })} />
        </div>
      </Card>
      <Card title="Configuración inicial">
        <div className="card-body">
          {perms.data && <SettingsFields settings={settings} setSettings={setSettings} perms={perms.data} />}
        </div>
      </Card>
      {group && (
        <Card title={`Integrantes autorizados de ${group.name}`}>
          <div className="card-body stack">
            {!group.members.length ? <p className="muted">El grupo aún no tiene integrantes. Los que se unan quedarán autorizados según la configuración.</p>
              : group.members.map((m) => (
                <Checkbox key={m.id} label={`${m.full_name} (${m.username})`} checked={Boolean(authorized[m.id])}
                  hint={authorized[m.id] ? 'Con los permisos iniciales' : 'Sin acceso a este inventario'}
                  onChange={(v) => setAuthorized({ ...authorized, [m.id]: v })} />
              ))}
          </div>
        </Card>
      )}
      <div className="row">
        <Button onClick={() => navigate('..')}>Cancelar</Button>
        <Button variant="primary" busy={busy} icon={<Save size={20} />} onClick={submit}>Crear inventario</Button>
      </div>
    </div>
  );
}

function InventoryDetail() {
  const { key } = useParams();
  const navigate = useNavigate();
  const { notify } = useToast();
  const { select, reload } = useInventory();
  const inv = useApi<any>(`/inventories/${key}`);
  const groups = useApi<GroupOpt[]>('/inventories/groups');
  const perms = useApi<Perm[]>('/inventories/permissions');
  const [form, setForm] = useState<any>(null);
  const [settings, setSettings] = useState<any>(null);
  const [members, setMembers] = useState<Record<number, string[] | null>>({});
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const d = inv.data;
  useEffect(() => {
    if (!d) return;
    setForm({ name: d.name, description: d.description, group: d.group?.public_id ?? '' });
    setSettings(d.settings);
    setMembers({});
  }, [d]);
  const history = useMemo(() => d?.history ?? {}, [d]);
  const hasHistory = useMemo(() => Object.values(history).some((v) => Number(v) > 0), [history]);

  const save = async (extra: Record<string, unknown> = {}, ok = 'Cambios guardados') => {
    setBusy(true);
    setError(null);
    try {
      const body: Record<string, unknown> = { name: form.name, description: form.description, settings, version: d.version, ...extra };
      if (form.group && form.group !== d.group?.public_id) body.group = form.group;
      const changed = Object.entries(members).map(([uid, p]) => ({ user_id: Number(uid), permissions: p }));
      if (changed.length) body.members = changed;
      await put(`/inventories/${key}`, body);
      notify('success', ok);
      inv.reload();
      groups.reload();
      reload();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    setConfirm(false);
    setBusy(true);
    try {
      await del(`/inventories/${key}`);
      notify('success', 'Inventario eliminado');
      reload();
      navigate('/gestion/inventarios');
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };

  if (inv.loading && !d) return <Loading />;
  if (inv.error) return <ErrorState error={inv.error} onRetry={inv.reload} />;
  if (!form || !settings) return <Loading />;
  const groupOpts = (groups.data ?? []).filter((g) => !g.inventory_key || g.inventory_key === key);
  return (
    <div className="stack">
      <ManageBack title={d.name} description={d.group ? `Grupo ${d.group.name}` : 'Sin grupo asociado'} actions={<>
        <Badge kind={STATUS_KIND[d.status]}>{STATUS_LABEL[d.status]}</Badge>
        <Button icon={<ArrowRight size={18} />} onClick={() => { select(d.key); navigate('/inventario/movimientos'); }}>Ver productos y movimientos</Button>
      </>} />
      <ErrorAlert error={error} />
      {!d.group && (
        <Alert kind="warning" title="Asocie este inventario a un grupo">
          Mientras no tenga grupo, solo entran usted y los empleados que no pertenecen a ningún grupo. Al asociarlo, los integrantes del grupo
          quedan autorizados según la configuración (no se mueve ni se borra ningún dato).
        </Alert>
      )}
      <div className="grid-2">
        <Card title="Datos">
          <div className="card-body stack">
            <TextField label="Nombre" value={form.name} maxLength={80} onChange={(v) => setForm({ ...form, name: v })} />
            <TextArea label="Descripción" value={form.description} maxLength={300} onChange={(v) => setForm({ ...form, description: v })} />
            <SelectField label="Grupo asociado" value={form.group} placeholder={d.group ? undefined : 'Elija un grupo…'}
              onChange={(v) => setForm({ ...form, group: v })}
              options={groupOpts.map((g) => ({ value: g.key, label: g.name }))}
              hint="Cada grupo tiene un solo inventario. Solo aparecen sus grupos sin inventario." />
            <dl className="dl">
              <dt>Productos</dt><dd>{d.products}</dd>
              <dt>Existencias</dt><dd>{qty(d.stock)}</dd>
              <dt>Ventas</dt><dd>{history.sales}</dd>
              <dt>Movimientos</dt><dd>{history.movements}</dd>
              <dt>Creado</dt><dd>{dateTime(d.created_at)}</dd>
            </dl>
          </div>
        </Card>
        <Card title="Configuración de este inventario">
          <div className="card-body">
            {perms.data && <SettingsFields settings={settings} setSettings={setSettings} perms={perms.data} />}
          </div>
        </Card>
      </div>
      <Card title="Integrantes y permisos">
        <div className="card-body stack">
          <p className="muted">Cada integrante necesita el permiso en este inventario y también en su usuario (Gestión › Usuarios).</p>
          {!d.members.length ? <p className="muted">No hay integrantes.</p> : (
            <ul className="result-list">
              {d.members.map((m: any) => {
                const value = members[m.id] !== undefined ? members[m.id] : m.custom ? m.permissions : null;
                // Sin cambios locales se muestra lo que calculó el servidor (permisos de usuario Y restricción del inventario).
                const effective: string[] = value ?? (members[m.id] === null ? m.effective : m.custom ? m.permissions : m.effective) ?? [];
                return (
                  <li key={m.id} className="result-item" style={{ display: 'block', cursor: 'default' }}>
                    <div className="row" style={{ justifyContent: 'space-between' }}>
                      <span><strong>{m.full_name}</strong> <span className="muted">({m.username})</span>
                        {!m.in_group && <> <Badge kind="warning">Ya no está en el grupo</Badge></>}
                        <br /><small className="muted">{value === null ? 'Permisos iniciales del inventario' : 'Permisos propios'} ·
                          {` ${effective.length ? `${effective.length} permiso(s)` : 'sin acceso'}`}</small></span>
                      <span className="row" style={{ gap: 6 }}>
                        <Button size="sm" variant="ghost" onClick={() => setOpen(open === m.id ? null : m.id)}>{open === m.id ? 'Cerrar' : 'Editar permisos'}</Button>
                        <Button size="sm" variant="ghost" onClick={() => setMembers({ ...members, [m.id]: [] })}>Quitar acceso</Button>
                      </span>
                    </div>
                    {open === m.id && perms.data && (
                      <Fragment>
                        <PermissionChecklist idPrefix={`m${m.id}`} perms={perms.data} value={effective}
                          onChange={(v) => setMembers({ ...members, [m.id]: v })} />
                        <Button size="sm" variant="ghost" onClick={() => setMembers({ ...members, [m.id]: null })}>Usar los permisos iniciales</Button>
                      </Fragment>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </Card>
      <div className="row">
        <Button variant="primary" busy={busy} icon={<Save size={20} />} onClick={() => save()}>Guardar cambios</Button>
        {d.status !== 'activo' ? <Button icon={<Power size={18} />} busy={busy} onClick={() => save({ status: 'activo' }, 'Inventario activado')}>Activar</Button> : (
          <Button icon={<Power size={18} />} busy={busy} onClick={() => save({ status: 'inactivo' }, 'Inventario desactivado')}>Desactivar</Button>)}
        {d.status !== 'archivado' && <Button icon={<Archive size={18} />} busy={busy} onClick={() => save({ status: 'archivado' }, 'Inventario archivado')}>Archivar</Button>}
        <Button variant="danger" icon={<Trash2 size={18} />} disabled={hasHistory || busy} onClick={() => setConfirm(true)}
          title={hasHistory ? 'Tiene historia: desactívelo o archívelo' : undefined}>Eliminar</Button>
      </div>
      {hasHistory && <p className="muted">No se puede eliminar porque tiene historia ({history.products} productos, {history.sales} ventas, {history.movements} movimientos). Desactívelo o archívelo: la información se conserva.</p>}
      <ConfirmDialog open={confirm} danger title="Eliminar inventario" confirmLabel="Eliminar" onClose={() => setConfirm(false)} onConfirm={remove}
        message={`¿Eliminar «${d.name}»? Está vacío; sus integrantes dejarán de verlo.`} />
    </div>
  );
}

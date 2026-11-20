import { Boxes, Briefcase, ClipboardList, Cloud, CloudOff, LineChart, LogOut, RefreshCw, Settings, ShoppingCart, TriangleAlert, Users, WifiOff } from 'lucide-react';
import { Suspense, useEffect, useRef, useState } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../../context/Auth';
import { InventoryProvider, useInventory } from '../../context/Inventory';
import { useApi, useOnline } from '../../lib/hooks';
import { useRealtimeConnection, useRealtimeEvents, useRealtimeStatus } from '../../lib/realtime';
import { Button } from '../ui/Button';
import { ConfirmDialog } from '../ui/Dialog';
import { Loading } from '../ui/Feedback';
import { UpdatePrompt } from './UpdatePrompt';

export interface Section { to: string; label: string; short?: string; icon: typeof Boxes; visible: boolean }

export function useSections(): Section[] {
  const { can, canAny } = useAuth();
  return [
    { to: '/inventario', label: 'Inventario', icon: Boxes, visible: can('inventario.ver') },
    { to: '/vender', label: 'Vender', icon: ShoppingCart, visible: canAny('ventas.vender', 'documentos.ver', 'ventas.historial') },
    { to: '/finanzas', label: 'Finanzas', icon: LineChart, visible: can('finanzas.ver') },
    { to: '/gestion', label: 'Gestión', icon: Briefcase, visible: canAny('gestion.usuarios', 'gestion.configuracion',
      'gestion.integraciones', 'gestion.respaldos', 'gestion.auditoria', 'terceros.gestionar') },
    { to: '/tareas', label: 'Notas y tareas', short: 'Tareas', icon: ClipboardList, visible: true },
    { to: '/grupos', label: 'Grupos', icon: Users, visible: true },
  ].filter((s) => s.visible);
}

const TITLES: [RegExp, string][] = [
  [/^\/inventario/, 'Inventario'], [/^\/vender\/documentos/, 'Cotizaciones y órdenes'], [/^\/vender\/historial/, 'Historial de ventas'],
  [/^\/vender/, 'Vender'], [/^\/finanzas/, 'Finanzas'], [/^\/gestion/, 'Gestión'], [/^\/configuracion/, 'Configuración'],
  [/^\/tareas/, 'Notas y tareas'], [/^\/grupos/, 'Grupos de trabajo'], [/^\/unirse/, 'Invitación'],
];

export function AppShell() {
  return <InventoryProvider><Shell /></InventoryProvider>;
}

/** Inventario activo. Con 2 se cambia con una lista simple; con 3 o más, desde el panel de selección. */
function InventorySwitcher() {
  const { options, current, select } = useInventory();
  if (!current) return null;
  const label = current.group ? `${current.name} · ${current.group.name}` : current.name;
  if (options.length < 2) return <span className="inventory-chip" title={`Inventario activo: ${label}`}>{current.name}</span>;
  if (options.length >= 3) {
    return (
      <Link to="/inventario/seleccionar" className="btn btn-outline btn-sm inventory-switch-btn" title={`Inventario activo: ${label}. Cambiar…`}>
        <Boxes size={16} aria-hidden /> <span className="inventory-chip-text">{current.name}</span>
      </Link>
    );
  }
  return (
    <label className="inventory-switch">
      <span className="sr-only">Inventario</span>
      <select className="input" value={current.key} onChange={(e) => select(e.target.value)} title={`Inventario activo: ${label}`}>
        {options.map((o) => <option key={o.key} value={o.key}>{o.name}{o.group ? ` · ${o.group.name}` : ''}{o.status !== 'activo' ? ` (${o.status})` : ''}</option>)}
      </select>
    </label>
  );
}

/** Versión mínima del esquema que necesita esta interfaz. Si el servidor en ejecución es anterior (se actualizó el
 *  programa sin reiniciar el servidor), se avisa en lugar de fallar con permisos o datos incompletos. */
export const REQUIRED_SCHEMA = 13;

function ServerVersionNotice() {
  const health = useApi<{ schema: number; version: string }>('/health');
  if (typeof health.data?.schema !== 'number' || health.data.schema >= REQUIRED_SCHEMA) return null;
  return (
    <div className="offline-banner" role="alert">
      <TriangleAlert size={20} aria-hidden />
      El servidor está ejecutando una versión anterior del programa (esquema {health.data.schema}). Ciérrelo y vuelva a
      iniciarlo con iniciar.cmd para completar la actualización; mientras tanto algunas secciones pueden no funcionar.
    </div>
  );
}

/** Estado de la sincronización con el servidor (fuente de verdad del inventario). */
export function SyncIndicator() {
  const online = useOnline();
  const status = useRealtimeStatus();
  const [label, kind, Icon] = !online ? ['Sin conexión', 'danger', CloudOff] as const
    : status === 'conectado' ? ['Sincronizado', 'success', Cloud] as const
      : status === 'desconectado' ? ['Error de sincronización', 'warning', TriangleAlert] as const
        : ['Sincronizando…', 'info', RefreshCw] as const;
  return (
    <span className={`badge badge-${kind} sync-status`} role="status" aria-live="polite" title="Estado de sincronización con el servidor">
      <Icon size={16} aria-hidden /> <span className="sync-label">{label}</span>
    </span>
  );
}

function Shell() {
  const { current } = useInventory();
  const { user, company, logout, directSession, access, refresh } = useAuth();
  // Canal de tiempo real mientras haya sesión: grupos, presencia y cambios en la propia cuenta.
  useRealtimeConnection(true);
  useRealtimeEvents((e) => { if (e.type === 'cuenta' || e.type === 'sesion') void refresh(); });
  const direct = directSession && Boolean(access?.setup_completed) && !access?.login_enabled;
  const sections = useSections();
  const online = useOnline();
  const location = useLocation();
  const mainRef = useRef<HTMLElement>(null);
  const [confirmLogout, setConfirmLogout] = useState(false);
  const title = TITLES.find(([re]) => re.test(location.pathname))?.[1] ?? 'POS-PY';

  useEffect(() => {
    document.title = `${title} · ${company?.name ?? 'POS-PY'}`;
    window.scrollTo({ top: 0 });       // solo el contenido vuelve arriba; la navegación no se mueve
  }, [title, company, location.pathname]);

  return (
    <div className="shell">
      <a className="skip-link" href="#contenido">Saltar al contenido</a>
      <aside className="sidebar" aria-label="Navegación principal">
        <Link to="/" className="brand">
          <img src="/api/company/logo" alt="" onError={(e) => { (e.target as HTMLImageElement).src = '/icons/icon.svg'; }} />
          <span className="brand-name">{company?.name ?? 'POS-PY'}</span>
        </Link>
        <nav className="nav">
          {sections.map(({ to, label, short, icon: Icon }) => (
            <NavLink key={to} to={to} aria-label={short ? label : undefined}
              className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
              <Icon size={26} aria-hidden />
              {/* En el teléfono (barra inferior) se usa el rótulo corto, si existe. */}
              <span className={`nav-label${short ? ' nav-full' : ''}`}>{label}</span>
              {short && <span className="nav-label nav-short">{short}</span>}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <NavLink to="/configuracion" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
            <Settings size={24} aria-hidden />
            <span className="nav-label">Configuración</span>
          </NavLink>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <span className="topbar-title">{title}</span>
          <div className="topbar-actions">
            <InventorySwitcher />
            <SyncIndicator />
            <div className="user-chip">
              <strong>{user?.full_name}</strong>
              <small>{user?.role === 'admin' ? 'Administrador' : 'Empleado'}{direct ? ' · acceso directo' : ''}</small>
            </div>
            <Link to="/configuracion" className="btn btn-ghost btn-icon" title="Configuración">
              <Settings size={22} aria-hidden /><span className="sr-only">Configuración</span>
            </Link>
            <Button variant="outline" icon={<LogOut size={20} />} onClick={() => setConfirmLogout(true)}>{direct ? 'Cambiar de perfil' : 'Salir'}</Button>
          </div>
        </header>
        {!online && (
          <div className="offline-banner" role="status">
            <WifiOff size={20} aria-hidden />
            Sin conexión con el servidor. Puede consultar el catálogo guardado; vender y guardar cambios requieren conexión.
          </div>
        )}
        <UpdatePrompt />
        <ServerVersionNotice />
        <main id="contenido" className="content" ref={mainRef} tabIndex={-1} key={`${location.pathname.split('/')[1]}:${current?.key ?? ''}`}>
          <Suspense fallback={<Loading />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
      <ConfirmDialog open={confirmLogout} title="Cerrar sesión" message="¿Desea cerrar la sesión en este equipo?"
        confirmLabel="Cerrar sesión" onClose={() => setConfirmLogout(false)} onConfirm={() => { setConfirmLogout(false); void logout(); }} />
    </div>
  );
}

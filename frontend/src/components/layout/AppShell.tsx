import { Boxes, Briefcase, LineChart, LogOut, Settings, ShoppingCart, WifiOff } from 'lucide-react';
import { Suspense, useEffect, useRef, useState } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../../context/Auth';
import { useOnline } from '../../lib/hooks';
import { Button } from '../ui/Button';
import { ConfirmDialog } from '../ui/Dialog';
import { Loading } from '../ui/Feedback';
import { UpdatePrompt } from './UpdatePrompt';

export interface Section { to: string; label: string; icon: typeof Boxes; visible: boolean }

export function useSections(): Section[] {
  const { can, canAny } = useAuth();
  return [
    { to: '/inventario', label: 'Inventario', icon: Boxes, visible: can('inventario.ver') },
    { to: '/vender', label: 'Vender', icon: ShoppingCart, visible: canAny('ventas.vender', 'documentos.ver', 'ventas.historial') },
    { to: '/finanzas', label: 'Finanzas', icon: LineChart, visible: can('finanzas.ver') },
    { to: '/gestion', label: 'Gestión', icon: Briefcase, visible: canAny('gestion.usuarios', 'gestion.configuracion',
      'gestion.integraciones', 'gestion.respaldos', 'gestion.auditoria', 'terceros.gestionar') },
  ].filter((s) => s.visible);
}

const TITLES: [RegExp, string][] = [
  [/^\/inventario/, 'Inventario'], [/^\/vender\/documentos/, 'Cotizaciones y órdenes'], [/^\/vender\/historial/, 'Historial de ventas'],
  [/^\/vender/, 'Vender'], [/^\/finanzas/, 'Finanzas'], [/^\/gestion/, 'Gestión'], [/^\/configuracion/, 'Configuración'],
];

export function AppShell() {
  const { user, company, logout } = useAuth();
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
          {sections.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
              <Icon size={26} aria-hidden />
              <span className="nav-label">{label}</span>
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
            <div className="user-chip">
              <strong>{user?.full_name}</strong>
              <small>{user?.role === 'admin' ? 'Administrador' : 'Empleado'}</small>
            </div>
            <Link to="/configuracion" className="btn btn-ghost btn-icon" title="Configuración">
              <Settings size={22} aria-hidden /><span className="sr-only">Configuración</span>
            </Link>
            <Button variant="outline" icon={<LogOut size={20} />} onClick={() => setConfirmLogout(true)}>Salir</Button>
          </div>
        </header>
        {!online && (
          <div className="offline-banner" role="status">
            <WifiOff size={20} aria-hidden />
            Sin conexión con el servidor. Puede consultar el catálogo guardado; vender y guardar cambios requieren conexión.
          </div>
        )}
        <UpdatePrompt />
        <main id="contenido" className="content" ref={mainRef} tabIndex={-1} key={location.pathname.split('/')[1]}>
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

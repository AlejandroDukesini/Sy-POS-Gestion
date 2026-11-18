import { Lock } from 'lucide-react';
import { lazy, Suspense, useCallback, useEffect, useState, type ReactNode } from 'react';
import { BrowserRouter, Link, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { get } from './api/client';
import { AppShell, useSections } from './components/layout/AppShell';
import { EmptyState, Loading } from './components/ui/Feedback';
import { AuthProvider, useAuth } from './context/Auth';
import { PrefsProvider } from './context/Prefs';
import { ToastProvider } from './context/Toast';
import { ChangePasswordPage } from './pages/ChangePassword';
import { LoginPage } from './pages/Login';
import { ProfilesPage } from './pages/Profiles';
import { SetupPage, type SetupStatus } from './pages/Setup';

const InventoryPage = lazy(() => import('./pages/inventory/InventoryPage'));
const SellPage = lazy(() => import('./pages/sell/SellPage'));
const FinanceRoutes = lazy(() => import('./pages/finance/FinanceRoutes'));
const ManageRoutes = lazy(() => import('./pages/manage/ManageRoutes'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));
const SetupWizard = lazy(() => import('./pages/SetupWizard').then((m) => ({ default: m.SetupWizard })));
const TasksPage = lazy(() => import('./pages/tasks/TasksPage'));
const GroupsRoutes = lazy(() => import('./pages/groups/GroupsPage'));
const JoinPage = lazy(() => import('./pages/groups/JoinPage'));

/** La interfaz oculta lo no autorizado por comodidad; la autorización real la hace el backend. */
export function RequirePermission({ any, children }: { any: string[]; children: ReactNode }) {
  const { canAny } = useAuth();
  if (!canAny(...any)) {
    return (
      <EmptyState title="No tiene permiso para esta sección" icon={<Lock size={40} aria-hidden />}>
        <p>Si lo necesita, pida a un administrador que se lo asigne en Gestión › Usuarios.</p>
        <Link to="/" className="btn btn-outline">Ir al inicio</Link>
      </EmptyState>
    );
  }
  return <>{children}</>;
}

function Home() {
  const sections = useSections();
  if (!sections.length) return <Navigate to="/configuracion" replace />;
  return <Navigate to={sections[0].to} replace />;
}

const MANAGE_PERMS = ['gestion.usuarios', 'gestion.configuracion', 'gestion.integraciones', 'gestion.respaldos',
  'gestion.auditoria', 'terceros.gestionar'];

function AuthenticatedApp() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Home />} />
        <Route path="inventario/*" element={<RequirePermission any={['inventario.ver']}><InventoryPage /></RequirePermission>} />
        <Route path="vender/*" element={
          <RequirePermission any={['ventas.vender', 'documentos.ver', 'ventas.historial']}><SellPage /></RequirePermission>} />
        <Route path="finanzas/*" element={<RequirePermission any={['finanzas.ver']}><FinanceRoutes /></RequirePermission>} />
        <Route path="gestion/*" element={<RequirePermission any={MANAGE_PERMS}><ManageRoutes /></RequirePermission>} />
        <Route path="configuracion/*" element={<SettingsPage />} />
        <Route path="tareas/*" element={<TasksPage />} />
        <Route path="grupos/*" element={<GroupsRoutes />} />
        <Route path="unirse/:token" element={<JoinPage />} />
        <Route path="*" element={<EmptyState title="Página no encontrada"><Link to="/" className="btn btn-outline">Ir al inicio</Link></EmptyState>} />
      </Route>
    </Routes>
  );
}

/**
 * Qué pantalla mostrar al arrancar:
 *  1. Configuración inicial pendiente → asistente (sin cuenta; continúa en el último paso guardado).
 *  2. Inicio de sesión activado → pantalla de ingreso.
 *  3. Inicio de sesión desactivado → elegir perfil (acceso directo), con los permisos de cada persona.
 */
function Gate() {
  const { status, mustChangePassword, user, access } = useAuth();
  const location = useLocation();
  // Enlace de invitación abierto sin sesión: se pide ingresar y, al hacerlo, la misma dirección muestra la invitación.
  const inviteNotice = location.pathname.startsWith('/unirse/')
    ? 'Le invitaron a un grupo de trabajo. Inicie sesión con su cuenta para ver la invitación; si no tiene cuenta, pídala al administrador.'
    : undefined;
  const [setup, setSetup] = useState<SetupStatus | null>(null);
  const checkSetup = useCallback(() => {
    get<SetupStatus>('/setup/status').then(setSetup).catch(() => setSetup({ needs_setup: false } as SetupStatus));
  }, []);
  // Se vuelve a consultar al iniciar o cerrar sesión (el modo de acceso puede haber cambiado).
  useEffect(checkSetup, [checkSetup, status]);

  if (status === 'loading' || setup === null) return <Loading label="Iniciando POS-PY…" />;
  if (setup.needs_setup) {
    if (status === 'authenticated' && user?.role === 'admin' && access && !access.setup_completed) {
      return <Suspense fallback={<Loading />}><SetupWizard initialStep={access.setup_step} onDone={checkSetup} /></Suspense>;
    }
    if (status === 'anonymous') return <SetupPage status={setup} />;
  }
  if (status === 'anonymous') return setup.direct_access ? <ProfilesPage /> : <LoginPage notice={inviteNotice} />;
  if (mustChangePassword) return <ChangePasswordPage />;
  return <AuthenticatedApp />;
}

export default function App() {
  return (
    <BrowserRouter>
      <ToastProvider>
        <AuthProvider>
          <PrefsProvider>
            <Gate />
          </PrefsProvider>
        </AuthProvider>
      </ToastProvider>
    </BrowserRouter>
  );
}

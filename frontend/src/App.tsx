import { Lock } from 'lucide-react';
import { lazy, useCallback, useEffect, useState, type ReactNode } from 'react';
import { BrowserRouter, Link, Navigate, Route, Routes } from 'react-router-dom';
import { get } from './api/client';
import { AppShell, useSections } from './components/layout/AppShell';
import { EmptyState, Loading } from './components/ui/Feedback';
import { AuthProvider, useAuth } from './context/Auth';
import { PrefsProvider } from './context/Prefs';
import { ToastProvider } from './context/Toast';
import { ChangePasswordPage } from './pages/ChangePassword';
import { LoginPage } from './pages/Login';
import { SetupPage } from './pages/Setup';

const InventoryPage = lazy(() => import('./pages/inventory/InventoryPage'));
const SellPage = lazy(() => import('./pages/sell/SellPage'));
const FinanceRoutes = lazy(() => import('./pages/finance/FinanceRoutes'));
const ManageRoutes = lazy(() => import('./pages/manage/ManageRoutes'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));

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
        <Route path="*" element={<EmptyState title="Página no encontrada"><Link to="/" className="btn btn-outline">Ir al inicio</Link></EmptyState>} />
      </Route>
    </Routes>
  );
}

function Gate() {
  const { status, mustChangePassword } = useAuth();
  const [setup, setSetup] = useState<any>(null);
  const checkSetup = useCallback(() => {
    get('/setup/status').then(setSetup).catch(() => setSetup({ needs_setup: false }));
  }, []);
  useEffect(checkSetup, [checkSetup]);

  if (status === 'loading' || setup === null) return <Loading label="Iniciando POS-PY…" />;
  if (setup.needs_setup) return <SetupPage status={setup} onDone={checkSetup} />;
  if (status === 'anonymous') return <LoginPage />;
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

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AppShell } from '../components/layout/AppShell';
import { AuthProvider } from '../context/Auth';
import { ToastProvider } from '../context/Toast';
import { LoginPage } from '../pages/Login';

type Handler = (url: string, init?: RequestInit) => unknown;

function mockApi(handler: Handler) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    const result = handler(url, init) as any;
    if (result instanceof Response) return result;
    return new Response(JSON.stringify(result ?? {}), { status: 200, headers: { 'content-type': 'application/json' } });
  });
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

function me(role: 'admin' | 'employee', permissions: string[]) {
  return { user: { id: 1, username: 'u', full_name: 'Usuaria', role, permissions }, must_change_password: false,
    company: { name: 'Ferretería', primary_color: '#1d4ed8', currency_symbol: '$', timezone: 'America/Bogota' }, desktop: false };
}

afterEach(() => vi.restoreAllMocks());

describe('pantalla de ingreso', () => {
  it('muestra el formulario a la izquierda y el espacio «Aquí tu logo»', async () => {
    mockApi((url) => (url.endsWith('/company/public') ? { name: 'X', has_logo: false } : json(401, {})));
    render(<ToastProvider><AuthProvider><LoginPage /></AuthProvider></ToastProvider>);
    expect(screen.getByRole('heading', { name: 'Iniciar sesión' })).toBeInTheDocument();
    expect(await screen.findByText('Aquí tu logo')).toBeInTheDocument();
  });

  it('valida campos junto a cada uno y muestra el error del servidor', async () => {
    const calls: string[] = [];
    mockApi((url) => {
      calls.push(url);
      if (url.endsWith('/auth/login')) return json(401, { error: 'Sesión no válida', detail: 'Usuario o contraseña incorrectos.', fields: {} });
      if (url.endsWith('/company/public')) return { name: 'X', has_logo: false };
      return json(401, {});
    });
    const user = userEvent.setup();
    render(<ToastProvider><AuthProvider><LoginPage /></AuthProvider></ToastProvider>);
    await user.click(screen.getByRole('button', { name: /Ingresar/ }));
    expect(screen.getByText('Escriba su usuario.')).toBeInTheDocument();
    expect(screen.getByLabelText(/Usuario/)).toHaveAttribute('aria-invalid', 'true');
    expect(calls.some((c) => c.endsWith('/auth/login'))).toBe(false);
    await user.type(screen.getByLabelText(/Usuario/), 'ana');
    await user.type(screen.getByLabelText(/Contraseña/), 'mala clave 1');
    await user.click(screen.getByRole('button', { name: /Ingresar/ }));
    expect(await screen.findByText('Usuario o contraseña incorrectos.')).toBeInTheDocument();
  });
});

function renderShell(role: 'admin' | 'employee', permissions: string[], path = '/inventario') {
  mockApi((url) => (url.endsWith('/me') ? me(role, permissions) : {}));
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ToastProvider>
        <AuthProvider>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="inventario" element={<p>Contenido inventario</p>} />
              <Route path="vender" element={<p>Contenido vender</p>} />
            </Route>
          </Routes>
        </AuthProvider>
      </ToastProvider>
    </MemoryRouter>,
  );
}

const ALL = ['inventario.ver', 'ventas.vender', 'finanzas.ver', 'gestion.usuarios', 'documentos.ver'];

describe('navegación por rol', () => {
  it('el administrador ve las cuatro secciones', async () => {
    renderShell('admin', ALL);
    await waitFor(() => expect(screen.getByRole('link', { name: 'Finanzas' })).toBeInTheDocument());
    for (const name of ['Inventario', 'Vender', 'Finanzas', 'Gestión']) expect(screen.getByRole('link', { name })).toBeInTheDocument();
  });

  it('el empleado solo ve lo que tiene permitido', async () => {
    renderShell('employee', ['inventario.ver', 'ventas.vender']);
    await waitFor(() => expect(screen.getByRole('link', { name: 'Vender' })).toBeInTheDocument());
    expect(screen.queryByRole('link', { name: 'Finanzas' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Gestión' })).not.toBeInTheDocument();
  });

  it('la barra lateral no se vuelve a montar ni cambia al navegar', async () => {
    const user = userEvent.setup();
    renderShell('admin', ALL);
    await waitFor(() => expect(screen.getByRole('link', { name: 'Vender' })).toBeInTheDocument());
    const sidebar = screen.getByLabelText('Navegación principal');
    const before = [...sidebar.querySelectorAll('a')].map((a) => a.className.replace(' active', ''));
    await user.click(screen.getByRole('link', { name: 'Vender' }));
    expect(await screen.findByText('Contenido vender')).toBeInTheDocument();
    expect(screen.getByLabelText('Navegación principal')).toBe(sidebar);
    expect([...sidebar.querySelectorAll('a')].map((a) => a.className.replace(' active', ''))).toEqual(before);
    expect(screen.getByRole('link', { name: 'Vender' })).toHaveClass('active');
  });
});

// ------------------------------------------------------------------ arranque: asistente, ingreso o acceso directo
describe('pantalla inicial según la configuración', () => {
  const status = (over: Record<string, unknown>) => ({ needs_setup: false, setup_step: 'listo', login_enabled: true,
    direct_access: false, local: true, code_file: null, code_injected: false, ...over });

  async function renderApp(handler: Handler) {
    const { default: App } = await import('../App');
    mockApi(handler);
    return render(<App />);
  }

  it('primera ejecución: muestra el asistente sin pedir cuenta', async () => {
    await renderApp((url) => (url.endsWith('/setup/status') ? status({ needs_setup: true, setup_step: 'empresa', login_enabled: false,
      code_file: 'C:/datos/setup-code.txt' }) : url.endsWith('/company/public') ? { name: 'X', has_logo: false } : json(401, {})));
    expect(await screen.findByRole('heading', { name: 'Bienvenido a POS-PY' })).toBeInTheDocument();
    expect(screen.getByText(/No necesita una cuenta/)).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Iniciar sesión' })).not.toBeInTheDocument();
  });

  it('autenticación activada: muestra el inicio de sesión', async () => {
    await renderApp((url) => (url.endsWith('/setup/status') ? status({}) : url.endsWith('/company/public') ? { name: 'X', has_logo: false } : json(401, {})));
    expect(await screen.findByRole('heading', { name: 'Iniciar sesión' })).toBeInTheDocument();
  });

  it('autenticación desactivada: se elige el perfil y el administrador con contraseña la pide', async () => {
    const calls: string[] = [];
    await renderApp((url) => {
      calls.push(url);
      if (url.endsWith('/setup/status')) return status({ login_enabled: false, direct_access: true });
      if (url.endsWith('/auth/profiles')) return [
        { id: 2, username: 'ana', full_name: 'Ana Caja', role: 'employee', requires_password: false },
        { id: 1, username: 'jefa', full_name: 'La Jefa', role: 'admin', requires_password: true }];
      if (url.endsWith('/company/public')) return { name: 'X', has_logo: false };
      return json(401, {});
    });
    const user = userEvent.setup();
    expect(await screen.findByRole('heading', { name: '¿Quién está trabajando?' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /La Jefa/ }));
    expect(await screen.findByRole('heading', { name: 'Iniciar sesión' })).toBeInTheDocument();
    expect(screen.getByLabelText(/Usuario/)).toHaveValue('jefa');
    expect(calls.some((c) => c.endsWith('/auth/open'))).toBe(false);
    await user.click(screen.getByRole('button', { name: /Volver a la lista/ }));
    await user.click(await screen.findByRole('button', { name: /Ana Caja/ }));
    await waitFor(() => expect(calls.some((c) => c.endsWith('/auth/open'))).toBe(true));
  });
});

describe('tareas', () => {
  it('cualquier empleado ve la sección Tareas', async () => {
    renderShell('employee', ['inventario.ver']);
    expect(await screen.findByRole('link', { name: 'Tareas' })).toBeInTheDocument();
  });
});

describe('proveedores', () => {
  it('la vista general muestra indicadores, pendientes y última visita', async () => {
    const { SuppliersPage } = await import('../pages/suppliers/SuppliersPage');
    mockApi((url) => (url.includes('/suppliers') ? {
      recent_visit_days: 30,
      metrics: { total: 3, active: 2, with_pending: 1, recent_visits: 1, with_quotes: 2 },
      items: [{ id: 7, name: 'Distribuidora Andina', identification: '900', phone: '555', whatsapp: '300', city: 'Cali', active: 1,
        advisor_name: 'Laura', pending_notes: 2, important_notes: 1, last_visit: '2026-11-01', recent_visit: true, quotes: 4 }],
    } : url.endsWith('/me') ? me('admin', ['terceros.gestionar']) : {}));
    render(<MemoryRouter><ToastProvider><AuthProvider><SuppliersPage /></AuthProvider></ToastProvider></MemoryRouter>);
    expect(await screen.findByText('Distribuidora Andina')).toBeInTheDocument();
    expect(screen.getByText('Con pendientes')).toBeInTheDocument();
    expect(screen.getByText('Laura')).toBeInTheDocument();
    expect(screen.getByText('Reciente')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Nuevo proveedor' })).toBeInTheDocument();
  });
});

describe('informes de ingresos', () => {
  it('un acceso rápido genera la vista previa con cierre anticipado y totales reales', async () => {
    const preview = (await import('./fixtures/report-preview.json')).default;
    const { default: IncomeReportsRoutes } = await import('../pages/finance/IncomeReports');
    const calls: { url: string; body: any }[] = [];
    mockApi((url, init) => {
      if (init?.body) calls.push({ url, body: JSON.parse(String(init.body)) });
      if (url.endsWith('/me')) return me('admin', ['finanzas.ver', 'finanzas.cierres']);
      if (url.includes('/finance/reports/presets')) return { today: '2026-11-13', week_start: 'lunes', week_start_label: 'lunes', presets: [
        { key: 'semana_actual', label: 'Semana actual', kind: 'semanal', date_from: '2026-11-09', date_to: '2026-11-13' }] };
      if (url.includes('/finance/reports/preview')) return preview;
      if (url.includes('/finance/reports')) return { items: [] };
      return {};
    });
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={['/finanzas/informes']}><ToastProvider><AuthProvider><Routes>
      <Route path="/finanzas/informes/*" element={<IncomeReportsRoutes />} /></Routes></AuthProvider></ToastProvider></MemoryRouter>);
    await user.click(await screen.findByRole('button', { name: /Semana actual/ }));
    expect(calls[0]).toEqual({ url: '/api/finance/reports/preview', body: { kind: 'semanal', date_from: '2026-11-09', date_to: '2026-11-13' } });
    expect(await screen.findByText(/Cubre 5 de 7 días del periodo semanal/)).toBeInTheDocument();
    expect(screen.getAllByText('$ 51.000').length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: 'Guardar informe' })).toBeInTheDocument();
    expect(screen.queryByText('-$ 0')).not.toBeInTheDocument();
    expect(screen.getByText('Sin informes guardados')).toBeInTheDocument();
  });
});

describe('observaciones de inventario', () => {
  const META = {
    categories: [{ id: 1, code: 'diferencia_inventario', name: 'Diferencia de inventario' }], suppliers: [], users: [{ id: 1, full_name: 'Usuaria', active: 1 }],
    priorities: [{ value: 'baja', label: 'Baja' }, { value: 'critica', label: 'Crítica' }],
    statuses: [{ value: 'pendiente', label: 'Pendiente' }, { value: 'resuelta', label: 'Resuelta' }],
    max_file_mb: 10, max_files: 10, file_types: ['.pdf', '.png'], recent_days: 7,
  };
  const OBS = { id: 12, code: 'OBS-00012', product_id: 3, product_code: 'ACE-20W50', product_description: 'Aceite 20W50', product_unit: 'und',
    category_id: 1, category_name: 'Diferencia de inventario', priority: 'critica', status: 'pendiente', description: 'Faltan 5 unidades',
    qty: '5', reference_doc: '', detected_on: '2026-11-15', follow_up_date: null, responsible_name: 'Usuaria', created_by_name: 'Usuaria',
    created_at: '2026-11-15T14:00:00Z', updated_at: '2026-11-15T14:00:00Z', version: 1, is_open: true, follow_up_overdue: false };

  function renderObs(path: string) {
    return import('../pages/inventory/observations/ObservationsPage').then(({ default: ObservationsRoutes }) => render(
      <MemoryRouter initialEntries={[path]}><ToastProvider><AuthProvider><Routes>
        <Route path="/inventario/observaciones/*" element={<ObservationsRoutes />} /></Routes></AuthProvider></ToastProvider></MemoryRouter>));
  }

  it('el panel muestra indicadores reales, la tabla y los filtros rápidos combinados con la búsqueda', async () => {
    const calls: string[] = [];
    const handler: Handler = (url) => {
      calls.push(url);
      if (url.endsWith('/me')) return me('employee', ['inventario.ver', 'observaciones.ver']);
      if (url.includes('/observations/meta')) return META;
      if (url.includes('/observations?')) return { items: [OBS], total: 1, page: 1, pages: 1, page_size: 25,
        metrics: { total: 4, pendiente: 2, en_proceso: 1, resuelta: 1, cerrada: 0, criticas: 1, recientes: 3, seguimiento_vencido: 0 } };
      return {};
    };
    mockApi(handler);
    await renderObs('/inventario/observaciones');
    expect(await screen.findByText('OBS-00012')).toBeInTheDocument();
    expect(screen.getByText('Total de observaciones').nextSibling).toHaveTextContent('4');
    expect(within(screen.getByRole('table')).getByText('Crítica')).toHaveClass('obs-priority-critica');
    // Sin permiso de crear, editar ni eliminar no se ofrecen esas acciones.
    expect(screen.queryByRole('button', { name: 'Nueva observación' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Eliminar OBS/ })).not.toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole('tab', { name: 'Críticas' }));
    await user.type(screen.getByLabelText('Buscar'), 'aceite');
    await waitFor(() => expect(calls.some((c) => c.includes('quick=criticas') && c.includes('q=aceite'))).toBe(true));
  });

  it('la ficha muestra el historial cronológico y el acceso al producto', async () => {
    const handler: Handler = (url) => {
      if (url.endsWith('/me')) return me('admin', ['observaciones.ver', 'observaciones.estado', 'observaciones.comentar']);
      if (url.includes('/observations/meta')) return META;
      if (url.endsWith('/observations/12')) return { ...OBS, notes: '', files: [],
        product: { id: 3, code: 'ACE-20W50', description: 'Aceite 20W50', unit: 'und', active: 1, stock: '40', category_name: 'Lubricantes',
          last_supplier: { id: 2, name: 'Distribuidora Andina' }, open_observations: 1 },
        events: [
          { id: 1, kind: 'creada', from_value: null, to_value: 'pendiente', comment: 'Faltan 5 unidades', details: null, user_name: 'Usuaria', created_at: '2026-11-15T14:00:00Z' },
          { id: 2, kind: 'estado', from_value: 'pendiente', to_value: 'en_proceso', comment: 'Se inició revisión', details: null, user_name: 'Usuaria', created_at: '2026-11-16T14:00:00Z' },
        ] };
      return {};
    };
    mockApi(handler);
    await renderObs('/inventario/observaciones/12');
    expect(await screen.findByText('Historial de seguimiento')).toBeInTheDocument();
    expect(screen.getByText('Se inició revisión')).toBeInTheDocument();
    expect(screen.getByText('Distribuidora Andina')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Ficha del producto/ })).toHaveAttribute('href', '/inventario?producto=3');
    expect(screen.getByRole('button', { name: /Cambiar estado/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Agregar comentario/ })).toBeInTheDocument();
  });
});

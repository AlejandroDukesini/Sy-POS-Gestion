import { render, screen, waitFor } from '@testing-library/react';
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

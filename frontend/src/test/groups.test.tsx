import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider } from '../context/Auth';
import { ToastProvider } from '../context/Toast';
import GroupsRoutes from '../pages/groups/GroupsPage';
import JoinPage from '../pages/groups/JoinPage';

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

const ME = {
  user: { id: 7, username: 'ana', full_name: 'Ana Caja', role: 'employee', permissions: ['ventas.vender'] },
  must_change_password: false, desktop: false,
  company: { name: 'Ferretería', primary_color: '#1d4ed8', currency_symbol: '$', timezone: 'America/Bogota' },
};

function mockApi(routes: Record<string, (init?: RequestInit) => Response>) {
  const calls: { url: string; method: string }[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    calls.push({ url, method: init?.method ?? 'GET' });
    const key = Object.keys(routes).find((k) => url.endsWith(k));
    return key ? routes[key](init) : json(404, { error: 'No encontrado', detail: 'x' });
  });
  return calls;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ToastProvider>
        <AuthProvider>
          <Routes>
            <Route path="grupos/*" element={<GroupsRoutes />} />
            <Route path="unirse/:token" element={<JoinPage />} />
          </Routes>
        </AuthProvider>
      </ToastProvider>
    </MemoryRouter>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe('enlace de invitación', () => {
  it('muestra el grupo, confirma el ingreso y avisa el resultado', async () => {
    const calls = mockApi({
      '/api/me': () => json(200, ME),
      '/api/invitations/TOKEN123': () => json(200, {
        group: { public_id: 'G-1', name: 'Turno tarde', description: 'Caja', owner_name: 'Gerente General', member_count: 3,
          join_policy: 'automatica' },
        invitation: { expires_at: '2030-01-01T00:00:00Z', remaining: 4 }, is_owner: false, my_status: null,
      }),
      '/api/invitations/TOKEN123/accept': () => json(200, { result: 'unido', group: 'G-1' }),
    });
    renderAt('/unirse/TOKEN123');
    expect(await screen.findByText('Turno tarde')).toBeInTheDocument();
    expect(screen.getByText('Gerente General')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Unirme al grupo' }));
    expect(await screen.findByText('Ya es integrante de «Turno tarde»')).toBeInTheDocument();
    expect(calls.some((c) => c.url.endsWith('/accept') && c.method === 'POST')).toBe(true);
  });

  it('explica claramente un enlace vencido', async () => {
    mockApi({
      '/api/me': () => json(200, ME),
      '/api/invitations/VIEJO': () => json(410, { error: 'Invitación no disponible',
        detail: 'Este enlace de invitación venció. Pida uno nuevo al administrador.', fields: { invitacion: 'vencida' } }),
    });
    renderAt('/unirse/VIEJO');
    expect(await screen.findByText(/venció/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Unirme al grupo' })).not.toBeInTheDocument();
  });
});

describe('vista del empleado', () => {
  it('no muestra controles administrativos y permite salir del grupo', async () => {
    mockApi({
      '/api/me': () => json(200, ME),
      '/api/permissions/catalog': () => json(200, [{ code: 'ventas.vender', label: 'Registrar ventas', group: 'Ventas' }]),
      '/api/groups/G-1': () => json(200, {
        view: 'member', members_visible: true, permissions: ['ventas.vender'],
        group: { public_id: 'G-1', name: 'Turno tarde', description: '', status: 'activo', owner_name: 'Gerente General',
          member_count: 2, created_at: '2026-11-01T00:00:00Z' },
        me: { status: 'activo', joined_at: '2026-11-02T00:00:00Z', connection: 'conectado' },
        members: [{ full_name: 'Ana Caja', joined_at: 'a' }, { full_name: 'Beto Bodega', joined_at: 'b' }],
      }),
    });
    renderAt('/grupos/G-1');
    expect(await screen.findByRole('heading', { name: 'Turno tarde' })).toBeInTheDocument();
    expect(screen.getByText('Gerente General')).toBeInTheDocument();
    expect(screen.getByText('Beto Bodega')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('Registrar ventas')).toBeInTheDocument());
    for (const admin of ['Generar enlace', 'Cerrar grupo', 'Editar', 'Retirar']) {
      expect(screen.queryByRole('button', { name: admin })).not.toBeInTheDocument();
    }
    expect(screen.getByRole('button', { name: 'Salir del grupo' })).toBeInTheDocument();
  });
});

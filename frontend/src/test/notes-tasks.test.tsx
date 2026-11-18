import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider } from '../context/Auth';
import { ToastProvider } from '../context/Toast';
import TasksPage from '../pages/tasks/TasksPage';

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

const me = (role: string, permissions: string[]) => ({
  user: { id: role === 'admin' ? 1 : 7, username: role === 'admin' ? 'gerente' : 'ana', full_name: role === 'admin' ? 'Gerente' : 'Ana Caja',
    role, permissions },
  must_change_password: false, desktop: false,
  company: { name: 'Ferretería', primary_color: '#1d4ed8', currency_symbol: '$', timezone: 'America/Bogota' },
});

const TASK = { id: 5, title: 'Contar bodega', description: 'Pasillo 3', status: 'pendiente', due_date: '2030-01-10', version: 1,
  personal: 0, assignee_id: 7, assignee_name: 'Ana Caja', assignee_active: 1, created_by: 1, created_by_name: 'Gerente' };

type Call = { url: string; method: string; body?: any };
function mockApi(routes: (url: string, method: string) => unknown) {
  const calls: Call[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const out = routes(url, method);
    return out instanceof Response ? out : json(200, out ?? {});
  });
  return calls;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ToastProvider><AuthProvider><Routes><Route path="/tareas/*" element={<TasksPage />} /></Routes></AuthProvider></ToastProvider>
    </MemoryRouter>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe('tareas asignadas', () => {
  it('el empleado ve su tarea, la completa y no tiene controles de administración', async () => {
    const calls = mockApi((url) => (url.endsWith('/api/me') ? me('employee', ['ventas.vender'])
      : url.includes('/api/tasks') ? [TASK] : {}));
    renderAt('/tareas/asignadas');
    const card = await screen.findByRole('article', { name: 'Contar bodega' });
    expect(within(card).getByText('Pasillo 3')).toBeInTheDocument();
    expect(within(card).getByText('Asignada por: Gerente')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Nueva tarea' })).not.toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: 'Editar' })).not.toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: 'Eliminar' })).not.toBeInTheDocument();
    await userEvent.click(within(card).getByRole('button', { name: 'Marcar como completada' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT' && c.url.endsWith('/api/tasks/5')
      && c.body.status === 'completada')).toBe(true));
  });

  it('el administrador asigna, ve el responsable y confirma antes de eliminar', async () => {
    const calls = mockApi((url, method) => {
      if (url.endsWith('/api/me')) return me('admin', ['tareas.gestionar']);
      if (url.endsWith('/api/tasks/assignees')) return [{ id: 7, full_name: 'Ana Caja', role: 'employee' }];
      if (url.includes('/api/tasks') && method === 'GET') return [{ ...TASK, status: 'en_curso' }];
      return {};
    });
    renderAt('/tareas/asignadas');
    const card = await screen.findByRole('article', { name: 'Contar bodega' });
    expect(within(card).getAllByText('En progreso').length).toBeGreaterThan(0);
    expect(within(card).getByText('Ana Caja')).toBeInTheDocument();
    await userEvent.click(within(card).getByRole('button', { name: 'Eliminar' }));
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false);          // primero pide confirmación
    const confirm = await screen.findByRole('dialog', { name: 'Eliminar tarea' });
    expect(within(confirm).getByText(/El empleado dejará de verla/)).toBeInTheDocument();
    await userEvent.click(within(confirm).getByRole('button', { name: 'Eliminar' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE' && c.url.endsWith('/api/tasks/5'))).toBe(true));
    await userEvent.click(screen.getByRole('button', { name: 'Nueva tarea' }));
    const dialog = await screen.findByRole('dialog', { name: 'Asignar tarea' });
    expect(within(dialog).getByRole('combobox', { name: /Responsable/ })).toBeInTheDocument();
  });
});

describe('mis tareas y mis notas', () => {
  it('muestra estados vacíos claros y crea una tarea personal sin responsable', async () => {
    const calls = mockApi((url, method) => (url.endsWith('/api/me') ? me('employee', [])
      : method === 'GET' ? [] : { id: 9 }));
    renderAt('/tareas/mias');
    await userEvent.click(await screen.findByRole('tab', { name: 'Todas' }));
    expect(await screen.findByText('Todavía no tiene tareas. Cree una para organizar su trabajo.')).toBeInTheDocument();
    expect(calls.some((c) => c.url.includes('scope=personales'))).toBe(true);
    await userEvent.click(screen.getAllByRole('button', { name: 'Nueva tarea' })[0]);
    expect(screen.queryByRole('combobox', { name: /Responsable/ })).not.toBeInTheDocument();
    await userEvent.type(screen.getByRole('textbox', { name: /Tarea/ }), 'Ordenar vitrina');
    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }));
    await waitFor(() => expect(calls.find((c) => c.method === 'POST')?.body).toEqual(
      { title: 'Ordenar vitrina', description: '', due_date: null, personal: true }));
  });

  it('las notas se buscan por título o contenido', async () => {
    const calls = mockApi((url) => (url.endsWith('/api/me') ? me('employee', [])
      : url.includes('/api/notes?q=') ? [] : url.includes('/api/notes') ? [
        { id: 3, title: 'Caja', content: 'Revisar cambio', created_at: '2026-11-17T12:00:00Z', updated_at: '2026-11-17T12:00:00Z', version: 1 }] : {}));
    renderAt('/tareas/notas');
    expect(await screen.findByRole('article', { name: 'Caja' })).toBeInTheDocument();
    await userEvent.type(screen.getByRole('searchbox', { name: /Buscar notas/ }), 'bolsas');
    expect(await screen.findByText('Ninguna nota coincide con «bolsas».')).toBeInTheDocument();
    expect(calls.some((c) => c.url.endsWith('/api/notes?q=bolsas'))).toBe(true);
  });
});

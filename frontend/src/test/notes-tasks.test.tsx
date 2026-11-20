import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider } from '../context/Auth';
import { ToastProvider } from '../context/Toast';
import TasksPage from '../pages/tasks/TasksPage';
import { inventoryList, isInventoriesList, rememberPermissions } from './inventoryMock';

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

const me = (role: string, permissions: string[]) => (rememberPermissions(permissions), {
  user: { id: role === 'admin' ? 1 : 7, username: role === 'admin' ? 'gerente' : 'ana', full_name: role === 'admin' ? 'Gerente' : 'Ana Caja',
    role, permissions },
  must_change_password: false, desktop: false,
  company: { name: 'Ferretería', primary_color: '#1d4ed8', currency_symbol: '$', timezone: 'America/Bogota' },
});

const ANA = { user_id: 7, full_name: 'Ana Caja', status: 'pendiente', in_group: 1, user_active: 1 };
const TASK = { id: 5, title: 'Contar bodega', description: 'Pasillo 3', notes: '', status: 'pendiente', priority: 'alta',
  due_date: '2030-01-10', version: 1, personal: 0, group_id: 3, group_public_id: 'G-1', group_name: 'Turno mañana',
  created_by: 1, created_by_name: 'Gerente', assignees: [ANA], progress: { done: 0, total: 1 }, my_status: 'pendiente',
  can_manage: false };
const GROUPS = [{ public_id: 'G-1', name: 'Turno mañana', members: [{ id: 7, full_name: 'Ana Caja' }, { id: 8, full_name: 'Beto Bodega' }] }];

type Call = { url: string; method: string; body?: any };
function mockApi(routes: (url: string, method: string) => unknown) {
  const calls: Call[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const out = isInventoriesList(url) && method === 'GET' ? inventoryList() : routes(url, method);
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
  it('el empleado ve su tarea, marca SU avance y no tiene controles de administración', async () => {
    const calls = mockApi((url) => (url.endsWith('/api/me') ? me('employee', ['ventas.vender'])
      : url.includes('/api/tasks') ? [TASK] : {}));
    renderAt('/tareas/asignadas');
    const card = await screen.findByRole('article', { name: 'Contar bodega' });
    expect(within(card).getByText('Pasillo 3')).toBeInTheDocument();
    expect(within(card).getByText('Asignada por: Gerente')).toBeInTheDocument();
    expect(within(card).getByText('Prioridad alta')).toBeInTheDocument();
    expect(within(card).getByText('Turno mañana')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Asignar tarea' })).not.toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: 'Editar' })).not.toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: 'Eliminar' })).not.toBeInTheDocument();
    await userEvent.click(within(card).getByRole('button', { name: 'Marcar como completada' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT' && c.url.endsWith('/api/tasks/5/mine')
      && c.body.status === 'completada')).toBe(true));
    await userEvent.click(screen.getByRole('tab', { name: 'En progreso' }));
    await waitFor(() => expect(calls.some((c) => c.url.includes('my_status=en_curso'))).toBe(true));
  });

  it('el empleado comenta y pide un cambio desde el detalle', async () => {
    const calls = mockApi((url, method) => {
      if (url.endsWith('/api/me')) return me('employee', []);
      if (url.endsWith('/api/tasks/5') && method === 'GET') return { ...TASK, events: [
        { id: 1, kind: 'creada', user_name: 'Gerente', details: { responsables: ['Ana Caja'] }, comment: '', created_at: '2026-11-18T12:00:00Z' }] };
      if (url.includes('/api/tasks') && method === 'GET') return [TASK];
      return { ...TASK, events: [] };
    });
    renderAt('/tareas/asignadas');
    const card = await screen.findByRole('article', { name: 'Contar bodega' });
    await userEvent.click(within(card).getByRole('button', { name: 'Detalle' }));
    const dialog = await screen.findByRole('dialog', { name: 'Contar bodega' });
    expect(await within(dialog).findByText(/creó la tarea para Ana Caja/)).toBeInTheDocument();
    await userEvent.type(within(dialog).getByRole('textbox', { name: /Comentario o novedad/ }), 'Necesito un día más');
    await userEvent.click(within(dialog).getByRole('checkbox', { name: /solicitud de cambio/ }));
    await userEvent.click(within(dialog).getByRole('button', { name: 'Enviar' }));
    await waitFor(() => expect(calls.find((c) => c.method === 'POST')?.body).toEqual(
      { comment: 'Necesito un día más', request_change: true }));
    expect(within(dialog).queryByRole('button', { name: 'Cancelar tarea' })).not.toBeInTheDocument();
  });

  it('el administrador ve el avance de cada responsable, confirma antes de eliminar y asigna a varios del grupo', async () => {
    const managed = { ...TASK, status: 'en_curso', can_manage: true, my_status: null, progress: { done: 1, total: 2 },
      assignees: [{ ...ANA, status: 'en_curso' }, { user_id: 8, full_name: 'Beto Bodega', status: 'completada', in_group: 1, user_active: 1 }] };
    const calls = mockApi((url, method) => {
      if (url.endsWith('/api/me')) return me('admin', ['tareas.gestionar', 'grupos.gestionar']);
      if (url.endsWith('/api/tasks/assignees')) return [{ id: 7, full_name: 'Ana Caja', role: 'employee' }];
      if (url.endsWith('/api/tasks/groups')) return GROUPS;
      if (url.includes('/api/tasks') && method === 'GET') return [managed];
      return {};
    });
    renderAt('/tareas/asignadas');
    const card = await screen.findByRole('article', { name: 'Contar bodega' });
    const people = within(card).getByRole('list', { name: 'Responsables' });
    expect(within(people).getByText('Ana Caja')).toBeInTheDocument();
    expect(within(people).getByText('Completada')).toBeInTheDocument();
    expect(within(card).getByText('Avance: 1 de 2 completaron')).toBeInTheDocument();
    expect(screen.getByLabelText('Seguimiento de tareas')).toBeInTheDocument();
    await userEvent.click(within(card).getByRole('button', { name: 'Eliminar' }));
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false);          // primero pide confirmación
    const confirm = await screen.findByRole('dialog', { name: 'Eliminar tarea' });
    expect(within(confirm).getByText(/Los responsables dejarán de verla/)).toBeInTheDocument();
    await userEvent.click(within(confirm).getByRole('button', { name: 'Eliminar' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE' && c.url.endsWith('/api/tasks/5'))).toBe(true));

    await userEvent.click(screen.getAllByRole('button', { name: 'Asignar tarea' })[0]);
    const dialog = await screen.findByRole('dialog', { name: 'Asignar tarea' });
    expect(within(dialog).getByRole('combobox', { name: /Grupo de trabajo/ })).toHaveValue('G-1');
    await userEvent.type(within(dialog).getByRole('textbox', { name: /^Tarea/ }), 'Etiquetar precios');
    await userEvent.selectOptions(within(dialog).getByRole('combobox', { name: /Prioridad/ }), 'urgente');
    await userEvent.click(within(dialog).getByRole('checkbox', { name: 'Ana Caja' }));
    await userEvent.click(within(dialog).getByRole('checkbox', { name: 'Beto Bodega' }));
    await userEvent.click(within(dialog).getByRole('button', { name: 'Asignar' }));
    await waitFor(() => expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ title: 'Etiquetar precios',
      description: '', priority: 'urgente', due_date: null, notes: '', assignee_ids: [7, 8], group: 'G-1' }));
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
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: /Grupo/ })).not.toBeInTheDocument();
    await userEvent.type(screen.getByRole('textbox', { name: /^Tarea/ }), 'Ordenar vitrina');
    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }));
    await waitFor(() => expect(calls.find((c) => c.method === 'POST')?.body).toEqual(
      { title: 'Ordenar vitrina', description: '', priority: 'media', due_date: null, personal: true }));
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

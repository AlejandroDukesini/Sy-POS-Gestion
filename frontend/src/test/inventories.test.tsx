import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { getInventoryKey } from '../api/client';
import { AuthProvider } from '../context/Auth';
import { InventoryProvider, useInventory } from '../context/Inventory';
import { ToastProvider } from '../context/Toast';
import { useAuth } from '../context/Auth';
import InventoryPage from '../pages/inventory/InventoryPage';

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

const me = (role: string, permissions: string[]) => ({
  user: { id: 4, username: 'u', full_name: 'Usuaria', role, permissions }, must_change_password: false, desktop: false,
  company: { name: 'Ferretería', primary_color: '#1d4ed8', currency_symbol: '$', timezone: 'America/Bogota' },
});

const inv = (key: string, name: string, group: string | null, extra: Record<string, unknown> = {}) => ({
  key, name, description: '', status: 'activo', group: group ? { public_id: `G-${key}`, name: group, status: 'activo' } : null,
  owner: true, products: 2, stock: '8', low_stock: 0, last_update: '2026-11-19T10:00:00Z', permissions: ['inventario.ver', 'ventas.vender'],
  first_products: [{ code: 'TAL-01', description: 'Taladro', stock: '5', unit: 'und' }, { code: 'MAR-02', description: 'Martillo', stock: '3', unit: 'und' }],
  ...extra,
});

function mockApi(user: unknown, inventories: unknown[]) {
  const seen: { url: string; headers: Record<string, string> }[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    seen.push({ url, headers: (init?.headers ?? {}) as Record<string, string> });
    if (url.endsWith('/api/me')) return json(200, user);
    if (/\/api\/inventories$/.test(url)) return json(200, inventories);
    if (url.includes('/api/products/meta')) return json(200, { units: ['und'], summary: { products: 0, low_stock: 0, out_of_stock: 0 } });
    if (url.includes('/api/products')) return json(200, { items: [], page: 1, pages: 1, total: 0 });
    if (url.includes('/api/inventory/columns')) return json(200, { columns: [], core: [] });
    return json(200, []);
  });
  return seen;
}

function Probe() {
  const { can } = useAuth();
  const { current } = useInventory();
  return <output aria-label="estado">{`${current?.name ?? 'ninguno'}|editar:${can('inventario.editar')}|vender:${can('ventas.vender')}`}</output>;
}

function renderAt(path = '/inventario') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ToastProvider><AuthProvider><InventoryProvider>
        <Probe />
        <Routes><Route path="/inventario/*" element={<InventoryPage />} /></Routes>
      </InventoryProvider></AuthProvider></ToastProvider>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  sessionStorage.clear();
});

describe('inventarios según la cantidad', () => {
  it('con un solo inventario entra directo, sin panel de selección', async () => {
    mockApi(me('admin', ['inventario.ver', 'inventario.editar']), [inv('I-1', 'Inventario Armenia', 'Sucursal Armenia')]);
    renderAt();
    expect(await screen.findByRole('heading', { name: 'Inventario · Inventario Armenia' })).toBeInTheDocument();
    expect(screen.getByText(/Grupo Sucursal Armenia/)).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Seleccione el inventario' })).not.toBeInTheDocument();
  });

  it('con tres o más muestra el panel con datos reales y al ingresar usa ese inventario', async () => {
    const seen = mockApi(me('admin', ['inventario.ver']), [
      inv('I-1', 'Inventario Armenia', 'Sucursal Armenia'),
      inv('I-2', 'Inventario Bodega', 'Bodega Central', { first_products: [{ code: 'BOD-9', description: 'Cemento', stock: '40', unit: 'bulto' }] }),
      inv('I-3', 'Inventario Pereira', 'Sucursal Pereira', { products: 0, stock: '0', first_products: [] }),
    ]);
    renderAt();
    expect(await screen.findByRole('heading', { name: 'Seleccione el inventario' })).toBeInTheDocument();
    const cards = screen.getAllByRole('article');
    expect(cards).toHaveLength(3);
    expect(within(cards[0]).getByText('Grupo Sucursal Armenia')).toBeInTheDocument();
    expect(within(cards[0]).getByText('TAL-01')).toBeInTheDocument();
    expect(within(cards[0]).getByText('MAR-02')).toBeInTheDocument();
    expect(within(cards[2]).getByText('Aún no tiene productos.')).toBeInTheDocument();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('Buscar inventario'), 'cemento');
    expect(screen.getAllByRole('article')).toHaveLength(1);
    await user.click(screen.getByRole('button', { name: 'Ingresar a Inventario Bodega' }));
    expect(await screen.findByRole('heading', { name: 'Inventario · Inventario Bodega' })).toBeInTheDocument();
    expect(getInventoryKey()).toBe('I-2');
    const productCalls = seen.filter((c) => c.url.includes('/api/products?'));
    expect(productCalls.at(-1)?.headers['X-Inventory']).toBe('I-2');
  });

  it('los permisos en pantalla son los del inventario activo, no los del usuario', async () => {
    mockApi(me('employee', ['inventario.ver', 'inventario.editar', 'ventas.vender']),
      [inv('I-1', 'Inventario Armenia', 'Sucursal Armenia', { owner: false, permissions: ['inventario.ver', 'ventas.vender'] })]);
    renderAt();
    expect(await screen.findByLabelText('estado')).toHaveTextContent('Inventario Armenia|editar:false|vender:true');
    expect(screen.queryByRole('button', { name: 'Nuevo producto' })).not.toBeInTheDocument();
    expect(screen.getByText(/Lo que puede hacer en este inventario \(2\)/)).toBeInTheDocument();
  });

  it('sin inventarios el empleado ve qué hacer', async () => {
    mockApi(me('employee', ['inventario.ver']), []);
    renderAt();
    expect(await screen.findByText('No tiene inventarios asignados')).toBeInTheDocument();
    expect(screen.getByText(/Pida al administrador que lo autorice/)).toBeInTheDocument();
    expect(screen.getByLabelText('estado')).toHaveTextContent('ninguno|editar:false|vender:false');
  });
});

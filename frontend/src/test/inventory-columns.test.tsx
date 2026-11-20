import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider } from '../context/Auth';
import { ToastProvider } from '../context/Toast';
import InventoryPage from '../pages/inventory/InventoryPage';
import { inventoryList, isInventoriesList, rememberPermissions } from './inventoryMock';
import { InventoryProvider } from '../context/Inventory';

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

const me = (role: string, permissions: string[]) => (rememberPermissions(permissions), {
  user: { id: 1, username: 'gerente', full_name: 'Gerente', role, permissions },
  must_change_password: false, desktop: false,
  company: { name: 'Ferretería', primary_color: '#1d4ed8', currency_symbol: '$', timezone: 'America/Bogota' },
});
const ADMIN = ['inventario.ver', 'inventario.editar', 'inventario.importar', 'inventario.columnas', 'inventario.costos'];
const OBS = { id: 1, name: 'Observaciones', data_type: 'texto_largo', description: 'Información adicional', required: 0,
  default_value: null, options: [], position: 10, is_system: 1, active: 1, version: 1, values_count: 1 };
const MARCA = { id: 2, name: 'Marca', data_type: 'texto', description: '', required: 0, default_value: null, options: [],
  position: 20, is_system: 0, active: 1, version: 1, values_count: 3 };
const LONG = 'Producto reservado para el cliente Ruiz hasta el viernes; revisar el estado del empaque antes de entregar.';
const PRODUCT = { id: 3, code: '001', description: 'Teclado', category_id: null, category_name: null, unit: 'und', price: '50000',
  discount_price: null, cost: '30000', tax_rate: '19', stock: '10', min_stock: '1', active: 1, low_stock: false, version: 1,
  external_ref: null, updated_at: '2026-11-18T12:00:00Z', custom: { 1: LONG, 2: 'Logitech' } };

type Call = { url: string; method: string; body?: any };
function mockApi(routes: (url: string, method: string) => unknown) {
  const calls: Call[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    const raw = init?.body;
    calls.push({ url, method, body: typeof raw === 'string' ? JSON.parse(raw) : raw });
    const out = isInventoriesList(url) && method === 'GET' ? inventoryList() : routes(url, method);
    return out instanceof Response ? out : json(200, out ?? {});
  });
  return calls;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ToastProvider><AuthProvider><InventoryProvider><Routes><Route path="/inventario/*" element={<InventoryPage />} /></Routes></InventoryProvider></AuthProvider></ToastProvider>
    </MemoryRouter>,
  );
}

const base = (url: string) => {
  if (url.endsWith('/api/me')) return me('admin', ADMIN);
  if (url.includes('/api/inventory/columns')) return { columns: [OBS, MARCA], core: [{ key: 'code', name: 'Código', data_type: 'texto', required: true }] };
  if (url.includes('/api/products/meta')) return { units: ['und'], summary: { products: 1, low_stock: 0, out_of_stock: 0 } };
  if (url.includes('/api/products/3')) return PRODUCT;
  if (url.includes('/api/products')) return { items: [PRODUCT], page: 1, pages: 1, total: 1 };
  if (url.includes('/api/categories') || url.includes('/api/movements') || url.includes('/api/imports')) return url.includes('movements') ? { items: [] } : [];
  return undefined;
};

afterEach(() => vi.restoreAllMocks());

describe('inventario con columnas personalizables', () => {
  it('la tabla muestra las columnas adicionales y recorta las observaciones extensas', async () => {
    mockApi((url) => base(url) ?? {});
    renderAt('/inventario');
    const table = await screen.findByRole('table', { name: 'Productos del inventario' });
    expect(within(table).getByRole('columnheader', { name: 'Observaciones' })).toBeInTheDocument();
    expect(within(table).getByRole('columnheader', { name: 'Marca' })).toBeInTheDocument();
    expect(within(table).getByText('Logitech')).toBeInTheDocument();
    const obs = within(table).getByText(LONG);
    expect(obs).toHaveClass('cell-clip');                       // recortada en la tabla, completa al pasar el cursor
    expect(obs).toHaveAttribute('title', LONG);
    expect(screen.getByRole('link', { name: 'Administrar columnas' })).toBeInTheDocument();
  });

  it('el formulario del producto guarda los valores de las columnas adicionales', async () => {
    const calls = mockApi((url, method) => (method === 'PUT' ? PRODUCT : base(url) ?? {}));
    renderAt('/inventario?producto=3');
    const panel = await screen.findByRole('complementary', { name: 'Detalle del producto' });
    expect(await within(panel).findByText('Logitech')).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole('button', { name: 'Editar' }));
    const dialog = await screen.findByRole('dialog', { name: 'Editar 001' });
    const marca = within(dialog).getByRole('textbox', { name: 'Marca' });
    await userEvent.clear(marca);
    await userEvent.type(marca, 'Genius');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Guardar' }));
    await waitFor(() => expect(calls.find((c) => c.method === 'PUT')?.body.custom).toEqual({ 1: LONG, 2: 'Genius' }));
  });

  it('administrar columnas: agrega una columna y avisa cuántos datos se pierden antes de eliminar', async () => {
    const calls = mockApi((url, method) => {
      if (method === 'DELETE' && url.includes('dry_run=true')) return { values: 3, dry_run: true };
      if (method !== 'GET') return { id: 9, name: 'Ubicación', filled: 0 };
      return base(url) ?? {};
    });
    renderAt('/inventario/columnas');
    const list = await screen.findByRole('list', { name: 'Columnas adicionales activas' });
    const obs = within(list).getAllByRole('listitem')[0];
    expect(within(obs).getByText('Del sistema')).toBeInTheDocument();
    expect(within(obs).queryByRole('button', { name: 'Eliminar' })).not.toBeInTheDocument();   // no se elimina
    const marca = within(list).getAllByRole('listitem')[1];
    await userEvent.click(within(marca).getByRole('button', { name: 'Eliminar' }));
    const confirm = await screen.findByRole('dialog', { name: 'Eliminar columna' });
    expect(within(confirm).getByText('3 producto(s)')).toBeInTheDocument();
    expect(calls.some((c) => c.method === 'DELETE' && !c.url.includes('dry_run'))).toBe(false);
    await userEvent.click(within(confirm).getByRole('button', { name: 'Volver' }));

    await userEvent.click(screen.getByRole('button', { name: 'Agregar columna' }));
    const dialog = await screen.findByRole('dialog', { name: 'Agregar columna' });
    await userEvent.type(within(dialog).getByRole('textbox', { name: /Nombre/ }), 'Ubicación');
    await userEvent.selectOptions(within(dialog).getByRole('combobox', { name: /Tipo de dato/ }), 'lista');
    await userEvent.type(within(dialog).getByRole('textbox', { name: /Opciones/ }), 'Bodega A{enter}Bodega B');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Guardar' }));
    await waitFor(() => expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ name: 'Ubicación', description: '',
      data_type: 'lista', required: false, default_value: null, options: ['Bodega A', 'Bodega B'] }));
  });

  it('antes de importar se asignan columnas existentes y se agregan columnas nuevas', async () => {
    const info = { file: 'inv.xlsx', sheets: ['Hoja1'], sheet: 'Hoja1', header_row: 1, rows: 1,
      headers: ['Código', 'Producto', 'Precio', 'Observaciones', 'Marca', 'Ubicación'],
      suggested_columns: { code: 'Código', description: 'Producto', price: 'Precio' }, suggested_custom: { 1: 'Observaciones', 2: 'Marca' },
      sample: [['001', 'Teclado', 50000, 'Revisar proveedor', 'Logitech', 'Bodega A']],
      fields: { code: 'Código', description: 'Descripción', price: 'Precio sin descuento' }, required: ['code', 'description', 'price'],
      duplicate_headers: [], custom_columns: [OBS, MARCA], can_create_columns: true };
    const calls = mockApi((url) => (url.includes('/imports/inspect') ? info
      : url.includes('/imports/preview') ? { id: 4, status: 'vista_previa', summary: { file: 'inv.xlsx', counts: { new: 1 }, warnings: [],
        will: { create: true, update_catalog: true, adjust_stock: false, new_columns: ['Ubicación'] },
        new: [{ row: 2, code: '001', description: 'Teclado', price: '50000', stock: '0', custom: { Ubicación: 'Bodega A' } }] } }
        : base(url) ?? {}));
    renderAt('/inventario/importar');
    const input = await screen.findByLabelText(/Archivo/);
    await userEvent.upload(input, new File(['x'], 'inv.xlsx'));
    expect(await screen.findByText('Primeras filas del archivo', { selector: 'summary' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Marca' })).toHaveValue('Marca');            // reconocida por el nombre
    await userEvent.click(screen.getByRole('button', { name: 'Ubicación' }));               // crear desde el encabezado libre
    expect(screen.getByRole('textbox', { name: /Nombre en el inventario/ })).toHaveValue('Ubicación');
    await userEvent.click(screen.getByRole('button', { name: 'Ver vista previa' }));
    expect(await screen.findByText(/Al aplicar se agregarán al inventario: Ubicación/)).toBeInTheDocument();
    const form = calls.find((c) => c.url.includes('/imports/preview'))!.body as FormData;
    expect(JSON.parse(String(form.get('options'))).custom).toEqual([
      { column_id: 1, header: 'Observaciones' }, { column_id: 2, header: 'Marca' },
      { header: 'Ubicación', new: { name: 'Ubicación', data_type: 'texto' } }]);
  });
});

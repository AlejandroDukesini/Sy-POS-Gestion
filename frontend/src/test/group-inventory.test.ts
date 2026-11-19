import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get, setInventoryKey } from '../api/client';
import { useApi } from '../lib/hooks';
import { useRealtimeConnection } from '../lib/realtime';

class FakeEventSource {
  static last: FakeEventSource | null = null;
  static CLOSED = 2;
  readyState = 1;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private handlers = new Map<string, (m: MessageEvent) => void>();
  constructor(public url: string) { FakeEventSource.last = this; }
  addEventListener(type: string, fn: (m: MessageEvent) => void) { this.handlers.set(type, fn); }
  close() { this.readyState = FakeEventSource.CLOSED; }
  send(type: string, data: unknown) { this.handlers.get(type)?.({ data: JSON.stringify(data) } as MessageEvent); }
}

const json = (body: unknown) => new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } });
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(async () => json({ items: [] }));
  vi.stubGlobal('fetch', fetchMock);
  vi.stubGlobal('EventSource', FakeEventSource);
});
afterEach(() => {
  setInventoryKey(null);
  vi.unstubAllGlobals();
});

describe('inventario por grupo en la interfaz', () => {
  it('envía el inventario elegido en la cabecera X-Inventory', async () => {
    setInventoryKey('grp123');
    await get('/products');
    const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>;
    expect(headers['X-Inventory']).toBe('grp123');
    setInventoryKey(null);
    await get('/products');
    expect((fetchMock.mock.calls[1][1].headers as Record<string, string>)['X-Inventory']).toBeUndefined();
  });

  it('recarga los datos del inventario cuando otra persona lo cambia, y solo los de ese inventario', async () => {
    setInventoryKey('grp123');
    const view = renderHook(() => {
      useRealtimeConnection(true);
      return { products: useApi('/products?page=1'), tasks: useApi('/tasks') };
    });
    await waitFor(() => expect(view.result.current.products.data).toBeDefined());
    const calls = (path: string) => fetchMock.mock.calls.filter((c) => String(c[0]).startsWith(`/api${path}`)).length;
    expect(calls('/products')).toBe(1);
    const es = FakeEventSource.last!;
    act(() => es.onopen?.());
    act(() => es.send('inventario', { inventory: 'otro', change: 'venta' }));   // otro inventario: no recarga
    act(() => es.send('inventario', { inventory: 'grp123', change: 'venta' }));
    await waitFor(() => expect(calls('/products')).toBe(2));
    expect(calls('/tasks')).toBe(1);                                             // lo que no es inventario no se recarga
    view.unmount();
  });
});

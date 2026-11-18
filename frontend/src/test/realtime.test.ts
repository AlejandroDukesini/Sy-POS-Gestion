import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  FALLBACK_POLL_MS, GREETING_TIMEOUT_MS, PING_MS, useRealtimeConnection, useRealtimeEvents, type RealtimeEvent,
} from '../lib/realtime';

/** EventSource mínimo controlado por la prueba. */
class FakeEventSource {
  static CLOSED = 2;
  static last: FakeEventSource | null = null;
  readyState = 1;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private handlers = new Map<string, (m: MessageEvent) => void>();
  constructor(public url: string) { FakeEventSource.last = this; }
  addEventListener(type: string, fn: (m: MessageEvent) => void) { this.handlers.set(type, fn); }
  close() { this.readyState = FakeEventSource.CLOSED; }
  send(type: string, data: unknown) { this.handlers.get(type)?.({ data: JSON.stringify(data) } as MessageEvent); }
}

function setup() {
  const events: RealtimeEvent[] = [];
  const view = renderHook(() => {
    useRealtimeConnection(true);
    useRealtimeEvents((e) => events.push(e));
  });
  const es = FakeEventSource.last!;
  act(() => es.onopen?.());
  return { events, es, view, resyncs: () => events.filter((e) => e.type === 'resync').length };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal('EventSource', FakeEventSource);
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{}')));
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('canal de tiempo real', () => {
  it('con un intermediario que retiene el stream, recarga periódicamente', () => {
    const { resyncs, view } = setup();
    act(() => { vi.advanceTimersByTime(GREETING_TIMEOUT_MS - 1); });
    expect(resyncs()).toBe(0);
    act(() => { vi.advanceTimersByTime(1); });
    expect(resyncs()).toBe(1);
    act(() => { vi.advanceTimersByTime(FALLBACK_POLL_MS * 2); });
    expect(resyncs()).toBe(3);
    view.unmount();
    act(() => { vi.advanceTimersByTime(FALLBACK_POLL_MS * 3); });
    expect(resyncs()).toBe(3);
  });

  it('envía ping mientras el canal está abierto y deja de hacerlo al cerrarlo', () => {
    const { view } = setup();
    const pings = () => vi.mocked(fetch).mock.calls.filter(([url]) => String(url) === '/api/realtime/ping').length;
    expect(pings()).toBe(1);
    act(() => { vi.advanceTimersByTime(PING_MS * 3); });
    expect(pings()).toBe(4);
    view.unmount();
    act(() => { vi.advanceTimersByTime(PING_MS * 3); });
    expect(pings()).toBe(4);
  });

  it('si el saludo llega, no usa el respaldo; y lo apaga si los eventos empiezan a llegar', () => {
    const first = setup();
    act(() => first.es.send('hola', { user: 1 }));
    act(() => { vi.advanceTimersByTime(GREETING_TIMEOUT_MS * 3); });
    expect(first.resyncs()).toBe(0);
    first.view.unmount();

    const second = setup();
    act(() => { vi.advanceTimersByTime(GREETING_TIMEOUT_MS); });
    expect(second.resyncs()).toBe(1);
    act(() => second.es.send('grupo', { group: 'G-1' }));
    act(() => { vi.advanceTimersByTime(FALLBACK_POLL_MS * 3); });
    expect(second.resyncs()).toBe(1);
    second.view.unmount();
  });
});

import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api, isReachable, newKey } from '../api/client';
import { money, qty, toApiNumber, date } from '../lib/format';
import { applyPrefs, DEFAULT_PREFS, loadLocal, normalize, storeLocal } from '../lib/prefs';

describe('formato de presentación', () => {
  it('muestra importes con separadores colombianos sin perder precisión', () => {
    expect(money('1234567.50')).toBe('$ 1.234.567,50');
    expect(money('1234.00')).toBe('$ 1.234');
    expect(money('-500.05')).toBe('-$ 500,05');
    expect(money(null)).toBe('—');
    expect(qty('2.5')).toBe('2,5');
    expect(qty('10000')).toBe('10.000');
    expect(date('2026-10-24')).toBe('24/10/2026');
  });
  it('normaliza lo que escribe la persona al formato de la API', () => {
    expect(toApiNumber('12.500')).toBe('12500');
    expect(toApiNumber('12.500,75')).toBe('12500.75');
    expect(toApiNumber('$ 1,234.5')).toBe('1234.5');
    expect(toApiNumber('3,5')).toBe('3.5');
  });
});

describe('preferencias', () => {
  it('descarta valores no válidos y claves desconocidas', () => {
    const p = normalize({ theme: 'neon', font_size: 99, density: 'compacta', token: 'x' });
    expect(p.theme).toBe('light');
    expect(p.font_size).toBe(16);
    expect(p.density).toBe('compacta');
    expect('token' in p).toBe(false);
  });
  it('aplica tema y tamaño de texto al documento', () => {
    applyPrefs({ ...DEFAULT_PREFS, theme: 'dark', font_size: 20, high_contrast: true });
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(document.documentElement.style.fontSize).toBe('20px');
    expect(document.documentElement.dataset.contrast).toBe('high');
  });
  it('persiste localmente para aplicar el tema antes del primer pintado', () => {
    storeLocal({ ...DEFAULT_PREFS, theme: 'dark', font_size: 22 });
    expect(loadLocal()).toMatchObject({ theme: 'dark', font_size: 22 });
    localStorage.setItem('pospy.ui', '{dañado');
    expect(loadLocal()).toEqual(DEFAULT_PREFS);
  });
});

describe('cliente de la API', () => {
  afterEach(() => vi.restoreAllMocks());

  it('envía la cabecera anti-CSRF y la clave de idempotencia en escrituras', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'content-type': 'application/json' } }));
    const key = newKey();
    await api('/sales', { method: 'POST', body: { a: 1 }, idempotencyKey: key });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/sales');
    expect((init!.headers as Record<string, string>)['X-Requested-With']).toBe('pos-py');
    expect((init!.headers as Record<string, string>)['Idempotency-Key']).toBe(key);
  });

  it('convierte errores de la API con mensajes por campo', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ error: 'Revise los datos', detail: 'Falta precio',
      fields: { price: 'Obligatorio' } }), { status: 422, headers: { 'content-type': 'application/json' } }));
    const err = await api('/products', { method: 'POST', body: {} }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(422);
    expect(err.fields.price).toBe('Obligatorio');
  });

  it('informa sin conexión sin afirmar que se guardó algo', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'));
    const err = await api('/sales', { method: 'POST', body: {} }).catch((e) => e);
    expect(err.offline).toBe(true);
    expect(err.message).toMatch(/no se guardó ningún cambio/);
    expect(isReachable()).toBe(false);
  });
});

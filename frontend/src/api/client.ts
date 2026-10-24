/**
 * Cliente HTTP de la API. Rutas relativas (/api) en el mismo origen: la cookie de sesión es HttpOnly
 * y JavaScript nunca ve el token. Toda operación que modifica datos envía la cabecera anti-CSRF.
 */

export class ApiError extends Error {
  status: number;
  title: string;
  fields: Record<string, string>;
  offline: boolean;

  constructor(status: number, title: string, detail: string, fields: Record<string, string> = {}, offline = false) {
    super(detail);
    this.status = status;
    this.title = title;
    this.fields = fields;
    this.offline = offline;
  }
}

type Listener = (online: boolean) => void;
const listeners = new Set<Listener>();
let serverReachable = true;
let unauthorizedHandler: (() => void) | null = null;

export function onConnectivity(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function setReachable(value: boolean) {
  if (value !== serverReachable) {
    serverReachable = value;
    listeners.forEach((l) => l(value));
  }
}

export function isReachable(): boolean {
  return serverReachable;
}

export function onUnauthorized(handler: () => void) {
  unauthorizedHandler = handler;
}

export function newKey(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  form?: FormData;
  idempotencyKey?: string;
  signal?: AbortSignal;
}

export async function api<T = any>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = opts.method ?? (opts.body !== undefined || opts.form ? 'POST' : 'GET');
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (method !== 'GET') headers['X-Requested-With'] = 'pos-py';
  if (opts.idempotencyKey) headers['Idempotency-Key'] = opts.idempotencyKey;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(opts.body);
  }
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { method, headers, body, credentials: 'same-origin', signal: opts.signal });
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err;
    setReachable(false);
    throw new ApiError(0, 'Sin conexión', 'No hay conexión con el servidor de POS-PY. Verifique la red e intente de nuevo; '
      + 'no se guardó ningún cambio.', {}, true);
  }
  setReachable(true);
  if (response.status === 401 && unauthorizedHandler && !path.startsWith('/auth/login')) unauthorizedHandler();
  const type = response.headers.get('content-type') ?? '';
  if (!response.ok) {
    let data: any = {};
    if (type.includes('application/json')) data = await response.json().catch(() => ({}));
    throw new ApiError(response.status, data.error ?? 'Error', data.detail ?? `Error ${response.status}`, data.fields ?? {});
  }
  if (type.includes('application/json')) return response.json() as Promise<T>;
  return (await response.blob()) as unknown as T;
}

export const get = <T = any>(path: string, signal?: AbortSignal) => api<T>(path, { signal });
export const post = <T = any>(path: string, body: unknown = {}, idempotencyKey?: string) =>
  api<T>(path, { method: 'POST', body, idempotencyKey });
export const put = <T = any>(path: string, body: unknown) => api<T>(path, { method: 'PUT', body });
export const del = <T = any>(path: string) => api<T>(path, { method: 'DELETE' });
export const upload = <T = any>(path: string, form: FormData) => api<T>(path, { method: 'POST', form });

export function qs(params: Record<string, unknown>): string {
  const search = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '' && v !== false) search.set(k, String(v));
  }
  const text = search.toString();
  return text ? `?${text}` : '';
}

/** Descarga un archivo de la API (Excel, CSV, PDF, copia de seguridad) conservando la sesión. */
export async function download(path: string, fallbackName: string) {
  const response = await fetch(`/api${path}`, { credentials: 'same-origin' });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new ApiError(response.status, data.error ?? 'Error', data.detail ?? 'No se pudo descargar el archivo.');
  }
  const disposition = response.headers.get('content-disposition') ?? '';
  const match = /filename="?([^";]+)"?/.exec(disposition);
  const url = URL.createObjectURL(await response.blob());
  const a = document.createElement('a');
  a.href = url;
  a.download = match?.[1] ?? fallbackName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

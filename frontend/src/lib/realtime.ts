/**
 * Canal de tiempo real con el servidor (Server-Sent Events, mismo origen, cookie de sesión HttpOnly).
 *
 * Los eventos solo avisan que algo cambió; cada pantalla vuelve a pedir sus datos a la API. Al
 * reconectar se emite «resync» para que todo se recargue (pudo haber cambios mientras no había red).
 * El navegador reintenta solo; si el servidor rechaza el canal (sesión vencida), se reintenta con
 * espera creciente. La pérdida de conexión nunca afecta la pertenencia a un grupo.
 *
 * Respaldo: algunos intermediarios (túneles rápidos de Cloudflare, antivirus, proxies corporativos)
 * retienen el stream y no entregan nada hasta que termina. Si el saludo «hola» no llega poco después
 * de abrir el canal, se emite «resync» periódicamente para que las pantallas recarguen solas. El canal
 * sigue abierto, así que la presencia (conectado/desconectado) funciona igual en el servidor.
 */
import { useEffect, useRef, useState } from 'react';

export type RealtimeStatus = 'conectando' | 'conectado' | 'reconectando' | 'desconectado';
export interface RealtimeEvent { type: string; group?: string; user?: number; change?: string; [key: string]: unknown }

const EVENT_TYPES = ['hola', 'grupo', 'presencia', 'cuenta', 'sesion', 'tarea', 'inventario', 'resync'];
const listeners = new Set<(e: RealtimeEvent) => void>();
const statusListeners = new Set<(s: RealtimeStatus) => void>();
let source: EventSource | null = null;
let status: RealtimeStatus = 'desconectado';
let everConnected = false;
let users = 0;
let retryTimer: ReturnType<typeof setTimeout> | undefined;
let retryDelay = 2000;
export const GREETING_TIMEOUT_MS = 8000;
export const FALLBACK_POLL_MS = 10000;
let greetingTimer: ReturnType<typeof setTimeout> | undefined;
let pollTimer: ReturnType<typeof setInterval> | undefined;
// Ping al servidor mientras el canal está abierto: si un proxy deja la conexión medio abierta tras
// irse el cliente, el servidor deja de recibir pings y marca a la persona como «reconectando».
export const PING_MS = 10000;
let pingTimer: ReturnType<typeof setInterval> | undefined;

function ping() {
  void fetch('/api/realtime/ping', {
    method: 'POST', credentials: 'same-origin', headers: { 'X-Requested-With': 'pos-py' },
  }).catch(() => { /* sin red: el canal mismo informará la reconexión */ });
}

function stopPing() {
  clearInterval(pingTimer);
  pingTimer = undefined;
}

function startFallback() {
  if (pollTimer) return;
  emit({ type: 'resync' });
  pollTimer = setInterval(() => emit({ type: 'resync' }), FALLBACK_POLL_MS);
}

function stopFallback() {
  clearTimeout(greetingTimer);
  greetingTimer = undefined;
  clearInterval(pollTimer);
  pollTimer = undefined;
}

function setStatus(next: RealtimeStatus) {
  if (next === status) return;
  status = next;
  statusListeners.forEach((l) => l(next));
}

function emit(event: RealtimeEvent) {
  listeners.forEach((l) => l(event));
}

function open() {
  clearTimeout(retryTimer);
  if (source || typeof EventSource === 'undefined') return;
  setStatus(everConnected ? 'reconectando' : 'conectando');
  const es = new EventSource('/api/realtime/stream', { withCredentials: true });
  source = es;
  es.onopen = () => {
    retryDelay = 2000;
    setStatus('conectado');
    if (everConnected) emit({ type: 'resync' });
    everConnected = true;
    ping();
    stopPing();
    pingTimer = setInterval(ping, PING_MS);
    if (!pollTimer) {
      clearTimeout(greetingTimer);
      greetingTimer = setTimeout(startFallback, GREETING_TIMEOUT_MS);
    }
  };
  es.onerror = () => {
    if (es.readyState === EventSource.CLOSED) {
      // El servidor rechazó el canal (por ejemplo, sesión vencida): reintento manual con espera creciente.
      es.close();
      source = null;
      stopPing();
      setStatus(navigator.onLine === false ? 'reconectando' : 'desconectado');
      retryTimer = setTimeout(open, retryDelay);
      retryDelay = Math.min(retryDelay * 2, 30000);
    } else {
      setStatus('reconectando');   // el navegador reintenta solo
    }
  };
  for (const type of EVENT_TYPES) {
    es.addEventListener(type, (msg) => {
      stopFallback();   // el stream entrega eventos: no hace falta el respaldo
      let data: Record<string, unknown> = {};
      try { data = JSON.parse((msg as MessageEvent).data); } catch { /* evento sin datos */ }
      emit({ ...data, type });
    });
  }
}

function close() {
  clearTimeout(retryTimer);
  stopFallback();
  stopPing();
  source?.close();
  source = null;
  everConnected = false;
  setStatus('desconectado');
}

function onOnline() {
  if (!users) return;
  retryDelay = 2000;
  // Volvió la red: se abre un canal nuevo aunque el anterior parezca abierto (pudo quedar medio cerrado
  // durante el corte y el estado se quedaría en «reconectando»). Al abrir se emite «resync».
  if (source) {
    source.close();
    source = null;
    stopPing();
  }
  open();
}

function onOffline() {
  if (users) setStatus('reconectando');
}

/** Mantiene abierto el canal mientras haya una sesión en pantalla. */
export function useRealtimeConnection(active: boolean) {
  useEffect(() => {
    if (!active) return;
    users += 1;
    if (users === 1) {
      window.addEventListener('online', onOnline);
      window.addEventListener('offline', onOffline);
      open();
    }
    return () => {
      users -= 1;
      if (users === 0) {
        window.removeEventListener('online', onOnline);
        window.removeEventListener('offline', onOffline);
        close();
      }
    };
  }, [active]);
}

/** Ejecuta el manejador con cada evento (siempre la versión más reciente del manejador). */
export function useRealtimeEvents(handler: (e: RealtimeEvent) => void) {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => {
    const l = (e: RealtimeEvent) => ref.current(e);
    listeners.add(l);
    return () => { listeners.delete(l); };
  }, []);
}

export function useRealtimeStatus(): RealtimeStatus {
  const [value, setValue] = useState(status);
  useEffect(() => {
    setValue(status);
    statusListeners.add(setValue);
    return () => { statusListeners.delete(setValue); };
  }, []);
  return value;
}

export const CONNECTION_LABELS: Record<string, string> = {
  conectado: 'Conectado', conectando: 'Conectando…', reconectando: 'Reconectando…', desconectado: 'Desconectado',
  desconocido: 'Sin datos de conexión',
};
export const CONNECTION_KIND: Record<string, 'success' | 'warning' | 'danger' | 'info' | undefined> = {
  conectado: 'success', conectando: 'info', reconectando: 'warning', desconectado: undefined, desconocido: undefined,
};

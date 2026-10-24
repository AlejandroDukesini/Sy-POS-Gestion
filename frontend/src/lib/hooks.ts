import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, get, isReachable, onConnectivity } from '../api/client';

export interface Resource<T> {
  data: T | undefined;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
}

/** Carga datos de la API con estados de carga y error; vuelve a cargar si cambia la ruta. */
export function useApi<T = any>(path: string | null): Resource<T> {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!path) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    get<T>(path, controller.signal)
      .then((value) => {
        setData(value);
        setError(null);
      })
      .catch((err) => {
        if ((err as Error).name !== 'AbortError') setError(err instanceof ApiError ? err : new ApiError(0, 'Error', String(err)));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}

export function useOnline(): boolean {
  const [online, setOnline] = useState(isReachable() && (typeof navigator === 'undefined' || navigator.onLine !== false));
  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener('online', up);
    window.addEventListener('offline', down);
    const off = onConnectivity(setOnline);
    return () => {
      window.removeEventListener('online', up);
      window.removeEventListener('offline', down);
      off();
    };
  }, []);
  return online;
}

export function useDebounced<T>(value: T, ms = 250): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}

/** Ejecuta una acción una sola vez a la vez (evita dobles clics) y expone su estado. */
export function useAction<A extends unknown[], R>(fn: (...args: A) => Promise<R>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const running = useRef(false);
  const run = useCallback(async (...args: A): Promise<R | undefined> => {
    if (running.current) return undefined;
    running.current = true;
    setBusy(true);
    setError(null);
    try {
      return await fn(...args);
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, 'Error', String(err)));
      return undefined;
    } finally {
      running.current = false;
      setBusy(false);
    }
  }, [fn]);
  return { run, busy, error, setError };
}

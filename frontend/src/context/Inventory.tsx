/**
 * Inventario en el que se trabaja: el «Inventario general» o el de un grupo de trabajo.
 *
 * El servidor decide a cuáles entra cada persona (GET /api/inventories) y valida la cabecera
 * X-Inventory en cada operación. En el navegador solo se recuerda la ÚLTIMA elección como comodidad
 * (localStorage); los productos, existencias y movimientos siempre vienen del servidor.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { get, setInventoryKey } from '../api/client';
import { Loading } from '../components/ui/Feedback';
import { useRealtimeEvents } from '../lib/realtime';
import { useAuth } from './Auth';

export interface InventoryOption { key: string; name: string; kind: 'general' | 'grupo'; status: string }

interface InventoryState {
  options: InventoryOption[];
  current: InventoryOption | null;
  select: (key: string) => void;
}

const InventoryContext = createContext<InventoryState>({ options: [], current: null, select: () => undefined });

function storageKey(userId: number) {
  return `pospy.inventory.${userId}`;
}

function remembered(userId: number): string | null {
  try {
    return localStorage.getItem(storageKey(userId));
  } catch {
    return null;
  }
}

export function InventoryProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const userId = user?.id ?? 0;
  const [options, setOptions] = useState<InventoryOption[] | null>(null);
  const [key, setKey] = useState<string | null>(() => remembered(userId));

  const load = useCallback(() => {
    get<InventoryOption[]>('/inventories')
      .then((list) => setOptions(list))
      .catch(() => setOptions((old) => old ?? []));   // sin conexión: se sigue con la última elección
  }, []);
  useEffect(load, [load, userId]);
  // Al entrar o salir de un grupo cambian los inventarios disponibles.
  useRealtimeEvents((e) => { if (e.type === 'grupo' || e.type === 'cuenta' || e.type === 'resync') load(); });

  const current = useMemo(() => {
    if (!options?.length) return null;
    return options.find((o) => o.key === key) ?? options[0];
  }, [options, key]);

  // La cabecera se fija antes de mostrar las pantallas (render), así sus primeras peticiones ya la llevan.
  const effective = current?.key ?? key;
  setInventoryKey(effective);

  const select = useCallback((next: string) => {
    setKey(next);
    try {
      localStorage.setItem(storageKey(userId), next);
    } catch { /* almacenamiento bloqueado: la elección dura esta sesión */ }
  }, [userId]);

  const value = useMemo(() => ({ options: options ?? [], current, select }), [options, current, select]);
  if (options === null) return <Loading label="Cargando inventarios…" />;
  return <InventoryContext.Provider value={value}>{children}</InventoryContext.Provider>;
}

export function useInventory(): InventoryState {
  return useContext(InventoryContext);
}

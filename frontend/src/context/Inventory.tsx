/**
 * Inventario en el que se trabaja. Cada administrador tiene uno o varios inventarios, cada uno de un grupo;
 * los empleados entran a los de su grupo según sus permisos.
 *
 * El servidor decide a cuáles entra cada persona (GET /api/inventories) y aplica en cada petición los
 * permisos del inventario indicado en la cabecera X-Inventory. En el navegador solo se recuerda la ÚLTIMA
 * elección como comodidad; productos, existencias y movimientos siempre vienen del servidor.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { api, setInventoryKey } from '../api/client';
import { Loading } from '../components/ui/Feedback';
import { useRealtimeEvents } from '../lib/realtime';
import { AuthContext, useAuth } from './Auth';

export interface InventoryOption {
  key: string; name: string; description: string; status: 'activo' | 'inactivo' | 'archivado';
  group: { public_id: string; name: string; status: string } | null; owner: boolean;
  products: number; stock: string; low_stock: number; last_update: string | null;
  first_products: { code: string; description: string; stock: string; unit: string }[];
  permissions: string[];
}

interface InventoryState {
  options: InventoryOption[];
  current: InventoryOption | null;
  /** La persona eligió un inventario en esta sesión (con 3 o más se muestra antes el panel de selección). */
  chosen: boolean;
  select: (key: string) => void;
  reload: () => void;
}

const InventoryContext = createContext<InventoryState>({ options: [], current: null, chosen: false, select: () => undefined, reload: () => undefined });

const storageKey = (userId: number) => `pospy.inventory.${userId}`;
const chosenKey = (userId: number) => `pospy.inventory.chosen.${userId}`;

function read(storage: () => Storage, key: string): string | null {
  try {
    return storage().getItem(key);
  } catch {
    return null;
  }
}

export function InventoryProvider({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const { user } = auth;
  const userId = user?.id ?? 0;
  const [options, setOptions] = useState<InventoryOption[] | null>(null);
  const [key, setKey] = useState<string | null>(() => read(() => localStorage, storageKey(userId)));
  const [chosen, setChosen] = useState(() => read(() => sessionStorage, chosenKey(userId)) === '1');

  const load = useCallback(() => {
    // Sin cabecera de inventario: la lista no depende del inventario elegido (una elección vieja no la bloquea).
    api<InventoryOption[]>('/inventories', { skipInventory: true })
      .then((list) => setOptions(list))
      .catch(() => setOptions((old) => old ?? []));   // sin conexión: se sigue con la última elección
  }, []);
  useEffect(load, [load, userId]);
  // Al entrar o salir de un grupo, o si el administrador cambia un inventario, cambian los disponibles.
  useRealtimeEvents((e) => {
    if (e.type === 'grupo' || e.type === 'cuenta' || e.type === 'resync' || (e.type === 'inventario' && e.change === 'configuracion')) load();
  });

  const current = useMemo(() => {
    if (!options?.length) return null;
    return options.find((o) => o.key === key) ?? options.find((o) => o.status === 'activo') ?? options[0];
  }, [options, key]);

  // La cabecera se fija antes de mostrar las pantallas (render), así sus primeras peticiones ya la llevan.
  setInventoryKey(current?.key ?? null);

  const select = useCallback((next: string) => {
    setKey(next);
    setChosen(true);
    try {
      localStorage.setItem(storageKey(userId), next);
      sessionStorage.setItem(chosenKey(userId), '1');
    } catch { /* almacenamiento bloqueado: la elección dura esta sesión */ }
  }, [userId]);

  const value = useMemo(() => ({ options: options ?? [], current, chosen, select, reload: load }), [options, current, chosen, select, load]);
  // Permisos en pantalla = los del servidor: un permiso de inventario exige el del usuario Y el del inventario activo.
  const scopedAuth = useMemo(() => {
    const allowed = new Set(current?.permissions ?? []);
    const can = (...perms: string[]) => perms.every((p) => (p in PERMISSION_LABELS ? allowed.has(p) : auth.can(p)));
    const canAny = (...perms: string[]) => perms.some((p) => can(p));
    return { ...auth, can, canAny };
  }, [auth, current]);
  if (options === null) return <Loading label="Cargando inventarios…" />;
  return (
    <AuthContext.Provider value={scopedAuth}>
      <InventoryContext.Provider value={value}>{children}</InventoryContext.Provider>
    </AuthContext.Provider>
  );
}

export function useInventory(): InventoryState {
  return useContext(InventoryContext);
}

export const PERMISSION_LABELS: Record<string, string> = {
  'inventario.ver': 'Consultar inventario', 'inventario.costos': 'Ver costos', 'inventario.editar': 'Ingresar y editar productos',
  'inventario.movimientos': 'Modificar cantidades (entradas, salidas y ajustes)', 'inventario.importar': 'Importar y exportar',
  'inventario.columnas': 'Administrar columnas', 'observaciones.ver': 'Consultar observaciones', 'observaciones.crear': 'Registrar observaciones',
  'observaciones.editar': 'Editar observaciones', 'observaciones.estado': 'Cambiar estado de observaciones',
  'observaciones.comentar': 'Comentar observaciones', 'observaciones.eliminar': 'Eliminar observaciones',
  'ventas.vender': 'Registrar ventas', 'ventas.descuento': 'Aplicar descuentos', 'ventas.historial': 'Consultar ventas y movimientos',
  'ventas.anular': 'Cancelar ventas y registrar devoluciones', 'documentos.ver': 'Consultar cotizaciones y órdenes',
  'documentos.crear': 'Crear cotizaciones y órdenes', 'documentos.anular': 'Anular cotizaciones y órdenes',
  'documentos.imprimir': 'Imprimir documentos',
};

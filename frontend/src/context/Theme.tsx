import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { get } from '../api/client';
import { normalizeTheme, themeCss, type ThemeConfig } from '../lib/theme';

/** Composición del panel visual de la pantalla de ingreso (Gestión › Apariencia › Inicio de sesión). */
export interface LoginLook {
  background: { fit: 'cover' | 'contain'; pos_x: number; pos_y: number; zoom: number; darken: number; overlay_color: string; overlay_opacity: number };
  logo: { size: number; position: string; offset: number; use_company: boolean };
  version: number; has_background: boolean; has_logo: boolean;
}
export interface Appearance { theme: ThemeConfig; login: LoginLook }

export const DEFAULT_LOGIN: LoginLook = {
  background: { fit: 'cover', pos_x: 50, pos_y: 50, zoom: 100, darken: 0, overlay_color: '#000000', overlay_opacity: 0 },
  logo: { size: 240, position: 'center', offset: 32, use_company: true }, version: 0, has_background: false, has_logo: false,
};

const STYLE_ID = 'pospy-theme';
export const THEME_CACHE = 'pospy.theme';     // solo para pintar sin parpadeo; la fuente de verdad es el servidor

/** «?tema=original» en la dirección desactiva el tema del negocio en esta pestaña (recuperación si quedó ilegible). */
const recovery = typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('tema') === 'original';

export function applyTheme(theme: ThemeConfig | null) {
  const root = document.documentElement;
  let el = document.getElementById(STYLE_ID) as HTMLStyleElement | null;
  if (!theme || !theme.enabled || recovery) {
    delete root.dataset.brand;
    el?.remove();
    return;
  }
  if (!el) {
    el = document.createElement('style');
    el.id = STYLE_ID;
    document.head.appendChild(el);
  }
  el.textContent = themeCss(theme);
  root.dataset.brand = 'custom';
}

function cache(theme: ThemeConfig) {
  try {
    if (theme.enabled) localStorage.setItem(THEME_CACHE, themeCss(theme));
    else localStorage.removeItem(THEME_CACHE);
  } catch {
    /* sin almacenamiento local: el tema se aplica al cargar la configuración del servidor */
  }
}

interface ThemeState {
  appearance: Appearance;
  loaded: boolean;
  /** Aplica un tema sin guardarlo (vista previa en toda la aplicación). null vuelve al guardado. */
  preview: (theme: ThemeConfig | null) => void;
  /** Vuelve a leer la configuración del servidor (después de guardar). */
  reload: () => Promise<void>;
}

const ThemeContext = createContext<ThemeState | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [appearance, setAppearance] = useState<Appearance>({ theme: normalizeTheme(null), login: DEFAULT_LOGIN });
  const [loaded, setLoaded] = useState(false);
  const [draft, setDraft] = useState<ThemeConfig | null>(null);

  const reload = useCallback(async () => {
    try {
      const data = await get<any>('/appearance');
      const next = { theme: normalizeTheme(data.theme), login: { ...DEFAULT_LOGIN, ...data.login } as LoginLook };
      setAppearance(next);
      cache(next.theme);
    } catch {
      /* sin conexión: se conserva el tema en uso */
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    void reload();
    // Otro dispositivo pudo cambiar el tema: se revisa al volver a la pestaña.
    const onFocus = () => { if (document.visibilityState === 'visible') void reload(); };
    document.addEventListener('visibilitychange', onFocus);
    return () => document.removeEventListener('visibilitychange', onFocus);
  }, [reload]);

  useEffect(() => {
    if (loaded) applyTheme(draft ?? appearance.theme);
  }, [draft, appearance.theme, loaded]);

  const preview = useCallback((theme: ThemeConfig | null) => setDraft(theme), []);
  const value = useMemo(() => ({ appearance, loaded, preview, reload }), [appearance, loaded, preview, reload]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

/** Igual que useTheme, pero devuelve null fuera del proveedor (pantallas que también se prueban aisladas). */
export function useOptionalTheme(): ThemeState | null {
  return useContext(ThemeContext);
}

export function useTheme(): ThemeState {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme fuera de ThemeProvider');
  return ctx;
}

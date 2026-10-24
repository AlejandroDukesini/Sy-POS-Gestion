/**
 * Preferencias personales de interfaz. Se guardan en el servidor por usuario y se copian en
 * localStorage solo para aplicar el tema antes del primer pintado (public/theme-init.js).
 * Nunca se guardan contraseñas ni tokens.
 */

export interface Prefs {
  theme: 'light' | 'dark' | 'system';
  font_size: 16 | 18 | 20 | 22;
  density: 'comoda' | 'compacta';
  motion: 'system' | 'reduced';
  high_contrast: boolean;
  underline_links: boolean;
  sidebar: 'expanded' | 'collapsed';
  preferred_printer: string;
}

export const DEFAULT_PREFS: Prefs = {
  theme: 'light', font_size: 16, density: 'comoda', motion: 'system', high_contrast: false,
  underline_links: false, sidebar: 'expanded', preferred_printer: '',
};

const ALLOWED: { [K in keyof Prefs]?: readonly Prefs[K][] } = {
  theme: ['light', 'dark', 'system'],
  font_size: [16, 18, 20, 22],
  density: ['comoda', 'compacta'],
  motion: ['system', 'reduced'],
  high_contrast: [false, true],
  underline_links: [false, true],
  sidebar: ['expanded', 'collapsed'],
};

export const STORAGE_KEY = 'pospy.ui';

export function normalize(raw: unknown): Prefs {
  const data = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>;
  const out = { ...DEFAULT_PREFS } as Record<string, unknown>;
  for (const key of Object.keys(DEFAULT_PREFS) as (keyof Prefs)[]) {
    const allowed = ALLOWED[key] as readonly unknown[] | undefined;
    const value = data[key];
    if (allowed) {
      if (allowed.includes(value)) out[key] = value;
    } else if (typeof value === 'string') {
      out[key] = value.slice(0, 200);
    }
  }
  return out as unknown as Prefs;
}

export function resolvedTheme(prefs: Prefs, systemDark: boolean): 'light' | 'dark' {
  if (prefs.theme === 'system') return systemDark ? 'dark' : 'light';
  return prefs.theme;
}

export function applyPrefs(prefs: Prefs, root: HTMLElement = document.documentElement) {
  const systemDark = typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches;
  root.dataset.theme = resolvedTheme(prefs, Boolean(systemDark));
  root.style.fontSize = `${prefs.font_size}px`;
  root.dataset.density = prefs.density;
  root.dataset.motion = prefs.motion === 'reduced' ? 'reduced' : 'system';
  root.dataset.contrast = prefs.high_contrast ? 'high' : 'normal';
  root.dataset.links = prefs.underline_links ? 'underline' : 'normal';
  root.dataset.sidebar = prefs.sidebar;
}

export function storeLocal(prefs: Prefs) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
  } catch {
    /* almacenamiento no disponible (modo privado): las preferencias siguen en el servidor */
  }
}

export function loadLocal(): Prefs {
  try {
    return normalize(JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}'));
  } catch {
    return { ...DEFAULT_PREFS };
  }
}

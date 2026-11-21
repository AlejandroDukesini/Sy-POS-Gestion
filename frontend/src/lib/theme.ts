/**
 * Tema del negocio (Gestión › Apariencia). El administrador elige 12 colores base por modo (claro y oscuro);
 * de ellos se derivan TODOS los tokens semánticos de styles/tokens.css (hover, fondos suaves, texto legible
 * sobre cada color, menú lateral…). Se aplican con una hoja de estilos generada (no con estilos en línea):
 *   :root[data-brand="custom"]                      → modo claro
 *   :root[data-brand="custom"][data-theme="dark"]   → modo oscuro
 * El modo (claro/oscuro/sistema) sigue siendo la preferencia personal de cada usuario.
 */

export type ColorKey = 'primary' | 'secondary' | 'accent' | 'background' | 'surface' | 'nav' | 'text' | 'text_muted' | 'border'
  | 'success' | 'warning' | 'danger';
export type Colors = Record<ColorKey, string>;
export type Mode = 'light' | 'dark';
export interface ThemeConfig { enabled: boolean; palette: string; light: Colors; dark: Colors }

export const COLOR_FIELDS: { key: ColorKey; label: string; hint: string }[] = [
  { key: 'primary', label: 'Color primario', hint: 'Botones principales, enlaces, pestaña y opción activas.' },
  { key: 'secondary', label: 'Color secundario', hint: 'Botones secundarios y bordes de acción.' },
  { key: 'accent', label: 'Color de acento', hint: 'Información, destacados e indicadores.' },
  { key: 'background', label: 'Fondo general', hint: 'Fondo de las pantallas.' },
  { key: 'surface', label: 'Tarjetas y paneles', hint: 'Tarjetas, tablas, formularios y ventanas.' },
  { key: 'nav', label: 'Fondo de navegación', hint: 'Menú lateral.' },
  { key: 'text', label: 'Texto principal', hint: 'Textos y títulos.' },
  { key: 'text_muted', label: 'Texto secundario', hint: 'Ayudas y descripciones.' },
  { key: 'border', label: 'Bordes y separadores', hint: 'Líneas de tarjetas y tablas.' },
  { key: 'success', label: 'Éxito', hint: 'Confirmaciones y estados correctos.' },
  { key: 'warning', label: 'Advertencia', hint: 'Avisos y estados pendientes.' },
  { key: 'danger', label: 'Error', hint: 'Errores y acciones destructivas.' },
];

const C = (primary: string, secondary: string, accent: string, background: string, surface: string, nav: string, text: string,
  text_muted: string, border: string, success: string, warning: string, danger: string): Colors =>
  ({ primary, secondary, accent, background, surface, nav, text, text_muted, border, success, warning, danger });

const DARK_PRO = C('#60a5fa', '#94a3b8', '#22d3ee', '#0b1120', '#111a2e', '#0a0f1c', '#e8eefb', '#a9b6cc', '#263452', '#4ade80', '#fbbf24', '#f87171');
export const PRESETS: Record<string, { label: string; light: Colors; dark: Colors }> = {
  corporate: { label: 'Corporate Blue',
    light: C('#1d4ed8', '#475569', '#0e7490', '#f4f6fa', '#ffffff', '#ffffff', '#111827', '#4b5563', '#c9d0dc', '#15803d', '#b45309', '#b91c1c'),
    dark: C('#8fb0ff', '#a5b4c8', '#5fd3e6', '#0f141c', '#171e29', '#171e29', '#f1f4f9', '#b6c0cf', '#364256', '#6ee7a0', '#fbbf5b', '#ff9b9b') },
  emerald: { label: 'Emerald',
    light: C('#047857', '#475569', '#0f766e', '#f3f8f6', '#ffffff', '#064e3b', '#0f1f1a', '#4a5d57', '#c7d6d0', '#15803d', '#b45309', '#b91c1c'),
    dark: C('#34d399', '#9fb3ad', '#5eead4', '#0b1512', '#12201b', '#0e1a16', '#eef7f3', '#b0c4bc', '#2f4a41', '#6ee7a0', '#fbbf5b', '#ff9b9b') },
  violet: { label: 'Violet',
    light: C('#6d28d9', '#52525b', '#be185d', '#f6f4fb', '#ffffff', '#2e1065', '#1c1530', '#5b5470', '#d4cde6', '#15803d', '#b45309', '#b91c1c'),
    dark: C('#c4b5fd', '#b4b0c2', '#f9a8d4', '#120e1c', '#1b1529', '#160f26', '#f4f1fb', '#c0b8d6', '#3d3354', '#6ee7a0', '#fbbf5b', '#ff9b9b') },
  warm: { label: 'Warm',
    light: C('#c2410c', '#78716c', '#a16207', '#faf6f1', '#ffffff', '#fff7ed', '#1c1410', '#5c4f46', '#e2d5c8', '#15803d', '#a16207', '#b91c1c'),
    dark: C('#fdba74', '#c4b8ae', '#fcd34d', '#17110d', '#211913', '#1b140f', '#faf3ec', '#d0c2b5', '#4a3a2e', '#6ee7a0', '#fcd34d', '#ff9b9b') },
  neutral: { label: 'Neutral',
    light: C('#334155', '#64748b', '#0f766e', '#f5f5f5', '#ffffff', '#f0f0f0', '#171717', '#525252', '#d4d4d4', '#15803d', '#b45309', '#b91c1c'),
    dark: C('#cbd5e1', '#a3a3a3', '#5eead4', '#121212', '#1c1c1c', '#161616', '#f5f5f5', '#bdbdbd', '#3a3a3a', '#6ee7a0', '#fbbf5b', '#ff9b9b') },
  dark_pro: { label: 'Dark Professional', light: DARK_PRO, dark: DARK_PRO },
};

export const DEFAULT_THEME: ThemeConfig = { enabled: false, palette: 'corporate', light: PRESETS.corporate.light, dark: PRESETS.corporate.dark };

// ------------------------------------------------------------------ color
const HEX = /^#[0-9a-fA-F]{6}$/;
export const isHex = (v: unknown): v is string => typeof v === 'string' && HEX.test(v);

function rgb(hex: string): [number, number, number] {
  return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)) as [number, number, number];
}

function toHex([r, g, b]: number[]): string {
  return `#${[r, g, b].map((v) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, '0')).join('')}`;
}

/** Mezcla a → b (t = 0 es a, t = 1 es b). */
export function mix(a: string, b: string, t: number): string {
  const x = rgb(a);
  const y = rgb(b);
  return toHex(x.map((v, i) => v + (y[i] - v) * t));
}

export function luminance(hex: string): number {
  const [r, g, b] = rgb(hex).map((c) => c / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

export const isDarkColor = (hex: string) => luminance(hex) < 0.18;

/** El candidato más legible sobre el fondo (el primero que llegue a min; si ninguno, el de mayor contraste). */
export function readable(bg: string, candidates: string[], min = 4.5): string {
  const ok = candidates.find((c) => contrast(c, bg) >= min);
  if (ok) return ok;
  return [...candidates, '#ffffff', '#000000'].sort((x, y) => contrast(y, bg) - contrast(x, bg))[0];
}

/** Ajusta un color hacia blanco o negro hasta que tenga el contraste pedido con el fondo (conserva el tono). */
export function ensure(color: string, bg: string, min: number): string {
  if (contrast(color, bg) >= min) return color;
  const target = isDarkColor(bg) ? '#ffffff' : '#000000';
  for (let t = 0.05; t <= 1; t += 0.05) {
    const c = mix(color, target, t);
    if (contrast(c, bg) >= min) return c;
  }
  return target;
}

// ------------------------------------------------------------------ tokens
/** Tokens semánticos derivados de los 12 colores base (mismos nombres que styles/tokens.css). */
export function deriveTokens(c: Colors): Record<string, string> {
  const dark = isDarkColor(c.background);
  // En modo claro el hover oscurece; en modo oscuro aclara (el texto elegido para el color sigue legible).
  const hover = (x: string) => (dark ? mix(x, '#ffffff', 0.18) : mix(x, '#000000', 0.14));
  const on = (x: string) => readable(x, ['#ffffff', '#0b1220']);
  const soft = (x: string) => mix(c.surface, x, dark ? 0.28 : 0.13);
  const onSoft = (x: string) => ensure(dark ? mix(x, '#ffffff', 0.55) : mix(x, '#000000', 0.4), soft(x), 4.5);
  const navText = readable(c.nav, [c.text, '#ffffff', '#0b1220']);
  const navActive = mix(c.nav, c.primary, isDarkColor(c.nav) ? 0.38 : 0.15);
  const t: Record<string, string> = {
    'color-scheme': dark ? 'dark' : 'light',
    bg: c.background, surface: c.surface,
    'surface-2': mix(c.surface, c.text, dark ? 0.07 : 0.05), 'surface-hover': mix(c.surface, c.text, dark ? 0.12 : 0.09),
    border: c.border, 'border-strong': ensure(mix(c.border, c.text, 0.35), c.surface, 3),
    text: c.text, 'text-muted': c.text_muted,
    primary: c.primary, 'primary-hover': hover(c.primary), 'on-primary': on(c.primary),
    'primary-soft': soft(c.primary), 'on-primary-soft': onSoft(c.primary),
    secondary: c.secondary, 'secondary-hover': hover(c.secondary), 'on-secondary': on(c.secondary),
    accent: c.accent, 'on-accent': on(c.accent),
    success: c.success, warning: c.warning,
    danger: c.danger, 'danger-hover': hover(c.danger), 'on-danger': on(c.danger),
    'danger-soft': soft(c.danger), 'on-danger-soft': onSoft(c.danger),
    'success-soft': soft(c.success), 'on-success-soft': onSoft(c.success),
    'warning-soft': soft(c.warning), 'on-warning-soft': onSoft(c.warning),
    'info-soft': soft(c.accent), 'on-info-soft': onSoft(c.accent),
    focus: ensure(c.primary, c.surface, 3),
    'nav-bg': c.nav, 'nav-text': navText, 'nav-hover': mix(c.nav, navText, 0.1), 'nav-border': mix(c.nav, navText, 0.18),
    'nav-active-bg': navActive, 'nav-active-text': readable(navActive, [ensure(c.primary, navActive, 4.5), navText]),
    'nav-indicator': ensure(c.primary, c.nav, 3),
  };
  return t;
}

function block(selector: string, tokens: Record<string, string>): string {
  const body = Object.entries(tokens).map(([k, v]) => (k === 'color-scheme' ? `  color-scheme: ${v};` : `  --${k}: ${v};`)).join('\n');
  return `${selector} {\n${body}\n}`;
}

/** Hoja de estilos del tema: toda la aplicación + las vistas previas de cada modo (Gestión › Apariencia). */
export function themeCss(theme: ThemeConfig): string {
  const light = deriveTokens(theme.light);
  const dark = deriveTokens(theme.dark);
  const parts = [
    '/* Tema del negocio (Gestión › Apariencia) */',
    block(':root[data-brand="custom"]', light),
    block(':root[data-brand="custom"][data-theme="dark"]', dark),
    ':root[data-brand="custom"][data-contrast="high"] { --border: var(--border-strong); --text-muted: var(--text); }',
  ];
  return parts.join('\n');
}

/** Variables de una vista previa de un modo concreto (se aplican a un contenedor de la página de apariencia). */
export function previewCss(theme: ThemeConfig): string {
  return [block('.theme-preview[data-mode="light"]', deriveTokens(theme.light)),
    block('.theme-preview[data-mode="dark"]', deriveTokens(theme.dark))].join('\n');
}

// ------------------------------------------------------------------ contraste
export interface ContrastIssue { mode: Mode; level: 'critico' | 'advertencia'; message: string; ratio: number }

/** Combinaciones con contraste insuficiente (WCAG 2.1 AA: 4,5:1 texto; 3:1 bordes de controles y foco). */
export function contrastIssues(theme: ThemeConfig): ContrastIssue[] {
  const out: ContrastIssue[] = [];
  for (const mode of ['light', 'dark'] as Mode[]) {
    const c = theme[mode];
    const t = deriveTokens(c);
    const checks: [string, string, string, number, number][] = [
      ['Texto principal sobre el fondo general', c.text, c.background, 4.5, 3],
      ['Texto principal sobre tarjetas', c.text, c.surface, 4.5, 3],
      ['Texto secundario sobre tarjetas', c.text_muted, c.surface, 4.5, 2],
      ['Texto secundario sobre el fondo', c.text_muted, c.background, 4.5, 2],
      ['Texto de botones principales', t['on-primary'], c.primary, 4.5, 3],
      ['Texto de botones secundarios', t['on-secondary'], c.secondary, 4.5, 3],
      ['Enlaces (color primario) sobre tarjetas', c.primary, c.surface, 4.5, 2.5],
      ['Mensajes de error sobre tarjetas', c.danger, c.surface, 4.5, 2.5],
      ['Texto del menú lateral', t['nav-text'], c.nav, 4.5, 3],
      ['Bordes de campos de formulario', t['border-strong'], c.surface, 3, 1.5],
      ['Texto de botones de error', t['on-danger'], c.danger, 4.5, 3],
    ];
    for (const [message, fg, bg, min, critical] of checks) {
      const ratio = contrast(fg, bg);
      if (ratio < min) out.push({ mode, level: ratio < critical ? 'critico' : 'advertencia', message, ratio: Math.round(ratio * 100) / 100 });
    }
  }
  return out;
}

export function normalizeTheme(raw: unknown): ThemeConfig {
  const data = (raw && typeof raw === 'object' ? raw : {}) as Partial<ThemeConfig>;
  const colors = (src: unknown, fallback: Colors): Colors => {
    const s = (src && typeof src === 'object' ? src : {}) as Record<string, unknown>;
    return Object.fromEntries(COLOR_FIELDS.map(({ key }) => [key, isHex(s[key]) ? (s[key] as string).toLowerCase() : fallback[key]])) as Colors;
  };
  return { enabled: Boolean(data.enabled), palette: typeof data.palette === 'string' ? data.palette : 'corporate',
    light: colors(data.light, DEFAULT_THEME.light), dark: colors(data.dark, DEFAULT_THEME.dark) };
}

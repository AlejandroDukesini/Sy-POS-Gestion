import { describe, expect, it } from 'vitest';
import {
  COLOR_FIELDS, contrast, contrastIssues, deriveTokens, ensure, isHex, normalizeTheme, PRESETS, readable, themeCss, type ThemeConfig,
} from '../lib/theme';

describe('tema del negocio', () => {
  it.each(Object.entries(PRESETS))('la paleta %s cumple el contraste AA en los dos modos', (_k, p) => {
    const theme: ThemeConfig = { enabled: true, palette: 'x', light: p.light, dark: p.dark };
    expect(contrastIssues(theme)).toEqual([]);
    for (const mode of ['light', 'dark'] as const) {
      expect(COLOR_FIELDS.every(({ key }) => isHex(p[mode][key]))).toBe(true);
      const t = deriveTokens(p[mode]);
      for (const [fg, bg] of [['on-primary', 'primary'], ['on-primary', 'primary-hover'], ['on-secondary', 'secondary-hover'], ['on-danger', 'danger-hover'], ['on-primary-soft', 'primary-soft'], ['on-danger-soft', 'danger-soft'],
        ['on-success-soft', 'success-soft'], ['on-warning-soft', 'warning-soft'], ['on-info-soft', 'info-soft'],
        ['nav-text', 'nav-bg'], ['nav-active-text', 'nav-active-bg'], ['on-secondary', 'secondary'], ['on-accent', 'accent']]) {
        expect(contrast(t[fg], t[bg]), `${mode} ${fg}/${bg}`).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it('los colores derivados siempre son legibles, aunque el administrador elija colores difíciles', () => {
    const odd = { ...PRESETS.corporate.light, primary: '#ffeb3b', nav: '#0a0a0a', danger: '#ff7f7f', success: '#a3e635' };
    const t = deriveTokens(odd);
    expect(contrast(t['on-primary'], t.primary)).toBeGreaterThanOrEqual(4.5);      // texto oscuro sobre amarillo
    expect(contrast(t['nav-text'], t['nav-bg'])).toBeGreaterThanOrEqual(4.5);      // texto claro sobre menú negro
    expect(contrast(t['on-success-soft'], t['success-soft'])).toBeGreaterThanOrEqual(4.5);
    expect(contrast(ensure('#cccccc', '#ffffff', 4.5), '#ffffff')).toBeGreaterThanOrEqual(4.5);
    expect(readable('#000000', ['#111111', '#eeeeee'])).toBe('#eeeeee');
  });

  it('advierte combinaciones ilegibles y marca como críticas las peores', () => {
    const bad = normalizeTheme({ enabled: true, light: { ...PRESETS.corporate.light, text: '#f0f0f0', text_muted: '#dddddd' },
      dark: PRESETS.corporate.dark });
    const issues = contrastIssues(bad);
    expect(issues.some((i) => i.mode === 'light' && i.level === 'critico' && i.message.startsWith('Texto principal'))).toBe(true);
    expect(issues.every((i) => i.mode === 'light')).toBe(true);
  });

  it('valida y completa la configuración recibida; la hoja de estilos usa los tokens semánticos', () => {
    const t = normalizeTheme({ enabled: true, palette: 'violet', light: { primary: '#6D28D9', text: 'rojo' }, dark: null });
    expect(t.light.primary).toBe('#6d28d9');
    expect(t.light.text).toBe(PRESETS.corporate.light.text);                    // valor inválido → el de fábrica
    const css = themeCss(t);
    expect(css).toContain(':root[data-brand="custom"] {');
    expect(css).toContain(':root[data-brand="custom"][data-theme="dark"]');
    expect(css).toContain('--primary: #6d28d9;');
    expect(css).toContain('--nav-bg:');
    expect(css).not.toMatch(/<|url\(|expression/);                                 // solo colores hexadecimales
  });

  it('el tema de fábrica reproduce los tokens base (sin cambios visuales al activarlo sin editar)', () => {
    const t = deriveTokens(PRESETS.corporate.light);
    expect([t.primary, t.bg, t.surface, t.text, t['text-muted'], t.border, t.danger]).toEqual(
      ['#1d4ed8', '#f4f6fa', '#ffffff', '#111827', '#4b5563', '#c9d0dc', '#b91c1c']);
  });
});

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

/** Verifica WCAG 2.1 AA (4,5:1 texto normal; 3:1 foco y bordes de controles) en los dos temas. */
const css = readFileSync(resolve(__dirname, '../styles/tokens.css'), 'utf-8');

function block(selector: string): Record<string, string> {
  const start = css.indexOf(`${selector} {`);
  const body = css.slice(start, css.indexOf('}', start));
  return Object.fromEntries([...body.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})/g)].map((m) => [m[1], m[2]]));
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function ratio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const light = block(':root');
const themes = { claro: light, oscuro: { ...light, ...block(':root[data-theme="dark"]') } };

const TEXT_PAIRS: [string, string][] = [
  ['text', 'bg'], ['text', 'surface'], ['text', 'surface-2'], ['text', 'surface-hover'], ['text-muted', 'bg'], ['text-muted', 'surface'],
  ['text-muted', 'surface-2'], ['on-primary', 'primary'], ['on-primary', 'primary-hover'], ['primary', 'surface'], ['primary', 'bg'],
  ['on-primary-soft', 'primary-soft'], ['on-danger', 'danger'], ['danger', 'surface'], ['on-danger-soft', 'danger-soft'],
  ['on-success-soft', 'success-soft'], ['on-warning-soft', 'warning-soft'], ['on-info-soft', 'info-soft'],
];

describe.each(Object.entries(themes))('contraste del tema %s', (_name, t) => {
  it.each(TEXT_PAIRS)('%s sobre %s ≥ 4,5:1', (fg, bg) => {
    expect(ratio(t[fg], t[bg])).toBeGreaterThanOrEqual(4.5);
  });
  it('el indicador de foco y los bordes de controles ≥ 3:1', () => {
    expect(ratio(t.focus, t.surface)).toBeGreaterThanOrEqual(3);
    expect(ratio(t['border-strong'], t.surface)).toBeGreaterThanOrEqual(3);
  });
});

describe('tipografía y tamaños', () => {
  it('usa Arial, texto base de 16 px y controles de al menos 44 px', () => {
    expect(css).toMatch(/--font: Arial/);
    const base = readFileSync(resolve(__dirname, '../styles/base.css'), 'utf-8');
    expect(base).toMatch(/font-size: 16px/);
    expect(Number(/--control-h: (\d+)px/.exec(css)![1])).toBeGreaterThanOrEqual(44);
    expect(css).toMatch(/prefers-reduced-motion: reduce/);
  });
});

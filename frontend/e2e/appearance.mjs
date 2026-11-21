// Personalización visual con navegador real y servidor real. Criterio de aceptación: el administrador cambia la
// paleta de TODO el POS, ve los cambios al instante, guarda el tema y personaliza la pantalla de ingreso con un
// fondo propio y un logotipo independiente sin marcos; todo persiste y el ingreso sigue funcionando.
//   npm run build && node e2e/appearance.mjs
import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { deflateSync } from 'node:zlib';
import { chromium } from 'playwright-core';

const root = resolve(import.meta.dirname, '..', '..');
const python = process.env.PYTHON ?? join(root, 'backend', '.venv', 'Scripts', 'python.exe');
const port = 8778;
const base = `http://127.0.0.1:${port}`;
const shots = process.env.SHOTS ?? mkdtempSync(join(tmpdir(), 'pospy-apariencia-shots-'));
mkdirSync(shots, { recursive: true });
const dataDir = mkdtempSync(join(tmpdir(), 'pospy-e2e-apariencia-'));
const failures = [];
const check = (ok, message) => { console.log(`${ok ? 'OK  ' : 'FALLA'} ${message}`); if (!ok) failures.push(message); };
const H = { 'X-Requested-With': 'pos-py', 'Content-Type': 'application/json' };
const ADMIN = { username: 'gerente', password: 'Clave segura 2026' };
const EMP = { username: 'cajero', password: 'Temporal 2026 x', final: 'Caja segura 2026' };

/** PNG generado aquí (sin archivos externos). rgba = con canal alfa (transparente fuera de una franja). */
function png(w, h, painter, rgba = false) {
  const table = Array.from({ length: 256 }, (_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c >>> 0; });
  const crc = (b) => { let c = 0xffffffff; for (const x of b) c = table[(c ^ x) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
  const chunk = (tag, data) => {
    const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
    const td = Buffer.concat([Buffer.from(tag), data]); const c = Buffer.alloc(4); c.writeUInt32BE(crc(td));
    return Buffer.concat([len, td, c]);
  };
  const bpp = rgba ? 4 : 3;
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = rgba ? 6 : 2;
  const raw = Buffer.alloc((w * bpp + 1) * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const p = painter(x, y); const o = y * (w * bpp + 1) + 1 + x * bpp;
    raw[o] = p[0]; raw[o + 1] = p[1]; raw[o + 2] = p[2]; if (rgba) raw[o + 3] = p[3];
  }
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk('IHDR', ihdr), chunk('IDAT', deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}
const BACKGROUND = png(1600, 900, (x, y) => [20 + (x * 120) / 1600, 60 + (y * 100) / 900, 140, 255]);
const LOGO = png(300, 120, (x, y) => (y > 30 && y < 90 ? [250, 200, 30, 255] : [0, 0, 0, 0]), true);   // transparente

const server = spawn(python, ['-m', 'pospy', '--port', String(port), '--data-dir', dataDir, '--web-dist', join(root, 'frontend', 'dist')],
  { cwd: join(root, 'backend'), env: { ...process.env, POS_SETUP_CODE: 'E2E-CODE-0011' } });
server.stderr.on('data', () => {});
server.stdout.on('data', () => {});
async function waitHealth() {
  for (let i = 0; i < 60; i++) {
    try { if ((await fetch(`${base}/api/health`)).ok) return; } catch { /* arrancando */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error('El servidor no arrancó');
}
const cssVar = (page, name) => page.evaluate((n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim(), name);
const bgOf = (page, sel) => page.locator(sel).first().evaluate((el) => getComputedStyle(el).backgroundColor);
const waitBg = (page, sel, value) => page.waitForFunction(([s, v]) => {
  const el = document.querySelector(s); return el && getComputedStyle(el).backgroundColor === v; }, [sel, value], { timeout: 5000 }).catch(() => {});
const waitVar = (page, name, value) => page.waitForFunction(([n, v]) => getComputedStyle(document.documentElement).getPropertyValue(n).trim() === v,
  [name, value], { timeout: 5000 }).catch(() => {});
const rgb = (hex) => `rgb(${[1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)).join(', ')})`;

async function signIn(page, user, password) {
  await page.goto(base);
  await page.getByLabel('Usuario', { exact: false }).fill(user);
  await page.getByLabel('Contraseña', { exact: false }).fill(password);
  await page.getByRole('button', { name: 'Ingresar' }).click();
  await page.getByRole('link', { name: 'Inventario' }).first().waitFor();
}

const browser = await chromium.launch({ channel: process.env.BROWSER ?? 'msedge', headless: true });
try {
  await waitHealth();
  await fetch(`${base}/api/setup`, { method: 'POST', headers: H,
    body: JSON.stringify({ code: 'E2E-CODE-0011', username: ADMIN.username, full_name: 'Gerente General', password: ADMIN.password }) });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 950 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await signIn(page, ADMIN.username, ADMIN.password);
  const api = ctx.request;
  check(await cssVar(page, '--primary') === '#1d4ed8' && await bgOf(page, '.sidebar') === 'rgb(255, 255, 255)', '0 Colores de fábrica');

  // 1. Gestión › Apariencia: paleta predefinida con vista previa inmediata en TODA la aplicación
  await page.goto(`${base}/gestion`);
  await page.getByRole('link', { name: /Apariencia del sistema/ }).click();
  await page.getByRole('button', { name: /Violet/ }).click();
  await waitBg(page, '.sidebar', rgb('#2e1065'));
  await page.waitForTimeout(400);                       // transición de color de los botones (160 ms)
  const violetNav = await bgOf(page, '.sidebar');
  const applyBg = await page.getByRole('button', { name: 'Aplicar cambios' }).evaluate((el) => getComputedStyle(el).backgroundColor);
  check(violetNav === rgb('#2e1065') && applyBg === rgb('#6d28d9'), `1 Paleta «Violet» al instante: menú ${violetNav}, botón principal ${applyBg}`);
  const navContrast = await page.evaluate(() => {
    const lum = (c) => { const v = c.match(/\d+/g).slice(0, 3).map((x) => x / 255).map((x) => (x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4)); return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]; };
    const a = document.querySelector('.nav-link'); const fg = lum(getComputedStyle(a).color); const bg = lum(getComputedStyle(document.querySelector('.sidebar')).backgroundColor);
    return (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05);
  });
  check(navContrast >= 4.5, `   El texto del menú se ajusta solo y se lee sobre el fondo oscuro (${navContrast.toFixed(1)}:1)`);
  await page.screenshot({ path: join(shots, '01-violet.png') });

  // 2. Selector + HEX editable, vista previa de componentes, Cancelar
  await page.getByLabel('Color primario', { exact: true }).fill('#0F766E');
  await waitVar(page, '--primary', '#0f766e');
  await page.waitForTimeout(400);
  const previewBtn = await page.getByTestId('theme-preview').locator('.btn-primary').evaluate((el) => getComputedStyle(el).backgroundColor);
  check(previewBtn === rgb('#0f766e') && await cssVar(page, '--primary') === '#0f766e', '2 Color primario por HEX: la vista previa y la aplicación cambian al instante');
  await page.getByLabel('Color primario', { exact: true }).fill('#12');
  check(await page.getByText('Use el formato #RRGGBB.').count() === 1 && await cssVar(page, '--primary') === '#0f766e', '   HEX inválido: se avisa y no se aplica');
  await page.getByRole('button', { name: 'Cancelar', exact: true }).click();
  await waitVar(page, '--primary', '#1d4ed8');
  check(await cssVar(page, '--primary') === '#1d4ed8', '   «Cancelar» devuelve los colores guardados');

  // 3. Advertencia de contraste y confirmación antes de guardar algo ilegible
  await page.getByRole('button', { name: /Emerald/ }).click();
  await page.getByLabel('Texto principal', { exact: true }).fill('#F2F2F2');
  check(await page.getByText(/Ilegible/).count() > 0, '3 Texto casi blanco sobre fondo claro: se marca «Ilegible»');
  await page.getByRole('button', { name: 'Aplicar cambios' }).click();
  const dlg = page.getByRole('dialog', { name: 'Hay textos que no se leen bien' });
  check(await dlg.isVisible(), '   Al aplicar pide confirmación (no se guarda a ciegas)');
  await dlg.getByRole('button', { name: /Cancelar|Volver/ }).first().click();
  await page.getByRole('button', { name: 'Restablecer paleta' }).click();
  check(await page.getByText('Todas las combinaciones cumplen el contraste recomendado (WCAG 2.1 AA).').count() === 1, '   «Restablecer paleta» vuelve a la paleta Emerald legible');

  // 4. Guardar el tema y comprobar persistencia (recarga, otra sesión, pantalla de ingreso)
  await page.getByRole('button', { name: 'Aplicar cambios' }).click();
  await page.getByText('Apariencia guardada').waitFor();
  await page.reload();
  await page.locator('.sidebar').waitFor();
  check(await bgOf(page, '.sidebar') === rgb('#064e3b') && await cssVar(page, '--primary') === '#047857', '4 Tema guardado: persiste al recargar');
  await page.goto(`${base}/vender`);
  check(await page.locator('.btn-primary').first().evaluate((el) => getComputedStyle(el).backgroundColor) === rgb('#047857'), '   Se aplica en Ventas (botones principales)');
  await page.goto(`${base}/inventario`);
  check(await bgOf(page, '.sidebar') === rgb('#064e3b'), '   Se aplica en Inventario (menú)');
  await page.screenshot({ path: join(shots, '02-emerald-inventario.png') });

  // 5. Modo oscuro con los colores oscuros del tema (preferencia personal)
  await api.put(`${base}/api/prefs`, { headers: H, data: { theme: 'dark' } });
  await page.reload();
  await page.locator('.sidebar').waitFor();
  await page.waitForFunction(() => getComputedStyle(document.documentElement).getPropertyValue('--primary').trim() === '#34d399');
  check(await page.evaluate(() => document.documentElement.dataset.theme) === 'dark' && await cssVar(page, '--bg') === '#0b1512',
    '5 Modo oscuro: usa los colores oscuros del tema (no los destruye el modo claro)');
  await api.put(`${base}/api/prefs`, { headers: H, data: { theme: 'light' } });
  await page.reload();
  await page.locator('.sidebar').waitFor();
  check(await cssVar(page, '--primary') === '#047857', '   De vuelta al modo claro: el tema claro sigue intacto');

  // 6. Pantalla de ingreso: fondo y logotipo independientes, composición y vista previa
  await page.goto(`${base}/gestion/apariencia`);
  await page.getByRole('tab', { name: 'Pantalla de ingreso' }).click();
  await page.getByLabel('Archivo de imagen de fondo').setInputFiles({ name: 'fondo.png', mimeType: 'image/png', buffer: BACKGROUND });
  await page.getByText('Imagen de fondo actualizada').waitFor();
  await page.getByLabel('Archivo del logotipo').setInputFiles({ name: 'logo.png', mimeType: 'image/png', buffer: LOGO });
  await page.getByText('Logotipo actualizado').waitFor();
  await page.getByLabel('Abajo a la derecha').check();
  await page.getByLabel('Opacidad de la superposición').fill('40');
  await page.getByLabel('Tamaño (ancho)').fill('200');
  const pv = page.getByTestId('login-preview');
  check(await pv.locator('img.login-bg').count() === 1 && await pv.locator('img.login-logo').count() === 1
    && await pv.locator('.login-logo-layer').getAttribute('data-pos') === 'bottom-right', '6 Vista previa con fondo, logotipo abajo a la derecha y superposición');
  await page.getByLabel('Archivo del logotipo').setInputFiles({ name: 'x.svg', mimeType: 'image/svg+xml', buffer: Buffer.from('<svg onload="alert(1)"/>') });
  check(await page.getByText(/no se admite SVG/).count() > 0, '   SVG rechazado en la interfaz');
  const fake = await api.post(`${base}/api/appearance/login/logotipo`, { headers: { 'X-Requested-With': 'pos-py' },
    multipart: { file: { name: 'falso.png', mimeType: 'image/png', buffer: Buffer.from('<svg onload="alert(1)"/>') } } });
  check(fake.status() === 422, '   El servidor rechaza un SVG disfrazado de PNG (valida el contenido real)');
  await page.getByRole('button', { name: 'Guardar pantalla de ingreso' }).click();
  await page.getByText('Pantalla de ingreso guardada').waitFor();
  await page.getByRole('radio', { name: /Teléfono/ }).click();
  await page.screenshot({ path: join(shots, '03-editor-ingreso.png') });

  // 7. Pantalla de ingreso real (sin sesión): fondo propio, logotipo sin marco, ingreso funcional
  const anon = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const lp = await anon.newPage();
  await lp.goto(base);
  await lp.locator('img.login-logo').waitFor();
  const bgLoaded = await lp.locator('img.login-bg').evaluate((img) => img.complete && img.naturalWidth === 1600);
  const logoInfo = await lp.locator('img.login-logo').evaluate((img) => {
    const cs = getComputedStyle(img); const r = img.getBoundingClientRect(); const panel = img.closest('.login-brand').getBoundingClientRect();
    return { w: Math.round(r.width), h: Math.round(r.height), border: cs.borderTopWidth, bg: cs.backgroundColor, natural: img.naturalWidth / img.naturalHeight,
      inside: r.left >= panel.left && r.right <= panel.right && r.top >= panel.top && r.bottom <= panel.bottom,
      bottomRight: panel.right - r.right < 40 && panel.bottom - r.bottom < 40 };
  });
  check(bgLoaded, '7 Ingreso: imagen de fondo propia (1600 × 900) ocupando el panel');
  check(logoInfo.w === 200 && Math.abs(logoInfo.w / logoInfo.h - logoInfo.natural) < 0.02 && logoInfo.border === '0px'
    && logoInfo.bg === 'rgba(0, 0, 0, 0)' && logoInfo.inside && logoInfo.bottomRight,
  `   Logotipo solo (sin borde ni fondo), sin deformar (${logoInfo.w}×${logoInfo.h}), abajo a la derecha y dentro del panel`);
  check(await lp.locator('.logo-slot').count() === 0 && await lp.getByText('Aquí tu logo').count() === 0, '   Sin marcos punteados ni textos de relleno');
  await lp.waitForFunction((v) => [...document.querySelectorAll('button')].some((x) => x.textContent.includes('Ingresar')
    && getComputedStyle(x).backgroundColor === v), rgb('#047857'), { timeout: 5000 }).catch(() => {});
  check(await lp.getByRole('button', { name: 'Ingresar' }).evaluate((el) => getComputedStyle(el).backgroundColor) === rgb('#047857'),
    '   La pantalla de ingreso usa el tema del negocio (botón «Ingresar»)');
  await lp.screenshot({ path: join(shots, '04-ingreso-escritorio.png') });
  for (const [w, h, label] of [[820, 1180, 'tableta'], [375, 740, 'teléfono']]) {
    await lp.setViewportSize({ width: w, height: h });
    const layout = await lp.evaluate(() => {
      const logo = document.querySelector('img.login-logo').getBoundingClientRect();
      const btn = [...document.querySelectorAll('button')].find((b) => b.textContent.includes('Ingresar')).getBoundingClientRect();
      const input = document.querySelector('.login-form input').getBoundingClientRect();
      return { hscroll: document.documentElement.scrollWidth > window.innerWidth, logoIn: logo.left >= 0 && logo.right <= window.innerWidth,
        inputW: input.width, btnVisible: btn.width > 100 && btn.left >= 0 && btn.right <= window.innerWidth };
    });
    check(!layout.hscroll && layout.logoIn && layout.inputW > 250 && layout.btnVisible,
      `   ${label} (${w}px): sin desplazamiento horizontal, logotipo dentro de la pantalla, campos y botón completos`);
    await lp.screenshot({ path: join(shots, `05-ingreso-${label}.png`) });
  }
  await lp.setViewportSize({ width: 1440, height: 900 });
  await lp.getByLabel('Usuario', { exact: false }).fill(ADMIN.username);
  await lp.getByLabel('Contraseña', { exact: false }).fill(ADMIN.password);
  await lp.getByRole('button', { name: 'Ingresar' }).click();
  await lp.getByRole('link', { name: 'Inventario' }).first().waitFor();
  check(await bgOf(lp, '.sidebar') === rgb('#064e3b'), '   El ingreso funciona y el otro equipo ya ve el tema guardado');
  const wrong = await anon.request.post(`${base}/api/auth/login`, { headers: H, data: { username: ADMIN.username, password: 'equivocada' } });
  check(wrong.status() === 401, '   La autenticación no cambió (contraseña equivocada: 401)');

  // 8. Eliminar el fondo no toca el logotipo y viceversa
  await page.goto(`${base}/gestion/apariencia`);
  await page.getByRole('tab', { name: 'Pantalla de ingreso' }).click();
  await page.getByRole('button', { name: 'Eliminar imagen' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Eliminar' }).click();
  await page.getByText('Imagen de fondo eliminada').waitFor();
  let pub = await (await anon.request.get(`${base}/api/appearance`)).json();
  check(!pub.login.has_background && pub.login.has_logo, '8 Eliminar el fondo conserva el logotipo');
  await page.getByRole('button', { name: 'Eliminar logotipo' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Eliminar' }).click();
  await page.getByText('Logotipo eliminado').waitFor();
  pub = await (await anon.request.get(`${base}/api/appearance`)).json();
  check(!pub.login.has_logo, '   Eliminar el logotipo');

  // 9. Permisos: un empleado no ve la sección ni puede cambiar la apariencia (aunque sí ve el tema)
  await api.post(`${base}/api/users`, { headers: H, data: { username: EMP.username, full_name: 'Cajero Uno', role: 'employee', password: EMP.password } });
  const ectx = await browser.newContext({ viewport: { width: 1280, height: 860 } });
  await ectx.request.post(`${base}/api/auth/login`, { headers: H, data: { username: EMP.username, password: EMP.password } });
  await ectx.request.post(`${base}/api/auth/password`, { headers: H, data: { current: EMP.password, password: EMP.final } });
  const denied = await ectx.request.put(`${base}/api/appearance/theme`, { headers: H, data: { enabled: false } });
  const deniedUp = await ectx.request.post(`${base}/api/appearance/login/fondo`, { headers: { 'X-Requested-With': 'pos-py' },
    multipart: { file: { name: 'f.png', mimeType: 'image/png', buffer: BACKGROUND } } });
  const ep = await ectx.newPage();
  await ep.goto(`${base}/gestion/apariencia`);
  await ep.locator('.sidebar').waitFor();
  await ep.waitForTimeout(800);
  check(denied.status() === 403 && deniedUp.status() === 403 && await ep.getByRole('tab', { name: 'Colores del sistema' }).count() === 0,
    '9 Empleado: sin permiso para cambiar la apariencia (403) y sin acceso a la sección');
  check(await bgOf(ep, '.sidebar').catch(() => '') === rgb('#064e3b') || await cssVar(ep, '--primary') === '#047857', '   El empleado ve el tema del negocio');

  check(errors.length === 0, `Sin errores de JavaScript${errors.length ? `: ${errors.join(' | ')}` : ''}`);
  console.log(`\nCapturas en ${shots}`);
} catch (err) {
  failures.push(String(err));
  console.error(err);
} finally {
  await browser.close();
  server.kill();
}
console.log(failures.length ? `\n${failures.length} falla(s)` : '\nTodo correcto');
process.exit(failures.length ? 1 : 0);

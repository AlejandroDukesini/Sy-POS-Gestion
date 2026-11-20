// Regresión del prompt 7 con navegador real: una instalación ANTERIOR (esquema 12, como la del negocio) se
// actualiza al arrancar el servidor nuevo. El administrador no debe quedar bloqueado y el empleado conserva sus
// funciones POS (vende por la pantalla del punto de venta). Sesiones independientes para cada rol.
//   npm run build && node e2e/upgrade-regression.mjs
import { spawn, spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { chromium } from 'playwright-core';

const root = resolve(import.meta.dirname, '..', '..');
const python = process.env.PYTHON ?? join(root, 'backend', '.venv', 'Scripts', 'python.exe');
const port = 8772;
const base = `http://127.0.0.1:${port}`;
const shots = process.env.SHOTS ?? mkdtempSync(join(tmpdir(), 'pospy-regresion-shots-'));
mkdirSync(shots, { recursive: true });
const dataDir = mkdtempSync(join(tmpdir(), 'pospy-e2e-regresion-'));
const failures = [];
const check = (ok, message) => { console.log(`${ok ? 'OK  ' : 'FALLA'} ${message}`); if (!ok) failures.push(message); };

const seed = spawnSync(python, [join(root, 'frontend', 'e2e', 'seed_v12.py'), dataDir], { cwd: join(root, 'backend'), encoding: 'utf8', env: { ...process.env, PYTHONPATH: join(root, 'backend') } });
check(seed.status === 0 && seed.stdout.includes('esquema 12'), `Base de una instalación anterior creada (${seed.stdout.trim() || seed.stderr.slice(-300)})`);
const server = spawn(python, ['-m', 'pospy', '--port', String(port), '--data-dir', dataDir, '--web-dist', join(root, 'frontend', 'dist')],
  { cwd: join(root, 'backend') });
server.stderr.on('data', () => {});
server.stdout.on('data', () => {});
async function waitHealth() {
  for (let i = 0; i < 60; i++) {
    try { const r = await fetch(`${base}/api/health`); if (r.ok) return r.json(); } catch { /* arrancando */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error('El servidor no arrancó');
}
async function login(ctx, username, password) {
  const page = await ctx.newPage();
  await page.goto(base);
  await page.getByLabel('Usuario', { exact: false }).fill(username);
  await page.getByLabel('Contraseña', { exact: false }).fill(password);
  await page.getByRole('button', { name: 'Ingresar' }).click();
  return page;
}

const browser = await chromium.launch({ channel: process.env.BROWSER ?? 'msedge', headless: true });
try {
  const health = await waitHealth();
  check(health.schema >= 13, `Al arrancar, el servidor nuevo migra la base (esquema ${health.schema})`);
  const errors = [];

  // ---------------------------------------------------------- ADMINISTRADOR
  const adminCtx = await browser.newContext({ viewport: { width: 1366, height: 900 } });
  const admin = await login(adminCtx, 'administrador', 'Clave segura 2026');
  admin.on('pageerror', (e) => errors.push(`admin: ${e.message}`));
  await admin.getByRole('link', { name: 'Inventario' }).first().click();
  await admin.getByRole('heading', { name: 'Inventario · Inventario general' }).waitFor();
  check(await admin.getByText('No tiene permiso para esta sección').count() === 0, 'A1 El administrador entra al inventario general (sin «No tiene permiso»)');
  const table = admin.getByRole('table', { name: 'Productos del inventario' });
  await table.getByText('0257').waitFor();
  check((await table.innerText()).includes('VARILLA ACEITE STEPWAY') && await admin.getByRole('button', { name: 'Nuevo producto' }).count() === 1,
    'A2 Consulta sus productos y puede gestionarlos («Nuevo producto»)');
  await admin.getByRole('link', { name: 'Movimientos de inventario' }).click();
  await admin.getByRole('table', { name: 'Movimientos de inventario' }).getByText('Existencia inicial').first().waitFor();
  check(true, 'A3 Consulta los movimientos');
  await admin.goto(`${base}/gestion`);
  await admin.getByRole('link', { name: /Administrar inventarios/ }).click();
  await admin.getByRole('table', { name: 'Mis inventarios' }).getByText('Inventario general').waitFor();
  await admin.getByRole('button', { name: 'Nuevo inventario' }).click();
  await admin.getByLabel('Grupo al que pertenece', { exact: false }).selectOption('G-E8748C2B');
  await admin.getByLabel('Nombre del inventario', { exact: false }).fill('Inventario Bodega');
  await admin.getByRole('button', { name: 'Crear inventario' }).click();
  await admin.getByText('Inventario creado').first().waitFor();
  check(true, 'A4 Gestión › Administrar inventarios: crea un inventario');
  await admin.goto(`${base}/inventario`);
  const switcher = admin.getByRole('combobox', { name: 'Inventario' });
  await switcher.waitFor();
  const options = await switcher.locator('option').allInnerTexts();
  await switcher.selectOption({ index: options.findIndex((o) => o.startsWith('Inventario Bodega')) });
  await admin.getByRole('heading', { name: 'Inventario · Inventario Bodega' }).waitFor();
  await switcher.selectOption({ index: options.findIndex((o) => o.startsWith('Inventario general')) });
  await admin.getByRole('heading', { name: 'Inventario · Inventario general' }).waitFor();
  check(true, `A5 Cambia de inventario y vuelve (${options.join(' | ')})`);

  // ---------------------------------------------------------- EMPLEADO
  const empCtx = await browser.newContext({ viewport: { width: 1280, height: 860 } });
  let emp = await login(empCtx, 'empleado', 'Caja segura 99x');
  emp.on('pageerror', (e) => errors.push(`empleado: ${e.message}`));
  await emp.getByRole('link', { name: 'Vender', exact: true }).first().click();
  const search = emp.getByLabel('Buscar producto por código o descripción');
  await search.waitFor();
  check(true, 'E1 El empleado abre el punto de venta');
  await search.fill('0257');
  await emp.getByRole('button', { name: /0257 · VARILLA/ }).waitFor();
  await search.press('Enter');
  await emp.getByLabel('Cantidad de 0257').fill('2');
  await emp.getByText('$ 56.000').first().waitFor();
  check(true, 'E2 Selecciona el producto, lo agrega al carrito y el total se calcula ($ 56.000)');
  await emp.getByRole('button', { name: 'Efectivo' }).click();
  await emp.getByLabel('Recibido').fill('60000');
  await emp.waitForTimeout(800);
  await emp.getByRole('button', { name: /^Cobrar/ }).click();
  await emp.getByRole('button', { name: 'Registrar venta' }).click();
  const done = emp.getByRole('heading', { name: /Venta V-\d+ registrada/ });
  await done.waitFor();
  const saleNumber = (await done.innerText()).match(/V-\d+/)[0];
  check(true, `E3 Confirma la venta ${saleNumber}`);
  const stock = await (await empCtx.request.get(`${base}/api/products/1`)).json();
  check(stock.stock === '8', `E4 El inventario se actualiza (10 → ${stock.stock})`);
  await admin.goto(`${base}/vender/historial`);
  await admin.getByRole('table', { name: 'Historial de ventas' }).getByText(saleNumber).waitFor();
  check(true, 'E5 El administrador ve la venta del empleado');
  await emp.goto(`${base}/inventario`);
  await emp.getByRole('heading', { name: 'Inventario · Inventario general' }).waitFor();
  check(await emp.getByRole('button', { name: 'Nuevo producto' }).count() === 1, 'E6 Conserva sus permisos de usuario en el inventario (puede ingresar productos)');
  await emp.getByRole('button', { name: /Salir/ }).click();
  await emp.getByRole('dialog', { name: 'Cerrar sesión' }).getByRole('button', { name: 'Cerrar sesión' }).click();
  await emp.getByRole('button', { name: 'Ingresar' }).waitFor();
  await emp.close();
  emp = await login(empCtx, 'empleado', 'Caja segura 99x');
  await emp.getByRole('link', { name: 'Vender', exact: true }).first().click();
  await emp.getByLabel('Buscar producto por código o descripción').waitFor();
  check(true, 'E7 Tras cerrar e iniciar sesión mantiene el punto de venta');

  // ---------------------------------------------------------- seguridad
  const foreign = await empCtx.request.get(`${base}/api/inventories`);
  check((await foreign.json()).every((i) => i.name !== 'Inventario Bodega'), 'S1 El empleado no ve el inventario de otro grupo');
  check(errors.length === 0, `Sin errores de JavaScript${errors.length ? `: ${errors.join(' | ')}` : ''}`);
  await admin.screenshot({ path: join(shots, 'admin-historial.png'), fullPage: true });
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

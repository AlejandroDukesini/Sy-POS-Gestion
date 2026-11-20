// Inventarios por administrador asociados a grupos, con navegador real y servidor real. Cada persona usa su propio
// contexto (cookies distintas = dispositivo independiente): administrador, Ana y Beto (grupo Armenia), Dani (Bodega)
// y Caro (sin grupo). Comprueba creación desde la interfaz, panel de selección, sincronización en vivo entre
// sesiones, permisos por inventario en caliente, manipulación de identificadores, reconexión, concurrencia y la
// asociación del inventario sin grupo.
//   npm run build && node e2e/inventories.mjs
import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { chromium } from 'playwright-core';

const root = resolve(import.meta.dirname, '..', '..');
const python = process.env.PYTHON ?? join(root, 'backend', '.venv', 'Scripts', 'python.exe');
const port = 8771;
const base = `http://127.0.0.1:${port}`;
const shots = process.env.SHOTS ?? mkdtempSync(join(tmpdir(), 'pospy-inventarios-shots-'));
mkdirSync(shots, { recursive: true });
const dataDir = mkdtempSync(join(tmpdir(), 'pospy-e2e-inventarios-'));
const failures = [];
const check = (ok, message) => { console.log(`${ok ? 'OK  ' : 'FALLA'} ${message}`); if (!ok) failures.push(message); };
const H = { 'X-Requested-With': 'pos-py', 'Content-Type': 'application/json' };
const ADMIN = { username: 'alejandro', password: 'Clave segura 2026' };
const PEOPLE = [
  { username: 'ana', full_name: 'Ana Caja', password: 'Caja segura 99x', final: 'Caja segura 99xN' },
  { username: 'beto', full_name: 'Beto Bodega', password: 'Bodega firme 88z', final: 'Bodega firme 88zN' },
  { username: 'dani', full_name: 'Dani Norte', password: 'Norte claro 66w', final: 'Norte claro 66wN' },
  { username: 'caro', full_name: 'Caro Centro', password: 'Centro fijo 55v', final: 'Centro fijo 55vN' },
];

const server = spawn(python, ['-m', 'pospy', '--port', String(port), '--data-dir', dataDir, '--web-dist', join(root, 'frontend', 'dist')],
  { cwd: join(root, 'backend'), env: { ...process.env, POS_SETUP_CODE: 'E2E-CODE-0007' } });
server.stderr.on('data', () => {});
server.stdout.on('data', () => {});
async function waitHealth() {
  for (let i = 0; i < 60; i++) {
    try { if ((await fetch(`${base}/api/health`)).ok) return; } catch { /* arrancando */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error('El servidor no arrancó');
}
async function until(fn, timeout = 15000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (await fn().catch(() => false)) return true;
    await new Promise((r) => setTimeout(r, 200));
  }
  return false;
}
async function overflowOf(page) {
  await page.waitForTimeout(300);
  return page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
}
const rowText = async (page, code) => (await page.getByRole('table', { name: 'Productos del inventario' })
  .getByRole('row', { name: new RegExp(code) }).innerText()).replace(/\s+/g, ' ');

const browser = await chromium.launch({ channel: process.env.BROWSER ?? 'msedge', headless: true });
try {
  await waitHealth();
  const setup = await fetch(`${base}/api/setup`, { method: 'POST', headers: H,
    body: JSON.stringify({ code: 'E2E-CODE-0007', username: ADMIN.username, full_name: 'Alejandro Admin', password: ADMIN.password }) });
  check(setup.ok, 'Instalación con administrador (empieza con su «Inventario principal», sin productos)');
  const adminCtx = await browser.newContext({ viewport: { width: 1366, height: 900 } });
  const admin = await adminCtx.newPage();
  const errors = [];
  admin.on('pageerror', (e) => errors.push(e.message));
  await admin.goto(base);
  await admin.getByLabel('Usuario', { exact: false }).fill(ADMIN.username);
  await admin.getByLabel('Contraseña', { exact: false }).fill(ADMIN.password);
  await admin.getByRole('button', { name: 'Ingresar' }).click();
  await admin.getByRole('link', { name: 'Inventario' }).first().waitFor();
  const api = adminCtx.request;
  const main = (await (await api.get(`${base}/api/inventories`)).json())[0];
  check(main.name === 'Inventario principal' && main.products === 0, '0 El administrador empieza con un inventario vacío');

  const emps = {};
  for (const p of PEOPLE) {
    const r = await api.post(`${base}/api/users`, { headers: H, data: { username: p.username, full_name: p.full_name, role: 'employee', password: p.password } });
    p.id = (await r.json()).id;
    if (p.username === 'ana') {   // como usuario puede ingresar productos; en el inventario decidirá el administrador
      await api.put(`${base}/api/users/${p.id}`, { headers: H, data: { permissions: ['inventario.ver', 'inventario.editar', 'ventas.vender',
        'ventas.historial', 'documentos.ver'] } });
    }
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 860 } });
    await ctx.request.post(`${base}/api/auth/login`, { headers: H, data: { username: p.username, password: p.password } });
    await ctx.request.post(`${base}/api/auth/password`, { headers: H, data: { current: p.password, password: p.final } });
    const page = await ctx.newPage();
    page.on('pageerror', (e) => errors.push(`${p.username}: ${e.message}`));
    emps[p.username] = { ctx, page, api: ctx.request, id: p.id };
  }
  const groups = {};
  for (const [k, name, members] of [['armenia', 'Sucursal Armenia', ['ana', 'beto']], ['bodega', 'Bodega Central', ['dani']],
    ['pereira', 'Sucursal Pereira', []]]) {
    const g = (await (await api.post(`${base}/api/groups`, { headers: H, data: { name } })).json()).group.public_id;
    const inv = await (await api.post(`${base}/api/groups/${g}/invitations`, { headers: H, data: { max_uses: 5 } })).json();
    const token = inv.url.split('/unirse/')[1];
    for (const m of members) await emps[m].api.post(`${base}/api/invitations/${token}/accept`, { headers: H });
    groups[k] = g;
  }

  // ---------------------------------------------------------- 1. crear un inventario desde la interfaz
  await admin.goto(`${base}/gestion`);
  await admin.getByRole('link', { name: /Administrar inventarios/ }).click();
  await admin.getByRole('button', { name: 'Nuevo inventario' }).click();
  await admin.getByLabel('Grupo al que pertenece', { exact: false }).selectOption(groups.armenia);
  await admin.getByLabel('Nombre del inventario', { exact: false }).fill('Inventario Armenia');
  await admin.getByText('Ana Caja (ana)').waitFor();
  check(await admin.getByRole('checkbox', { name: /Ana Caja/ }).isChecked() && await admin.getByRole('checkbox', { name: /Beto Bodega/ }).isChecked(),
    '1 El formulario muestra los integrantes del grupo para autorizarlos');
  await admin.getByRole('button', { name: 'Crear inventario' }).click();
  await admin.getByText('Inventario creado').first().waitFor();
  const armenia = admin.url().split('/').pop();
  check(armenia.startsWith('I-'), `   Inventario creado y asociado al grupo (${armenia})`);
  const bodega = (await (await api.post(`${base}/api/inventories`, { headers: H, data: { name: 'Inventario Bodega', group: groups.bodega } })).json()).key;
  const pereira = (await (await api.post(`${base}/api/inventories`, { headers: H, data: { name: 'Inventario Pereira', group: groups.pereira } })).json()).key;
  const dup = await api.post(`${base}/api/inventories`, { headers: H, data: { name: 'Otro', group: groups.armenia } });
  check(dup.status() === 409, '   Un grupo no puede tener dos inventarios');

  // ---------------------------------------------------------- 2. con 3 o más: panel de selección
  for (const [code, desc, stock] of [['TAL-01', 'Taladro', '5'], ['MAR-02', 'Martillo', '3']]) {
    await api.post(`${base}/api/products`, { headers: { ...H, 'X-Inventory': armenia }, data: { code, description: desc, price: '10000', initial_stock: stock } });
  }
  await api.post(`${base}/api/products`, { headers: { ...H, 'X-Inventory': bodega }, data: { code: 'TAL-01', description: 'Taladro bodega', price: '9000', initial_stock: '50' } });
  await admin.goto(`${base}/inventario`);
  await admin.getByRole('heading', { name: 'Seleccione el inventario' }).waitFor();
  const cards = admin.getByRole('article');
  const cardArm = admin.getByRole('article', { name: 'Inventario Armenia' });
  check(await cards.count() === 4 && (await cardArm.innerText()).includes('Grupo Sucursal Armenia') && (await cardArm.innerText()).includes('TAL-01')
    && (await cardArm.innerText()).includes('MAR-02') && (await admin.getByRole('article', { name: 'Inventario Pereira' }).innerText()).includes('Aún no tiene productos'),
  '2 Con 4 inventarios aparece el panel: grupo, primeros productos reales y estado vacío');
  await admin.screenshot({ path: join(shots, '01-panel-seleccion.png'), fullPage: true });
  await admin.getByLabel('Grupo').selectOption(groups.bodega);
  check(await cards.count() === 1, '   Filtrar por grupo');
  await admin.getByLabel('Grupo').selectOption('');
  await admin.getByRole('button', { name: 'Ingresar a Inventario Armenia' }).click();
  await admin.getByRole('heading', { name: 'Inventario · Inventario Armenia' }).waitFor();
  check(true, '   Ingresar fija el inventario activo y lo muestra en el título');

  // ---------------------------------------------------------- 3. empleados de un solo inventario: entran directo
  const ana = emps.ana.page;
  const beto = emps.beto.page;
  const dani = emps.dani.page;
  await ana.goto(`${base}/inventario`);
  await beto.goto(`${base}/inventario`);
  await dani.goto(`${base}/inventario`);
  await ana.getByRole('heading', { name: 'Inventario · Inventario Armenia' }).waitFor();
  await beto.getByRole('table', { name: 'Productos del inventario' }).getByText('TAL-01').waitFor();
  await dani.getByRole('heading', { name: 'Inventario · Inventario Bodega' }).waitFor();
  check(await ana.getByRole('heading', { name: 'Seleccione el inventario' }).count() === 0
    && await ana.getByRole('button', { name: 'Nuevo producto' }).count() === 1,
  '3 Ana (un inventario) entra directo y conserva lo que permite su usuario (ve «Nuevo producto»)');
  check((await dani.getByRole('table', { name: 'Productos del inventario' }).innerText()).includes('Taladro bodega')
    && !(await dani.getByRole('table', { name: 'Productos del inventario' }).innerText()).includes('Martillo'), '   Dani ve solo el inventario de su grupo');

  // ---------------------------------------------------------- 4. sincronización entre sesiones independientes
  await admin.getByRole('button', { name: 'Nuevo producto' }).click();
  const dlg = admin.getByRole('dialog', { name: 'Nuevo producto' });
  await dlg.getByLabel('Código', { exact: false }).fill('BRO-03');
  await dlg.getByLabel('Descripción', { exact: false }).fill('Broca');
  await dlg.getByLabel('Precio sin descuento', { exact: false }).fill('500');
  await dlg.getByLabel('Existencia inicial', { exact: false }).fill('6');
  let t0 = Date.now();
  await dlg.getByRole('button', { name: 'Guardar' }).click();
  check(await until(async () => (await ana.getByRole('table', { name: 'Productos del inventario' }).innerText()).includes('BRO-03')),
    `4 El administrador ingresa un producto y Ana lo ve sin recargar (${Date.now() - t0} ms)`);
  const bro = (await (await api.get(`${base}/api/products?q=BRO-03`, { headers: { 'X-Inventory': armenia } })).json()).items[0];
  const methods = Object.fromEntries((await (await api.get(`${base}/api/payment-methods`)).json()).map((m) => [m.code, m.id]));
  await admin.getByRole('link', { name: 'Movimientos de inventario' }).click();
  await admin.getByRole('table', { name: 'Movimientos de inventario' }).waitFor();
  t0 = Date.now();
  const sale = await emps.ana.api.post(`${base}/api/sales`, { headers: { ...H, 'Idempotency-Key': `e2e-${Date.now()}` },
    data: { lines: [{ product_id: bro.id, qty: '2' }], payments: [{ method_id: methods.efectivo, amount: '1000' }] } });
  check(sale.ok(), '   Ana registra una venta (su sesión, su dispositivo)');
  check(await until(async () => /BRO-03.*\b4\b/.test(await rowText(beto, 'BRO-03'))), `   Beto ve la existencia nueva (6 → 4) sin recargar (${Date.now() - t0} ms)`);
  check(await until(async () => (await admin.getByRole('table', { name: 'Movimientos de inventario' }).innerText()).includes('Ana Caja')),
    '   El administrador ve el movimiento de Ana sin recargar');
  check(!(await dani.getByRole('table', { name: 'Productos del inventario' }).innerText()).includes('BRO-03'), '   Dani (otro inventario) no recibe nada');

  // ---------------------------------------------------------- 5. permisos por inventario en caliente
  await admin.goto(`${base}/gestion/inventarios/${armenia}`);
  const anaRow = admin.locator('li', { has: admin.getByText('Ana Caja', { exact: true }) });
  await anaRow.getByRole('button', { name: 'Editar permisos' }).click();
  await anaRow.getByRole('checkbox', { name: 'Crear, editar y desactivar productos' }).uncheck();
  await admin.getByRole('button', { name: 'Guardar cambios' }).click();
  await admin.getByText('Cambios guardados').first().waitFor();
  check(await until(async () => await ana.getByRole('button', { name: 'Nuevo producto' }).count() === 0, 20000),
    '5 El administrador restringe a Ana en este inventario (sin ingresar productos) y su pantalla se actualiza sola, sin cerrar su sesión');
  const blocked = await emps.ana.api.post(`${base}/api/products`, { headers: H, data: { code: 'X-1', description: 'X', price: '1' } });
  check(blocked.status() === 403, '   El servidor aplica la misma restricción (403)');

  // ---------------------------------------------------------- 6. seguridad y manipulación de identificadores
  const d1 = await emps.dani.api.get(`${base}/api/products/${bro.id}`);
  const d2 = await emps.dani.api.get(`${base}/api/products`, { headers: { 'X-Inventory': armenia } });
  const d3 = await emps.dani.api.post(`${base}/api/sales`, { headers: { ...H, 'X-Inventory': armenia, 'Idempotency-Key': `e2e-x-${Date.now()}` },
    data: { lines: [{ product_id: bro.id, qty: '1' }], payments: [{ method_id: methods.efectivo, amount: '500' }] } });
  const d4 = await emps.dani.api.put(`${base}/api/inventories/${armenia}`, { headers: H, data: { name: 'Mío' } });
  check(d1.status() === 404 && d2.status() === 403 && d3.status() >= 403 && d4.status() >= 403,
    `6 Dani no ve, no vende ni edita el inventario de otro grupo aunque cambie identificadores (${[d1, d2, d3, d4].map((r) => r.status())})`);

  // ---------------------------------------------------------- 7. reconexión y concurrencia
  await emps.beto.ctx.setOffline(true);
  await beto.evaluate(() => window.dispatchEvent(new Event('offline')));
  await emps.ana.api.post(`${base}/api/sales`, { headers: { ...H, 'Idempotency-Key': `e2e-r-${Date.now()}` },
    data: { lines: [{ product_id: bro.id, qty: '1' }], payments: [{ method_id: methods.efectivo, amount: '500' }] } });
  await emps.beto.ctx.setOffline(false);
  await beto.evaluate(() => window.dispatchEvent(new Event('online')));
  check(await until(async () => /BRO-03.*\b3\b/.test(await rowText(beto, 'BRO-03')), 30000), '7 Beto pierde la red; al volver ve la venta hecha mientras estaba desconectado');
  const tries = await Promise.all(['ana', 'beto'].map((w, i) => emps[w].api.post(`${base}/api/sales`, { headers: { ...H, 'Idempotency-Key': `e2e-c${i}-${Date.now()}` },
    data: { lines: [{ product_id: bro.id, qty: '2' }], payments: [{ method_id: methods.efectivo, amount: '1000' }] } })));
  const fin = await (await api.get(`${base}/api/products/${bro.id}`, { headers: { 'X-Inventory': armenia } })).json();
  check(tries.map((r) => r.status()).sort().join(',') === '200,422' && fin.stock === '1', `   Dos ventas simultáneas de 2 de 3 unidades: una se rechaza (existencia ${fin.stock})`);

  // ---------------------------------------------------------- 8. asociar el inventario sin grupo
  const caro = emps.caro.page;
  await caro.goto(`${base}/inventario`);
  await caro.getByRole('heading', { name: 'Inventario · Inventario principal' }).waitFor();
  const gc = (await (await api.post(`${base}/api/groups`, { headers: H, data: { name: 'Casa Renault' } })).json()).group.public_id;
  const ic = await (await api.post(`${base}/api/groups/${gc}/invitations`, { headers: H, data: { max_uses: 5 } })).json();
  await emps.caro.api.post(`${base}/api/invitations/${ic.url.split('/unirse/')[1]}/accept`, { headers: H });
  await admin.goto(`${base}/gestion/inventarios/${main.key}`);
  await admin.getByText('Asocie este inventario a un grupo').waitFor();
  await admin.getByLabel('Grupo asociado').selectOption(gc);
  await admin.getByRole('button', { name: 'Guardar cambios' }).click();
  await admin.getByText('Cambios guardados').first().waitFor();
  check(await until(async () => (await caro.getByRole('heading', { level: 1 }).innerText()).includes('Inventario principal')
    && (await caro.getByText(/Grupo Casa Renault/).count()) === 1, 20000),
  '8 El inventario sin grupo se asocia a «Casa Renault» y Caro sigue en él, ahora por su grupo');

  // ---------------------------------------------------------- 9. persistencia y teléfono
  const again = await (await emps.ana.api.get(`${base}/api/products/${bro.id}`)).json();
  check(again.stock === '1', '9 Los datos persisten en el servidor (consulta independiente)');
  await admin.setViewportSize({ width: 360, height: 780 });
  for (const path of ['/inventario/seleccionar', '/gestion/inventarios', `/gestion/inventarios/${armenia}`]) {
    await admin.goto(`${base}${path}`);
    await admin.getByRole('heading').first().waitFor();
    const o = await overflowOf(admin);
    check(o <= 0, `   Teléfono de 360 px sin desplazamiento horizontal en ${path} (${o}px)`);
  }
  await admin.screenshot({ path: join(shots, '02-movil-panel.png'), fullPage: true });
  void pereira;
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

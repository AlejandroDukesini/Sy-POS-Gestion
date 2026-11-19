// Inventario por grupo con navegador real y servidor real: administrador y empleados en contextos separados
// (cookies distintas = dispositivos independientes). Registro de productos desde la aplicación, ventas que se
// ven en vivo, anulación con movimientos compensatorios, devoluciones con estado del producto, concurrencia,
// aislamiento entre grupos, indicador de sincronización y persistencia tras reiniciar el servidor.
//   npm run build && node e2e/group-inventory.mjs
// Variables: PYTHON, BROWSER (msedge | chrome), SHOTS (carpeta de capturas).
import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { chromium } from 'playwright-core';

const root = resolve(import.meta.dirname, '..', '..');
const python = process.env.PYTHON ?? join(root, 'backend', '.venv', 'Scripts', 'python.exe');
const port = 8769;
const base = `http://127.0.0.1:${port}`;
const shots = process.env.SHOTS ?? mkdtempSync(join(tmpdir(), 'pospy-inventario-grupo-shots-'));
mkdirSync(shots, { recursive: true });
const dataDir = mkdtempSync(join(tmpdir(), 'pospy-e2e-inventario-grupo-'));
const failures = [];
const check = (ok, message) => { console.log(`${ok ? 'OK  ' : 'FALLA'} ${message}`); if (!ok) failures.push(message); };
const H = { 'X-Requested-With': 'pos-py', 'Content-Type': 'application/json' };
const ADMIN = { username: 'gerente', password: 'Clave segura 2026' };
const PEOPLE = [
  { username: 'ana', full_name: 'Ana Caja', password: 'Caja segura 99x', final: 'Caja segura 99xN' },
  { username: 'beto', full_name: 'Beto Bodega', password: 'Bodega firme 88z', final: 'Bodega firme 88zN' },
  { username: 'caro', full_name: 'Caro Compras', password: 'Compras claras 77y', final: 'Compras claras 77yN' },
];

let server = null;
function startServer() {
  server = spawn(python, ['-m', 'pospy', '--port', String(port), '--data-dir', dataDir, '--web-dist', join(root, 'frontend', 'dist')],
    { cwd: join(root, 'backend'), env: { ...process.env, POS_SETUP_CODE: 'E2E-CODE-0005' } });
  server.stderr.on('data', () => {});
  server.stdout.on('data', () => {});
}
async function stopServer() {
  const exited = new Promise((r) => server.once('exit', r));
  server.kill();
  await exited;
  for (let i = 0; i < 40; i++) {
    try { await fetch(`${base}/api/health`); } catch { return; }
    await new Promise((r) => setTimeout(r, 250));
  }
}
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
const metric = (page, label) => page.locator('.metric', { has: page.getByText(label, { exact: true }) }).locator('.metric-value');
const stockCell = async (page, code) => {
  const row = page.getByRole('table', { name: 'Productos del inventario' }).getByRole('row', { name: new RegExp(code) });
  return (await row.innerText()).replace(/\s+/g, ' ');
};

startServer();
const browser = await chromium.launch({ channel: process.env.BROWSER ?? 'msedge', headless: true });
try {
  await waitHealth();
  const setup = await fetch(`${base}/api/setup`, { method: 'POST', headers: H,
    body: JSON.stringify({ code: 'E2E-CODE-0005', username: ADMIN.username, full_name: 'Gerente General', password: ADMIN.password }) });
  check(setup.ok, 'Instalación local con administrador');

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
  // Un producto del inventario general (anterior a los grupos)
  await api.post(`${base}/api/products`, { headers: H, data: { code: 'GEN-01', description: 'Producto general', price: '1000', initial_stock: '3' } });

  // Empleados (cada uno en su propio contexto = otro dispositivo) y grupo «Sucursal Armenia» con Ana y Beto
  const emps = {};
  for (const p of PEOPLE) {
    const r = await api.post(`${base}/api/users`, { headers: H,
      data: { username: p.username, full_name: p.full_name, role: 'employee', password: p.password } });
    p.id = (await r.json()).id;
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 860 } });
    await ctx.request.post(`${base}/api/auth/login`, { headers: H, data: { username: p.username, password: p.password } });
    await ctx.request.post(`${base}/api/auth/password`, { headers: H, data: { current: p.password, password: p.final } });
    const page = await ctx.newPage();
    page.on('pageerror', (e) => errors.push(e.message));
    emps[p.username] = { ctx, page, api: ctx.request, id: p.id };
  }
  const group = await (await api.post(`${base}/api/groups`, { headers: H, data: { name: 'Sucursal Armenia' } })).json();
  const G = group.group.public_id;
  const invite = await (await api.post(`${base}/api/groups/${G}/invitations`, { headers: H, data: { max_uses: 5 } })).json();
  const token = invite.url.split('/unirse/')[1];
  for (const who of ['ana', 'beto']) await emps[who].api.post(`${base}/api/invitations/${token}/accept`, { headers: H });
  const GH = { ...H, 'X-Inventory': G };

  // ---------------------------------------------------------------- 1. el admin elige el inventario del grupo
  await admin.reload();
  const switcher = admin.getByRole('combobox', { name: 'Inventario' });
  await switcher.waitFor();
  const optionsText = await switcher.locator('option').allInnerTexts();
  check(optionsText.join('|') === 'Inventario general|Sucursal Armenia', `1 El administrador elige entre sus inventarios (${optionsText.join(', ')})`);
  await switcher.selectOption(G);
  await admin.goto(`${base}/inventario`);
  await admin.getByRole('heading', { name: 'Inventario · Sucursal Armenia' }).waitFor();
  check(await until(async () => await admin.getByText('Aún no hay productos').count() === 1), '   El inventario del grupo empieza vacío (no mezcla el general)');

  // ---------------------------------------------------------------- 2. registrar un producto desde la aplicación
  await admin.getByRole('button', { name: 'Nuevo producto' }).click();
  let dlg = admin.getByRole('dialog', { name: 'Nuevo producto' });
  await dlg.getByLabel('Código', { exact: false }).fill('TAL-01');
  await dlg.getByLabel('Descripción', { exact: false }).fill('Taladro percutor');
  await dlg.getByLabel('Precio sin descuento', { exact: false }).fill('10000');
  await dlg.getByLabel('Existencia inicial', { exact: false }).fill('-3');
  await dlg.getByRole('button', { name: 'Guardar' }).click();
  check(await until(async () => (await dlg.innerText()).match(/negativ|mayor|cero/i)), '2 No acepta una existencia inicial negativa');
  await dlg.getByLabel('Existencia inicial', { exact: false }).fill('5');
  await dlg.getByLabel('Existencia mínima', { exact: false }).fill('1');
  await dlg.getByRole('button', { name: 'Guardar' }).click();
  await dlg.waitFor({ state: 'detached' });
  await admin.getByRole('table', { name: 'Productos del inventario' }).getByText('TAL-01').waitFor();
  check(true, '2 Producto creado desde la aplicación en el inventario del grupo');
  const dup = await api.post(`${base}/api/products`, { headers: GH, data: { code: 'TAL-01', description: 'Otro', price: '1' } });
  check(dup.status() === 422, '   El código no se repite dentro del mismo inventario');
  const prod = (await (await api.get(`${base}/api/products?q=TAL-01`, { headers: GH })).json()).items[0];

  // ---------------------------------------------------------------- 3. todos ven el mismo inventario
  const ana = emps.ana.page;
  const beto = emps.beto.page;
  await ana.goto(`${base}/inventario`);
  await beto.goto(`${base}/inventario`);
  await ana.getByRole('table', { name: 'Productos del inventario' }).getByText('TAL-01').waitFor();
  await beto.getByRole('table', { name: 'Productos del inventario' }).getByText('TAL-01').waitFor();
  check(await ana.getByRole('combobox', { name: 'Inventario' }).count() === 0
    && (await ana.locator('.inventory-chip').innerText()) === 'Sucursal Armenia',
  '3 Ana y Beto (otro dispositivo) trabajan sobre el mismo inventario del grupo');
  check(await ana.getByText('GEN-01').count() === 0, '   Los integrantes no ven el inventario general');

  // ---------------------------------------------------------------- 4. venta de Ana: el admin y Beto lo ven sin recargar
  await admin.goto(`${base}/inventario/movimientos`);
  await metric(admin, 'Salidas').waitFor();
  const salidasAntes = await metric(admin, 'Salidas').innerText();
  const methods = Object.fromEntries((await (await api.get(`${base}/api/payment-methods`)).json()).map((m) => [m.code, m.id]));
  const t0 = Date.now();
  const saleRes = await emps.ana.api.post(`${base}/api/sales`, { headers: { ...H, 'Idempotency-Key': `e2e-a-${Date.now()}` },
    data: { lines: [{ product_id: prod.id, qty: '3' }], payments: [{ method_id: methods.efectivo, amount: '30000' }] } });
  const sale = await saleRes.json();
  check(saleRes.ok(), '4 Ana registra una venta de 3 unidades');
  const live = await until(async () => (await metric(admin, 'Salidas').innerText()) === '1');
  check(salidasAntes === '0' && live, `   El panel del administrador muestra la salida sin recargar (${Date.now() - t0} ms)`);
  check(await until(async () => /TAL-01.*\b2\b/.test(await stockCell(beto, 'TAL-01'))),
    '   Beto ve las existencias actualizadas (5 → 2) sin recargar');
  const salidaRow = admin.getByRole('table', { name: 'Movimientos de inventario' }).getByRole('row', { name: new RegExp(sale.number) });
  await salidaRow.waitFor();
  const rowText = (await salidaRow.innerText()).replace(/\s+/g, ' ');
  check(rowText.includes('Venta') && rowText.includes('Ana Caja') && rowText.includes('-3'),
    `   El movimiento muestra tipo, referencia, cantidad y responsable (${rowText.slice(0, 120)})`);
  await admin.screenshot({ path: join(shots, '01-movimientos-grupo.png'), fullPage: true });

  // ---------------------------------------------------------------- 5. anulación por la interfaz
  await admin.goto(`${base}/vender/historial/${sale.id}`);
  await admin.getByRole('button', { name: 'Anular' }).click();
  dlg = admin.getByRole('dialog', { name: `Anular venta ${sale.number}` });
  await dlg.getByLabel('Motivo', { exact: false }).fill('Cliente desistió');
  await dlg.getByRole('button', { name: 'Anular venta' }).click();
  await admin.getByText('Venta anulada', { exact: true }).first().waitFor();
  const afterVoid = await (await api.get(`${base}/api/products/${prod.id}`)).json();
  const again = await api.post(`${base}/api/sales/${sale.id}/void`, { headers: H, data: { reason: 'otra vez' } });
  const hist = (await (await api.get(`${base}/api/movements?product_id=${prod.id}`)).json()).items.map((m) => m.kind);
  check(afterVoid.stock === '5' && again.status() === 422 && hist.join(',') === 'anulacion_venta,venta,inicial',
    `5 Anular devuelve las 5 unidades, conserva la salida original y no se puede anular dos veces (${hist.join(', ')})`);
  check((await admin.getByText(/anulada por Gerente General/).count()) === 1, '   Queda quién anuló y el motivo');
  const anaVoid = await emps.ana.api.post(`${base}/api/sales/${sale.id}/void`, { headers: H, data: { reason: 'x' } });
  check(anaVoid.status() === 403, '   Un empleado sin permiso no puede anular');

  // ---------------------------------------------------------------- 6. devolución con estado por la interfaz
  const sale2 = await (await emps.beto.api.post(`${base}/api/sales`, { headers: { ...H, 'Idempotency-Key': `e2e-b-${Date.now()}` },
    data: { lines: [{ product_id: prod.id, qty: '2' }], payments: [{ method_id: methods.efectivo, amount: '20000' }] } })).json();
  await admin.goto(`${base}/vender/historial/${sale2.id}`);
  await admin.getByRole('button', { name: 'Devolución' }).click();
  dlg = admin.getByRole('dialog', { name: `Devolución de la venta ${sale2.number}` });
  await dlg.getByLabel(/Cantidad a devolver de TAL-01/).fill('2');
  await dlg.getByLabel('Estado del producto devuelto TAL-01').selectOption('revision');
  await dlg.getByLabel('Motivo', { exact: false }).fill('Cliente reporta falla');
  await dlg.getByLabel('Reembolsar con').selectOption({ label: 'Efectivo' });
  await dlg.getByRole('button', { name: 'Registrar devolución' }).click();
  await dlg.waitFor({ state: 'detached' });
  const pend = await (await api.get(`${base}/api/products/${prod.id}`)).json();
  check(pend.stock === '3', `6 Devolución «pendiente de revisión»: no vuelve al inventario todavía (existencia ${pend.stock})`);
  await admin.goto(`${base}/inventario/movimientos`);
  await admin.getByRole('tab', { name: 'Devoluciones' }).click();
  const retRow = admin.getByRole('table', { name: 'Devoluciones de clientes' }).getByRole('row', { name: new RegExp(sale2.number) });
  await retRow.waitFor();
  check((await retRow.innerText()).includes('Pendiente de revisión'), '   Aparece con la venta original y estado pendiente');
  await retRow.getByRole('button', { name: 'Revisar' }).click();
  dlg = admin.getByRole('dialog', { name: /Revisar devolución/ });
  await dlg.getByRole('button', { name: 'Apto: reingresar' }).click();
  await dlg.waitFor({ state: 'detached' });
  const resolved = await (await api.get(`${base}/api/products/${prod.id}`)).json();
  check(resolved.stock === '5' && await until(async () => (await retRow.innerText()).includes('Apto')),
    `   Al revisarlo como apto vuelve al inventario (existencia ${resolved.stock})`);
  await admin.screenshot({ path: join(shots, '02-devoluciones.png'), fullPage: true });

  // ---------------------------------------------------------------- 7. concurrencia: dos ventas de las últimas unidades
  const tries = await Promise.all(['ana', 'beto'].map((who, i) => emps[who].api.post(`${base}/api/sales`, {
    headers: { ...H, 'Idempotency-Key': `e2e-c${i}-${Date.now()}` },
    data: { lines: [{ product_id: prod.id, qty: '4' }], payments: [{ method_id: methods.efectivo, amount: '40000' }] } })));
  const codes = tries.map((r) => r.status()).sort();
  const fin = await (await api.get(`${base}/api/products/${prod.id}`)).json();
  check(codes.join(',') === '200,422' && fin.stock === '1', `7 Dos ventas simultáneas de 4 de 5 unidades: una se rechaza (${codes}), existencia ${fin.stock}`);
  const retry = await emps.ana.api.post(`${base}/api/sales`, { headers: { ...H, 'Idempotency-Key': 'e2e-repetida-0001' },
    data: { lines: [{ product_id: prod.id, qty: '1' }], payments: [{ method_id: methods.efectivo, amount: '10000' }] } });
  const retry2 = await emps.ana.api.post(`${base}/api/sales`, { headers: { ...H, 'Idempotency-Key': 'e2e-repetida-0001' },
    data: { lines: [{ product_id: prod.id, qty: '1' }], payments: [{ method_id: methods.efectivo, amount: '10000' }] } });
  const zero = await (await api.get(`${base}/api/products/${prod.id}`)).json();
  check(retry.ok() && (await retry2.json()).duplicate === true && zero.stock === '0',
    '   Reenviar la misma venta (reconexión) no la duplica');

  // ---------------------------------------------------------------- 8. aislamiento entre grupos
  const caro = emps.caro;
  const c1 = await caro.api.get(`${base}/api/products`, { headers: { 'X-Inventory': G } });
  const c2 = await caro.api.get(`${base}/api/products/${prod.id}`);
  const c3 = await caro.api.post(`${base}/api/sales`, { headers: { ...H, 'Idempotency-Key': `e2e-x-${Date.now()}` },
    data: { lines: [{ product_id: prod.id, qty: '1' }], payments: [{ method_id: methods.efectivo, amount: '10000' }] } });
  const c4 = await caro.api.get(`${base}/api/sales/${sale.id}`);
  check([c1, c2, c3, c4].every((r) => r.status() === 404), '8 Quien no pertenece al grupo no ve ni vende en su inventario, aunque cambie identificadores');
  await caro.page.goto(`${base}/inventario`);
  await caro.page.getByRole('table', { name: 'Productos del inventario' }).getByText('GEN-01').waitFor();
  check(await caro.page.getByText('TAL-01').count() === 0, '   Caro (sin grupo) trabaja en el inventario general');

  // ---------------------------------------------------------------- 9. indicador de sincronización
  await admin.goto(`${base}/inventario`);
  check(await until(async () => (await admin.locator('.sync-status').innerText()).includes('Sincronizado')), '9 Indicador «Sincronizado»');
  await adminCtx.setOffline(true);
  await admin.evaluate(() => window.dispatchEvent(new Event('offline')));
  check(await until(async () => (await admin.locator('.sync-status').innerText()).includes('Sin conexión')), '   Sin red: «Sin conexión»');
  await adminCtx.setOffline(false);
  await admin.evaluate(() => window.dispatchEvent(new Event('online')));
  const back = await until(async () => (await admin.locator('.sync-status').innerText()).includes('Sincronizado'), 30000);
  check(back, `   Al volver la red se reconecta y queda «Sincronizado» (${await admin.locator('.sync-status').innerText()})`);

  // ---------------------------------------------------------------- 10. persistencia tras reiniciar el servidor
  await stopServer();
  startServer();
  await waitHealth();
  await admin.goto(`${base}/inventario/movimientos`);
  await admin.getByRole('table', { name: 'Movimientos de inventario' }).waitFor();
  const dash = await (await api.get(`${base}/api/inventory/dashboard`, { headers: GH })).json();
  check(dash.inventory.key === G && dash.sales.completed >= 3 && dash.sales.voided === 1 && dash.counts.devoluciones.restocked === '2',
    `10 Tras reiniciar el servidor siguen ventas, anulación y devoluciones (${dash.sales.completed} ventas, ${dash.sales.voided} anulada)`);

  // ---------------------------------------------------------------- teléfono
  await admin.setViewportSize({ width: 360, height: 780 });
  for (const path of ['/inventario/movimientos', '/inventario']) {
    await admin.goto(`${base}${path}`);
    await admin.getByRole('heading').first().waitFor();
    const o = await overflowOf(admin);
    check(o <= 0, `Teléfono de 360 px sin desplazamiento horizontal en ${path} (${o}px)`);
  }
  await admin.screenshot({ path: join(shots, '03-movil-movimientos.png'), fullPage: true });
  check(errors.length === 0, `Sin errores de JavaScript en las páginas${errors.length ? `: ${errors.join(' | ')}` : ''}`);
  console.log(`\nCapturas en ${shots}`);
} catch (err) {
  failures.push(String(err));
  console.error(err);
} finally {
  await browser.close();
  server?.kill();
}
console.log(failures.length ? `\n${failures.length} falla(s)` : '\nTodo correcto');
process.exit(failures.length ? 1 : 0);

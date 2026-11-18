// Inventario con columnas personalizables + tareas de grupos de trabajo, con navegador real y servidor real:
// administrador y tres empleados en contextos separados (cookies distintas), un archivo CSV real importado por la
// interfaz y un reinicio REAL del servidor para comprobar la persistencia.
//   npm run build && node e2e/columns-group-tasks.mjs
// Variables: PYTHON, BROWSER (msedge | chrome), SHOTS (carpeta de capturas).
import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { chromium } from 'playwright-core';

const root = resolve(import.meta.dirname, '..', '..');
const python = process.env.PYTHON ?? join(root, 'backend', '.venv', 'Scripts', 'python.exe');
const port = 8768;
const base = `http://127.0.0.1:${port}`;
const shots = process.env.SHOTS ?? mkdtempSync(join(tmpdir(), 'pospy-columnas-shots-'));
mkdirSync(shots, { recursive: true });
const dataDir = mkdtempSync(join(tmpdir(), 'pospy-e2e-columnas-'));
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
    { cwd: join(root, 'backend'), env: { ...process.env, POS_SETUP_CODE: 'E2E-CODE-0004' } });
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
async function overflowOf(page) {
  await page.waitForTimeout(300);
  return page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
}
const card = (page, name) => page.getByRole('article', { name, exact: true });
const section = (page, title) => page.locator('section.card', { has: page.getByRole('heading', { name: title, exact: true }) });
const headers = (page) => page.getByRole('table', { name: 'Productos del inventario' }).getByRole('columnheader').allInnerTexts();
const columnNames = async (page) => {
  const names = page.getByRole('list', { name: 'Columnas adicionales activas' }).locator('.column-main > strong');
  await names.first().waitFor();
  return (await names.allInnerTexts()).map((t) => t.replace(/^\d+\.\s*/, ''));
};
async function until(fn, timeout = 15000) {   // espera a que la pantalla refleje el cambio
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (await fn()) return true;
    await new Promise((r) => setTimeout(r, 200));
  }
  return false;
}

startServer();
const browser = await chromium.launch({ channel: process.env.BROWSER ?? 'msedge', headless: true });
try {
  await waitHealth();
  const setup = await fetch(`${base}/api/setup`, { method: 'POST', headers: H,
    body: JSON.stringify({ code: 'E2E-CODE-0004', username: ADMIN.username, full_name: 'Gerente General', password: ADMIN.password }) });
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

  // Producto creado ANTES de las columnas: debe seguir funcionando igual.
  const old = await (await api.post(`${base}/api/products`, { headers: H, data: { code: 'MART-01', description: 'Martillo',
    price: '20000', cost: '10000', initial_stock: '5' } })).json();

  // ================================================================ PARTE A: inventario
  await admin.goto(`${base}/inventario/columnas`);
  const firstItem = admin.getByRole('list', { name: 'Columnas adicionales activas' }).getByRole('listitem').first();
  await firstItem.waitFor();
  check((await firstItem.innerText()).includes('Observaciones') && (await firstItem.innerText()).includes('Del sistema')
    && await firstItem.getByRole('button', { name: 'Eliminar' }).count() === 0, 'A1 «Observaciones» existe por defecto y no se puede eliminar');

  // A2-A4: columnas nuevas antes de importar un archivo real
  const csv = join(dataDir, 'inventario.csv');
  writeFileSync(csv, '﻿Código;Producto;Precio;Cantidad;Observaciones;Marca;Ubicación\n'
    + '001;Teclado;50000;10;Revisar proveedor;Logitech;Bodega A\n002;Mouse;20000;5;;Genius;Bodega B\n003;Monitor;900000;2;Pedido especial;Samsung;Bodega Z\n');
  await admin.getByRole('link', { name: 'Importar y exportar' }).click();
  await admin.getByLabel(/Archivo/).setInputFiles(csv);
  await admin.getByText('Primeras filas del archivo', { exact: true }).first().waitFor();
  check(await admin.getByRole('combobox', { name: 'Observaciones' }).inputValue() === 'Observaciones',
    'A2 El archivo se analiza, se ve la muestra y «Observaciones» se asigna sola por su nombre');
  await admin.getByRole('button', { name: 'Marca', exact: true }).click();
  await admin.getByRole('button', { name: 'Ubicación', exact: true }).click();
  await admin.getByLabel('Tipo de dato').nth(1).selectOption('lista');
  await admin.getByLabel('Opciones (separadas por coma)').fill('Bodega A, Bodega B');
  await admin.screenshot({ path: join(shots, '01-importar-columnas.png'), fullPage: true });
  await admin.getByRole('button', { name: 'Ver vista previa' }).click();
  await admin.getByText(/Al aplicar se agregarán al inventario: Marca, Ubicación/).waitFor();
  const invalidRow = await admin.getByText(/Filas con errores \(1\)/).count();
  check(invalidRow === 1, 'A3 La vista previa informa la fila inválida (Ubicación «Bodega Z» no está en la lista)');
  check(await (await api.get(`${base}/api/inventory/columns`)).json().then((d) => d.columns.length === 1),
    '   La vista previa todavía no crea columnas (se puede cancelar sin rastro)');
  await admin.getByRole('button', { name: 'Aplicar cambios' }).click();
  await admin.getByRole('dialog', { name: 'Aplicar importación' }).getByRole('button', { name: 'Aplicar' }).click();
  await admin.getByText(/Columnas agregadas: Marca, Ubicación/).waitFor();
  check(true, 'A4 Al aplicar se crean las columnas y los productos válidos');

  await admin.getByRole('link', { name: 'Productos', exact: true }).click();
  await admin.getByRole('table', { name: 'Productos del inventario' }).getByText('Logitech').waitFor();
  const h = await headers(admin);
  check(['Observaciones', 'Marca', 'Ubicación'].every((x) => h.includes(x)) && h.indexOf('Marca') > h.indexOf('Observaciones'),
    `A4 La tabla muestra las columnas en su orden (${h.slice(-3).join(', ')})`);
  check(await admin.getByRole('table', { name: 'Productos del inventario' }).getByText('Bodega A').count() === 1,
    '   Los valores quedan guardados en cada producto');

  // A5: columna después de crear el inventario + edición de valores (observación extensa)
  await admin.getByRole('link', { name: 'Administrar columnas' }).click();
  await admin.getByRole('button', { name: 'Agregar columna' }).click();
  let dlg = admin.getByRole('dialog', { name: 'Agregar columna' });
  await dlg.getByLabel('Nombre').fill('Garantía');
  await dlg.getByLabel('Tipo de dato').selectOption('si_no');
  await dlg.getByRole('button', { name: 'Guardar' }).click();
  await admin.getByRole('list', { name: 'Columnas adicionales activas' }).locator('.column-main > strong', { hasText: 'Garantía' }).waitFor();
  check(true, 'A5 Se agrega la columna «Garantía» (Sí/No) después de importar');
  await admin.getByRole('link', { name: 'Productos', exact: true }).click();
  await admin.getByRole('table', { name: 'Productos del inventario' }).getByText('Teclado').click();
  const panel = admin.getByRole('complementary', { name: 'Detalle del producto' });
  await panel.getByRole('button', { name: 'Editar' }).click();
  dlg = admin.getByRole('dialog', { name: 'Editar 001' });
  const longText = 'Producto reservado para el cliente Ruiz hasta el viernes. Revisar el estado del empaque y confirmar con el proveedor la fecha de reposición antes de entregarlo.';
  await dlg.getByLabel('Observaciones').fill(longText);
  await dlg.getByLabel('Garantía').selectOption('1');
  await dlg.getByRole('button', { name: 'Guardar' }).click();
  await panel.getByText(longText).waitFor();
  const clipped = admin.getByRole('table', { name: 'Productos del inventario' }).locator('.cell-clip', { hasText: 'Producto reservado' });
  const box = await clipped.boundingBox();
  check(Boolean(box) && box.width <= 330 && await clipped.getAttribute('title') === longText,
    `A5 Una observación extensa se recorta en la tabla (${Math.round(box?.width ?? 0)} px) y se ve completa en la ficha`);
  await admin.screenshot({ path: join(shots, '02-tabla-columnas.png') });

  // A6: editar con validación (conversión no segura)
  await admin.getByRole('link', { name: 'Administrar columnas' }).click();
  const marcaItem = admin.getByRole('list', { name: 'Columnas adicionales activas' }).getByRole('listitem').filter({ hasText: 'Marca' });
  await marcaItem.getByRole('button', { name: 'Editar' }).click();
  dlg = admin.getByRole('dialog', { name: 'Editar columna «Marca»' });
  await dlg.getByLabel('Tipo de dato').selectOption('entero');
  await dlg.getByRole('button', { name: 'Revisar el cambio' }).click();
  await dlg.getByText('No se puede aplicar').waitFor();
  check(await dlg.getByRole('button', { name: 'Aplicar el cambio' }).isDisabled(), 'A6 Cambiar «Marca» a número entero se bloquea: muestra qué productos lo impiden');
  await dlg.getByLabel('Tipo de dato').selectOption('texto');
  await dlg.getByLabel('Nombre').fill('Marca comercial');
  await dlg.getByRole('button', { name: 'Guardar' }).click();
  await admin.getByRole('list', { name: 'Columnas adicionales activas' }).locator('.column-main > strong', { hasText: 'Marca comercial' }).waitFor();
  check(true, 'A6 Se renombra la columna');

  // A8: reordenar y comprobar que persiste
  await admin.getByRole('button', { name: 'Subir Garantía' }).click();
  await admin.getByText('Orden guardado').first().waitFor();
  await admin.reload();
  let order = [];
  await until(async () => (order = await columnNames(admin)).join('|') === 'Observaciones|Marca comercial|Garantía|Ubicación', 5000);
  check(order.join('|') === 'Observaciones|Marca comercial|Garantía|Ubicación', `A8 El nuevo orden se conserva al recargar (${order.join(', ')})`);

  // A7: archivar conserva los datos; eliminar avisa y borra
  const garantia = admin.getByRole('list', { name: 'Columnas adicionales activas' }).getByRole('listitem').filter({ hasText: 'Garantía' });
  await garantia.getByRole('button', { name: 'Archivar' }).click();
  await section(admin, 'Columnas archivadas').getByText('Garantía').waitFor();
  await admin.getByRole('link', { name: 'Productos', exact: true }).click();
  await admin.getByRole('table', { name: 'Productos del inventario' }).waitFor();
  check(!(await headers(admin)).includes('Garantía'), 'A7 Una columna archivada desaparece de la tabla');
  await admin.getByRole('link', { name: 'Administrar columnas' }).click();
  await section(admin, 'Columnas archivadas').getByRole('button', { name: 'Restaurar' }).click();
  await admin.getByRole('list', { name: 'Columnas adicionales activas' }).locator('.column-main > strong', { hasText: 'Garantía' }).waitFor();
  const teclado = await (await api.get(`${base}/api/products?q=teclado`)).json();
  const cols = await (await api.get(`${base}/api/inventory/columns`)).json();
  const gid = String(cols.columns.find((c) => c.name === 'Garantía').id);
  check(teclado.items[0].custom[gid] === '1', '   Al restaurarla vuelve con sus datos');
  const ubic = admin.getByRole('list', { name: 'Columnas adicionales activas' }).getByRole('listitem').filter({ hasText: 'Ubicación' });
  await ubic.getByRole('button', { name: 'Eliminar' }).click();
  const confirm = admin.getByRole('dialog', { name: 'Eliminar columna' });
  check((await confirm.innerText()).includes('2 producto(s)'), 'A7 Antes de eliminar avisa cuántos productos tienen datos');
  await confirm.getByRole('button', { name: 'Eliminar definitivamente' }).click();
  await admin.getByText('Columna eliminada').first().waitFor();
  check(await until(async () => !(await columnNames(admin)).includes('Ubicación')), 'A7 La columna personalizada se elimina');

  // A9-A10: registros antiguos, ventas y exportación
  const oldNow = await (await api.get(`${base}/api/products/${old.id}`)).json();
  const methods = Object.fromEntries((await (await api.get(`${base}/api/payment-methods`)).json()).map((m) => [m.code, m.id]));
  const sale = await api.post(`${base}/api/sales`, { headers: { ...H, 'Idempotency-Key': `e2e-${Date.now()}` },
    data: { lines: [{ product_id: teclado.items[0].id, qty: '1' }], payments: [{ method_id: methods.efectivo, amount: '50000' }] } });
  const after = await (await api.get(`${base}/api/products/${teclado.items[0].id}`)).json();
  check(oldNow.stock === '5' && sale.ok() && after.stock === '9' && after.custom[gid] === '1',
    'A9 Un producto anterior sigue igual y vender un producto con columnas descuenta existencias sin tocar sus datos');
  const exported = await (await api.get(`${base}/api/products/export?fmt=csv`)).text();
  const head = exported.split('\n')[0];
  check(head.includes('Observaciones;Marca comercial;Garantía') && exported.includes('Logitech') && !head.includes('Ubicación'),
    'A10 La exportación incluye las columnas activas, en su orden, con sus valores');

  // ================================================================ PARTE B: tareas del grupo
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
  const group = await (await api.post(`${base}/api/groups`, { headers: H, data: { name: 'Turno mañana' } })).json();
  const G = group.group.public_id;
  const invite = await (await api.post(`${base}/api/groups/${G}/invitations`, { headers: H, data: { max_uses: 5 } })).json();
  const token = invite.url.split('/unirse/')[1];
  for (const who of ['ana', 'beto']) await emps[who].api.post(`${base}/api/invitations/${token}/accept`, { headers: H });
  check(true, 'B  Ana y Beto se unen al grupo con el enlace; Caro no');

  const ana = emps.ana.page;
  await ana.goto(`${base}/tareas/asignadas`);
  await ana.getByText('No tiene tareas en esta vista.').waitFor();

  await admin.goto(`${base}/grupos/${G}`);
  const board = section(admin, 'Tareas del grupo');
  await board.getByRole('button', { name: 'Asignar tarea' }).first().click();
  dlg = admin.getByRole('dialog', { name: 'Asignar tarea' });
  await dlg.getByRole('checkbox', { name: 'Ana Caja' }).waitFor();
  check((await dlg.innerText()).includes('Grupo: Turno mañana') && await dlg.getByRole('checkbox', { name: 'Caro Compras' }).count() === 0,
    'B2 El diálogo muestra solo a los integrantes del grupo (Caro no aparece)');
  await dlg.getByLabel('Tarea', { exact: false }).first().fill('Inventario de bodega');
  await dlg.getByLabel('Descripción', { exact: false }).fill('Contar pasillos 1 a 4');
  await dlg.getByLabel('Prioridad').selectOption('urgente');
  await dlg.getByLabel('Observaciones (opcional)').fill('Usar el lector de códigos');
  await dlg.getByLabel('Fecha límite', { exact: false }).fill('2030-01-10');
  await dlg.getByRole('checkbox', { name: 'Ana Caja' }).check();
  await dlg.getByRole('checkbox', { name: 'Beto Bodega' }).check();
  let t0 = Date.now();
  await dlg.getByRole('button', { name: 'Asignar' }).click();
  const adminCard = card(admin, 'Inventario de bodega');
  await adminCard.waitFor();
  check(true, 'B1/B3 El administrador crea la tarea y la asigna a dos integrantes');
  const anaCard = card(ana, 'Inventario de bodega');
  await anaCard.waitFor({ timeout: 15000 });
  check(true, `B4/B10 Ana recibe la tarea en su navegador sin recargar (${Date.now() - t0} ms)`);
  check((await anaCard.innerText()).includes('Prioridad urgente') && (await anaCard.innerText()).includes('Turno mañana'),
    '   Ana ve prioridad, fecha y grupo');
  check(await anaCard.getByRole('button', { name: 'Editar' }).count() === 0 && await anaCard.getByRole('button', { name: 'Eliminar' }).count() === 0,
    '   Ana no tiene botones de edición ni eliminación');

  const taskId = (await (await api.get(`${base}/api/tasks?group=${G}`)).json())[0].id;
  const caro = emps.caro.api;
  check((await (await caro.get(`${base}/api/tasks`)).json()).length === 0 && (await caro.get(`${base}/api/tasks/${taskId}`)).status() === 404,
    'B5 Caro (fuera del grupo) no ve la tarea (lista vacía y 404)');
  check((await api.post(`${base}/api/tasks`, { headers: H, data: { title: 'x', group: G, assignee_ids: [emps.caro.id] } })).status() === 422,
    'B5 El servidor no deja asignar a alguien que no es del grupo (422)');

  await board.getByRole('tab', { name: 'Todas' }).click();
  await anaCard.getByRole('button', { name: 'Iniciar' }).click();
  t0 = Date.now();
  const anaRow = adminCard.getByRole('list', { name: 'Responsables' }).getByRole('listitem').filter({ hasText: 'Ana Caja' });
  await anaRow.getByText('En progreso').waitFor({ timeout: 15000 });
  check(true, `B6/B7 Ana inicia y el administrador lo ve en vivo (${Date.now() - t0} ms)`);
  await anaCard.getByRole('button', { name: 'Marcar como completada' }).click();
  await adminCard.getByText('Avance: 1 de 2 completaron').waitFor({ timeout: 15000 });
  check((await adminCard.innerText()).includes('En progreso'), 'B8 Ana termina su parte: avance 1 de 2 y la tarea sigue «En progreso»');

  const beto = emps.beto.page;
  await beto.goto(`${base}/grupos/${G}`);
  const betoCard = card(beto, 'Inventario de bodega');
  await betoCard.waitFor();
  await betoCard.getByRole('button', { name: 'Marcar como completada' }).click();
  await adminCard.getByText('Avance: 2 de 2 completaron').waitFor({ timeout: 15000 });
  const states = await adminCard.getByRole('list', { name: 'Responsables' }).innerText();
  check(/Ana Caja\s*Completada/.test(states) && /Beto Bodega\s*Completada/.test(states)
    && (await adminCard.getByText('Completada', { exact: true }).count()) === 3,
    'B8 Cuando ambos terminan la tarea queda «Completada» y se ve el estado de cada uno');

  await anaCard.getByRole('button', { name: 'Detalle' }).click();
  const anaDlg = ana.getByRole('dialog', { name: 'Inventario de bodega' });
  await anaDlg.getByLabel('Comentario o novedad').fill('Faltan etiquetas en el pasillo 4: ¿se puede mover la fecha?');
  await anaDlg.getByRole('checkbox', { name: /solicitud de cambio/ }).check();
  await anaDlg.getByRole('button', { name: 'Enviar' }).click();
  await anaDlg.getByText('Faltan etiquetas en el pasillo 4', { exact: false }).waitFor();
  await anaDlg.getByRole('button', { name: 'Cerrar' }).first().click();
  await adminCard.getByRole('button', { name: 'Detalle' }).click();
  const admDlg = admin.getByRole('dialog', { name: 'Inventario de bodega' });
  await admDlg.getByText('Solicitud de cambio').waitFor();
  check((await admDlg.innerText()).includes('Faltan etiquetas'), 'B  Ana pide un cambio por comentario y el administrador lo ve en el historial');
  await admin.screenshot({ path: join(shots, '03-detalle-tarea.png') });
  await admDlg.getByRole('button', { name: 'Cerrar' }).first().click();

  const anaApi = emps.ana.api;
  check((await anaApi.put(`${base}/api/tasks/${taskId}`, { headers: H, data: { priority: 'baja' } })).status() === 403
    && (await anaApi.put(`${base}/api/tasks/${taskId}`, { headers: H, data: { due_date: '2031-01-01' } })).status() === 403
    && (await anaApi.put(`${base}/api/tasks/${taskId}`, { headers: H, data: { assignee_ids: [emps.ana.id] } })).status() === 403
    && (await anaApi.delete(`${base}/api/tasks/${taskId}`, { headers: H })).status() === 403,
  'B  Por API manipulada Ana no cambia prioridad, fechas ni responsables, ni elimina (403)');
  check((await anaApi.post(`${base}/api/tasks`, { headers: H, data: { title: 'x', group: G, assignee_ids: [emps.beto.id] } })).status() === 403,
    'B  Un empleado no crea tareas para otros (403)');

  // ================================================================ persistencia: reinicio real
  await stopServer();
  startServer();
  await waitHealth();
  await admin.goto(`${base}/grupos/${G}`);
  await section(admin, 'Tareas del grupo').getByRole('tab', { name: 'Todas' }).click();
  await card(admin, 'Inventario de bodega').getByText('Completada', { exact: true }).first().waitFor();
  await ana.goto(`${base}/tareas/asignadas`);
  await card(ana, 'Inventario de bodega').waitFor();
  await admin.goto(`${base}/inventario/columnas`);
  const persisted = await columnNames(admin);
  await admin.goto(`${base}/inventario`);
  await admin.getByRole('table', { name: 'Productos del inventario' }).getByText('Logitech').waitFor();
  check(persisted.join('|') === 'Observaciones|Marca comercial|Garantía', 'A11/B9 Tras reiniciar el servidor siguen columnas, orden, valores y tareas con su avance');

  // ================================================================ teléfono
  for (const [path, label] of [[`/grupos/${G}`, 'grupo con tareas'], ['/inventario', 'inventario con columnas'], ['/inventario/columnas', 'administrar columnas']]) {
    await admin.setViewportSize({ width: 360, height: 780 });
    await admin.goto(`${base}${path}`);
    await admin.getByRole('heading').first().waitFor();
    const o = await overflowOf(admin);
    check(o <= 0, `Teléfono de 360 px sin desplazamiento horizontal en ${label} (${o}px)`);
  }
  await admin.screenshot({ path: join(shots, '04-movil-columnas.png'), fullPage: true });
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

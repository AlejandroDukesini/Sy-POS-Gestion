// Notas y tareas con navegador real y servidor real: administrador y dos empleados en contextos separados
// (cookies distintas) y un reinicio REAL del servidor para comprobar la persistencia.
//   npm run build && node e2e/notes-tasks.mjs
// Variables: PYTHON, BROWSER (msedge | chrome), SHOTS (carpeta de capturas).
import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { chromium } from 'playwright-core';

const root = resolve(import.meta.dirname, '..', '..');
const python = process.env.PYTHON ?? join(root, 'backend', '.venv', 'Scripts', 'python.exe');
const port = 8767;
const base = `http://127.0.0.1:${port}`;
const shots = process.env.SHOTS ?? mkdtempSync(join(tmpdir(), 'pospy-notas-shots-'));
mkdirSync(shots, { recursive: true });
const dataDir = mkdtempSync(join(tmpdir(), 'pospy-e2e-notas-'));
const failures = [];
const check = (ok, message) => { console.log(`${ok ? 'OK  ' : 'FALLA'} ${message}`); if (!ok) failures.push(message); };
const H = { 'X-Requested-With': 'pos-py', 'Content-Type': 'application/json' };
const ADMIN = { username: 'gerente', password: 'Clave segura 2026' };
const PEOPLE = [
  { username: 'ana', full_name: 'Ana Caja', password: 'Caja segura 99x', final: 'Caja segura 99xN' },
  { username: 'beto', full_name: 'Beto Bodega', password: 'Bodega firme 88z', final: 'Bodega firme 88zN' },
];

let server = null;
function startServer() {
  server = spawn(python, ['-m', 'pospy', '--port', String(port), '--data-dir', dataDir, '--web-dist', join(root, 'frontend', 'dist')],
    { cwd: join(root, 'backend'), env: { ...process.env, POS_SETUP_CODE: 'E2E-CODE-0003' } });
  server.stderr.on('data', () => {});
  server.stdout.on('data', () => {});
}
async function stopServer() {
  const exited = new Promise((r) => server.once('exit', r));
  server.kill();
  await exited;
  for (let i = 0; i < 40; i++) {   // espera a que el puerto quede libre
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
const card = (page, name) => page.getByRole('article', { name, exact: true });

startServer();
const browser = await chromium.launch({ channel: process.env.BROWSER ?? 'msedge', headless: true });
try {
  await waitHealth();
  const setup = await fetch(`${base}/api/setup`, { method: 'POST', headers: H,
    body: JSON.stringify({ code: 'E2E-CODE-0003', username: ADMIN.username, full_name: 'Gerente General', password: ADMIN.password }) });
  check(setup.ok, 'Instalación local con administrador');

  // ------------------------------------------------------------ sesiones independientes
  const adminCtx = await browser.newContext({ viewport: { width: 1366, height: 860 } });
  const admin = await adminCtx.newPage();
  const errors = [];
  admin.on('pageerror', (e) => errors.push(e.message));
  await admin.goto(base);
  await admin.getByLabel('Usuario', { exact: false }).fill(ADMIN.username);
  await admin.getByLabel('Contraseña', { exact: false }).fill(ADMIN.password);
  await admin.getByRole('button', { name: 'Ingresar' }).click();
  await admin.getByRole('link', { name: 'Notas y tareas' }).waitFor();
  check(true, 'El administrador inicia sesión y ve «Notas y tareas» en el menú');

  const ids = {};
  const emps = {};
  for (const p of PEOPLE) {
    const r = await adminCtx.request.post(`${base}/api/users`, { headers: H,
      data: { username: p.username, full_name: p.full_name, role: 'employee', password: p.password } });
    ids[p.username] = (await r.json()).id;
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 860 } });
    await ctx.request.post(`${base}/api/auth/login`, { headers: H, data: { username: p.username, password: p.password } });
    await ctx.request.post(`${base}/api/auth/password`, { headers: H, data: { current: p.password, password: p.final } });
    const page = await ctx.newPage();
    page.on('pageerror', (e) => errors.push(e.message));
    emps[p.username] = { ctx, page };
  }
  const ana = emps.ana.page;
  check((await emps.ana.ctx.request.get(`${base}/api/me`)).ok(), 'Ana y Beto inician sesión, cada uno en su propio navegador');

  // ------------------------------------------------------------ 1. nota del administrador
  await admin.getByRole('link', { name: 'Notas y tareas' }).click();
  await admin.getByRole('heading', { name: 'Notas y tareas' }).waitFor();
  check(admin.url().endsWith('/tareas/asignadas'), 'La sección abre en «Tareas asignadas»');
  await admin.getByRole('link', { name: 'Mis notas' }).click();
  await admin.getByText('Todavía no tiene notas. Cree una para guardar sus ideas.').waitFor();
  check(true, 'Estado vacío de notas');
  await admin.getByRole('button', { name: 'Nueva nota' }).first().click();
  await admin.getByRole('dialog').getByLabel('Título').fill('Proveedores');
  await admin.getByRole('dialog').getByLabel('Nota').fill('Llamar a Distribuidora Andina el lunes');
  await admin.getByRole('dialog').getByRole('button', { name: 'Guardar' }).click();
  await card(admin, 'Proveedores').waitFor();
  check(true, '1  El administrador crea una nota y la ve en su bloc');

  // ------------------------------------------------------------ 2. nota privada de Ana
  await ana.goto(`${base}/tareas/notas`);
  await ana.getByRole('button', { name: 'Nueva nota' }).first().click();
  await ana.getByRole('dialog').getByLabel('Título').fill('Caja');
  await ana.getByRole('dialog').getByLabel('Nota').fill('Revisar el cambio de 50.000');
  await ana.getByRole('dialog').getByRole('button', { name: 'Guardar' }).click();
  await card(ana, 'Caja').waitFor();
  check(await card(ana, 'Proveedores').count() === 0, '2  Ana crea su nota y no ve la del administrador');
  await admin.reload();
  await card(admin, 'Proveedores').waitFor();
  check(await card(admin, 'Caja').count() === 0, '2  El administrador no ve la nota de Ana');
  const beto = emps.beto.ctx.request;
  check((await (await beto.get(`${base}/api/notes`)).json()).length === 0, '2  Beto no ve notas ajenas');
  await ana.getByRole('searchbox', { name: /Buscar notas/ }).fill('50.000');
  await ana.waitForTimeout(600);
  check(await card(ana, 'Caja').count() === 1, '   Búsqueda por contenido');
  await ana.screenshot({ path: join(shots, '01-ana-notas.png') });

  // ------------------------------------------------------------ 3 y 4. tareas personales
  await ana.getByRole('link', { name: 'Mis tareas' }).click();
  await ana.getByText('No tiene tareas pendientes.').waitFor();
  await ana.getByRole('button', { name: 'Nueva tarea' }).first().click();
  await ana.getByRole('dialog').getByLabel('Tarea', { exact: false }).first().fill('Ordenar vitrina');
  check(await ana.getByRole('dialog').getByRole('checkbox').count() === 0, '3  Una tarea personal no pide responsable');
  await ana.getByRole('dialog').getByRole('button', { name: 'Guardar' }).click();
  await card(ana, 'Ordenar vitrina').waitFor();
  check(true, '3  Ana crea una tarea personal');

  await admin.getByRole('link', { name: 'Mis tareas' }).click();
  await admin.getByRole('button', { name: 'Nueva tarea' }).first().click();
  await admin.getByRole('dialog').getByLabel('Tarea', { exact: false }).first().fill('Pagar arriendo');
  await admin.getByRole('dialog').getByRole('button', { name: 'Guardar' }).click();
  await card(admin, 'Pagar arriendo').waitFor();
  check(await card(admin, 'Ordenar vitrina').count() === 0, '4  El administrador crea su tarea personal y no ve la de Ana');

  // ------------------------------------------------------------ 5. asignar a Ana
  await admin.getByRole('link', { name: 'Tareas asignadas' }).click();
  await admin.getByRole('tab', { name: 'Todas' }).click();
  await admin.getByText('No hay tareas asignadas en esta vista.').waitFor();
  await admin.getByRole('button', { name: 'Asignar tarea' }).first().click();
  const dlg = admin.getByRole('dialog');
  await dlg.getByLabel('Tarea', { exact: false }).first().fill('Contar bodega');
  await dlg.getByLabel('Descripción', { exact: false }).fill('Pasillo 3, estantería B');
  await dlg.getByRole('checkbox', { name: 'Ana Caja' }).check();   // sin grupos: cualquier persona activa
  await dlg.getByLabel('Fecha límite', { exact: false }).fill('2030-01-10');
  await dlg.getByRole('button', { name: 'Asignar' }).click();
  const adminTask = card(admin, 'Contar bodega');
  await adminTask.waitFor();
  check(await adminTask.getByText('Ana Caja').count() === 1, '5  El administrador asigna la tarea y ve a la responsable');
  check(await card(admin, 'Pagar arriendo').count() === 0, '   Sus tareas personales no se mezclan con las asignadas');

  // ------------------------------------------------------------ 6–9. Ana trabaja la tarea; el admin lo ve en vivo
  await ana.getByRole('link', { name: 'Asignadas a mí' }).click();
  const anaTask = card(ana, 'Contar bodega');
  await anaTask.waitFor();
  check(await anaTask.getByText('Pasillo 3, estantería B').count() === 1, '6  Ana ve la tarea asignada y su descripción');
  check(await anaTask.getByRole('button', { name: 'Editar' }).count() === 0
    && await anaTask.getByRole('button', { name: 'Eliminar' }).count() === 0
    && await ana.getByRole('button', { name: 'Asignar tarea' }).count() === 0, '11 Ana no tiene botones para editar, eliminar ni asignar');
  await anaTask.getByLabel('Mi estado').selectOption('en_curso');
  let t0 = Date.now();
  await adminTask.getByText('En progreso', { exact: true }).first().waitFor({ timeout: 15000 });
  check(true, `7/9 Ana la pone «En progreso» y el administrador lo ve sin recargar (${Date.now() - t0} ms)`);
  await anaTask.getByRole('button', { name: 'Marcar como completada' }).click();
  t0 = Date.now();
  await adminTask.getByText('Completada', { exact: true }).first().waitFor({ timeout: 15000 });
  check(true, `8/9 Ana la marca «Completada» y el administrador lo ve sin recargar (${Date.now() - t0} ms)`);
  await admin.screenshot({ path: join(shots, '02-admin-asignadas.png') });

  // ------------------------------------------------------------ 10 y 11. intentos por API manipulada
  const taskId = (await (await adminCtx.request.get(`${base}/api/tasks`)).json())[0].id;
  check((await (await beto.get(`${base}/api/tasks`)).json()).length === 0, '10 Beto no ve las tareas de Ana');
  check((await beto.get(`${base}/api/tasks?assignee_id=${ids.ana}`)).status() === 403, '10 Beto no puede pedir las tareas de Ana (403)');
  check((await beto.put(`${base}/api/tasks/${taskId}`, { headers: H, data: { status: 'pendiente' } })).status() === 404,
    '10 Beto no puede modificar la tarea de Ana (404)');
  const anaApi = emps.ana.ctx.request;
  check((await anaApi.delete(`${base}/api/tasks/${taskId}`, { headers: H })).status() === 403, '11 Ana no puede eliminar la tarea asignada (403)');
  check((await anaApi.put(`${base}/api/tasks/${taskId}`, { headers: H, data: { assignee_id: ids.beto } })).status() === 403,
    '11 Ana no puede cambiar la responsable (403)');

  // ------------------------------------------------------------ 12. reinicio real del servidor
  await stopServer();
  startServer();
  await waitHealth();
  await ana.goto(`${base}/tareas/notas`);
  await card(ana, 'Caja').waitFor();
  await ana.goto(`${base}/tareas/mias`);
  await card(ana, 'Ordenar vitrina').waitFor();
  await ana.goto(`${base}/tareas/asignadas`);
  await ana.getByRole('tab', { name: 'Todas' }).click();
  await card(ana, 'Contar bodega').getByText('Completada', { exact: true }).first().waitFor();
  await admin.goto(`${base}/tareas/notas`);
  await card(admin, 'Proveedores').waitFor();
  check(true, '12 Tras reiniciar el servidor siguen las notas, las tareas personales y la asignada (con su estado)');

  // ------------------------------------------------------------ diseño adaptable
  await admin.goto(`${base}/tareas/asignadas`);
  await admin.setViewportSize({ width: 360, height: 780 });
  await admin.getByRole('tab', { name: 'Todas' }).click();
  await card(admin, 'Contar bodega').waitFor();
  await admin.waitForTimeout(300);
  const overflow = await admin.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  await admin.screenshot({ path: join(shots, '03-admin-movil.png'), fullPage: true });
  const wide = overflow > 0 ? await admin.evaluate(() => [...document.querySelectorAll('body *')]
    .filter((el) => el.getBoundingClientRect().right > window.innerWidth + 0.5)
    .slice(0, 8).map((el) => `${el.tagName.toLowerCase()}.${[...el.classList].join('.')}=${Math.round(el.getBoundingClientRect().right)}`)
    .join(', ')) : '';
  check(overflow <= 0, `Teléfono de 360 px sin desplazamiento horizontal (${overflow}px)${wide ? `: ${wide}` : ''}`);
  check(await admin.getByText('Tareas', { exact: true }).first().isVisible(), 'En el teléfono el menú muestra el rótulo corto «Tareas»');

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

// Grupos de trabajo con navegador real: administrador y empleado en contextos separados (cookies distintas).
//   npm run build && node e2e/groups.mjs
// Variables: PYTHON, BROWSER (msedge | chrome), SHOTS (carpeta de capturas), BASE (usar un servidor ya en marcha,
// por ejemplo detrás de un túnel HTTPS; en ese caso SETUP_BASE es la dirección local para la instalación).
import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { chromium } from 'playwright-core';

const root = resolve(import.meta.dirname, '..', '..');
const python = process.env.PYTHON ?? join(root, 'backend', '.venv', 'Scripts', 'python.exe');
const port = 8766;
const base = process.env.BASE ?? `http://127.0.0.1:${port}`;
const setupBase = process.env.SETUP_BASE ?? base;
const shots = process.env.SHOTS ?? mkdtempSync(join(tmpdir(), 'pospy-grupos-shots-'));
mkdirSync(shots, { recursive: true });
const failures = [];
const check = (ok, message) => { console.log(`${ok ? 'OK  ' : 'FALLA'} ${message}`); if (!ok) failures.push(message); };
const H = { 'X-Requested-With': 'pos-py', 'Content-Type': 'application/json' };
const ADMIN = { username: 'gerente', password: 'Clave segura 2026' };
const EMP = { username: 'ana', password: 'Caja segura 99x', final: 'Caja segura 99xN' };

let server = null;
if (!process.env.BASE) {
  const dataDir = mkdtempSync(join(tmpdir(), 'pospy-e2e-grupos-'));
  server = spawn(python, ['-m', 'pospy', '--port', String(port), '--data-dir', dataDir, '--web-dist', join(root, 'frontend', 'dist')],
    { cwd: join(root, 'backend'), env: { ...process.env, POS_SETUP_CODE: 'E2E-CODE-0002' } });
  server.stderr.on('data', () => {});
}

async function waitHealth(url) {
  for (let i = 0; i < 60; i++) {
    try { if ((await fetch(`${url}/api/health`)).ok) return; } catch { /* arrancando */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`El servidor no arrancó: ${url}`);
}

async function login(page) {
  await page.getByLabel('Usuario', { exact: false }).fill(page.__user.username);
  await page.getByLabel('Contraseña', { exact: false }).fill(page.__user.password);
  await page.getByRole('button', { name: 'Ingresar' }).click();
}

const browser = await chromium.launch({ channel: process.env.BROWSER ?? 'msedge', headless: true });
try {
  await waitHealth(setupBase);
  const setup = await fetch(`${setupBase}/api/setup`, { method: 'POST', headers: H,
    body: JSON.stringify({ code: 'E2E-CODE-0002', username: ADMIN.username, full_name: 'Gerente General', password: ADMIN.password }) });
  check(setup.ok, 'Instalación local con administrador');

  // ------------------------------------------------------------ administrador (escritorio)
  const adminCtx = await browser.newContext({ viewport: { width: 1366, height: 860 } });
  const admin = await adminCtx.newPage();
  const errors = [];
  for (const p of [admin]) p.on('pageerror', (e) => errors.push(e.message));
  admin.__user = ADMIN;
  await admin.goto(base);
  await login(admin);
  await admin.getByRole('link', { name: 'Grupos' }).click();
  await admin.getByRole('heading', { name: 'Grupos de trabajo' }).waitFor();
  await admin.getByText('Todavía no ha creado grupos').waitFor();
  check(true, 'A  Estado vacío para el administrador');
  const created = await adminCtx.request.post(`${base}/api/users`, { headers: H,
    data: { username: EMP.username, full_name: 'Ana Caja', role: 'employee', password: EMP.password } });
  check(created.ok(), 'A  Cuenta de empleada creada por el administrador');

  await admin.getByRole('button', { name: 'Nuevo grupo' }).click();
  await admin.getByLabel('Nombre del grupo', { exact: false }).fill('Turno tarde');
  await admin.getByLabel('Descripción', { exact: false }).fill('Equipo de caja de la sede centro');
  await admin.getByRole('button', { name: 'Guardar' }).click();
  await admin.getByRole('heading', { name: 'Turno tarde' }).waitFor();
  check(/\/grupos\/G-/.test(admin.url()), 'A  Grupo creado y abierto en su página');
  await admin.getByRole('button', { name: 'Generar enlace' }).click();
  await admin.getByRole('dialog').getByRole('button', { name: 'Generar' }).click();
  const linkInput = admin.getByRole('textbox', { name: 'Enlace de invitación' });
  await linkInput.waitFor();
  const link = await linkInput.inputValue();
  check(link.startsWith(`${base}/unirse/`), `A  Enlace generado: ${link.slice(0, base.length + 14)}…`);
  check(await admin.getByRole('button', { name: 'Copiar enlace' }).isVisible(), 'A  Botón «Copiar enlace» disponible');
  await admin.screenshot({ path: join(shots, '01-admin-enlace.png') });
  await admin.getByRole('button', { name: 'Listo' }).click();
  check(await admin.getByText('Aún no hay integrantes').isVisible(), 'A  Lista de integrantes vacía');

  // ------------------------------------------------------------ empleada (teléfono, otra sesión)
  const empCtx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
    userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36' });
  const req = empCtx.request;
  await req.post(`${base}/api/auth/login`, { headers: H, data: { username: EMP.username, password: EMP.password } });
  await req.post(`${base}/api/auth/password`, { headers: H, data: { current: EMP.password, password: EMP.final } });
  await req.post(`${base}/api/auth/logout`, { headers: H });
  const emp = await empCtx.newPage();
  emp.on('pageerror', (e) => errors.push(e.message));
  emp.__user = { username: EMP.username, password: EMP.final };
  await emp.goto(link);
  await emp.getByText('Le invitaron a un grupo de trabajo', { exact: false }).waitFor();
  check(true, 'B  Sin sesión: pide iniciar sesión y explica la invitación');
  await emp.screenshot({ path: join(shots, '02-empleada-ingreso.png') });
  await login(emp);
  await emp.getByRole('button', { name: 'Unirme al grupo' }).waitFor();
  check(await emp.getByText('Gerente General').first().isVisible(), 'B  Muestra el grupo y su administrador antes de unirse');
  await emp.screenshot({ path: join(shots, '03-empleada-invitacion.png') });
  const t0 = Date.now();
  await emp.getByRole('button', { name: 'Unirme al grupo' }).click();
  await emp.getByText('Ya es integrante de «Turno tarde»').waitFor();
  check(true, 'B  La empleada confirma y ve el resultado');

  // ------------------------------------------------------------ actualización en vivo en la pantalla del administrador
  const row = admin.getByRole('row', { name: /Ana Caja/ });
  await row.waitFor({ timeout: 15000 });
  check(true, `D  El administrador ve a Ana sin recargar (${Date.now() - t0} ms)`);
  await emp.getByRole('button', { name: 'Ir al grupo' }).click();
  await emp.getByRole('heading', { name: 'Turno tarde' }).waitFor();
  check(!emp.url().includes('/unirse/'), 'B  El token sale de la barra de direcciones al ir al grupo');
  await row.getByText('Conectado').waitFor({ timeout: 15000 });
  check(true, 'D  El administrador ve a Ana «Conectado»');
  check(!(await emp.getByRole('button', { name: 'Generar enlace' }).count()), 'E  La empleada no ve controles administrativos');
  await emp.screenshot({ path: join(shots, '04-empleada-grupo.png'), fullPage: true });
  await admin.screenshot({ path: join(shots, '05-admin-integrantes.png'), fullPage: true });

  // ------------------------------------------------------------ pérdida de conexión y reconexión
  await empCtx.setOffline(true);
  await emp.evaluate(() => window.dispatchEvent(new Event('offline')));
  await emp.close();   // el canal se corta
  await row.getByText(/Reconectando|Desconectado/).waitFor({ timeout: 70000 });
  check(true, 'F  Al perder la conexión, el administrador ve «Reconectando…» y Ana sigue en la lista');
  await empCtx.setOffline(false);
  const emp2 = await empCtx.newPage();
  await emp2.goto(`${base}/grupos`);
  await emp2.getByRole('link', { name: /Turno tarde/ }).waitFor();
  await row.getByText('Conectado').waitFor({ timeout: 20000 });
  check(true, 'F  Ana vuelve con su misma sesión: «Conectado», sin duplicados');
  check(await admin.getByRole('row', { name: /Ana Caja/ }).count() === 1, 'F  Una sola fila para Ana');

  await admin.setViewportSize({ width: 360, height: 780 });
  await admin.waitForTimeout(300);
  const overflow = await admin.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  await admin.screenshot({ path: join(shots, '06-admin-movil.png') });
  check(overflow <= 0, `Administrador en teléfono de 360 px sin desplazamiento horizontal (${overflow}px)`);

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

// Equipos autorizados con navegador real y servidor real. Simula «otros computadores» entrando por la IP de red del
// equipo (no es el equipo servidor) y el propio equipo servidor por 127.0.0.1.
//   npm run build && node e2e/devices.mjs
// El navegador de prueba trata la dirección de red como segura (WebCrypto exige https o el propio equipo).
import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync } from 'node:fs';
import { networkInterfaces, tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { chromium } from 'playwright-core';

const root = resolve(import.meta.dirname, '..', '..');
const python = process.env.PYTHON ?? join(root, 'backend', '.venv', 'Scripts', 'python.exe');
const port = 8786;
const lanIp = Object.values(networkInterfaces()).flat().find((i) => i && i.family === 'IPv4' && !i.internal)?.address;
const local = `http://127.0.0.1:${port}`;
const remote = `http://${lanIp}:${port}`;
const shots = process.env.SHOTS ?? mkdtempSync(join(tmpdir(), 'pospy-equipos-shots-'));
mkdirSync(shots, { recursive: true });
const dataDir = mkdtempSync(join(tmpdir(), 'pospy-e2e-equipos-'));
const failures = [];
const check = (ok, message) => { console.log(`${ok ? 'OK  ' : 'FALLA'} ${message}`); if (!ok) failures.push(message); };
const H = { 'X-Requested-With': 'pos-py', 'Content-Type': 'application/json' };
const ADMIN = { username: 'gerente', password: 'Clave segura 2026' };
const EMP = { username: 'cajero', password: 'Temporal 2026 x', final: 'Caja segura 2026' };

if (!lanIp) {
  console.log('(omitido) el equipo no tiene una dirección IPv4 de red');
  process.exit(0);
}
const server = spawn(python, ['-m', 'pospy', '--host', '0.0.0.0', '--port', String(port), '--data-dir', dataDir,
  '--web-dist', join(root, 'frontend', 'dist')], { cwd: join(root, 'backend'), env: { ...process.env, POS_SETUP_CODE: 'E2E-CODE-0013' } });
server.stderr.on('data', () => {});
server.stdout.on('data', () => {});
async function waitHealth() {
  for (let i = 0; i < 60; i++) {
    try { if ((await fetch(`${local}/api/health`)).ok) return; } catch { /* arrancando */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error('El servidor no arrancó');
}
async function signIn(page, base, user, password) {
  await page.goto(base);
  await page.getByLabel('Usuario', { exact: false }).fill(user);
  await page.getByLabel('Contraseña', { exact: false }).fill(password);
  await page.getByRole('button', { name: 'Ingresar' }).click();
}

const browser = await chromium.launch({ channel: process.env.BROWSER ?? 'msedge', headless: true,
  args: [`--unsafely-treat-insecure-origin-as-secure=${remote}`] });
try {
  await waitHealth();
  await fetch(`${local}/api/setup`, { method: 'POST', headers: H,
    body: JSON.stringify({ code: 'E2E-CODE-0013', username: ADMIN.username, full_name: 'Gerente General', password: ADMIN.password }) });
  const errors = [];
  const newPage = async (ctx) => { const p = await ctx.newPage(); p.on('pageerror', (e) => errors.push(e.message)); return p; };
  check((await (await fetch(`${remote}/api/devices/policy`)).json()).local === false, `0 ${remote} se trata como otro computador (no el servidor)`);

  // 1. Administrador en su computador: autoriza ESTE equipo y activa la restricción
  const adminCtx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const ap = await newPage(adminCtx);
  await signIn(ap, remote, ADMIN.username, ADMIN.password);
  await ap.getByRole('link', { name: 'Inventario' }).first().waitFor();
  await ap.goto(`${remote}/gestion/equipos`);
  await ap.getByRole('button', { name: 'Autorizar este equipo' }).click();
  await ap.getByText('Este equipo quedó autorizado y su sesión vinculada').waitFor();
  await ap.getByRole('table', { name: 'Equipos registrados' }).getByText('autorizado', { exact: true }).waitFor({ timeout: 5000 }).catch(() => {});
  check(await ap.getByRole('table', { name: 'Equipos registrados' }).getByText('autorizado', { exact: true }).count() === 1, '1 «Autorizar este equipo»: autorizado con su clave propia');
  await ap.getByLabel('Solo permitir el ingreso desde equipos autorizados').click();
  await ap.getByText('Restricción activada').waitFor();
  check((await (await fetch(`${remote}/api/devices/policy`)).json()).enforced === true, '   Restricción activada (el administrador sigue dentro)');
  await ap.screenshot({ path: join(shots, '01-equipos.png') });

  // 2. Empleado desde OTRO computador: rechazado aunque la contraseña sea correcta; solicita autorización
  await adminCtx.request.post(`${remote}/api/users`, { headers: H, data: { username: EMP.username, full_name: 'Cajero Uno', role: 'employee', password: EMP.password } });
  const empCtx = await browser.newContext({ viewport: { width: 1280, height: 860 } });
  const ep = await newPage(empCtx);
  await signIn(ep, remote, EMP.username, EMP.password);
  await ep.getByText('Equipo no autorizado').waitFor();
  check(await ep.getByText(/no está autorizado para usar el POS/).count() === 1, '2 Empleado en un equipo nuevo: «Equipo no autorizado» (contraseña correcta)');
  await ep.getByLabel('Nombre de este equipo').fill('Caja 2');
  await ep.getByRole('button', { name: 'Solicitar autorización de este equipo' }).click();
  await ep.getByText(/Solicitud enviada/).waitFor();
  check(true, '   Solicitud enviada (queda pendiente: no se autoriza sola)');
  await ep.getByRole('button', { name: 'Ingresar' }).click();
  await ep.getByText(/pendiente/).first().waitFor();
  check(await ep.getByText(/está pendiente/).count() === 1, '   Mientras está pendiente no puede ingresar');

  // 3. El administrador lo aprueba; el empleado entra y conserva sus funciones (vender)
  await ap.reload();
  const row = ap.getByRole('row', { name: /Caja 2/ });
  await row.getByRole('button', { name: 'Autorizar' }).click();
  await ap.getByText('«Caja 2» autorizado').waitFor();
  await ep.getByRole('button', { name: 'Ingresar' }).click();
  await ep.getByLabel('Contraseña actual', { exact: false }).waitFor().catch(() => {});
  if (await ep.getByLabel('Contraseña actual', { exact: false }).count()) {        // contraseña temporal: la cambia
    await ep.getByLabel('Contraseña actual', { exact: false }).fill(EMP.password);
    await ep.getByLabel(/^Nueva contraseña/).fill(EMP.final);
    await ep.getByLabel(/^Repita la nueva contraseña/).fill(EMP.final);
    await ep.getByRole('button', { name: /Guardar contraseña/ }).click();
  }
  await ep.getByRole('link', { name: 'Vender' }).first().waitFor();
  await ep.goto(`${remote}/vender`);
  await ep.getByRole('link', { name: 'Vender' }).first().waitFor();
  const prodResp = await empCtx.request.get(`${remote}/api/products`);
  if (!prodResp.ok()) console.log('products', prodResp.status(), (await prodResp.text()).slice(0, 200));
  check(await ep.getByRole('link', { name: 'Vender' }).first().isVisible() && prodResp.ok(),
    '3 Aprobado: el empleado ingresa y conserva sus funciones (Vender, productos)');
  const denied = await empCtx.request.put(`${remote}/api/devices/1/status`, { headers: H, data: { status: 'autorizado' } });
  check(denied.status() === 403, '   El empleado no puede autorizar equipos (403)');

  // 4. Otro computador con las mismas credenciales: rechazado
  const thief = await browser.newContext();
  const tp = await newPage(thief);
  await signIn(tp, remote, EMP.username, EMP.final);
  await tp.getByText('Equipo no autorizado').waitFor();
  check(true, '4 Las mismas credenciales en otro computador no sirven');

  // 5. Revocar el equipo cierra la sesión abierta de inmediato
  await ap.reload();
  await ap.getByRole('row', { name: /Caja 2/ }).getByRole('button', { name: 'Revocar' }).click();
  await ap.getByRole('dialog').getByRole('button', { name: 'Revocar' }).click();
  await ap.getByText('Equipo revocado y sesiones cerradas').waitFor();
  const after = await empCtx.request.get(`${remote}/api/products`);
  check(after.status() === 401, `5 Revocado: la sesión abierta deja de valer (${after.status()})`);
  await ep.goto(`${remote}/vender`);
  await ep.getByRole('button', { name: 'Ingresar' }).waitFor();
  await ep.getByLabel('Usuario', { exact: false }).fill(EMP.username);
  await ep.getByLabel('Contraseña', { exact: false }).fill(EMP.final);
  await ep.getByRole('button', { name: 'Ingresar' }).click();
  await ep.getByText(/fue revocada/).waitFor();
  check(true, '   Y no puede volver a ingresar desde ese equipo');
  await ep.screenshot({ path: join(shots, '02-revocado.png') });

  // 6. El equipo servidor siempre puede ingresar (nadie queda bloqueado)
  const srvCtx = await browser.newContext();
  const sp = await newPage(srvCtx);
  await signIn(sp, local, ADMIN.username, ADMIN.password);
  await sp.getByRole('link', { name: 'Inventario' }).first().waitFor();
  check(true, '6 El equipo servidor ingresa con la restricción activa');
  const history = await (await srvCtx.request.get(`${local}/api/devices`)).json();
  const actions = new Set(history.history.map((h) => h.action));
  check(['dispositivo.solicitado', 'dispositivo.autorizado', 'dispositivo.revocado', 'sesion.equipo_rechazado', 'seguridad.dispositivos_activada']
    .every((a) => actions.has(a)), '   Historial: solicitud, autorización, revocación, ingresos rechazados y activación');
  await srvCtx.request.put(`${local}/api/devices/policy`, { headers: H, data: { enforced: false } });

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

// Prueba de extremo a extremo con navegador real (Edge o Chrome) contra el servidor real.
//   npm run build && npm run e2e
// Variables: PYTHON (intérprete con las dependencias del backend), BROWSER (msedge | chrome), SHOTS (carpeta de capturas).
import { spawn } from 'node:child_process';
import { mkdtempSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { chromium } from 'playwright-core';

const root = resolve(import.meta.dirname, '..', '..');
const python = process.env.PYTHON ?? join(root, 'backend', '.venv', 'Scripts', 'python.exe');
const port = 8765;
const base = `http://127.0.0.1:${port}`;
const shots = process.env.SHOTS ?? mkdtempSync(join(tmpdir(), 'pospy-shots-'));
mkdirSync(shots, { recursive: true });
const dataDir = mkdtempSync(join(tmpdir(), 'pospy-e2e-'));
const failures = [];
const check = (ok, message) => { console.log(`${ok ? 'OK  ' : 'FALLA'} ${message}`); if (!ok) failures.push(message); };

const server = spawn(python, ['-m', 'pospy', '--port', String(port), '--data-dir', dataDir,
  '--web-dist', join(root, 'frontend', 'dist')], { cwd: join(root, 'backend'), env: { ...process.env, POS_SETUP_CODE: 'E2E-CODE-0001' } });
server.stderr.on('data', () => {});

async function waitHealth() {
  for (let i = 0; i < 60; i++) {
    try { if ((await fetch(`${base}/api/health`)).ok) return; } catch { /* aún arrancando */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error('El servidor no arrancó');
}

const browser = await chromium.launch({ channel: process.env.BROWSER ?? 'msedge', headless: true });
try {
  await waitHealth();
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const consoleErrors = [];
  page.on('console', (m) => { if (m.type() === 'error' && !/401|Failed to load resource/.test(m.text())) consoleErrors.push(m.text()); });
  const serverErrors = [];
  page.on('response', (r) => { if (r.status() >= 500) serverErrors.push(`${r.status()} ${r.url()}`); });

  // 1. Instalación con el código inyectado por el escritorio (#setup=…)
  await page.goto(`${base}/#setup=E2E-CODE-0001`);
  await page.getByRole('heading', { name: 'Instalación de POS-PY' }).waitFor();
  check(await page.getByLabel('Código de instalación').inputValue() === 'E2E-CODE-0001', 'el código de instalación llega por el fragmento');
  await page.getByLabel('Usuario del administrador').fill('admin');
  await page.getByLabel('Nombre completo').fill('Ana Administradora');
  await page.getByLabel(/^Contraseña/).fill('Clave segura 2026');
  await page.getByLabel('Repita la contraseña').fill('Clave segura 2026');
  await page.getByRole('button', { name: 'Crear administrador' }).click();

  // 2. Ingreso (formulario a la izquierda, logo a la derecha)
  await page.getByRole('heading', { name: 'Iniciar sesión' }).waitFor();
  check(await page.getByText('Aquí tu logo').isVisible(), 'pantalla de ingreso con «Aquí tu logo»');
  const form = await page.locator('.login-form').boundingBox();
  const brand = await page.locator('.login-brand').boundingBox();
  check(form.x < brand.x && Math.abs(form.width - brand.width) < 4, 'ingreso en dos columnas en pantalla ancha');
  await page.screenshot({ path: join(shots, '01-ingreso.png') });
  await page.getByLabel(/^Usuario/).fill('admin');
  await page.getByLabel(/^Contraseña/).fill('Clave segura 2026');
  await page.getByRole('button', { name: 'Ingresar' }).click();

  // 3. Inventario: crear producto con existencia inicial
  await page.getByRole('heading', { name: 'Inventario' }).first().waitFor();
  for (const name of ['Inventario', 'Vender', 'Finanzas', 'Gestión']) {
    check(await page.getByRole('link', { name, exact: true }).first().isVisible(), `barra lateral: ${name}`);
  }
  await page.getByRole('button', { name: 'Nuevo producto' }).click();
  await page.getByLabel(/^Código/).fill('MART-01');
  await page.getByLabel(/^Descripción/).fill('Martillo de uña');
  await page.getByLabel(/^Precio sin descuento/).fill('20.000');
  await page.getByLabel('Precio con descuento').fill('18.000');
  await page.getByLabel('Costo unitario').fill('10000');
  await page.getByLabel('IVA (%)').fill('19');
  await page.getByLabel('Existencia mínima').fill('2');
  await page.getByLabel('Existencia inicial').fill('10');
  await page.getByRole('button', { name: 'Guardar' }).click();
  await page.getByRole('row', { name: /MART-01/ }).waitFor();
  check(await page.getByRole('row', { name: /MART-01.*\$ 18\.000.*\$ 20\.000/ }).isVisible(), 'producto creado con precios en la tabla');
  await page.getByRole('row', { name: /MART-01/ }).click();
  await page.getByRole('complementary', { name: 'Detalle del producto' }).waitFor();
  await page.screenshot({ path: join(shots, '02-inventario.png') });

  // 4. Entrada de inventario
  await page.getByRole('button', { name: 'Entrada' }).click();
  await page.getByLabel(/^Cantidad/).fill('5');
  await page.getByLabel(/^Pagado con/).selectOption({ label: 'Efectivo' });
  await page.getByLabel(/^Motivo/).fill('Compra de prueba');
  await page.getByRole('button', { name: 'Confirmar entrada' }).click();
  await page.getByText(/ahora hay 15/).waitFor();
  check(true, 'entrada registrada: existencia 15');

  // 5. Estabilidad de la barra lateral al navegar
  const boxes = async () => Promise.all((await page.locator('.sidebar .nav-link').all()).map((l) => l.boundingBox()));
  const before = await boxes();
  await page.getByRole('link', { name: 'Vender', exact: true }).first().click();
  await page.getByLabel('Buscar producto por código o descripción').waitFor();
  const after = await boxes();
  check(JSON.stringify(after) === JSON.stringify(before), `la barra lateral no se mueve al navegar ${JSON.stringify(before)} ${JSON.stringify(after)}`);

  // 6. Venta completa en efectivo con cambio
  await page.getByLabel('Buscar producto por código o descripción').fill('MART-01');
  await page.getByRole('button', { name: /MART-01 · Martillo/ }).waitFor();
  await page.getByLabel('Buscar producto por código o descripción').press('Enter');
  await page.getByLabel('Cantidad de MART-01').fill('2');
  await page.getByText('$ 36.000').first().waitFor();
  await page.getByRole('button', { name: 'Efectivo' }).click();
  await page.getByLabel('Recibido').fill('50000');
  await page.getByText('Cambio').first().waitFor();
  await page.waitForTimeout(800);
  const payText = await page.locator('.pos .card').nth(2).innerText();
  check(payText.includes('$ 14.000'), `el cambio (calculado en el servidor) es $ 14.000: ${payText.replace(/\s+/g, ' ')}`);
  await page.screenshot({ path: join(shots, '03-punto-de-venta.png') });
  await page.getByRole('button', { name: /^Cobrar/ }).click();
  await page.getByRole('button', { name: 'Registrar venta' }).click();
  await page.getByRole('heading', { name: /Venta V-000001 registrada/ }).waitFor();
  check(true, 'venta V-000001 registrada');
  await page.getByRole('button', { name: 'Nueva venta' }).click();

  // 7. Finanzas: balance general cuadrado con datos reales
  await page.getByRole('link', { name: 'Finanzas', exact: true }).first().click();
  await page.getByRole('link', { name: /Balance general/ }).click();
  await page.getByText('El balance cuadra.', { exact: false }).waitFor();
  check(true, 'balance general cuadra');
  await page.screenshot({ path: join(shots, '04-balance.png') });

  // 8. Gestión y configuración personal persistente
  await page.getByRole('link', { name: 'Gestión', exact: true }).first().click();
  await page.getByRole('link', { name: /Usuarios y permisos/ }).waitFor();
  await page.screenshot({ path: join(shots, '05-gestion.png') });
  await page.goto(`${base}/configuracion`);
  await page.getByLabel('Tema').selectOption('dark');
  await page.getByLabel('Tamaño del texto').selectOption('20');
  await page.getByRole('button', { name: 'Guardar', exact: true }).click();
  await page.getByText('Preferencias guardadas').waitFor();
  await page.reload();
  await page.getByRole('heading', { name: 'Configuración', exact: true }).waitFor();
  const theme = await page.evaluate(() => [document.documentElement.dataset.theme, document.documentElement.style.fontSize]);
  check(theme[0] === 'dark' && theme[1] === '20px', `tema y tamaño persisten tras recargar (${theme})`);
  await page.screenshot({ path: join(shots, '06-configuracion-oscuro.png') });

  // 9. Pantalla estrecha: sin desborde horizontal, navegación inferior
  const mobile = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const m = await mobile.newPage();
  await m.goto(base);
  await m.getByRole('heading', { name: 'Iniciar sesión' }).waitFor();
  check(await m.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'ingreso en móvil sin desborde horizontal');
  await m.screenshot({ path: join(shots, '07-ingreso-movil.png') });
  await m.getByLabel(/^Usuario/).fill('admin');
  await m.getByLabel(/^Contraseña/).fill('Clave segura 2026');
  await m.getByRole('button', { name: 'Ingresar' }).click();
  await m.getByRole('heading', { name: 'Inventario' }).first().waitFor();
  check(await m.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), 'inventario en móvil sin desborde horizontal');
  await m.screenshot({ path: join(shots, '08-inventario-movil.png'), fullPage: true });

  // 10. PWA: manifiesto y service worker
  const manifest = await (await fetch(`${base}/manifest.webmanifest`)).json();
  check(manifest.name === 'POS-PY' && manifest.icons.length >= 3, 'manifiesto PWA con iconos');
  check((await fetch(`${base}/sw.js`)).ok, 'service worker publicado');

  check(consoleErrors.length === 0, `sin errores de consola ${consoleErrors.join(' | ')}`);
  check(serverErrors.length === 0, `sin errores 5xx ${serverErrors.join(' | ')}`);
  console.log(`Capturas en: ${shots}`);
} catch (err) {
  failures.push(String(err));
  console.error(err);
} finally {
  await browser.close();
  server.kill();
}
if (failures.length) {
  console.error(`\n${failures.length} verificaciones fallaron.`);
  process.exit(1);
}
console.log('\nTodas las verificaciones de extremo a extremo pasaron.');

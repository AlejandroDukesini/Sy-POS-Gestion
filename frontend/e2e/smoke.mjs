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

let closing = false;      // el navegador se está cerrando (ver manejo de pestañas de Edge)
let activePage = null;   // para la captura de diagnóstico si algo falla
const browser = await chromium.launch({ channel: process.env.BROWSER ?? 'msedge', headless: true });
try {
  await waitHealth();
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  activePage = page;
  // Edge abre por su cuenta una pestaña para mostrar PDF y archivos de Office recién descargados. Bajo
  // automatización queda en blanco con una navegación pendiente, y al cerrar el navegador Playwright rechaza
  // esa navegación con un TargetClosedError interno que no es un fallo de la aplicación. Solo ese caso se
  // ignora (y se avisa); cualquier otro error sigue haciendo fallar la prueba.
  const extraTabs = [];
  context.on('page', (extra) => { if (extra !== page) extraTabs.push(extra); });
  process.on('unhandledRejection', (err) => {
    if (closing && err?.name === 'TargetClosedError' && extraTabs.length) {
      console.log(`AVISO pestaña${extraTabs.length > 1 ? 's' : ''} de vista de descargas de Edge cerrada${extraTabs.length > 1 ? 's' : ''} al terminar`);
      return;
    }
    failures.push(String(err));
    console.error(err);
    process.exitCode = 1;
  });
  page.on('pageerror', (e) => console.error('ERROR DE PÁGINA:', e.message));
  const consoleErrors = [];
  page.on('console', (m) => { if (m.type() === 'error' && !/401|Failed to load resource/.test(m.text())) consoleErrors.push(m.text()); });
  const serverErrors = [];
  page.on('response', (r) => { if (r.status() >= 500) serverErrors.push(`${r.status()} ${r.url()}`); });

  // 1. Configuración inicial sin cuenta: el código llega por el fragmento (#setup=…) y abre el asistente
  await page.goto(`${base}/#setup=E2E-CODE-0001`);
  await page.getByRole('heading', { name: 'Configuración inicial' }).waitFor();
  check(true, 'el asistente abre sin exigir cuenta');
  await page.getByLabel('Nombre comercial').fill('Ferretería E2E');
  await page.getByRole('button', { name: 'Guardar y continuar' }).click();
  await page.getByRole('button', { name: 'Continuar', exact: true }).click();          // preferencias
  // Seguridad: activar sin contraseña está bloqueado; se asigna la contraseña y se activa
  await page.getByRole('button', { name: 'Activar inicio de sesión' }).waitFor();
  check(await page.getByRole('button', { name: 'Activar inicio de sesión' }).isDisabled(), 'no se activa el ingreso sin administrador con contraseña');
  await page.getByLabel('Nombre completo').first().fill('Ana Administradora');
  await page.getByRole('button', { name: 'Guardar datos' }).click();
  await page.getByText('Cuenta administrativa actualizada').waitFor();
  await page.getByLabel(/^Nueva contraseña/).fill('Clave segura 2026');
  await page.getByLabel(/^Repita la nueva contraseña/).fill('Clave segura 2026');
  await page.getByRole('button', { name: 'Asignar contraseña' }).click();
  await page.getByText('Contraseña asignada').first().waitFor();
  await page.getByRole('button', { name: 'Activar inicio de sesión' }).click();
  await page.getByRole('button', { name: 'Activar', exact: true }).click();
  await page.getByText('Inicio de sesión activado').first().waitFor();
  await page.screenshot({ path: join(shots, '00-asistente-seguridad.png') });
  await page.getByRole('button', { name: 'Continuar', exact: true }).click();
  // Empleados: uno sin cuenta de acceso
  await page.getByRole('button', { name: 'Nuevo empleado' }).click();
  await page.getByRole('dialog').getByLabel('Nombre completo').fill('Pedro Pérez');
  await page.getByRole('dialog').getByRole('button', { name: 'Guardar' }).click();
  await page.getByText('Empleado registrado').first().waitFor();
  await page.getByRole('cell', { name: 'Pedro Pérez' }).waitFor();
  check(await page.getByText('Sin cuenta', { exact: true }).count() >= 1, 'empleado registrado sin cuenta de acceso');
  await page.getByRole('button', { name: 'Continuar', exact: true }).click();
  await page.getByRole('button', { name: 'Finalizar y entrar' }).click();

  // 2. Ingreso (formulario a la izquierda, logo a la derecha)
  await page.getByRole('heading', { name: 'Iniciar sesión' }).waitFor();
  check(await page.locator('.login-brand').isVisible() && (await page.locator('.login-brand').innerText()).trim() === '', 'pantalla de ingreso con panel visual limpio (sin «Aquí tu logo»)');
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
  // Se tolera menos de 1 px: con la página desplazada, el elemento «sticky» redondea a medio píxel (no visible).
  const same = before.length === after.length && before.every((b, i) => ['x', 'y', 'width', 'height'].every((k) => Math.abs(b[k] - after[i][k]) < 1));
  check(same, `la barra lateral no se mueve al navegar ${JSON.stringify(before)} ${JSON.stringify(after)}`);

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

  // 7b. Finanzas › Informes: informe de hoy, guardado, observación y exportación (sin tocar ventas ni inventario)
  const salesBefore = await (await page.request.get(`${base}/api/sales`)).text();
  const productsBefore = await (await page.request.get(`${base}/api/products?page_size=200`)).text();
  await page.goto(`${base}/finanzas`);
  await page.getByRole('link', { name: /Informes de ingresos/ }).click();
  await page.getByRole('button', { name: /^Hoy/ }).click();
  await page.getByText('Vista previa (sin guardar)').waitFor();
  const previewText = await page.locator('.metrics').first().innerText();
  check(previewText.includes('$ 36.000'), `informe de hoy: total recibido $ 36.000 (${previewText.replace(/\s+/g, ' ')})`);
  await page.getByLabel(/^Observaciones/).fill('Cierre de prueba E2E');
  await page.getByRole('button', { name: 'Guardar informe' }).click();
  await page.getByRole('heading', { name: /Informe diario del/ }).waitFor();
  check(await page.getByText('Cierre de prueba E2E').isVisible(), 'informe guardado con su observación');
  await page.getByRole('button', { name: 'Agregar' }).click();
  await page.getByRole('dialog').getByLabel('Categoría').selectOption('diferencia_caja');
  await page.getByRole('dialog').getByLabel(/^Observación/).fill('Sobraron 500 en el arqueo');
  await page.getByRole('dialog').getByLabel(/^Importe relacionado/).fill('500');
  await page.getByRole('dialog').getByRole('button', { name: 'Guardar' }).click();
  await page.getByText('Sobraron 500 en el arqueo').waitFor();
  const { readFileSync: readReport } = await import('node:fs');
  const [pdfDl] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'PDF' }).click()]);
  const pdfBytes = readReport(await pdfDl.path());
  check(pdfDl.suggestedFilename() === 'INF-00001.pdf' && pdfBytes.subarray(0, 5).toString() === '%PDF-', 'exportación PDF descargada');
  const [xlsDl] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Excel' }).click()]);
  const xlsBytes = readReport(await xlsDl.path());
  check(xlsDl.suggestedFilename() === 'INF-00001.xlsx' && xlsBytes.subarray(0, 2).toString() === 'PK', 'exportación Excel descargada');
  await page.screenshot({ path: join(shots, '04b-informe.png'), fullPage: true });
  await page.getByRole('link', { name: '← Informes' }).click();
  await page.getByRole('cell', { name: 'INF-00001' }).waitFor();
  check(true, 'el informe figura en el historial');
  check(await (await page.request.get(`${base}/api/sales`)).text() === salesBefore
    && await (await page.request.get(`${base}/api/products?page_size=200`)).text() === productsBefore, 'ventas e inventario sin cambios');

  // 8. Gestión y configuración personal persistente
  await page.getByRole('link', { name: 'Gestión', exact: true }).first().click();
  await page.getByRole('link', { name: /Empleados, usuarios y permisos/ }).waitFor();
  await page.screenshot({ path: join(shots, '05-gestion.png') });

  // 8b. Expediente de proveedor: alta, nota de deuda, visita y lista de productos en Excel
  const stockBefore = await (await page.request.get(`${base}/api/products?page_size=200`)).json();
  await page.getByRole('link', { name: /^Proveedores/ }).click();
  await page.getByRole('button', { name: 'Nuevo proveedor' }).click();
  await page.getByRole('dialog').getByLabel(/^Nombre o razón social/).fill('Distribuidora E2E');
  await page.getByRole('dialog').getByLabel(/^WhatsApp/).fill('3001234567');
  await page.getByRole('dialog').getByRole('button', { name: 'Guardar' }).click();
  await page.getByRole('heading', { name: 'Distribuidora E2E' }).waitFor();
  check(await page.getByText('3001234567').isVisible(), 'proveedor creado y resumen con WhatsApp');
  await page.getByRole('link', { name: /^Notas y pendientes/ }).click();
  await page.getByRole('button', { name: 'Nueva nota' }).click();
  await page.getByRole('dialog').getByLabel('Categoría').selectOption('deuda');
  await page.getByRole('dialog').getByLabel(/^Título/).fill('Debemos factura 77');
  await page.getByRole('dialog').getByRole('button', { name: 'Guardar' }).click();
  await page.getByRole('cell', { name: /Debemos factura 77/ }).waitFor();
  await page.getByRole('button', { name: 'Resolver' }).click();
  await page.getByText('Marcada como resuelta').first().waitFor();
  await page.getByText('No hay notas en esta vista').waitFor();       // ya no figura entre las pendientes
  await page.getByRole('tab', { name: 'Resueltas' }).click();
  const resolvedOk = await page.getByRole('cell', { name: /Debemos factura 77/ }).waitFor({ timeout: 10000 }).then(() => true, () => false);
  check(resolvedOk, 'nota de deuda creada y resuelta');
  await page.getByRole('link', { name: 'Visitas', exact: true }).click();
  await page.getByRole('button', { name: 'Registrar visita' }).click();
  await page.getByRole('dialog').getByLabel(/^Motivo/).fill('Toma de pedido');
  await page.getByRole('dialog').getByRole('button', { name: 'Guardar' }).click();
  await page.getByRole('cell', { name: /Toma de pedido/ }).waitFor();
  check(await page.locator('.metric-value').first().innerText() !== '—', 'última visita calculada');
  const sample = await (await page.request.get(`${base}/api/products/export?fmt=xlsx`)).body();
  await page.getByRole('link', { name: 'Lista de productos', exact: true }).click();
  await page.getByLabel('Elegir archivo de Excel').setInputFiles({ name: 'lista proveedor.xlsx',
    mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: sample });
  await page.getByText('Lista cargada').first().waitFor();
  const [dl] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Descargar original' }).click()]);
  const { readFileSync } = await import('node:fs');
  check(dl.suggestedFilename() === 'lista proveedor.xlsx' && readFileSync(await dl.path()).equals(sample), 'Excel cargado y descargado sin cambios');
  await page.getByLabel('Elegir archivo de Excel').setInputFiles({ name: 'falso.xlsx', mimeType: 'text/plain', buffer: Buffer.from('hola') });
  await page.getByText('No se pudo cargar el archivo').waitFor();
  check(true, 'archivo inválido rechazado con mensaje visible');
  const stockAfter = await (await page.request.get(`${base}/api/products?page_size=200`)).json();
  check(JSON.stringify(stockAfter.items) === JSON.stringify(stockBefore.items), 'el inventario no cambió');
  await page.screenshot({ path: join(shots, '05b-proveedor.png') });
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
  await m.goto(`${base}/finanzas/informes/1`);
  await m.getByText('Desglose por método de pago').first().waitFor();
  check(await m.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), 'informe en móvil sin desborde horizontal');
  await m.screenshot({ path: join(shots, '08b-informe-movil.png'), fullPage: true });

  // 10. PWA: manifiesto y service worker
  const manifest = await (await fetch(`${base}/manifest.webmanifest`)).json();
  check(manifest.name === 'POS-PY' && manifest.icons.length >= 3, 'manifiesto PWA con iconos');
  check((await fetch(`${base}/sw.js`)).ok, 'service worker publicado');

  check(consoleErrors.length === 0, `sin errores de consola ${consoleErrors.join(' | ')}`);
  check(serverErrors.length === 0, `sin errores 5xx ${serverErrors.join(' | ')}`);
  console.log(`Capturas en: ${shots}`);
} catch (err) {
  failures.push(String(err));
  if (activePage) await activePage.screenshot({ path: join(shots, 'zz-fallo.png') }).catch(() => {});
  if (activePage) console.error('URL al fallar:', activePage.url(), '· captura:', join(shots, 'zz-fallo.png'));
  console.error(err);
} finally {
  closing = true;
  await browser.close();
  server.kill();
}
await new Promise((r) => setTimeout(r, 300));   // deja llegar los rechazos del cierre
if (failures.length) {
  console.error(`\n${failures.length} verificaciones fallaron.`);
  process.exit(1);
}
console.log('\nTodas las verificaciones de extremo a extremo pasaron.');

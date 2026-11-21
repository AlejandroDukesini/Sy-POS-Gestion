// Plantillas de impresión con navegador real y servidor real: importar los Excel de la empresa (docs/), elegir
// la hoja, revisar vinculaciones, vista previa en PDF, activar, emitir el PDF de una cotización real con 30
// productos y diseñar una plantilla desde cero arrastrando campos.
//   npm run build && node e2e/print-templates.mjs
// Si docs/*.xlsm no existen, la parte de importación se omite (se informa).
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { chromium } from 'playwright-core';

const root = resolve(import.meta.dirname, '..', '..');
const python = process.env.PYTHON ?? join(root, 'backend', '.venv', 'Scripts', 'python.exe');
const port = 8770;
const base = `http://127.0.0.1:${port}`;
const shots = process.env.SHOTS ?? mkdtempSync(join(tmpdir(), 'pospy-plantillas-shots-'));
mkdirSync(shots, { recursive: true });
const dataDir = mkdtempSync(join(tmpdir(), 'pospy-e2e-plantillas-'));
const COT = join(root, 'docs', 'COTIZACIÓNv3.7.2.xlsm');
const ORD = join(root, 'docs', 'ORDEN-CASARENAULTv3.4.2.xlsm');
const failures = [];
const check = (ok, message) => { console.log(`${ok ? 'OK  ' : 'FALLA'} ${message}`); if (!ok) failures.push(message); };
const H = { 'X-Requested-With': 'pos-py', 'Content-Type': 'application/json' };
const ADMIN = { username: 'gerente', password: 'Clave segura 2026' };

const server = spawn(python, ['-m', 'pospy', '--port', String(port), '--data-dir', dataDir, '--web-dist', join(root, 'frontend', 'dist')],
  { cwd: join(root, 'backend'), env: { ...process.env, POS_SETUP_CODE: 'E2E-CODE-0006' } });
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
const cell = (page, ref) => page.locator(`td[data-ref="${ref}"]`);

const browser = await chromium.launch({ channel: process.env.BROWSER ?? 'msedge', headless: true });
try {
  await waitHealth();
  const setup = await fetch(`${base}/api/setup`, { method: 'POST', headers: H,
    body: JSON.stringify({ code: 'E2E-CODE-0006', username: ADMIN.username, full_name: 'Gerente General', password: ADMIN.password }) });
  check(setup.ok, 'Instalación local con administrador');
  const ctx = await browser.newContext({ viewport: { width: 1500, height: 950 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(base);
  await page.getByLabel('Usuario', { exact: false }).fill(ADMIN.username);
  await page.getByLabel('Contraseña', { exact: false }).fill(ADMIN.password);
  await page.getByRole('button', { name: 'Ingresar' }).click();
  await page.getByRole('link', { name: 'Inventario' }).first().waitFor();
  const api = ctx.request;
  const types = Object.fromEntries((await (await api.get(`${base}/api/document-types`)).json()).map((t) => [t.code, t.id]));

  await page.goto(`${base}/gestion`);
  await page.getByRole('link', { name: /Plantillas de impresión/ }).click();
  await page.getByText('Aún no hay plantillas').waitFor();
  check(true, '1 Gestión › Plantillas de impresión');

  let cotId = null;
  if (existsSync(COT) && existsSync(ORD)) {
    // ---------------------------------------------------------- 2. importar la COTIZACIÓN (2 pasos, sin hoja automática)
    await page.getByRole('button', { name: 'Importar Excel' }).click();
    let dlg = page.getByRole('dialog', { name: 'Importar plantilla de Excel' });
    await dlg.getByLabel('Tipo de documento').selectOption(String(types.cotizacion));
    await dlg.getByLabel(/Archivo de Excel/).setInputFiles(COT);
    await dlg.getByRole('button', { name: 'Analizar archivo' }).click();
    await dlg.getByText(/Elija la hoja que se usará/).waitFor();
    const radios = dlg.getByRole('radio');
    check(await radios.count() === 3 && !(await radios.nth(0).isChecked()) && (await dlg.innerText()).includes('macros'),
      '2 Detecta 3 hojas, avisa de las macros y no elige ninguna hoja automáticamente');
    await dlg.getByRole('button', { name: 'Importar hoja' }).click();
    check(await dlg.getByText('Elija la hoja que se usará como plantilla.').count() >= 1, '   Sin elegir hoja no importa');
    await dlg.getByRole('radio', { name: /Hoja1/ }).check();
    await page.screenshot({ path: join(shots, '01-elegir-hoja.png') });
    await dlg.getByRole('button', { name: 'Importar hoja' }).click();
    await page.getByText('Resultado de la importación').waitFor({ timeout: 30000 });
    cotId = page.url().split('/').pop();
    check((await cell(page, 'B8').innerText()).includes('Identificación') && (await cell(page, 'D7').innerText()).includes('Hora')
      && (await cell(page, 'A15').innerText()).includes('Cantidad') && (await cell(page, 'E28').innerText()).includes('subtotal'),
    `3 Vinculaciones sugeridas visibles: B8 identificación, D7 hora, tabla desde A15, E28 subtotal`);
    check(await page.locator('.tpl-image img').count() === 1, '   El logotipo del Excel aparece en el diseño');
    await page.screenshot({ path: join(shots, '02-editor-cotizacion.png'), fullPage: true });
    // valor alternativo editable
    await cell(page, 'B8').click();
    await page.getByRole('tab', { name: 'Celda' }).click();
    check(await page.getByLabel('Valor alternativo si viene vacío').inputValue() === '222222222222', '   Valor alternativo 222222222222 configurable');
    // vista previa (PDF real del servidor)
    await page.getByRole('button', { name: 'Vista previa' }).click();
    const prev = page.getByRole('dialog', { name: 'Vista previa con datos de demostración' });
    await prev.getByLabel('Productos de demostración').selectOption('30');
    check(await until(async () => (await prev.locator('iframe').getAttribute('src'))?.startsWith('blob:')), '4 Vista previa en PDF con 30 productos de demostración');
    await prev.getByRole('button', { name: 'Cerrar' }).first().click();
    await page.getByRole('button', { name: 'Guardar y activar' }).click();
    await page.getByText('Plantilla guardada y activa').first().waitFor();
    await page.getByRole('button', { name: 'Usar como predeterminada' }).click();
    await page.getByText('Ahora es la predeterminada').first().waitFor();
    check(true, '5 Guardada (versión 2), activa y predeterminada para Cotización');

    // ---------------------------------------------------------- 6. cotización real con 30 productos
    const prods = [];
    for (let i = 0; i < 30; i++) {
      prods.push(await (await api.post(`${base}/api/products`, { headers: H, data: { code: `${1000 + i}`, description: `REPUESTO ${i + 1}`,
        price: String(5000 + i * 100), initial_stock: '10' } })).json());
    }
    const doc = await (await api.post(`${base}/api/documents`, { headers: { ...H, 'Idempotency-Key': `e2e-doc-${Date.now()}` },
      data: { type_id: types.cotizacion, customer_name: 'Taller Ruiz', lines: prods.map((p) => ({ product_id: p.id, qty: '2' })) } })).json();
    const pdf = await api.get(`${base}/api/documents/${doc.id}/template-pdf`);
    const body = await pdf.body();
    const outs = await (await api.get(`${base}/api/print-outputs?target_type=documento&target_id=${doc.id}`)).json();
    check(pdf.ok() && body.subarray(0, 4).toString() === '%PDF' && outs.length === 1 && outs[0].template_version === 2,
      `6 PDF real de una cotización con 30 productos (${pdf.headers()['x-pages']} página(s) en rollo) guardado en el historial con la versión 2`);
    await page.goto(`${base}/vender/documentos/${doc.id}`);
    await page.getByRole('button', { name: 'PDF con plantilla' }).click();
    const pd = page.getByRole('dialog', { name: 'PDF con plantilla' });
    check(await until(async () => (await pd.locator('iframe').getAttribute('src'))?.startsWith('blob:'), 30000),
      '   Desde el documento se abre el PDF con la plantilla');
    await pd.getByRole('button', { name: 'Cerrar' }).first().click();

    // ---------------------------------------------------------- 7. ORDEN con 20 %
    await page.goto(`${base}/gestion/plantillas`);
    await page.getByRole('button', { name: 'Importar Excel' }).click();
    dlg = page.getByRole('dialog', { name: 'Importar plantilla de Excel' });
    await dlg.getByLabel('Tipo de documento').selectOption(String(types.orden));
    await dlg.getByLabel(/Archivo de Excel/).setInputFiles(ORD);
    await dlg.getByRole('button', { name: 'Analizar archivo' }).click();
    await dlg.getByRole('radio', { name: /Hoja1/ }).check();
    await dlg.getByRole('button', { name: 'Importar hoja' }).click();
    await page.getByText('Resultado de la importación').waitFor({ timeout: 30000 });
    await page.getByRole('tab', { name: 'Productos' }).click();
    check(await page.getByLabel('Descuento de la plantilla (%)').inputValue() === '20', '7 La ORDEN importada trae el descuento del 20 % (configurable)');
  } else {
    console.log('AVISO  docs/*.xlsm no están: se omite la importación de los Excel de la empresa');
  }

  // ---------------------------------------------------------- 8. diseñar desde cero
  await page.goto(`${base}/gestion/plantillas`);
  await page.getByRole('button', { name: 'Crear desde cero' }).click();
  const cd = page.getByRole('dialog', { name: 'Crear plantilla desde cero' });
  await cd.getByLabel('Nombre', { exact: false }).fill('Orden diseñada');
  await cd.getByLabel('Tipo de documento').selectOption(String(types.orden));
  await cd.getByLabel('Editor').selectOption('grid');
  await cd.getByRole('button', { name: 'Crear y diseñar' }).click();
  await page.getByRole('heading', { name: 'Orden diseñada' }).waitFor();
  const grid = page.getByRole('grid', { name: 'Diseño de la plantilla' });
  await cell(page, 'A1').click();
  await page.keyboard.type('ORDEN DE PRUEBA');
  await page.keyboard.press('Enter');
  await cell(page, 'A1').click();
  await cell(page, 'F1').click({ modifiers: ['Shift'] });
  await page.getByRole('button', { name: 'Combinar' }).click();
  await page.getByRole('button', { name: 'Negrita' }).click();
  check(await cell(page, 'A1').getAttribute('colspan') === '6' && (await cell(page, 'A1').innerText()).includes('ORDEN DE PRUEBA'),
    '8 Escribir en una celda y combinar A1:F1');
  await page.getByRole('button', { name: 'Deshacer (Ctrl+Z)' }).click();
  await page.getByRole('button', { name: 'Deshacer (Ctrl+Z)' }).click();
  const undone = await cell(page, 'A1').getAttribute('colspan');
  await page.getByRole('button', { name: 'Rehacer (Ctrl+Y)' }).click();
  await page.getByRole('button', { name: 'Rehacer (Ctrl+Y)' }).click();
  check(undone === null && await cell(page, 'A1').getAttribute('colspan') === '6', '   Deshacer y rehacer');
  await page.getByLabel('Ancho de la columna A').fill('20');
  await page.getByRole('button', { name: /Tabla de productos/ }).dragTo(cell(page, 'A5'));
  await page.getByRole('tab', { name: 'Campos' }).click();
  await page.getByRole('button', { name: 'Nombre', exact: true }).dragTo(cell(page, 'B3'));
  check((await cell(page, 'B3').innerText()).includes('Nombre') && (await cell(page, 'A6').innerText()).includes('Cantidad')
    , '   Arrastrar «Tabla de productos» y «Nombre del cliente» a celdas');
  await page.getByRole('tab', { name: 'Productos' }).click();
  await page.getByLabel('Descuento de la plantilla (%)').fill('20');
  await page.getByRole('tab', { name: 'Página' }).click();
  await page.getByLabel('Papel', { exact: true }).selectOption('a4');
  await page.screenshot({ path: join(shots, '03-editor-desde-cero.png'), fullPage: true });
  await page.getByRole('button', { name: 'Guardar y activar' }).click();
  await page.getByText('Plantilla guardada y activa').first().waitFor();
  const id = page.url().split('/').pop();
  const saved = await (await api.get(`${base}/api/print-templates/${id}`)).json();
  check(saved.layout.merges.includes('A1:F1') && saved.layout.cols[0] === 20 && saved.bindings.products?.start === 6
    && saved.bindings.cells.B3?.field === 'cliente_nombre' && saved.bindings.discount_pct === '20' && saved.layout.page.paper === 'a4'
    && saved.active === 1, '9 Guardar y volver a abrir conserva combinación, ancho, tabla, campos, descuento y papel');
  await page.reload();
  await cell(page, 'A1').waitFor();
  check(await cell(page, 'A1').getAttribute('colspan') === '6', '   Al recargar la página el diseño sigue igual');
  const preview = await api.post(`${base}/api/print-templates/${id}/preview`, { headers: H, data: { lines: 100 } });
  check(preview.ok() && Number(preview.headers()['x-pages']) >= 2, `   Vista previa con 100 productos: ${preview.headers()['x-pages']} páginas A4`);

  // ---------------------------------------------------------- 10. lista y permisos
  await page.goto(`${base}/gestion/plantillas`);
  await page.getByRole('table', { name: 'Plantillas de impresión' }).waitFor();
  const rows = await page.getByRole('table', { name: 'Plantillas de impresión' }).getByRole('row').count();
  check(rows >= 2, `10 La lista muestra las plantillas (${rows - 1})`);
  void grid;
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

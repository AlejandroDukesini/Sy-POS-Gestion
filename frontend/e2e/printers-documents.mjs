// Impresoras configurables, documentos sin Microsoft Excel, datos opcionales y descuento máximo de 20 %, con
// navegador real y servidor real. No imprime en papel: valida la elección de impresoras y los registros.
//   npm run build && node e2e/printers-documents.mjs
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { chromium } from 'playwright-core';

const root = resolve(import.meta.dirname, '..', '..');
const python = process.env.PYTHON ?? join(root, 'backend', '.venv', 'Scripts', 'python.exe');
const port = 8776;
const base = `http://127.0.0.1:${port}`;
const shots = process.env.SHOTS ?? mkdtempSync(join(tmpdir(), 'pospy-impresoras-shots-'));
mkdirSync(shots, { recursive: true });
const dataDir = mkdtempSync(join(tmpdir(), 'pospy-e2e-impresoras-'));
const ORD = join(root, 'docs', 'ORDEN-CASARENAULTv3.4.2.xlsm');
const failures = [];
const check = (ok, message) => { console.log(`${ok ? 'OK  ' : 'FALLA'} ${message}`); if (!ok) failures.push(message); };
const H = { 'X-Requested-With': 'pos-py', 'Content-Type': 'application/json' };
const ADMIN = { username: 'gerente', password: 'Clave segura 2026' };

function zipNames(bytes, name) {
  const file = join(dataDir, name);
  writeFileSync(file, bytes);
  const code = 'import json,sys,zipfile,openpyxl\nz=zipfile.ZipFile(sys.argv[1]);wb=openpyxl.load_workbook(sys.argv[1],keep_vba=True)\n'
    + 'print(json.dumps({"names":z.namelist(),"values":[str(c.value) for ws in wb.worksheets for r in ws.iter_rows() for c in r if c.value is not None]}))';
  const res = spawnSync(python, ['-c', code, file], { encoding: 'utf8' });
  if (res.status !== 0) throw new Error(res.stderr);
  return JSON.parse(res.stdout);
}

const server = spawn(python, ['-m', 'pospy', '--port', String(port), '--data-dir', dataDir, '--web-dist', join(root, 'frontend', 'dist')],
  { cwd: join(root, 'backend'), env: { ...process.env, POS_SETUP_CODE: 'E2E-CODE-0010' } });
server.stderr.on('data', () => {});
server.stdout.on('data', () => {});
async function waitHealth() {
  for (let i = 0; i < 60; i++) {
    try { if ((await fetch(`${base}/api/health`)).ok) return; } catch { /* arrancando */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error('El servidor no arrancó');
}
process.on('unhandledRejection', (e) => { if (!String(e).includes('Target page, context or browser has been closed')) throw e; });

const browser = await chromium.launch({ channel: process.env.BROWSER ?? 'msedge', headless: true });
try {
  await waitHealth();
  check((await (await fetch(`${base}/api/health`)).json()).schema >= 14, 'Servidor con el esquema 14 (impresoras)');
  await fetch(`${base}/api/setup`, { method: 'POST', headers: H,
    body: JSON.stringify({ code: 'E2E-CODE-0010', username: ADMIN.username, full_name: 'Gerente General', password: ADMIN.password }) });
  const ctx = await browser.newContext({ viewport: { width: 1500, height: 950 }, acceptDownloads: true });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(base);
  await page.getByLabel('Usuario', { exact: false }).fill(ADMIN.username);
  await page.getByLabel('Contraseña', { exact: false }).fill(ADMIN.password);
  await page.getByRole('button', { name: 'Ingresar' }).click();
  await page.getByRole('link', { name: 'Inventario' }).first().waitFor();
  const api = ctx.request;

  // 1. Descuento manual máximo de 20 %
  const prod = await (await api.post(`${base}/api/products`, { headers: H,
    data: { code: 'FIL-01', description: 'Filtro de aceite', price: '50000', initial_stock: '20' } })).json();
  const methods = Object.fromEntries((await (await api.get(`${base}/api/payment-methods`)).json()).map((m) => [m.code, m.id]));
  const sale20 = await api.post(`${base}/api/sales`, { headers: { ...H, 'Idempotency-Key': `e2e-${Date.now()}-a` },
    data: { lines: [{ product_id: prod.id, qty: '1', discount_pct: '20' }], payments: [{ method_id: methods.efectivo, amount: '40000' }] } });
  const sale21 = await api.post(`${base}/api/sales`, { headers: { ...H, 'Idempotency-Key': `e2e-${Date.now()}-b` },
    data: { lines: [{ product_id: prod.id, qty: '1', discount_pct: '21' }], payments: [{ method_id: methods.efectivo, amount: '39500' }] } });
  check(sale20.ok() && !sale21.ok() && (await sale21.text()).includes('20 %'), '1 Venta: descuento de 20 % permitido, 21 % rechazado');

  // 2. Gestión › Impresión: cualquier impresora de Windows como predeterminada
  await page.goto(`${base}/gestion/impresion`);
  const def = page.getByLabel('Impresora predeterminada (documentos y plantillas)');
  await def.waitFor();
  const options = await def.locator('option').allInnerTexts();
  const installed = (await (await api.get(`${base}/api/printing/printers`)).json()).printers.map((p) => p.name);
  check(options.length === installed.length + 1 && installed.every((n) => options.some((o) => o.startsWith(n))),
    `2 Lista todas las impresoras de Windows (${installed.join(', ')}) más «La predeterminada de Windows»`);
  const chosen = installed.find((n) => /XPS/i.test(n)) ?? installed[0];
  await def.selectOption(chosen);
  check(await page.getByLabel('Modo de impresión de comprobantes').locator('option', { hasText: 'Plantilla de recibo en cualquier impresora' }).count() === 1,
    '   Modo de comprobante «Plantilla de recibo en cualquier impresora»');
  await page.getByRole('button', { name: 'Guardar' }).first().click();
  await page.getByText('Configuración guardada').waitFor();
  const settings = await (await api.get(`${base}/api/settings`)).json();
  const imp = settings.impresion?.values ?? settings.impresion;
  check(JSON.stringify(settings).includes(chosen), `   Predeterminada guardada: «${chosen}»`);
  await page.screenshot({ path: join(shots, '01-impresion.png') });
  void imp;

  // 3. Plantilla de cotización (diseñador visual) con su propia impresora
  const types = Object.fromEntries((await (await api.get(`${base}/api/document-types`)).json()).map((t) => [t.code, t.id]));
  const tpl = await (await api.post(`${base}/api/print-templates`, { headers: H,
    data: { name: 'Cotización visual', kind: 'documento', document_type_id: types.cotizacion, designer: 'canvas', paper: 'roll80' } })).json();
  const full = await (await api.get(`${base}/api/print-templates/${tpl.public_id}`)).json();
  await api.put(`${base}/api/print-templates/${tpl.public_id}`, { headers: H, data: { layout: full.layout, bindings: {}, activate: true, version: full.version } });
  await api.patch(`${base}/api/print-templates/${tpl.public_id}`, { headers: H, data: { is_default: true } });
  await page.goto(`${base}/gestion/plantillas`);
  await page.getByRole('button', { name: 'Impresora de Cotización visual' }).click();
  const pd = page.getByRole('dialog', { name: /Impresora de/ });
  const other = installed.find((n) => n !== chosen) ?? chosen;
  await pd.getByLabel('Impresora').selectOption(other);
  await pd.getByRole('button', { name: 'Guardar' }).click();
  await page.getByText('Impresora de la plantilla guardada').waitFor();
  const row = page.getByRole('row', { name: /Cotización visual/ });
  check((await row.innerText()).includes(other), `3 Impresora propia de la plantilla: «${other}» (columna «Impresora»)`);

  // 4. Documento: vista previa = PDF de la plantilla, impresora elegible, PDF y Excel sin Microsoft Excel
  const doc = await (await api.post(`${base}/api/documents`, { headers: { ...H, 'Idempotency-Key': `e2e-${Date.now()}-d` },
    data: { type_id: types.cotizacion, customer_name: 'Taller Ruiz', lines: [{ product_id: prod.id, qty: '3' }] } })).json();
  await page.goto(`${base}/vender/documentos/${doc.id}`);
  await page.locator('iframe.doc-preview').waitFor();
  check((await page.getByText(/Vista previa con la plantilla «Cotización visual»/).count()) === 1, '4 La vista previa del documento es la plantilla (PDF real)');
  const printerSel = page.getByLabel('Impresora', { exact: true });
  check((await printerSel.locator('option').first().innerText()).includes(other), `   Impresora preseleccionada: la de la plantilla («${other}»)`);
  check(await page.getByRole('button', { name: 'PDF', exact: true }).isVisible(), '   Botón PDF disponible sin Microsoft Excel');
  const dl = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Excel', exact: true }).click();
  const xfile = await dl;
  const xpath = join(dataDir, 'doc.xlsx');
  await xfile.saveAs(xpath);
  const xinfo = zipNames(readFileSync(xpath), 'doc-check.xlsx');
  check(xinfo.values.includes('Taller Ruiz') && xinfo.values.includes('Filtro de aceite'), '   Excel del documento generado con la plantilla (cliente y producto)');
  await page.screenshot({ path: join(shots, '02-documento.png') });

  // 5. Impresión directa a una impresora que no existe: error claro y registrado (no se imprime en papel)
  const bad = await api.post(`${base}/api/documents/${doc.id}/print`, { headers: H, data: { printer: 'IMPRESORA-INEXISTENTE' } });
  const badText = await bad.text();
  const jobs = await (await api.get(`${base}/api/printing/jobs`)).json();
  check(!bad.ok() && badText.includes('IMPRESORA-INEXISTENTE') && !badText.includes('Microsoft Excel')
    && jobs.some((j) => j.printer === 'IMPRESORA-INEXISTENTE' && j.status === 'error' && j.mode === 'directa'),
  '5 Impresora inexistente: mensaje claro, registrado como trabajo «directa» con error');

  // 6. Plantilla Excel de «Tipos de documento» con imágenes y macros: ya no pide Microsoft Excel
  if (existsSync(ORD)) {
    const up = await api.post(`${base}/api/document-types/${types.orden}/template`, { headers: { 'X-Requested-With': 'pos-py' },
      multipart: { file: { name: 'ORDEN.xlsm', mimeType: 'application/vnd.ms-excel.sheet.macroEnabled.12', buffer: readFileSync(ORD) } } });
    check(up.ok(), '6 Se sube la ORDEN real (.xlsm con imagen y macros) como plantilla del tipo «Orden»');
    await page.goto(`${base}/gestion/documentos`);
    await page.getByText('Orden', { exact: true }).first().click().catch(() => {});
    const body = await page.locator('body').innerText();
    check(!body.includes('se necesita Microsoft Excel'), '   Ya no aparece «se necesita Microsoft Excel en el equipo del servidor»');
    const od = await (await api.post(`${base}/api/documents`, { headers: { ...H, 'Idempotency-Key': `e2e-${Date.now()}-o` },
      data: { type_id: types.orden, customer_name: 'Distrirenault', lines: [{ product_id: prod.id, qty: '1' }] } })).json();
    const f = await api.get(`${base}/api/documents/${od.id}/file`);
    const info = f.ok() ? zipNames(await f.body(), 'orden.xlsm') : { names: [] };
    check(f.ok() && info.names.includes('xl/vbaProject.bin') && info.names.some((n) => n.startsWith('xl/drawings/')),
      `   La orden se genera sin Excel y conserva imagen y macros (${f.status()})`);
    const p = await api.get(`${base}/api/documents/${od.id}/pdf`);
    check(p.ok() && (await p.body()).subarray(0, 4).toString() === '%PDF', '   PDF de la orden sin Microsoft Excel');
    await page.screenshot({ path: join(shots, '03-tipos.png') });
  } else {
    console.log('(omitido) docs/ORDEN-*.xlsm no existe');
  }

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

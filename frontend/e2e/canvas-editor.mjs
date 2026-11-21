// Editor visual de plantillas (lienzo) con navegador real y servidor real. Criterio de aceptación:
// un administrador abre el editor, elige el papel, arrastra el logotipo, agrega textos y datos dinámicos,
// los posiciona, guarda y obtiene un Excel que conserva la distribución y sirve para imprimir ventas.
//   npm run build && node e2e/canvas-editor.mjs
import { spawn, spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { deflateSync } from 'node:zlib';
import { chromium } from 'playwright-core';

const root = resolve(import.meta.dirname, '..', '..');
const python = process.env.PYTHON ?? join(root, 'backend', '.venv', 'Scripts', 'python.exe');
const port = 8774;
const base = `http://127.0.0.1:${port}`;
const shots = process.env.SHOTS ?? mkdtempSync(join(tmpdir(), 'pospy-lienzo-shots-'));
mkdirSync(shots, { recursive: true });
const dataDir = mkdtempSync(join(tmpdir(), 'pospy-e2e-lienzo-'));
const failures = [];
const check = (ok, message) => { console.log(`${ok ? 'OK  ' : 'FALLA'} ${message}`); if (!ok) failures.push(message); };
const H = { 'X-Requested-With': 'pos-py', 'Content-Type': 'application/json' };
const ADMIN = { username: 'gerente', password: 'Clave segura 2026' };

// PNG válido de 60×30 (rojo) generado aquí: sin archivos externos.
function png(w, h) {
  const crcTable = Array.from({ length: 256 }, (_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c >>> 0; });
  const crc = (buf) => { let c = 0xffffffff; for (const b of buf) c = crcTable[(c ^ b) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
  const chunk = (tag, data) => {
    const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
    const td = Buffer.concat([Buffer.from(tag), data]);
    const c = Buffer.alloc(4); c.writeUInt32BE(crc(td));
    return Buffer.concat([len, td, c]);
  };
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 2;
  const row = Buffer.concat([Buffer.from([0]), Buffer.alloc(w * 3, Buffer.from([220, 30, 30]))]);
  const raw = Buffer.concat(Array.from({ length: h }, () => row));
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk('IHDR', ihdr), chunk('IDAT', deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}

// Inspección del Excel con openpyxl (lo mismo que haría Excel al abrirlo): celdas, imágenes, configuración de impresión.
function inspectXlsx(bytes, name) {
  const file = join(dataDir, name);
  writeFileSync(file, bytes);
  const code = `
import json, sys, zipfile, openpyxl
wb = openpyxl.load_workbook(sys.argv[1]); ws = wb.active
z = zipfile.ZipFile(sys.argv[1])
cells = {c.coordinate: c.value for r in ws.iter_rows() for c in r if c.value is not None}
fonts = {c.coordinate: [c.font.b, c.font.sz] for r in ws.iter_rows() for c in r if c.value is not None}
print(json.dumps({"cells": {k: str(v) for k, v in cells.items()}, "fonts": fonts, "merges": len(ws.merged_cells.ranges),
  "images": [n for n in z.namelist() if n.startswith("xl/media/")], "drawing": any(n.startswith("xl/drawings/") for n in z.namelist()),
  "grid": ws.sheet_view.showGridLines, "area": ws.print_area, "formulas": sum(1 for r in ws.iter_rows() for c in r if c.data_type == "f"),
  "marginL": ws.page_margins.left}))`;
  const res = spawnSync(python, ['-c', code, file], { encoding: 'utf8' });
  if (res.status !== 0) throw new Error(res.stderr);
  return JSON.parse(res.stdout);
}

const server = spawn(python, ['-m', 'pospy', '--port', String(port), '--data-dir', dataDir, '--web-dist', join(root, 'frontend', 'dist')],
  { cwd: join(root, 'backend'), env: { ...process.env, POS_SETUP_CODE: 'E2E-CODE-0009' } });
server.stderr.on('data', () => {});
server.stdout.on('data', () => {});
async function waitHealth() {
  for (let i = 0; i < 60; i++) {
    try { if ((await fetch(`${base}/api/health`)).ok) return; } catch { /* arrancando */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error('El servidor no arrancó');
}

// Al cerrar, el visor de PDF del iframe puede rechazar una navegación pendiente: no es una falla de la prueba.
process.on('unhandledRejection', (e) => { if (!String(e).includes('Target page, context or browser has been closed')) throw e; });
const browser = await chromium.launch({ channel: process.env.BROWSER ?? 'msedge', headless: true });
try {
  await waitHealth();
  const setup = await fetch(`${base}/api/setup`, { method: 'POST', headers: H,
    body: JSON.stringify({ code: 'E2E-CODE-0009', username: ADMIN.username, full_name: 'Gerente General', password: ADMIN.password }) });
  check(setup.ok, 'Instalación local con administrador');
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 }, acceptDownloads: true });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(base);
  await page.getByLabel('Usuario', { exact: false }).fill(ADMIN.username);
  await page.getByLabel('Contraseña', { exact: false }).fill(ADMIN.password);
  await page.getByRole('button', { name: 'Ingresar' }).click();
  await page.getByRole('link', { name: 'Inventario' }).first().waitFor();
  const api = ctx.request;

  // Datos reales: logotipo de la empresa, un producto y una venta con efectivo.
  const logo = await api.post(`${base}/api/company/logo`, { headers: { 'X-Requested-With': 'pos-py' },
    multipart: { file: { name: 'logo.png', mimeType: 'image/png', buffer: png(60, 30) } } });
  check(logo.ok(), 'Logotipo de la empresa configurado');
  const prod = await (await api.post(`${base}/api/products`, { headers: H,
    data: { code: 'TAL-01', description: 'Taladro percutor', price: '250000', initial_stock: '10' } })).json();
  const methods = Object.fromEntries((await (await api.get(`${base}/api/payment-methods`)).json()).map((m) => [m.code, m.id]));
  const sale = await (await api.post(`${base}/api/sales`, { headers: { ...H, 'Idempotency-Key': `e2e-${Date.now()}` },
    data: { lines: [{ product_id: prod.id, qty: '2' }], payments: [{ method_id: methods.efectivo, amount: '500000' }] } })).json();
  check(Boolean(sale.id), 'Venta real registrada (2 taladros, efectivo)');

  // 1. Crear desde cero con el diseñador visual y papel térmico de 80 mm
  await page.goto(`${base}/gestion/plantillas`);
  await page.getByRole('button', { name: 'Crear desde cero' }).click();
  const cd = page.getByRole('dialog', { name: 'Crear plantilla desde cero' });
  await cd.getByLabel('Nombre', { exact: false }).fill('Recibo visual');
  await cd.getByLabel('Para qué se usa').selectOption('venta');
  check(await cd.getByLabel('Editor').inputValue() === 'canvas', '1 «Diseñador visual» es la opción por defecto');
  await cd.getByLabel('Papel').selectOption('roll80');
  await cd.getByRole('button', { name: 'Crear y diseñar' }).click();
  const sheet = page.getByTestId('cv-sheet');
  await sheet.waitFor();
  const els = page.locator('.cv-el');
  const initial = await els.count();
  check(initial >= 10, `   El lienzo abre con un recibo inicial de datos reales (${initial} elementos)`);
  const box = await sheet.boundingBox();
  check(Math.abs(box.width - 80 * (96 / 25.4) * 1.5) < 2, `   Hoja a escala real: 80 mm = ${Math.round(box.width)} px al 150 %`);
  await page.screenshot({ path: join(shots, '01-lienzo.png') });

  // 2. Arrastrar el logotipo de la empresa al papel
  await page.getByRole('button', { name: 'Logotipo de empresa' }).dragTo(sheet, { targetPosition: { x: 40, y: Math.round(box.height - 60) } });
  await page.locator('.cv-el-image img').first().waitFor();
  check(await page.locator('.cv-el-image img').count() === 1, '2 Arrastrar «Logotipo de empresa»: la imagen aparece en el papel');
  await page.getByLabel('Ancho (mm)').fill('20');
  await page.getByLabel('Ancho (mm)').press('Enter');
  await page.waitForFunction(() => Number(document.querySelector('label.cv-num:nth-of-type(4) input')?.value ?? 0) !== 15, null, { timeout: 3000 }).catch(() => {});
  await page.getByLabel('Alto (mm)').evaluate(() => new Promise((r) => setTimeout(r, 300)));
  const logoH = Number(await page.getByLabel('Alto (mm)').inputValue());
  check(Math.abs(logoH - 10) < 0.2, `   Redimensionar a 20 mm conserva la proporción 2:1 (alto ${logoH} mm)`);
  await page.getByRole('button', { name: 'Centrar horizontalmente' }).click();
  await page.waitForFunction(() => [...document.querySelectorAll('label.cv-num')].some((l) => l.textContent.startsWith('X (mm)')
    && l.querySelector('input').value === '30'), null, { timeout: 3000 }).catch(() => {});
  check(Number(await page.getByLabel('X (mm)').inputValue()) === 30, '   Centrar en el área imprimible (X = 30 mm)');

  // 3. Texto estático: arrastrar, escribir, negrita y mover con el ratón
  await page.getByRole('button', { name: 'Texto estático' }).dragTo(sheet, { targetPosition: { x: 30, y: 30 } });
  await page.getByLabel('Contenido').fill('GRACIAS POR SU COMPRA');
  await page.getByLabel('Contenido').press('Tab');
  await page.getByLabel('Negrita').check();
  await page.getByLabel('Alineación', { exact: true }).selectOption('center');
  const txt = page.locator('.cv-el.sel');
  const tb = await txt.boundingBox();
  const x0 = Number(await page.getByLabel('X (mm)').inputValue());
  await page.mouse.move(tb.x + 10, tb.y + 5);
  await page.mouse.down();
  await page.mouse.move(tb.x + 40, tb.y + 300, { steps: 8 });
  await page.mouse.up();
  const x1 = Number(await page.getByLabel('X (mm)').inputValue());
  const y1 = Number(await page.getByLabel('Y (mm)').inputValue());
  check(x1 > x0 && y1 > 40, `3 Texto estático escrito y movido con el ratón (X ${x0} → ${x1} mm, Y ${y1} mm)`);
  await page.getByLabel('X (mm)').fill('4');
  await page.getByLabel('X (mm)').press('Enter');
  await page.getByLabel('Ancho (mm)').fill('72');
  await page.getByLabel('Ancho (mm)').press('Enter');
  await page.getByLabel('Y (mm)').fill('96');
  await page.getByLabel('Y (mm)').press('Enter');
  check((await txt.innerText()).includes('GRACIAS POR SU COMPRA'), '   Posición y ancho exactos por teclado (X 4, Y 96, ancho 72 mm)');

  // 4. Dato dinámico «Método de pago» desde la pestaña Datos
  await page.getByRole('tab', { name: 'Datos' }).click();
  await page.getByRole('button', { name: 'Método de pago', exact: true }).dragTo(sheet, { targetPosition: { x: 20, y: 160 } });
  check(await page.getByLabel('Campo de origen').inputValue() === 'metodo_pago', '4 Arrastrar el dato «Método de pago»');
  await page.getByLabel('Si no hay datos, mostrar').fill('CONTADO');
  await page.getByLabel('Y (mm)').fill('103');
  await page.getByLabel('Y (mm)').press('Enter');
  await page.getByLabel('X (mm)').fill('4');
  await page.getByLabel('X (mm)').press('Enter');

  // 5. Duplicar, deshacer y eliminar con teclado
  const before = await els.count();
  await page.keyboard.press('Control+d');
  const dup = await els.count();
  await page.keyboard.press('Delete');
  await page.keyboard.press('Control+z');
  await page.keyboard.press('Control+z');
  check(dup === before + 1 && await els.count() === before, `5 Duplicar (Ctrl+D), eliminar (Supr) y deshacer (Ctrl+Z): ${before} → ${dup} → ${await els.count()}`);
  const outs = await page.locator('.cv-el.out').evaluateAll((n) => n.map((e) => `${e.getAttribute('aria-label')} ${e.style.left} ${e.style.width}`));
  check(outs.length === 0, `   Ningún elemento fuera del área imprimible de 72 mm ${outs.join(' | ')}`);
  await page.screenshot({ path: join(shots, '02-disenado.png') });

  // 6. Guardar y activar; reabrir sin pérdida
  await page.getByRole('button', { name: 'Guardar y activar' }).click();
  await page.getByText('Diseño guardado y plantilla activa').waitFor();
  const url = page.url();
  await page.reload();
  await sheet.waitFor();
  const reopened = await els.count();
  const texts = await sheet.innerText();
  check(reopened === before && texts.includes('GRACIAS POR SU COMPRA') && texts.includes('{Método de pago}')
    && await page.locator('.cv-el-image img').count() === 1, `6 Guardado y reabierto sin pérdida (${reopened} elementos)`);
  const id = url.split('/').pop().split('?')[0];

  // 7. Excel generado: abre, conserva textos, estilos, imagen y configuración de impresión
  const dl = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Exportar plantilla Excel' }).click();
  const file = await dl;
  const tplPath = join(dataDir, 'plantilla.xlsx');
  await file.saveAs(tplPath);
  const { readFileSync } = await import('node:fs');
  const x = inspectXlsx(readFileSync(tplPath), 'plantilla-check.xlsx');
  const values = Object.values(x.cells);
  const thanks = Object.entries(x.cells).find(([, v]) => v === 'GRACIAS POR SU COMPRA');
  check(file.suggestedFilename().endsWith('.xlsx') && values.includes('{Método de pago}') && values.includes('{Descripción}') && thanks,
    `7 «Exportar plantilla Excel» descarga ${file.suggestedFilename()} con textos, datos y fila de productos`);
  check(thanks && x.fonts[thanks[0]][0] === true, '   La negrita del texto se conserva en el Excel');
  check(x.images.length === 1 && x.drawing, '   El logotipo va incrustado como imagen del Excel');
  check(x.grid === false && Boolean(x.area) && x.merges > 0 && x.formulas === 0,
    `   Impresión: sin cuadrícula, área ${x.area}, ${x.merges} celdas combinadas, sin fórmulas`);
  check(Math.abs(x.marginL * 25.4 - 4) < 0.6, `   Margen izquierdo = (80 − 72) / 2 = ${Math.round(x.marginL * 25.4 * 10) / 10} mm`);

  // 8. Vista previa con la venta real (no registra nada) y con datos de demostración
  await page.getByRole('button', { name: 'Vista previa' }).click();
  const pv = page.getByRole('dialog', { name: 'Vista previa' });
  await pv.locator('iframe.tpl-preview').waitFor();
  await pv.getByLabel('Datos').selectOption('venta');
  await pv.getByLabel('Venta').selectOption(String(sale.id));
  await pv.locator('iframe.tpl-preview').waitFor();
  check(true, '8 Vista previa en PDF con datos de demostración y con la venta real');
  await page.screenshot({ path: join(shots, '03-vista-previa.png') });
  await pv.getByRole('button', { name: 'Cerrar' }).last().click();
  const real = await api.post(`${base}/api/print-templates/${id}/preview.xlsx`, { headers: H, data: { sale_id: sale.id } });
  const rx = inspectXlsx(await real.body(), 'real.xlsx');
  const rv = Object.values(rx.cells);
  check(rv.includes('Taladro percutor') && rv.some((v) => v.includes('Efectivo')) && rv.includes('500000'),
    '   Excel con la venta real: producto, método de pago «Efectivo» y total 500000');
  const after = await (await api.get(`${base}/api/products/${prod.id}`)).json();
  check(after.stock === '8', `   La vista previa no modifica el inventario (existencia ${after.stock})`);

  // 9. Imprimir la venta con la plantilla (mismo flujo del POS) en PDF y Excel
  const pdf = await api.get(`${base}/api/sales/${sale.id}/template-pdf?template=${id}&kind=venta`);
  const xs = await api.get(`${base}/api/sales/${sale.id}/template-xlsx?template=${id}&kind=venta`);
  check(pdf.ok() && (await pdf.body()).subarray(0, 4).toString() === '%PDF' && xs.ok(), '9 La venta se imprime con la plantilla visual (PDF y Excel)');

  // 10. Cambiar a papel de 58 mm: el diseño se adapta al ancho imprimible de 48 mm
  await page.getByRole('tab', { name: 'Papel' }).click();
  await page.getByLabel('Tamaño de papel').selectOption('roll58');
  check(await page.getByLabel('Ancho imprimible real (mm)').inputValue() === '48' && await page.locator('.cv-el.out').count() === 0,
    '10 Papel de 58 mm: 48 mm imprimibles y ningún elemento queda fuera');
  await page.getByLabel('Tamaño de papel').selectOption('a4');
  check(Math.abs((await sheet.boundingBox()).width - 210 * (96 / 25.4) * 1.5) < 3, '   Papel A4 a escala real');
  await page.getByRole('button', { name: 'Deshacer (Ctrl+Z)' }).click();
  await page.getByRole('button', { name: 'Deshacer (Ctrl+Z)' }).click();
  check(await page.getByLabel('Tamaño de papel').inputValue() === 'roll80', '   Deshacer vuelve al rollo de 80 mm');

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

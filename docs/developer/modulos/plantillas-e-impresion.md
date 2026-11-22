> Documento técnico del módulo (estado vigente). La historia de cambios está en git; la visión general en [../README.md](../README.md).

> Estado vigente: ningún flujo usa Microsoft Excel. Los documentos se generan con el motor propio (PDF, Excel e impresión directa por GDI); las plantillas Excel antiguas con imágenes o macros se rellenan editando el XML. Ver parte 3.

PARTE 1 — MOTOR DE PLANTILLAS (IMPORTAR EXCEL O DISEÑAR EN CUADRÍCULA)
======================================================================

POS-PY — PLANTILLAS DE IMPRESIÓN (IMPORTAR EXCEL O DISEÑAR DESDE EL POS)
Documentación técnica y de pruebas · 18-11-2026
==========================================================================================
Rutas relativas a la carpeta del proyecto (CRM-P-COMPANY).


1. DIAGNÓSTICO DEL SISTEMA ANTERIOR
------------------------------------------------------------------------------------------
- Gestión › Tipos de documento: cada tipo tenía UNA plantilla Excel con marcadores {{campo}} o
  celdas asignadas a mano (documents/templates.py).
- La zona de productos tenía capacidad FIJA: con más productos que filas, la generación fallaba.
- openpyxl no conserva imágenes ni macros al guardar. Si la plantilla las tenía, el relleno
  dependía de Microsoft Excel instalado (COM). Un servidor web o un equipo sin Excel no podía
  generar ese documento.
- Sin vista previa real (solo una tabla HTML aproximada), sin versiones, sin editor visual y sin
  cálculos propios: las fórmulas las recalculaba Excel al abrir el archivo.
Los Excel de referencia (docs/):
- COTIZACIÓNv3.7.2.xlsm: 3 hojas (Hoja1 es el documento), macros VBA, logotipo JPEG con
  recorte, 29 combinaciones, fecha con =TODAY(), productos en A15:E25, subtotal en E28 y total en E29.
- Ambos archivos usan papelSize 120 con escala 33 % y márgenes 0. Es una impresora térmica de
  rollo: el ancho impreso es de unos 67 mm.
- ORDEN-CASARENAULTv3.4.2.xlsm: productos en A13:E28, descuento 0,2 en E32 y total en E34.
  Tiene combinaciones hasta la columna XFD y filas ocultas por defecto (zeroHeight).
Decisión: un motor nuevo y propio, SIN dependencias nuevas. En el equipo no hay PIL, lxml ni
reportlab. Excel queda solo como opción, no como requisito. El mecanismo anterior se conserva:
si un tipo no tiene plantilla nueva predeterminada, todo funciona como antes.


2. ARQUITECTURA DEL MOTOR
------------------------------------------------------------------------------------------
backend/pospy/documents/
- layout.py: modelo «layout» (JSON con celdas, estilos, combinaciones, imágenes y página). Incluye:
  - formatos numéricos estilo Excel en español (moneda, %, fechas, horas);
  - evaluador de cálculos seguro con Decimal;
  - validación (sanitize_layout) de todo lo que envía el editor.
- xlsx_import.py: lee el libro sin modificarlo y propone las vinculaciones.
- engine.py: aplica las vinculaciones a los datos de una operación (ver puntos 6 a 8).
- layout_pdf.py: genera el PDF propio.
backend/pospy/services/print_templates.py: plantillas, versiones, permisos, grupos, vista previa,
emisión e historial.
Diseño y vinculaciones se guardan por separado. El diseño es la copia del aspecto; las
vinculaciones dicen qué celda recibe qué dato o cálculo. El Excel original se guarda intacto
aparte, macros incluidas, y se puede descargar.
Ambas modalidades (Excel importado y diseño desde cero) usan el mismo modelo, el mismo editor y
el mismo motor.

Base de datos (migración v012):
- print_templates: nombre, tipo (documento con su tipo, venta o recibo), grupo, activa,
  predeterminada (máximo una por grupo y tipo), origen y archivo original.
- print_template_versions: cada guardado es una versión nueva. Las versiones son INMUTABLES:
  hay triggers que impiden modificarlas o borrarlas.
- print_outputs: cada documento emitido guarda la versión usada, el PDF, su huella SHA-256 y
  los datos usados. Editar una plantilla no cambia lo ya emitido. Eliminar una plantilla es
  lógico.


3. TECNOLOGÍA Y JUSTIFICACIÓN
------------------------------------------------------------------------------------------
- openpyxl (ya estaba en el proyecto): lee estilos, combinaciones, valores, fórmulas y la
  configuración de impresión.
- Lectura directa del XML del archivo con la biblioteca estándar, para lo que openpyxl no da:
  imágenes con posición y recorte, y colores del tema. Se rechaza todo XML con DOCTYPE o
  entidades (evita ataques de expansión).
- PDF: escritor propio que amplía simple_pdf.py. Usa Helvetica (mismas medidas que Arial),
  incrusta imágenes JPEG directamente y PNG (con transparencia) descomprimiendo con zlib.
- Editor: React propio sobre una tabla HTML. No se agregó ninguna librería de hojas de cálculo.


4. IMPORTACIÓN DE EXCEL
------------------------------------------------------------------------------------------
Gestión › Plantillas de impresión › Importar Excel:
1. Elija el tipo (cotización, orden, otro tipo, venta o recibo) y el archivo .xlsx o .xlsm.
   - Máximo 10 MB. Se valida el formato y el tamaño descomprimido.
2. «Analizar archivo» muestra cada hoja: dimensiones, celdas con datos, combinaciones,
   fórmulas, imágenes, área de impresión y contenido de muestra.
   - NO se elige ninguna hoja automáticamente.
   - Avisa si hay macros: se conservan en el original pero nunca se ejecutan.
3. Al importar, la plantilla queda en BORRADOR y se abre en el editor con las vinculaciones
   sugeridas y los avisos. El usuario las confirma o cambia y pulsa «Guardar y activar».
Qué se conserva (verificado con la COTIZACIÓN):
- valores, fuentes, tamaños, negrita, cursiva, subrayado y colores (incluidos los del tema);
- rellenos, bordes por lado y su tipo (por ejemplo, guiones medios);
- alineaciones y ajuste de texto, formatos numéricos;
- combinaciones, anchos y altos, filas y columnas ocultas;
- logotipo con su recorte;
- área de impresión, márgenes, escala, orientación, filas repetidas, saltos, encabezado y pie.
Configuración inicial sugerida para la COTIZACIÓN (coincide con la pedida):
- B8: identificación del cliente o «222222222222»;
- D7: hora de impresión;
- B7: fecha en texto (reemplaza el =TODAY() del archivo);
- tabla de productos A15:E25: cantidad, código, descripción, precio y cantidad × precio;
- E28: subtotal; E29: total.
Para la ORDEN también sugiere E32 = porcentaje, E33 = valor del descuento y E34 = total, con
descuento inicial del 20 %.


5. EDITOR VISUAL
------------------------------------------------------------------------------------------
Cuadrícula con coordenadas, tipo hoja de cálculo:
- Selección: clic, arrastre o Mayús.
- Edición en la celda: doble clic, Enter o empezar a escribir. Supr borra.
- Ctrl+Z y Ctrl+Y deshacen y rehacen (hasta 100 pasos). Ctrl+B aplica negrita.
- Ancho y alto: se arrastra el borde del encabezado o se escribe el valor.
- Barra de formato: negrita, cursiva, subrayado, tamaño, color de letra y de relleno,
  alineación horizontal y vertical, ajuste de texto, formato numérico o monetario, bordes
  (todos, contorno, inferior, superior, quitar) con tipo de línea, combinar y separar,
  insertar o eliminar filas y columnas, y zoom.
  - Al insertar o eliminar filas y columnas se mueven también las vinculaciones, la tabla de
    productos, las imágenes y el área de impresión.
Panel lateral:
- Campos: se arrastran a una celda o se pulsan con la celda elegida.
  - Grupos: Empresa, Cliente, Operación, Totales y Productos.
  - Bloque «Tabla de productos»: crea títulos, 5 filas con bordes y los totales debajo.
- Celda: texto fijo, dato del POS (con valor alternativo y formato de fecha u hora) o cálculo.
  Muestra la fórmula original de Excel si la había.
- Productos: filas de la tabla, fila de títulos, campo o cálculo de cada columna y
  porcentaje de descuento.
- Página: papel (carta, oficio, A4, A5, rollo de 80 o 58 mm, personalizado), orientación,
  márgenes, ajustar al ancho o escala, área de impresión, filas repetidas, encabezado y pie
  (&P y &N), saltos.
- Imágenes: subir un logotipo JPG o PNG en la celda elegida, cambiar su tamaño o quitarlo.
En la cuadrícula, las celdas vinculadas muestran una etiqueta azul (dato) o verde (cálculo). Los
datos de ejemplo del Excel dentro de la tabla se ven en gris: no se imprimen.
«Vista previa» abre el PDF REAL del servidor con 1, 3, 10, 30 o 100 productos de demostración,
marcados con «DEMOSTRACIÓN». Funciona también con cambios aún sin guardar.
Hay historial de versiones: se puede abrir una anterior, y al guardarla pasa a ser la actual.


6. CAMPOS Y TABLA DE PRODUCTOS
------------------------------------------------------------------------------------------
Campos por grupo:
- Empresa: nombre, razón social, NIT, dirección, ciudad, teléfono, correo, pie.
- Cliente: nombre, identificación, tipo de documento, dirección, teléfono, correo.
- Operación: tipo, número, fecha, fecha en texto, hora de impresión, fecha y hora de
  impresión, válido hasta, empleado responsable, observaciones.
- Totales: subtotal, porcentaje de descuento, descuento, total, IVA incluido, cantidad de
  productos, total de unidades.
- Productos: n.º, cantidad, código, descripción, unidad, precio unitario, precio sin descuento,
  descuento del producto, valor e IVA %.
La hora de impresión es la del momento real de generación (zona horaria de la empresa). Se
escribe como hora de Excel, así que se aplica el formato de la celda (por ejemplo
h:mm:ss AM/PM). También se puede indicar otro formato en la vinculación.
Tabla dinámica:
- Por cada producto se usa una fila. Las filas sobrantes quedan vacías, SIN los datos de ejemplo.
- Con más productos que filas se insertan filas con el formato de la fila modelo. La última fila
  conserva el cierre de la tabla.
- TODO lo de abajo se desplaza: celdas, combinaciones, imágenes, área de impresión y saltos.
  Nunca se sobrescriben el subtotal, el total, la firma ni el pie.
- Comprobado con 1, 10, 30 y 100 productos.


7. CÁLCULOS
------------------------------------------------------------------------------------------
- valor de cada producto = cantidad × precio unitario, redondeado a centavos;
- subtotal = suma de todos los productos (no depende de un rango fijo como E15:E25);
- descuento = subtotal × porcentaje de la plantilla, UNA sola vez;
- total = subtotal − descuento.
Los precios y cantidades no se modifican para simular el descuento.
Fórmulas propias:
- Operaciones: + − × ÷, %, paréntesis.
- Funciones: SUMA(expresión de producto), REDONDEAR(x; decimales), MAX, MIN, ABS y
  SI_CERO(valor; alternativo). Los argumentos se separan con «;».
- Todo con Decimal. No hay eval ni ejecución de código.
- Variables desconocidas, funciones no permitidas, potencias, datos de producto fuera de SUMA y
  referencias fuera del diseño se rechazan al guardar, con el motivo.
- Las fórmulas de Excel que no se vinculan NO se ejecutan: se imprime el último valor guardado en
  el archivo, y la importación lo avisa celda por celda.
IMPORTANTE (decisión a confirmar): el descuento de la plantilla ORDEN se aplica al documento
IMPRESO. El total guardado de la orden en el POS sigue siendo el de sus precios, sin ese 20 %.


8. PAGINACIÓN
------------------------------------------------------------------------------------------
- Nunca se corta una fila ni una combinación vertical.
- Se respetan los saltos manuales.
- Las filas de títulos configuradas se repiten en cada página SOLO mientras sigan productos.
- Los totales van después del último producto.
- Con «ajustar al ancho» se reduce la escala (nunca se amplía).
- Papel de rollo (80 o 58 mm): es una sola tira continua del alto del contenido. Por ejemplo,
  100 productos de la COTIZACIÓN salen en 1 página de rollo.
- En carta y A4 se crean las páginas necesarias: 100 productos de la COTIZACIÓN en carta ocupan
  11 páginas.


9. INTEGRACIÓN CON LA OPERACIÓN
------------------------------------------------------------------------------------------
- Cotizaciones, órdenes y otros documentos: si el tipo tiene una plantilla nueva
  PREDETERMINADA, el PDF del documento (GET /api/documents/{id}/pdf) la usa sin necesitar Excel.
  - El botón «PDF con plantilla» deja elegir entre las plantillas activas del tipo.
- Ventas: en el detalle de la venta están «PDF con plantilla» y «Recibo con plantilla», con
  plantillas de tipo venta o recibo.
- Cada PDF emitido queda en print_outputs con versión, datos y huella. Se descarga con
  GET /api/print-outputs/{id}.
- Impresión: directa en cualquier impresora de Windows (parte 3); ya no se usa Microsoft Excel (COM).


10. SEGURIDAD Y PERMISOS
------------------------------------------------------------------------------------------
- Administrar plantillas exige gestion.configuracion (solo administradores).
- Generar el PDF exige documentos.ver, ventas.historial o ventas.vender, según el caso.
- Las plantillas de un grupo solo existen para quienes entran a ese inventario; para los demás
  responden 404.
- El identificador público se valida con una expresión estricta y los archivos se sirven solo
  desde la carpeta de la plantilla. Se probó con rutas manipuladas.
- Imágenes: solo JPG y PNG verificados, máximo 3 MB.
- Archivos temporales de importación: carpeta propia, ligados al usuario que los subió, de un
  solo uso y con limpieza automática.


11. ARCHIVOS
------------------------------------------------------------------------------------------
Creados:
- backend: pospy/documents/{layout,xlsx_import,engine,layout_pdf}.py,
  pospy/services/print_templates.py, pospy/api/routes/print_templates.py,
  pospy/migrations/v012_print_templates.py, tests/test_print_templates.py.
- frontend: src/lib/templateModel.ts, src/pages/manage/{PrintTemplates,TemplateEditor}.tsx,
  src/pages/sell/TemplatePdf.tsx, src/styles/template-editor.css,
  src/test/template-model.test.ts, e2e/print-templates.mjs.
- iniciar.cmd y este documento.
Modificados:
- backend: api/app.py, context.py, migrations/__init__.py, services/documents.py (el PDF usa
  la plantilla nueva si existe), __main__.py (mensaje claro si faltan dependencias).
- frontend: pages/manage/ManageRoutes.tsx, pages/sell/{DocumentsPage,SalesHistory}.tsx,
  styles/components.css, e2e/groups.mjs (localizador más específico).
- README.md.
Eliminados: ninguno.


12. PRUEBAS EJECUTADAS (resultados reales, 18-11-2026)
------------------------------------------------------------------------------------------
Backend (pytest): 198 pasan, 13 de ellas nuevas en test_print_templates.py.
- Pasan también las 2 que usan los Excel reales de docs/. Si esos archivos no están, se omiten.
- Cubren:
  - formatos y cálculos seguros;
  - tabla dinámica con 1, 5, 30 y 100 productos (pie y totales desplazados, sin datos de ejemplo);
  - identificación con y sin valor alternativo, y hora real;
  - ORDEN: subtotal 100.000, descuento 20.000 y total 80.000, una sola vez;
  - vinculaciones no válidas;
  - importación real de la COTIZACIÓN: original intacto (SHA-256), combinaciones, imagen,
    estilos, bordes, papel y vinculaciones exactas;
  - versiones inmutables e historial de lo emitido;
  - editor (guardar y reabrir), vista previa, duplicar y eliminar;
  - permisos, grupos, PDF de venta y validación de archivos;
  - XML con DOCTYPE rechazado;
  - API HTTP.
- ruff: sin errores.
- Aviso existente, no nuevo: una prueba anterior de Excel COM imprime «Windows fatal exception
  0x80010108» al cerrar Excel, pero pasa.
Frontend: tsc y eslint sin errores. vitest: 84 pasan, 7 nuevas del modelo del editor (combinar,
bordes, insertar o eliminar filas y columnas moviendo vinculaciones, formatos).
Extremo a extremo con Edge real y servidor real (frontend/e2e/print-templates.mjs): todo correcto.
Cubre:
- importar la COTIZACIÓN real: 3 hojas, aviso de macros, ninguna hoja elegida
  automáticamente, error si no se elige;
- vinculaciones sugeridas visibles, logotipo en el diseño, valor alternativo editable;
- vista previa en PDF con 30 productos; guardar, activar y predeterminar;
- PDF real de una cotización con 30 productos guardado en el historial con su versión, y
  abierto desde la pantalla del documento;
- ORDEN importada con el 20 %;
- diseño desde cero: escribir, combinar, negrita, deshacer y rehacer, ancho, arrastrar la tabla
  de productos y un campo del cliente, descuento y papel A4; guardar, recargar y verificar;
- vista previa de 100 productos en A4: 2 páginas.
Regresión E2E: smoke, groups, notes-tasks, columns-group-tasks y group-inventory pasan.
- groups falló una vez por un localizador ambiguo de la prueba (el nombre del grupo ahora
  también aparece en la barra superior). Se corrigió la prueba.
Revisión visual: se revisaron los PDF generados (rollo y carta) y las capturas del editor. Esa
revisión encontró y corrigió:
- texto que invadía celdas vecinas;
- encabezados repetidos en una página sin productos;
- etiquetas de la tabla con la clave interna en vez del rótulo;
- una pestaña del panel cortada.
Pruebas manuales adicionales: ninguna.
Sin probar: imprimir en la impresora térmica física de rollo, y abrir los PDF en otros visores
además de Edge.


13. LIMITACIONES REALES
------------------------------------------------------------------------------------------
- Las fuentes se sustituyen por Helvetica, con métricas compatibles con Arial. Calibri u otras
  fuentes se ven parecidas, no idénticas.
- No se dibujan texto girado, degradados, formato condicional, gráficos, formas ni WordArt de
  Excel. La importación avisa si hay formas o gráficos.
- Las fórmulas de Excel no se recalculan: hay que vincularlas a un dato o cálculo de POS-PY.
- La salida es PDF. No se genera un XLSX rellenado con el motor nuevo: el XLSX sigue
  disponible con el mecanismo anterior (requiere Excel para conservar imágenes y macros).
- Imágenes PNG: solo de 8 bits y sin entrelazado.
- El papel 120 del archivo se interpretó como rollo de 80 mm por su ancho impreso. Si la
  impresora es de otro ancho, cámbielo en «Página».
- El descuento de la plantilla afecta solo al documento impreso (ver el punto 7).


14. INSTRUCCIONES
------------------------------------------------------------------------------------------
Iniciar: iniciar.cmd en la carpeta del proyecto. Usa backend\.venv; con el Python global de
Windows falta uvicorn.
Importar: Gestión › Plantillas de impresión › Importar Excel. Elija el tipo y el archivo, luego la
hoja; revise las sugerencias en el editor y pulse «Guardar y activar». Después pulse «Usar como
predeterminada».
Crear: «Crear desde cero». Arrastre «Tabla de productos» y los campos, dé formato, configure la
página, use «Vista previa» y guarde.
Usar: en la cotización u orden, o en el detalle de la venta, pulse «PDF con plantilla».
Pruebas:
- backend: cd backend && .venv\Scripts\python -m pytest -q
- frontend: cd frontend && npm run typecheck && npm run lint && npm test
- extremo a extremo: npm run build && node e2e/print-templates.mjs


PARTE 2 — EDITOR VISUAL (LIENZO EN MILÍMETROS)
======================================================================

EDITOR VISUAL (ARRASTRAR Y SOLTAR) PARA PLANTILLAS DE IMPRESIÓN POS
====================================================================

Extiende el módulo existente «Gestión › Plantillas de impresión». No es un módulo aparte: las plantillas de
lienzo se guardan en las mismas tablas, se versionan igual, usan el mismo motor de impresión (PDF) y el mismo
flujo del POS (vender, historial, documentos comerciales).


1. DIAGNÓSTICO (ANTES DE ESTE CAMBIO)
-------------------------------------
- Existía el modo «cuadrícula tipo Excel»: plantillas importadas de Excel o diseñadas celda por celda. El motor
  trabaja con un modelo de cuadrícula (columnas en caracteres, filas en puntos, celdas, combinaciones, estilos,
  imágenes flotantes) y produce un PDF propio.
- No había forma de diseñar por posición libre (milímetros) ni de obtener un archivo Excel generado desde el
  diseño. Tampoco existían: método de pago como dato, ancho imprimible real de las térmicas, logotipo de la
  empresa como elemento ni vista previa con una venta real.


2. QUÉ SE AGREGÓ
----------------
Interfaz (frontend/src):
- pages/manage/CanvasEditor.tsx  Editor de tres paneles.
    Izquierda: «Elementos» (texto estático, texto dinámico, imagen, logotipo de empresa, línea horizontal,
      línea vertical, rectángulo, separador, espacio, tabla de productos), «Datos» (todos los datos comerciales:
      empresa, NIT, dirección, teléfono, número, fecha, hora, cliente, identificación, empleado, subtotal,
      descuento, total, método de pago, observaciones…), «Papel» y «Capas».
    Centro: hoja blanca a escala real (mm → px a 96 ppp × zoom), reglas horizontal y vertical, cuadrícula
      opcional, imán a la cuadrícula y a bordes/centros de otros elementos con guías de alineación, área
      imprimible punteada, elementos fuera del área marcados en rojo, zoom 75–300 %, desplazamiento.
      Acciones: arrastrar desde el panel, mover con el ratón, redimensionar con 8 puntos de control,
      selección múltiple (Mayús/Ctrl + clic, Ctrl+A), duplicar (Ctrl+D), eliminar (Supr), mover con flechas
      (0,5 mm; Mayús 5 mm), alinear, distribuir, bloquear, ocultar, capas (frente/fondo), deshacer/rehacer
      (Ctrl+Z / Ctrl+Y, 150 pasos), aviso al salir con cambios sin guardar.
    Derecha: propiedades. X/Y/Ancho/Alto numéricos en mm, cm o pulgadas. Texto: contenido, fuente, tamaño,
      negrita, cursiva, subrayado, alineación horizontal y vertical, color, texto largo (ajustar / reducir /
      una línea), giro 0/90/270. Dato dinámico: campo de origen, formato, valor si no hay datos. Imagen:
      archivo, vista previa, reemplazar, mantener proporción. Línea y rectángulo: grosor, estilo, colores.
      Tabla: columnas visibles, orden, encabezados, anchos, alineación, letra, alto de fila, bordes,
      encabezado sí/no, ajuste de descripciones.
- lib/canvasModel.ts  Operaciones puras del lienzo (insertar, mover, redimensionar, alinear, distribuir,
  capas, cambio de papel, imán, área imprimible). Probadas en test/canvas-model.test.ts.
- styles/canvas-editor.css
- TemplateEditor.tsx abre el editor visual cuando la plantilla es de lienzo; PrintTemplates.tsx (Crear desde
  cero) pregunta el editor (Diseñador visual por defecto, o Cuadrícula) y el papel.

Servidor (backend/pospy):
- documents/canvas.py  Modelo del lienzo, validación estricta y compilación al motor (ver sección 4).
  Ancho imprimible real de las térmicas (PRINTABLE_DEFAULT).
- documents/layout_xlsx.py  Escritura del Excel (openpyxl + dibujo OOXML para imágenes).
- documents/engine.py  Nuevo dato «Método de pago» (metodo_pago).
- services/print_templates.py
    _sale_data: datos reales de una venta en solo lectura (incluye métodos de pago).
    preview / preview_xlsx con sale_id: vista previa con una venta real (no registra emisión ni modifica nada).
    add_company_logo: copia el logotipo de Gestión › Empresa a la plantilla (con la misma validación de imagen).
    template_xlsx: «Exportar plantilla Excel» (campos como {Nombre del dato} y una fila modelo de productos).
- api/routes/print_templates.py
    POST /api/print-templates/{id}/company-logo
    GET  /api/print-templates/{id}/template.xlsx
    POST /api/print-templates/{id}/preview.xlsx       (body: layout?, lines?, sale_id?)
    POST /api/print-templates/{id}/preview            (ahora acepta sale_id)
    GET  /api/sales/{id}/template-xlsx  y  /api/documents/{id}/template-xlsx

Dependencias nuevas: NINGUNA (openpyxl ya estaba; no se usa Pillow; el arrastre usa HTML5 y Pointer Events).


3. PAPEL Y ANCHO IMPRIMIBLE
---------------------------
Tamaños: Térmica 80 mm, Térmica 58 mm, A4, Carta, Personalizado (ancho/alto, alto variable opcional).
Orientación vertical/horizontal (hojas), márgenes configurables, unidad mm/cm/pulgadas, cuadrícula ajustable.

Las impresoras térmicas NO imprimen todo el ancho del rollo. Valor predeterminado (configurable por plantilla
en «Papel › Ancho imprimible real»):
    rollo 80 mm → 72 mm imprimibles (márgenes laterales de 4 mm)
    rollo 58 mm → 48 mm imprimibles (márgenes laterales de 5 mm)
El valor se define en backend/pospy/documents/canvas.py (PRINTABLE_DEFAULT) y en
frontend/src/lib/canvasModel.ts (PAPERS). Si la impresora imprime otro ancho (p. ej. 64 o 76 mm), cámbielo en
la pestaña «Papel»: los márgenes laterales se recalculan centrados. En los rollos el alto crece con el
contenido y con la cantidad de productos.

Al cambiar de papel, las posiciones y anchos horizontales se convierten en proporción al nuevo ancho
imprimible (nada queda fuera del papel); las verticales y los tamaños de letra se conservan. Se puede deshacer.


4. CONVERSIÓN DEL LIENZO A EXCEL (CÓMO FUNCIONA)
-----------------------------------------------
Excel no tiene posiciones libres: todo vive en celdas. La compilación (canvas.compile_canvas) hace:
1. Recoge todos los bordes izquierdo/derecho y superior/inferior de los elementos visibles (en mm, relativos
   al área imprimible). Bordes a menos de 0,3 mm se unen.
2. Cada franja entre dos bordes verticales es una COLUMNA (ancho mm → ancho Excel en caracteres de Calibri 11);
   cada franja entre bordes horizontales es una FILA (alto mm → puntos, 1 mm = 2,835 pt).
3. Texto y datos → celda combinada que cubre exactamente el rectángulo del elemento, con su fuente, tamaño,
   negrita, cursiva, subrayado, color, relleno, alineación, ajuste/reducción y giro.
4. Líneas → borde de las celdas (grosor fino/medio/grueso, guiones, puntos, doble); rectángulos → bordes del
   contorno y relleno.
5. Imágenes → imagen flotante anclada a la celda de su esquina, con desplazamiento y tamaño exactos
   (EMU), incrustada en el .xlsx (xl/media + xl/drawings).
6. Tabla de productos → fila de encabezados + fila modelo; el motor repite la fila por cada producto y desplaza
   lo que está debajo (totales, pie). En el Excel exportado la fila modelo muestra {Descripción}, {Cantidad}…
7. Página: tamaño de papel (Carta/A4 con su código; rollo como ancho ajustado a 1 página), orientación,
   márgenes en cm, área de impresión, filas de encabezado repetidas, sin líneas de cuadrícula.
Seguridad del Excel: los textos que empiezan con = + - @ se escriben como texto (nunca como fórmula); el
archivo es .xlsx sin macros.

El PDF del POS se dibuja desde el MISMO modelo compilado, así que el PDF, la vista previa y el Excel coinciden.


5. PERSISTENCIA
---------------
Tabla print_templates (sin cambios de esquema): id público, nombre, tipo (documento/venta/recibo), inventario,
activa/predeterminada, versión actual. Cada guardado crea una fila en print_template_versions con:
    layout = {"kind": "canvas", "v": 1,
              "page": {paper, width_mm, height_mm, orientation, unit, auto_height, printable_width_mm,
                       margins{t,r,b,l}},
              "grid": {size_mm, snap, show}, "discount_pct",
              "elements": [{id, type, x, y, w, h, z, locked, hidden, rotation, name?,
                            text{…} | field/fallback/format | image{file, keep_ratio} | line{…} | rect{…} |
                            table{columns[{field, header, width_mm, align}], header{…}, size, row_height_mm, …}}]}
    bindings = {} (se generan al compilar), fecha y autor de la versión.
Las imágenes se guardan aparte en la carpeta de datos de la plantilla, con nombre «img-<sha256>.png|jpg».
El diseño (JSON) es la fuente; el Excel se genera cada vez desde él. Las plantillas existentes (cuadrícula e
importadas de Excel) no cambian y conviven con las de lienzo.


6. SEGURIDAD
------------
- Solo «gestion.configuracion» crea, edita, exporta o inserta imágenes/logo. Los empleados solo imprimen con
  las plantillas activas de su inventario (y ven sus propias ventas).
- Imágenes: solo PNG/JPEG; se validan extensión, contenido real (firma y cabeceras), tamaño (3 MB) y
  dimensiones (máx. 6000 × 6000 px);
  nombre derivado del hash (sin rutas del usuario → sin path traversal).
- Diseño: validado en el servidor (tipos, rangos, colores #RRGGBB, campos existentes, máximo 300 elementos,
  una sola tabla); los valores se escriben como texto.
- La vista previa con venta real comprueba inventario y permisos y no registra nada (ni auditoría, ni stock).
- No se ejecutan macros: los .xlsm importados solo se leen como datos; el Excel generado no tiene macros.
- Sin contenido externo: imágenes y fuentes locales.


7. PRUEBAS Y RESULTADOS
-----------------------
backend/tests/test_canvas.py (11 pruebas, todas pasan): papeles 80/58/A4/Carta/personalizado con 1 y 60
productos; Excel real con imagen y sin fórmulas; diseño inválido rechazado; crear, guardar, reabrir, PDF,
Excel de una venta; ancho imprimible real y configurable; vista previa con venta real (producto, «Efectivo»)
sin modificar auditoría ni existencias; exportar plantilla; logotipo de la empresa; permisos del empleado.
frontend/src/test/canvas-model.test.ts (6 pruebas): área imprimible, mover, redimensionar, proporción,
tabla única, cambio de papel, alinear, distribuir, capas e imán.
frontend/e2e/canvas-editor.mjs (navegador Edge real + servidor real, criterio de aceptación, todo correcto):
crear con el diseñador visual en 80 mm; hoja a escala real; arrastrar el logotipo (proporción 2:1
conservada, centrado); arrastrar y escribir un texto, negrita, moverlo con el ratón y fijar X/Y/ancho;
arrastrar «Método de pago»; duplicar/eliminar/deshacer con teclado; guardar y reabrir sin pérdida; exportar
el Excel y abrirlo (textos, negrita, imagen incrustada, sin cuadrícula, área de impresión, margen de 4 mm,
sin fórmulas); vista previa con demostración y con la venta real; la venta se imprime con la plantilla en PDF
y Excel; papel 58 mm (48 mm útiles, nada fuera) y A4; deshacer el cambio de papel.
Regresión: e2e/print-templates.mjs y e2e/smoke.mjs pasan; pytest completo; vitest, tsc y eslint limpios.
Ejecutar:  cd frontend && npm run build && node e2e/canvas-editor.mjs


8. LIMITACIONES CONOCIDAS
-------------------------
- El PDF usa Helvetica (la fuente elegida se conserva en el Excel).
- En Excel no existe el papel «rollo»: se ajusta al ancho de 1 página; el tamaño del rollo se configura en el
  controlador de la impresora térmica.
- Excel no admite: giro ni opacidad de imágenes, espaciado entre letras, giro de 270° exacto (se usa 180 de
  Excel, que equivale a texto hacia abajo).
- Textos superpuestos: en la celda queda el de la capa superior (el editor avisa al compilar).
- Las líneas diagonales no existen (solo horizontales y verticales).
- En navegadores sin visor de PDF integrado la vista previa se descarga en lugar de mostrarse.


9. USO
------
1. Gestión › Plantillas de impresión › «Crear desde cero». Elija nombre, uso (Venta, Recibo o Documento),
   «Diseñador visual» y el papel.
2. El lienzo abre con un recibo inicial hecho con datos reales. Arrastre desde «Elementos» o «Datos» al papel
   (o pulse el botón para insertarlo al final).
3. Seleccione un elemento para cambiar sus propiedades a la derecha. Muévalo con el ratón o las flechas;
   redimensiónelo con los puntos azules. Mayús + clic para seleccionar varios y alinearlos o distribuirlos.
4. «Papel»: tamaño, ancho imprimible real de su térmica, márgenes, cuadrícula e imán.
5. «Vista previa»: datos de demostración (marcados) o una venta real. «Excel de ejemplo» descarga el Excel
   con datos de demostración.
6. «Guardar y activar». Después «Exportar plantilla Excel» descarga el Excel generado con el diseño.
7. Para que el POS la use automáticamente, márquela como predeterminada en la lista de plantillas.


PARTE 3 — IMPRESORAS, DOCUMENTOS SIN EXCEL Y DATOS OPCIONALES
======================================================================

IMPRESORAS CONFIGURABLES, DOCUMENTOS SIN MICROSOFT EXCEL, DATOS OPCIONALES Y DESCUENTO DE 20 %
==============================================================================================

Respuesta a las pruebas del usuario (2026-11-21):
  1. «Venta: el descuento puede ser máximo del 20 %».
  2. «La plantilla contiene imágenes o formas, macros: se necesita Microsoft Excel en el equipo del servidor
     para generarla» → no debe pasar.
  3. «Válido hasta», «Elaborado por»… son innecesarios en su caso y sin casilla se dañaba: debe ser flexible.
  4. Poder configurar cualquier impresora (no solo la POS), con una predeterminada.


1. DESCUENTO MANUAL MÁXIMO: 20 %
--------------------------------
- Valor de fábrica: 20 % (Gestión › Configuración › Ventas › «Descuento manual máximo (%)»). Sigue siendo
  configurable de 0 a 100.
- Migración 14: si la base tenía el valor de fábrica anterior (10 %), pasa a 20 %. Si el administrador había
  elegido otro valor, se respeta.


2. DOCUMENTOS SIN MICROSOFT EXCEL
---------------------------------
Causa: la pantalla de cotizaciones/órdenes usaba la plantilla de «Tipos de documento» y, si el Excel tenía
imágenes, formas o macros, solo sabía rellenarla con Excel (COM).

Ahora:
- Si el tipo de documento tiene una plantilla de impresión predeterminada (Gestión › Plantillas de
  impresión), TODO usa el motor propio: vista previa (el PDF real), Excel (generado con el diseño, con
  imágenes), PDF e impresión directa.
- Si solo tiene la plantilla Excel de «Tipos de documento»:
  · Excel: se escriben solo las celdas dentro del XML de la hoja; dibujos, imágenes, gráficos, macros
    (vbaProject.bin), estilos y fórmulas se copian intactos. Se quita calcChain.xml y se marca
    «recalcular al abrir» (Excel lo reconstruye). Verificado abriendo el archivo con Excel real: sin
    reparación, la imagen sigue, la macro sigue, =SUMA se recalcula, el papel y el ajuste al ancho aplican.
  · PDF e impresión: la plantilla se convierte al motor propio (importación de la hoja + valores).
- Ningún flujo usa ya Microsoft Excel. Las macros nunca se ejecutan.
Archivos: documents/templates.py (write_cells_xml, render_layout), services/documents.py.


3. DATOS OPCIONALES (FLEXIBILIDAD)
----------------------------------
- Plantillas de impresión (editor visual y cuadrícula): cualquier dato vacío o ausente se imprime en blanco
  (o con el texto «Si no hay datos, mostrar»). Probado con TODOS los campos vacíos y ausentes: PDF y Excel
  se generan igual.
- Plantillas de «Tipos de documento»: ya no hay campos obligatorios (antes: Número, Cliente, Total y la fila
  de productos). Solo se bloquea un marcador asignado que ya no está en su celda (evita un documento mal
  impreso). Sin fila de productos, el documento se genera sin tabla.
- Los editores lo indican: «Todos son opcionales: use solo los que necesite».
Si aún ve un caso en que falte un dato y algo falle, anote el mensaje exacto: es un defecto a corregir.


4. IMPRESORAS: CUALQUIERA, CON UNA PREDETERMINADA
-------------------------------------------------
Impresión directa desde el equipo servidor a CUALQUIER impresora instalada en Windows (térmica, láser,
tinta, PDF…). printing/gdi.py dibuja la plantilla con GDI usando la misma geometría que el PDF (lo que se ve
en la vista previa es lo que sale impreso): texto Arial (métricas de la Helvetica del PDF), líneas con su
estilo, imágenes JPEG/PNG con GDI+ de Windows, recorte, varias páginas, copias. En hojas se pide al
controlador el papel y la orientación de la plantilla; en rollos se usa el papel del controlador y se divide si
el contenido es más alto. Sin dependencias nuevas (pywin32 ya estaba).

Dónde se elige:
- Gestión › Impresión › «Impresora predeterminada (documentos y plantillas)»: lista de impresoras de Windows
  (vacío = la predeterminada de Windows).
- Cada plantilla: Gestión › Plantillas de impresión › botón de impresora (columna «Impresora»).
- Al imprimir: selector «Impresora» en el documento y en «PDF con plantilla».
Prioridad: la elegida al imprimir → la de la plantilla → la del tipo de documento → la predeterminada de
Configuración → la predeterminada de Windows.

Comprobante del POS: nuevo «Modo de impresión de comprobantes» = «Plantilla de recibo en cualquier impresora»
(usa la plantilla de recibo predeterminada; si no hay, la de venta). Los modos «Térmica directa (ESC/POS)» y
«Diálogo del navegador» siguen disponibles.

Cada impresión queda en «Últimas impresiones» (modo «directa», impresora, copias, resultado o error) y en la
actividad. Errores claros: impresora inexistente, desconectada, etc.

Rutas nuevas: POST /api/sales/{id}/template-print, POST /api/documents/{id}/template-print,
GET /api/documents/{id}/template-preview (solo lectura), GET /api/sales/{id}/template-info.
Migración 14: print_templates.printer; print_jobs admite el modo «directa» (tabla reconstruida sin perder
registros); descuento 20 %. La interfaz exige el esquema 14 (aviso si el servidor es viejo).


5. PRUEBAS
----------
backend/tests/test_direct_print.py (11): datos ausentes nunca rompen; descuento 20/21 %; migración respeta
valores elegidos; impresión de venta con prioridad de impresoras y registro; error de impresión registrado;
comprobante en modo plantilla; documentos con el motor propio (vista previa sin emisión, Excel, PDF,
impresión); Excel antiguo con imagen rellenado sin Excel; .xlsm real con dibujo y macros; plantilla antigua
sin campos «obligatorios»; impresión GDI real en «Microsoft Print to PDF».
tests/test_documents.py actualizado (la plantilla con gráfico se rellena sin Excel).
frontend/e2e/printers-documents.mjs (navegador real): descuento, lista de impresoras de Windows y
predeterminada, impresora por plantilla, vista previa del documento con la plantilla, Excel/PDF, impresora
inexistente registrada, ORDEN .xlsm real sin Excel (imagen y macros conservadas, PDF).
Regresión: pytest completo, vitest (96), tsc, eslint, E2E canvas-editor, print-templates y smoke: todo correcto.


6. LIMITACIONES
---------------
- La impresión directa usa las impresoras del EQUIPO SERVIDOR (donde corre POS-PY). Desde otro equipo de la
  red se sigue pudiendo descargar el PDF.
- «Microsoft Print to PDF»/«XPS» como impresora abren en el servidor la ventana para guardar el archivo.
- En plantillas antiguas, las celdas con fórmula que no son datos del POS muestran en el PDF el valor que
  tenían guardado (en el Excel se recalculan al abrir). Para totales use los datos del POS.

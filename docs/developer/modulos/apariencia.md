> Documento técnico del módulo (estado vigente). La historia de cambios está en git; la visión general en [../README.md](../README.md).

PERSONALIZACIÓN VISUAL GLOBAL Y PANTALLA DE INGRESO
===================================================

Gestión › Apariencia del sistema (permiso «gestion.configuracion»). Dos pestañas:
  A. Colores del sistema: paleta de TODO el POS (modo claro y modo oscuro).
  B. Pantalla de ingreso: imagen de fondo y logotipo independientes.


1. DIAGNÓSTICO (ANTES)
----------------------
- Ya existía un sistema de tokens CSS (styles/tokens.css) con modo claro/oscuro y alto contraste, y los
  componentes usaban esos tokens. El modo claro/oscuro es una preferencia PERSONAL (por usuario, en el
  servidor; copia local solo para pintar sin parpadeo).
- No había forma de cambiar la paleta del negocio: el «Color corporativo» (empresa.primary_color) se guardaba
  pero no se usaba en ningún estilo.
- Faltaban tokens para color secundario, acento, éxito/advertencia base y menú de navegación.
- Algunos colores fijos que debían seguir al tema (selección del editor de plantillas, lienzo, estrella de
  proveedores, aviso del historial). Los colores fijos que quedan son intencionales: la hoja blanca de las
  vistas previas e impresiones, la cuadrícula tipo Excel y la regla/mesa del lienzo (representan papel).
- La pantalla de ingreso mostraba el logotipo de la empresa dentro de un marco punteado «Aquí tu logo».


2. ARQUITECTURA
---------------
Un solo sistema de temas (no se duplicó):
- styles/tokens.css: valores de fábrica de todos los tokens + tokens nuevos.
- lib/theme.ts: 12 colores base por modo → se DERIVAN todos los tokens (hover, fondos suaves, texto legible
  sobre cada color, menú…). Genera una hoja de estilos:
      :root[data-brand="custom"]                       modo claro
      :root[data-brand="custom"][data-theme="dark"]    modo oscuro
      :root[data-brand="custom"][data-contrast="high"] alto contraste se sigue respetando
  No usa estilos en línea en los componentes: todos siguen leyendo var(--token).
- context/Theme.tsx (ThemeProvider, fuera de la sesión: también lo usa la pantalla de ingreso): lee
  GET /api/appearance, aplica la hoja, permite vista previa (sin guardar) y relee al volver a la pestaña
  (otro dispositivo pudo cambiarla).
- public/theme-init.js: copia local de la hoja SOLO para pintar sin parpadeo (la fuente de verdad es el
  servidor). Ignora contenido sospechoso.
- Recuperación: abrir el POS con «?tema=original» al final de la dirección muestra los colores de fábrica en
  esa pestaña (por si un tema quedara ilegible).

Modos: el negocio define los colores del modo CLARO y del modo OSCURO por separado; cada persona elige claro,
oscuro o sistema en sus preferencias. Cambiar de modo no destruye los colores del otro. «Usar el tema
personalizado» apagado = colores de fábrica.


3. TOKENS
---------
Colores base editables (12): primario, secundario, acento, fondo general, tarjetas y paneles, navegación,
texto principal, texto secundario, bordes, éxito, advertencia, error.
Tokens semánticos (nombres de la arquitectura existente):
  --bg  --surface  --surface-2  --surface-hover  --border  --border-strong  --text  --text-muted
  --primary  --primary-hover  --on-primary  --primary-soft  --on-primary-soft
  --secondary  --secondary-hover  --on-secondary  --accent  --on-accent
  --success  --warning  --danger  --danger-hover  --on-danger
  --success-soft/--on-success-soft  --warning-soft/--on-warning-soft  --danger-soft/--on-danger-soft
  --info-soft/--on-info-soft (del acento)  --focus
  --nav-bg  --nav-text  --nav-hover  --nav-border  --nav-active-bg  --nav-active-text  --nav-indicator
Los «--on-*» y el texto del menú se ELIGEN automáticamente para cumplir 4,5:1; los bordes de campos y el foco
se ajustan a 3:1. En modo claro el hover oscurece y en oscuro aclara.

Componentes afectados (todos por tokens): menú lateral y barra inferior móvil (nav-*), botones (nuevo
«secondary»; «outline» con borde secundario), formularios, tablas, pestañas, ventanas, avisos, insignias,
tarjetas y mosaicos, gráficos (barras de finanzas/actividad), editor de plantillas y lienzo, Ventas,
Inventario, Usuarios, Tareas, Configuración y la pantalla de ingreso.

Paletas predefinidas (claro + oscuro, todas cumplen AA en ambos modos, verificado por pruebas):
Corporate Blue (fábrica), Emerald, Violet, Warm, Neutral, Dark Professional.


4. EDITOR (Colores del sistema)
-------------------------------
- Selector visual + HEX editable (se valida #RRGGBB; un HEX inválido se marca y no se aplica).
- Vista previa inmediata en TODA la aplicación mientras se edita (también el menú) y una vista previa de
  componentes (menú, tarjeta, campo, botones principal/secundario/contorno, avisos, tabla, insignias, enlace)
  con los colores del modo que se edita.
- Acciones: Aplicar cambios, Cancelar, Restablecer paleta, elegir paleta predefinida.
- Contraste: lista de combinaciones bajo el mínimo (AA) con su relación; las casi ilegibles se marcan
  «Ilegible» y al aplicar se pide confirmación. No se bloquea arbitrariamente.


5. PANTALLA DE INGRESO
----------------------
Se conserva el formulario, la autenticación, las validaciones, los mensajes de error y carga (no se tocó el
inicio de sesión). El panel visual ahora tiene:
- Imagen de fondo: seleccionar/reemplazar/eliminar, ajuste (cubrir / mostrar completa: object-fit),
  posición horizontal y vertical (object-position), zoom 100–300 %, oscurecimiento 0–80 %, color y opacidad
  de superposición. Llena el panel sin deformarse.
- Logotipo independiente: seleccionar/reemplazar/eliminar, tamaño (ancho 40–520 px, sin superar el panel),
  posición en una cuadrícula 3 × 3, separación del borde. Solo la imagen: sin borde, marco, tarjeta ni fondo;
  respeta la transparencia; nunca se deforma (object-fit: contain). Opción: si no hay logotipo propio, usar el
  de la empresa (Gestión › Empresa).
- Sin logotipo ni fondo: panel limpio con el color del tema (se quitó «Aquí tu logo» y el marco punteado).
- Vista previa al tamaño real de escritorio, tableta o teléfono (reducida para caber).
- Responsive: en pantallas angostas el panel va arriba (máx. 40 % del alto) y el formulario debajo; sin
  desplazamiento horizontal, logotipo dentro de la pantalla, campos y botón completos (verificado a 375 y 820 px).
- La pantalla de cambio de contraseña usa el mismo panel.


6. PERSISTENCIA
---------------
Misma tabla «settings» de la configuración del POS (no se creó otro sistema), una clave por módulo:
  «apariencia»: {enabled, palette, light{12 colores}, dark{12 colores}}
  «login»: {background{fit,pos_x,pos_y,zoom,darken,overlay_color,overlay_opacity},
            logo{size,position,offset,use_company}, version}
Imágenes: archivos en <carpeta de datos>/branding/login-background.(png|jpg|webp) y login-logo.(…) — nunca
Base64 en la base. «version» cambia con cada imagen o ajuste para que los navegadores no usen la anterior.
Alcance: una instalación = un negocio; inventarios y grupos comparten la apariencia (no hay apariencia por
inventario, así que uno no puede sobrescribir la de otro).
Persiste al recargar, al cerrar sesión, al reiniciar el servidor y en otros equipos (verificado: otro
navegador sin sesión y otra sesión ven el tema guardado).
Las copias de seguridad incluyen la base (settings); la carpeta branding/ está dentro de la carpeta de datos.

API: GET /api/appearance (pública), PUT /api/appearance/theme, PUT /api/appearance/login,
POST/DELETE /api/appearance/login/{fondo|logotipo}, GET /api/appearance/login/{fondo|logotipo} (pública).


7. SEGURIDAD
------------
- Escritura solo con «gestion.configuracion», validado en el SERVIDOR (empleado: 403; sin sesión: 401).
- Imágenes: tipo reconocido por el CONTENIDO real (firma y cabeceras PNG/JPEG/WEBP), no por la extensión ni
  el MIME declarado; SVG rechazado (incluso disfrazado de .png); fondo ≤ 6 MB y ≤ 8000 px por lado, logotipo
  ≤ 2 MB y ≤ 4000 px. Nombres fijos en el servidor: sin rutas arbitrarias. Se sirven con su tipo correcto y
  «X-Content-Type-Options: nosniff».
- Colores: solo #RRGGBB (validado en el servidor y en la interfaz): la hoja generada no puede contener otra cosa.
- No se modificó la autenticación, los permisos, el modelo de usuarios, ventas ni inventarios.


8. PRUEBAS EJECUTADAS
---------------------
backend/tests/test_appearance.py (7): detección de imágenes por contenido (PNG, PNG transparente, JPEG, WEBP;
rechazo de SVG, ejecutables, GIF, PNG truncado); valores de fábrica públicos; guardar/validar/recuperar el
tema; composición del ingreso y eliminación independiente de fondo y logotipo; límites de tamaño y
dimensiones; permisos del empleado; HTTP (público, 401, 403, SVG 422, nosniff, otra sesión).
frontend/src/test/theme.test.ts (10): las 6 paletas cumplen AA en claro y oscuro (texto, botones, hover,
menú, avisos); legibilidad automática con colores difíciles; advertencias e «Ilegible»; validación; hoja
generada solo con colores; el tema de fábrica reproduce los tokens base.
contrast.test.ts ampliado (secundario y acento); screens.test.tsx: panel de ingreso limpio y fondo/logotipo
propios (src, posición, zoom, superposición).
frontend/e2e/appearance.mjs (navegador real): colores de fábrica; paleta Violet al instante (menú y botón);
texto del menú legible; HEX editable y vista previa; HEX inválido; Cancelar; aviso «Ilegible» y confirmación;
Restablecer; guardar y persistir al recargar; aplicación en Ventas e Inventario; modo oscuro con los colores
oscuros del tema y regreso al claro; fondo y logotipo PNG transparente; SVG rechazado (interfaz y servidor);
ingreso con fondo propio, logotipo sin borde ni fondo, sin deformar, abajo a la derecha; botón con el tema;
tableta y teléfono sin desplazamiento horizontal; ingreso funcional y 401 con contraseña equivocada; eliminar
fondo/logotipo por separado; empleado sin permiso (403) que sí ve el tema. Todo correcto.
Regresión: pytest completo, vitest (113), tsc, eslint, E2E smoke, inventories, groups, notes-tasks,
print-templates, canvas-editor y printers-documents: todo correcto. (En canvas-editor se corrigieron dos
lecturas de la prueba que leían un campo antes de que la pantalla lo actualizara.)


9. LIMITACIONES
---------------
- La paleta es del negocio completo (no por inventario ni por usuario); cada usuario solo elige claro/oscuro.
- El «Color corporativo» de Gestión › Empresa sigue existiendo pero no define la paleta: use Apariencia.
- Las hojas de impresión, vistas previas de documentos y la cuadrícula tipo Excel siguen en blanco y negro a
  propósito (representan el papel).
- No se recorta la imagen de fondo en el servidor: se ajusta en pantalla (posición, zoom, ajuste).

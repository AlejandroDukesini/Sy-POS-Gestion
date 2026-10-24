// Aplica tema y tamaño de texto antes del primer pintado (sin parpadeo). Acepta solo valores válidos.
(function () {
  try {
    var p = JSON.parse(localStorage.getItem('pospy.ui') || '{}');
    var root = document.documentElement;
    var dark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    var theme = p.theme === 'dark' || p.theme === 'light' ? p.theme : p.theme === 'system' && dark ? 'dark' : 'light';
    root.dataset.theme = theme;
    if ([16, 18, 20, 22].indexOf(p.font_size) >= 0) root.style.fontSize = p.font_size + 'px';
    if (p.density === 'compacta') root.dataset.density = 'compacta';
    if (p.high_contrast === true) root.dataset.contrast = 'high';
    if (p.sidebar === 'collapsed') root.dataset.sidebar = 'collapsed';
    if (p.motion === 'reduced') root.dataset.motion = 'reduced';
  } catch (e) {
    /* sin preferencias guardadas */
  }
})();

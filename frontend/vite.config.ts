/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
import { VitePWA } from 'vite-plugin-pwa';

// En desarrollo, Vite reenvía /api al backend Python (python -m pospy). En producción la interfaz
// compilada (dist/) la sirve el mismo backend: mismo origen, sin CORS ni URLs codificadas.
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'prompt',
      injectRegister: false,
      manifest: {
        name: 'POS-PY',
        short_name: 'POS-PY',
        description: 'Punto de venta y control de inventario',
        lang: 'es-CO',
        start_url: '/',
        display: 'standalone',
        background_color: '#f4f6fa',
        theme_color: '#1d4ed8',
        icons: [
          { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/icons/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,png,woff2}'],
        navigateFallback: '/index.html',
        navigateFallbackDenylist: [/^\/api\//],
        cleanupOutdatedCaches: true,
        runtimeCaching: [
          {
            // Solo el catálogo se guarda para consulta sin conexión. Ventas, pagos y cambios nunca.
            urlPattern: ({ url, request }) =>
              request.method === 'GET' && /^\/api\/(products(\/lookup)?|settings\/public|payment-methods|categories)$/.test(url.pathname),
            handler: 'NetworkFirst',
            options: {
              cacheName: 'pospy-catalogo',
              networkTimeoutSeconds: 4,
              expiration: { maxEntries: 200, maxAgeSeconds: 60 * 60 * 24 * 7 },
              cacheableResponse: { statuses: [200] },
            },
          },
        ],
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false } },
  },
  build: { target: 'es2022', sourcemap: false, chunkSizeWarningLimit: 700 },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
});

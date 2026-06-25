import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// Vite + React for the QueueLab terminal-CLI dashboard, with Vitest wired for component tests
// (jsdom DOM, jest-dom matchers loaded in the setup file, globals so tests need no imports).
export default defineConfig({
  plugins: [react()],
  server: {
    // Docker dev mounts the source from the Windows host; inotify events don't cross that
    // bind-mount boundary, so Vite never sees edits and serves stale modules. Poll instead.
    watch: { usePolling: true, interval: 200 },
    // Dev: proxy the REST API and the WebSocket to the backend so the app uses same-origin
    // relative URLs (/api, /ws) in every environment. Prod serves both same-origin via nginx
    // (Epic 19). Override the target with VITE_PROXY_TARGET when the backend runs elsewhere.
    // `xfwd` adds X-Forwarded-For so the backend rate-limiter keys on the real client IP, not the
    // proxy's — otherwise every visitor collapses into one shared per-IP bucket.
    proxy: {
      '/api': {
        target: process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
        xfwd: true,
      },
      '/ws': { target: process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000', ws: true, xfwd: true },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: true,
    // Vitest owns the src unit tests; the Playwright e2e specs (e2e/**) are run by Playwright.
    include: ['src/**/*.test.{ts,tsx}'],
  },
});

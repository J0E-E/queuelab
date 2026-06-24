import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// Vite + React for the QueueLab terminal-CLI dashboard, with Vitest wired for component tests
// (jsdom DOM, jest-dom matchers loaded in the setup file, globals so tests need no imports).
export default defineConfig({
  plugins: [react()],
  server: {
    // Dev: proxy the REST API and the WebSocket to the backend so the app uses same-origin
    // relative URLs (/api, /ws) in every environment. Prod serves both same-origin via nginx
    // (Epic 19). Override the target with VITE_PROXY_TARGET when the backend runs elsewhere.
    proxy: {
      '/api': {
        target: process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': { target: process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000', ws: true },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: true,
  },
});

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// Vite + React for the QueueLab terminal-CLI dashboard, with Vitest wired for component tests
// (jsdom DOM, jest-dom matchers loaded in the setup file, globals so tests need no imports).
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: true,
  },
});

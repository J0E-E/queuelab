import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright config for the QueueLab end-to-end narrative (Epic 17).
 *
 * The spec drives the live dashboard against a running stack. In CI (Epic 19) the stack is brought
 * up by Compose; locally, point `E2E_BASE_URL` at a `vite preview` / dev server fronting the
 * backend. The spec lives in `e2e/` so Vitest (which owns `src/**`) never picks it up.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: 'list',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:4173',
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});

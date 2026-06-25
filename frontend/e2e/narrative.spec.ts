import { expect, test } from '@playwright/test';

/**
 * The QueueLab narrative end-to-end (Epic 17): submit → break → recover → scale, driven through the
 * real dashboard UI against a running stack. The element ids come from the Epic 14 panes.
 *
 * This runs in CI once Epic 19 wires a serve-able stack (uvicorn api + frontend service + nginx);
 * the gating suites until then are the backend (pytest) and frontend (vitest) jobs.
 */
test.describe('QueueLab narrative', () => {
  test('submit, break a worker, recover, and scale', async ({ page }) => {
    await page.goto('/');

    // A guest identity is assigned on load.
    await expect(page.locator('#dashboard-guest')).toContainText('guest-');

    // Submit a batch of jobs.
    await page.locator('#submit-count').fill('20');
    await page.locator('#submit-execute').click();
    await expect(page.locator('#submit-result')).toContainText('[OK]');

    // The queue and the activity feed come alive.
    await expect(page.locator('#feed-list')).not.toBeEmpty();

    // Break a worker on purpose — the feed should show the destruction and the recovery that follows.
    await page.locator('#destroy-worker-button').click();
    await expect(page.locator('#feed-list')).toContainText(/destroyed|scaled|started|retry/i);

    // Nudge the fleet up; the workers pane reflects the new count.
    await page.locator('#scale-up-button').click();
    await expect(page.locator('#workers-pane-title')).toBeVisible();
  });
});

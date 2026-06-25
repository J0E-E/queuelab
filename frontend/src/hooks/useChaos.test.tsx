import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError, destroyWorker } from '../lib/api';
import { useChaos } from './useChaos';

// Keep the real ApiError (so `instanceof` checks in the hook hold) and stub only the network calls.
vi.mock('../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../lib/api')>('../lib/api');
  return { ...actual, destroyWorker: vi.fn(), injectFailures: vi.fn() };
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('useChaos', () => {
  it('returns the destroyed worker id on success so the grid can mark it dead', async () => {
    vi.mocked(destroyWorker).mockResolvedValue({ worker_id: 'worker-9' });
    const { result } = renderHook(() => useChaos());

    let returned: string | null = null;
    await act(async () => {
      returned = await result.current.destroy('sess', 'worker-9');
    });
    expect(returned).toBe('worker-9');
    expect(result.current.success).toContain('destroyed worker-9');
  });

  it('auto-clears a rate-limit warning once the Retry-After window passes', async () => {
    // A 429 with a 0.05s window so the test doesn't wait on a real rate-limit period.
    vi.mocked(destroyWorker).mockRejectedValue(new ApiError(429, '[WARN] rate limit: 1 / 3s', 0.05));
    const { result } = renderHook(() => useChaos());

    await act(async () => {
      await result.current.destroy('sess');
    });
    expect(result.current.warning).toContain('rate limit');

    // After the window the notice clears itself — the action is allowed again, so it shouldn't linger.
    await waitFor(() => expect(result.current.warning).toBeNull(), { timeout: 1000 });
  });

  it('leaves a non-rate-limit warning up (no Retry-After, no auto-clear)', async () => {
    vi.mocked(destroyWorker).mockRejectedValue(new ApiError(409, '[WARN] no workers to destroy'));
    const { result } = renderHook(() => useChaos());

    await act(async () => {
      await result.current.destroy('sess');
    });
    expect(result.current.warning).toContain('no workers');

    // Wait past a plausible window; a 409 carries no Retry-After, so the warning must stay.
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(result.current.warning).toContain('no workers');
  });
});

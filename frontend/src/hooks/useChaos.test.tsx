import { act, renderHook } from '@testing-library/react';
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

  it('counts a rate-limit warning down and clears it once the Retry-After window passes', async () => {
    vi.useFakeTimers();
    try {
      vi.mocked(destroyWorker).mockRejectedValue(new ApiError(429, '[WARN] rate limit: 1 / 3s', 3));
      const { result } = renderHook(() => useChaos());

      await act(async () => {
        await result.current.destroy('sess');
      });
      expect(result.current.warning).toContain('rate limit');
      expect(result.current.warningSecondsLeft).toBe(3);

      // The window ticks down a second at a time.
      act(() => vi.advanceTimersByTime(1000));
      expect(result.current.warningSecondsLeft).toBe(2);

      // At zero the notice clears itself — the action is allowed again, so it shouldn't linger.
      act(() => vi.advanceTimersByTime(2000));
      expect(result.current.warning).toBeNull();
      expect(result.current.warningSecondsLeft).toBeNull();
    } finally {
      vi.useRealTimers();
    }
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

import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError, submitJobs } from '../lib/api';
import { useSubmitJobs } from './useSubmitJobs';

// Keep the real ApiError (so `instanceof` checks in the hook hold) and stub only the network call.
vi.mock('../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../lib/api')>('../lib/api');
  return { ...actual, submitJobs: vi.fn() };
});

const body = { session_id: 'sess', count: 10, type: 'email', complexity: 3 };

afterEach(() => {
  vi.clearAllMocks();
});

describe('useSubmitJobs', () => {
  it('reports the accepted count on a successful submit', async () => {
    vi.mocked(submitJobs).mockResolvedValue({ batch_id: 'batch-1', accepted: 10 });
    const { result } = renderHook(() => useSubmitJobs());

    await act(async () => {
      await result.current.submit(body);
    });
    expect(result.current.accepted).toBe(10);
    expect(result.current.error).toBeNull();
  });

  it('counts a rate-limit error down and clears it once the Retry-After window passes', async () => {
    vi.useFakeTimers();
    try {
      vi.mocked(submitJobs).mockRejectedValue(new ApiError(429, '[WARN] rate limit: 1 / 3s', 3));
      const { result } = renderHook(() => useSubmitJobs());

      await act(async () => {
        await result.current.submit(body);
      });
      expect(result.current.error).toContain('rate limit');
      expect(result.current.errorSecondsLeft).toBe(3);

      // The window ticks down a second at a time.
      act(() => vi.advanceTimersByTime(1000));
      expect(result.current.errorSecondsLeft).toBe(2);

      // At zero the notice clears itself — the submit is allowed again, so it shouldn't linger.
      act(() => vi.advanceTimersByTime(2000));
      expect(result.current.error).toBeNull();
      expect(result.current.errorSecondsLeft).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('leaves a non-rate-limit error up (no Retry-After, no auto-clear)', async () => {
    vi.mocked(submitJobs).mockRejectedValue(new ApiError(422, '[ERR] --count exceeds cap (max 100)'));
    const { result } = renderHook(() => useSubmitJobs());

    await act(async () => {
      await result.current.submit(body);
    });
    expect(result.current.error).toContain('exceeds cap');

    // Wait past a plausible window; a 422 carries no Retry-After, so the error must stay.
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(result.current.error).toContain('exceeds cap');
  });
});

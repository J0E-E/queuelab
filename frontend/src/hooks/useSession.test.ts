import { StrictMode } from 'react';

import { act, renderHook, waitFor } from '@testing-library/react';

import * as api from '../lib/api';
import { useSession } from './useSession';

const IDENTITY: api.GuestIdentity = {
  session_id: 'session-1',
  guest_handle: 'guest-1',
  color: '#00ff88',
};

describe('useSession', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('returns the minted identity once the call resolves', async () => {
    vi.spyOn(api, 'createSession').mockResolvedValue(IDENTITY);
    const { result } = renderHook(() => useSession());
    expect(result.current).toBeNull();
    await waitFor(() => expect(result.current).toEqual(IDENTITY));
  });

  it('mints only once under StrictMode double-mount (avoids the rate-limit 429)', async () => {
    const createSession = vi.spyOn(api, 'createSession').mockResolvedValue(IDENTITY);
    const { result } = renderHook(() => useSession(), { wrapper: StrictMode });
    await waitFor(() => expect(result.current).toEqual(IDENTITY));
    expect(createSession).toHaveBeenCalledTimes(1);
  });

  it('retries a failed mint until it succeeds (the cold-start race)', async () => {
    vi.useFakeTimers();
    const createSession = vi
      .spyOn(api, 'createSession')
      .mockRejectedValueOnce(new Error('api not up yet'))
      .mockResolvedValueOnce(IDENTITY);

    const { result } = renderHook(() => useSession());

    // First attempt rejects; the dashboard stays "connecting…" (identity null), not stuck forever.
    await vi.waitFor(() => expect(createSession).toHaveBeenCalledTimes(1));
    expect(result.current).toBeNull();

    // Advancing past the 1s backoff fires the retry, which succeeds.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    await vi.waitFor(() => expect(result.current).toEqual(IDENTITY));
    expect(createSession).toHaveBeenCalledTimes(2);
  });
});

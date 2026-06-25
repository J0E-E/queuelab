import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useExpiringNotice } from './useExpiringNotice';

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('useExpiringNotice', () => {
  it('shows a sticky notice that does not count down or clear on its own', () => {
    const { result } = renderHook(() => useExpiringNotice());

    act(() => result.current.show('[WARN] no workers to destroy'));
    expect(result.current.notice).toBe('[WARN] no workers to destroy');
    expect(result.current.secondsLeft).toBeNull();

    // Well past any plausible window — a sticky notice must stay.
    act(() => vi.advanceTimersByTime(60_000));
    expect(result.current.notice).toBe('[WARN] no workers to destroy');
  });

  it('counts the window down a second at a time, then clears itself at zero', () => {
    const { result } = renderHook(() => useExpiringNotice());

    act(() => result.current.showWithCountdown('[WARN] rate limit', 3));
    expect(result.current.secondsLeft).toBe(3);

    act(() => vi.advanceTimersByTime(1000));
    expect(result.current.secondsLeft).toBe(2);

    act(() => vi.advanceTimersByTime(1000));
    expect(result.current.secondsLeft).toBe(1);

    act(() => vi.advanceTimersByTime(1000));
    expect(result.current.notice).toBeNull();
    expect(result.current.secondsLeft).toBeNull();
  });

  it('clears immediately on clear()', () => {
    const { result } = renderHook(() => useExpiringNotice());

    act(() => result.current.showWithCountdown('[WARN] rate limit', 5));
    act(() => result.current.clear());
    expect(result.current.notice).toBeNull();
    expect(result.current.secondsLeft).toBeNull();
  });

  it('a new countdown replaces a running one rather than stacking timers', () => {
    const { result } = renderHook(() => useExpiringNotice());

    act(() => result.current.showWithCountdown('first', 3));
    act(() => vi.advanceTimersByTime(1000));
    expect(result.current.secondsLeft).toBe(2);

    act(() => result.current.showWithCountdown('second', 5));
    expect(result.current.notice).toBe('second');
    expect(result.current.secondsLeft).toBe(5);

    // Only the second timer is live: one tick takes it to 4 (the first timer was cancelled).
    act(() => vi.advanceTimersByTime(1000));
    expect(result.current.secondsLeft).toBe(4);
  });
});

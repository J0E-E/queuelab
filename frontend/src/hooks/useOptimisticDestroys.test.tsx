import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { useOptimisticDestroys } from './useOptimisticDestroys';

describe('useOptimisticDestroys', () => {
  it('marks a worker dead at once and clears it once it leaves the live registry', () => {
    const { result, rerender } = renderHook(({ ids }) => useOptimisticDestroys(ids), {
      initialProps: { ids: ['worker-1', 'worker-2'] },
    });
    expect(result.current.destroyedIds.size).toBe(0);

    act(() => result.current.markDestroyed('worker-1'));
    expect(result.current.destroyedIds.has('worker-1')).toBe(true);

    // The worker is still registered (the kill isn't reaped yet), so the mark survives.
    rerender({ ids: ['worker-1', 'worker-2'] });
    expect(result.current.destroyedIds.has('worker-1')).toBe(true);

    // The autoscaler replaced it — worker-1 drops out, a fresh worker-3 joins — so the mark clears.
    rerender({ ids: ['worker-2', 'worker-3'] });
    expect(result.current.destroyedIds.has('worker-1')).toBe(false);
  });

  it('ignores a duplicate mark', () => {
    const { result } = renderHook(() => useOptimisticDestroys(['worker-1']));
    act(() => result.current.markDestroyed('worker-1'));
    act(() => result.current.markDestroyed('worker-1'));
    expect(result.current.destroyedIds.size).toBe(1);
  });
});

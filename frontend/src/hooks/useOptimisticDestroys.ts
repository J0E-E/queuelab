import { useCallback, useEffect, useState } from 'react';

/**
 * Track workers the user just clicked destroy on, so the grid can mark them dead *immediately* —
 * the instant the killed worker is identified, rather than ~one heartbeat later when the backend's
 * staleness check notices.
 *
 * A marked id clears on its own once the worker drops out of the live registry (the autoscaler
 * replaced it), so the dead cell is cleaned up by real backend state, never a timer. A destroy that
 * turned out to be a no-op (the worker was already gone) clears on the same signal, since a worker
 * that isn't in the live set can't stay marked.
 *
 * `liveWorkerIds` is the ids the backend currently reports (`state.workers`).
 */
export function useOptimisticDestroys(liveWorkerIds: string[]): {
  destroyedIds: Set<string>;
  markDestroyed: (id: string) => void;
} {
  const [destroyedIds, setDestroyedIds] = useState<Set<string>>(new Set());
  // A stable key so the prune effect runs only when the set of live workers actually changes.
  const liveKey = liveWorkerIds.join(',');

  useEffect(() => {
    const live = new Set(liveKey ? liveKey.split(',') : []);
    setDestroyedIds((previous) => {
      const next = new Set([...previous].filter((id) => live.has(id)));
      return next.size === previous.size ? previous : next;
    });
  }, [liveKey]);

  const markDestroyed = useCallback((id: string) => {
    setDestroyedIds((previous) => {
      if (previous.has(id)) return previous;
      const next = new Set(previous);
      next.add(id);
      return next;
    });
  }, []);

  return { destroyedIds, markDestroyed };
}

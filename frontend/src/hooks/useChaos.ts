import { useEffect, useRef, useState } from 'react';

import { ApiError, destroyWorker, injectFailures } from '../lib/api';

export interface ChaosState {
  /** The last successful chaos action as an `[OK]` line, or null. */
  success: string | null;
  /** The last rejected chaos action as a `[WARN]`/`[ERR]` line, or null. */
  warning: string | null;
}

export interface UseChaos extends ChaosState {
  /** Destroy a worker; resolves to the worker id that was targeted, or null if the call failed. */
  destroy: (sessionId: string, workerId?: string) => Promise<string | null>;
  inject: (sessionId: string, bias: number) => Promise<void>;
}

/**
 * Run a chaos action and surface its outcome as a system-voice line.
 *
 * The chaos endpoints reject with a system-voice `detail` — a `409 [WARN] no workers to destroy`
 * when the fleet is empty, a `429` when rate-limited — so without surfacing it a click looks like it
 * did nothing. Success and rejection are kept in separate slots so a rate-limit `[WARN]` never wipes
 * the last `[OK]` (or vice versa): each line updates on its own, and both can show at once.
 */
export function useChaos(): UseChaos {
  const [state, setState] = useState<ChaosState>({ success: null, warning: null });
  // Pending timer that clears a rate-limit warning once its window passes. Held in a ref so a new
  // warning can cancel the previous timer, and so it can be cleared on unmount.
  const clearWarningTimer = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => () => clearTimeout(clearWarningTimer.current), []);

  async function run(action: () => Promise<string>): Promise<void> {
    try {
      const success = await action();
      setState((previous) => ({ ...previous, success }));
    } catch (error) {
      const warning =
        error instanceof ApiError ? error.message : '[ERR] could not reach the server';
      setState((previous) => ({ ...previous, warning }));
      // A rate-limit (429) notice self-clears once its `Retry-After` window passes — by then the
      // action is allowed again, so the stale warning shouldn't linger. Only this exact warning is
      // cleared, so a newer message that replaced it in the meantime is left untouched.
      clearTimeout(clearWarningTimer.current);
      if (error instanceof ApiError && error.status === 429 && error.retryAfterSeconds) {
        clearWarningTimer.current = setTimeout(() => {
          setState((previous) =>
            previous.warning === warning ? { ...previous, warning: null } : previous,
          );
        }, error.retryAfterSeconds * 1000);
      }
    }
  }

  return {
    ...state,
    destroy: async (sessionId, workerId) => {
      // Capture the targeted id so the caller can mark that worker dead in the grid at once; stays
      // null when the call fails (the catch in `run` sets the warning instead).
      let destroyedId: string | null = null;
      await run(async () => {
        const { worker_id } = await destroyWorker(sessionId, workerId);
        destroyedId = worker_id;
        return `[OK] destroyed ${worker_id}`;
      });
      return destroyedId;
    },
    inject: (sessionId, bias) =>
      run(async () => {
        const { bias: applied, ttl_seconds } = await injectFailures(sessionId, bias);
        return `[OK] failure bias ${applied} for ${ttl_seconds}s`;
      }),
  };
}

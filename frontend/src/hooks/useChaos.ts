import { useState } from 'react';

import { ApiError, destroyWorker, injectFailures } from '../lib/api';

export interface ChaosState {
  /** The last successful chaos action as an `[OK]` line, or null. */
  success: string | null;
  /** The last rejected chaos action as a `[WARN]`/`[ERR]` line, or null. */
  warning: string | null;
}

export interface UseChaos extends ChaosState {
  destroy: (sessionId: string, workerId?: string) => Promise<void>;
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

  async function run(action: () => Promise<string>): Promise<void> {
    try {
      const success = await action();
      setState((previous) => ({ ...previous, success }));
    } catch (error) {
      const warning =
        error instanceof ApiError ? error.message : '[ERR] could not reach the server';
      setState((previous) => ({ ...previous, warning }));
    }
  }

  return {
    ...state,
    destroy: (sessionId, workerId) =>
      run(async () => {
        const { worker_id } = await destroyWorker(sessionId, workerId);
        return `[OK] destroyed ${worker_id}`;
      }),
    inject: (sessionId, bias) =>
      run(async () => {
        const { bias: applied, ttl_seconds } = await injectFailures(sessionId, bias);
        return `[OK] failure bias ${applied} for ${ttl_seconds}s`;
      }),
  };
}

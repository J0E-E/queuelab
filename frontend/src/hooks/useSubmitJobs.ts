import { useState } from 'react';

import { ApiError, submitJobs, type SubmitJobsRequest } from '../lib/api';
import { useExpiringNotice } from './useExpiringNotice';

export interface SubmitState {
  isSubmitting: boolean;
  /** The system-voice `[ERR]` / `[WARN]` message from the last rejected submit, or null. */
  error: string | null;
  /** Seconds left on a rate-limit error while it counts down, or null. */
  errorSecondsLeft: number | null;
  /** How many jobs the last successful submit accepted, or null. */
  accepted: number | null;
}

export interface UseSubmitJobs extends SubmitState {
  submit: (body: SubmitJobsRequest) => Promise<void>;
}

/**
 * Submit a batch and track the in-flight / error / accepted state for the form.
 *
 * A `422`/`429`/`409` carries a system-voice `detail` (the validation/rate-limit/capacity message);
 * it is surfaced verbatim as `error` so the form renders it inline beneath the offending flag. A
 * rate-limit (429) error counts its `Retry-After` window down and clears itself at zero — by then
 * the submit is allowed again, so the stale error shouldn't linger.
 */
export function useSubmitJobs(): UseSubmitJobs {
  const [state, setState] = useState<{ isSubmitting: boolean; accepted: number | null }>({
    isSubmitting: false,
    accepted: null,
  });
  const error = useExpiringNotice();

  async function submit(body: SubmitJobsRequest): Promise<void> {
    error.clear();
    setState({ isSubmitting: true, accepted: null });
    try {
      const response = await submitJobs(body);
      setState({ isSubmitting: false, accepted: response.accepted });
    } catch (caught) {
      setState({ isSubmitting: false, accepted: null });
      const message =
        caught instanceof ApiError ? caught.message : '[ERR] could not reach the server';
      if (caught instanceof ApiError && caught.status === 429 && caught.retryAfterSeconds) {
        error.showWithCountdown(message, caught.retryAfterSeconds);
      } else {
        error.show(message);
      }
    }
  }

  return {
    isSubmitting: state.isSubmitting,
    error: error.notice,
    errorSecondsLeft: error.secondsLeft,
    accepted: state.accepted,
    submit,
  };
}

import { useState } from 'react';

import { ApiError, submitJobs, type SubmitJobsRequest } from '../lib/api';

export interface SubmitState {
  isSubmitting: boolean;
  /** The system-voice `[ERR]` / `[WARN]` message from the last rejected submit, or null. */
  error: string | null;
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
 * it is surfaced verbatim as `error` so the form renders it inline beneath the offending flag.
 */
export function useSubmitJobs(): UseSubmitJobs {
  const [state, setState] = useState<SubmitState>({
    isSubmitting: false,
    error: null,
    accepted: null,
  });

  async function submit(body: SubmitJobsRequest): Promise<void> {
    setState({ isSubmitting: true, error: null, accepted: null });
    try {
      const response = await submitJobs(body);
      setState({ isSubmitting: false, error: null, accepted: response.accepted });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : '[ERR] could not reach the server';
      setState({ isSubmitting: false, error: message, accepted: null });
    }
  }

  return { ...state, submit };
}

import { type FormEvent, useState } from 'react';

import { BracketButton } from '../components/BracketButton';
import { Pane } from '../components/Pane';
import { PaneTitle } from '../components/PaneTitle';
import { Prompt } from '../components/Prompt';

export interface SubmitFields {
  count: number;
  type: string;
  complexity: number;
  max_retries: number;
  retry_delay_ms: number;
}

export interface SubmitPaneProps {
  guestHandle?: string;
  onSubmit: (fields: SubmitFields) => void;
  isSubmitting: boolean;
  /** System-voice `[ERR]`/`[WARN]` from the last rejected submit, or null. */
  error: string | null;
  /** Seconds left on a rate-limit error while it counts down, or null. */
  errorSecondsLeft?: number | null;
  /** Jobs accepted by the last successful submit, or null. */
  accepted: number | null;
  /** Disabled until a session is minted. */
  isDisabled: boolean;
}

const JOB_TYPES = ['email', 'report', 'image', 'webhook'];

/**
 * The submit pane (Guide §7.3): a job batch rendered as a shell command being built, each control a
 * flag. Validation rejections come back system-voiced from the API and render inline.
 */
export function SubmitPane({
  guestHandle,
  onSubmit,
  isSubmitting,
  error,
  errorSecondsLeft = null,
  accepted,
  isDisabled,
}: SubmitPaneProps) {
  const [count, setCount] = useState(10);
  const [type, setType] = useState('email');
  const [complexity, setComplexity] = useState(3);
  const [maxRetries, setMaxRetries] = useState(3);
  const [retryDelayMs, setRetryDelayMs] = useState(2000);

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    onSubmit({
      count,
      type,
      complexity,
      max_retries: maxRetries,
      retry_delay_ms: retryDelayMs,
    });
  }

  return (
    <Pane id="submit-pane">
      <PaneTitle id="submit-pane-title" title="submit jobs" />
      <form id="submit-form" onSubmit={handleSubmit} className="space-y-2 pt-3">
        <div id="submit-prompt-line">
          <Prompt id="submit-prompt" user={guestHandle} /> submit \
        </div>

        <div id="submit-field-count" className="flex items-center gap-2">
          <label htmlFor="submit-count" className="text-fg-dim">
            --count
          </label>
          <input
            id="submit-count"
            type="number"
            min={1}
            value={count}
            onChange={(event) => setCount(Number(event.target.value))}
            className="w-20 border border-solid border-muted bg-bg px-2 text-fg"
          />
        </div>

        <div id="submit-field-type" className="flex items-center gap-2">
          <label htmlFor="submit-type" className="text-fg-dim">
            --type
          </label>
          <select
            id="submit-type"
            value={type}
            onChange={(event) => setType(event.target.value)}
            className="border border-solid border-muted bg-bg px-2 text-fg"
          >
            {JOB_TYPES.map((jobType) => (
              <option key={jobType} value={jobType}>
                {jobType}
              </option>
            ))}
          </select>
        </div>

        <div id="submit-field-complexity" className="flex items-center gap-2">
          <label htmlFor="submit-complexity" className="text-fg-dim">
            --complexity
          </label>
          <input
            id="submit-complexity"
            type="number"
            min={1}
            max={5}
            value={complexity}
            onChange={(event) => setComplexity(Number(event.target.value))}
            className="w-20 border border-solid border-muted bg-bg px-2 text-fg"
          />
        </div>

        <div id="submit-field-max-retries" className="flex items-center gap-2">
          <label htmlFor="submit-max-retries" className="text-fg-dim">
            --max-retries
          </label>
          <input
            id="submit-max-retries"
            type="number"
            min={0}
            max={10}
            value={maxRetries}
            onChange={(event) => setMaxRetries(Number(event.target.value))}
            className="w-20 border border-solid border-muted bg-bg px-2 text-fg"
          />
        </div>

        <div id="submit-field-retry-delay" className="flex items-center gap-2">
          <label htmlFor="submit-retry-delay" className="text-fg-dim">
            --retry-delay-ms
          </label>
          <input
            id="submit-retry-delay"
            type="number"
            min={0}
            max={60000}
            value={retryDelayMs}
            onChange={(event) => setRetryDelayMs(Number(event.target.value))}
            className="w-28 border border-solid border-muted bg-bg px-2 text-fg"
          />
        </div>

        <div id="submit-actions" className="pt-2">
          <BracketButton id="submit-execute" type="submit" isDisabled={isDisabled || isSubmitting}>
            execute
          </BracketButton>
        </div>

        {/* Reserve the submit-outcome space up front (min height for one line) so an `[ERR]`/`[OK]`
            appearing or clearing — including a rate-limit notice that self-clears — never shifts the
            layout below it. `aria-live` announces each outcome. */}
        <div id="submit-status" aria-live="polite" className="min-h-6 pt-1">
          {error ? (
            <p id="submit-error" className="text-error">
              {error}
              {errorSecondsLeft !== null ? (
                // aria-hidden so the per-second tick isn't re-announced by the live region above.
                <span id="submit-error-countdown" aria-hidden="true" className="text-fg-dim">
                  {' '}
                  · retry in {errorSecondsLeft}s
                </span>
              ) : null}
            </p>
          ) : null}
          {accepted !== null ? (
            <p id="submit-result" className="text-ok">
              [OK] {accepted} jobs queued
            </p>
          ) : null}
        </div>
      </form>
    </Pane>
  );
}

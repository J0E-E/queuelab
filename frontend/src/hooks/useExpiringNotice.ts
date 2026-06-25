import { useEffect, useRef, useState } from 'react';

export interface ExpiringNotice {
  /** The current notice text, or null when nothing is showing. */
  notice: string | null;
  /** Whole seconds left on a counting-down notice; null when the notice isn't counting down. */
  secondsLeft: number | null;
}

export interface UseExpiringNotice extends ExpiringNotice {
  /** Show a sticky notice that stays until it's replaced or cleared (no countdown). */
  show: (notice: string) => void;
  /** Show a notice that counts the seconds down and clears itself when the window passes. */
  showWithCountdown: (notice: string, seconds: number) => void;
  /** Clear the notice now. */
  clear: () => void;
}

/**
 * A single system-voice notice that can either sit until replaced or count its remaining seconds
 * down to zero and then clear itself. Used for rate-limit warnings, where the window the backend
 * gives back (`Retry-After`) is shown ticking down so the user sees exactly when they may retry.
 *
 * The countdown ticks once a second via an interval held in a ref, so a new notice (or unmount)
 * cancels the previous one rather than leaving a stale timer running.
 */
export function useExpiringNotice(): UseExpiringNotice {
  const [notice, setNotice] = useState<string | null>(null);
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);
  const countdownTimer = useRef<ReturnType<typeof setInterval>>();

  function stopCountdown() {
    clearInterval(countdownTimer.current);
    countdownTimer.current = undefined;
  }

  // Cancel any pending tick when the consumer unmounts.
  useEffect(() => stopCountdown, []);

  function show(next: string) {
    stopCountdown();
    setSecondsLeft(null);
    setNotice(next);
  }

  function clear() {
    stopCountdown();
    setSecondsLeft(null);
    setNotice(null);
  }

  function showWithCountdown(next: string, seconds: number) {
    stopCountdown();
    setNotice(next);
    // Round up so even a sub-second window still shows "1s" for a beat before clearing.
    let remaining = Math.max(1, Math.ceil(seconds));
    setSecondsLeft(remaining);
    countdownTimer.current = setInterval(() => {
      remaining -= 1;
      if (remaining <= 0) {
        clear();
      } else {
        setSecondsLeft(remaining);
      }
    }, 1000);
  }

  return { notice, secondsLeft, show, showWithCountdown, clear };
}

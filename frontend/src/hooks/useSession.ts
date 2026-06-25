import { useEffect, useState } from 'react';

import { createSession, type GuestIdentity } from '../lib/api';

// Mirror the live WebSocket's backoff (lib/ws.ts): retry the mint starting at 1s, doubling up to
// a 10s cap, so a cold-start race heals itself instead of stalling the dashboard forever.
const BASE_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 10_000;

// Single-flight the mint across concurrent callers. React StrictMode (dev) mounts the effect
// twice, firing two `POST /api/session` within milliseconds; the second would be rejected by the
// per-IP rate limiter (1 session / 5s) and leave the dashboard stuck on "connecting…". Sharing one
// in-flight request collapses the double-mount into a single POST. It is cleared once settled, so a
// later attempt (after a failure, or a genuine remount) still starts a fresh request.
let pendingMint: Promise<GuestIdentity> | null = null;

function mintSession(): Promise<GuestIdentity> {
  if (!pendingMint) {
    const request = createSession();
    pendingMint = request;
    // Clear on either outcome so the next attempt starts fresh. Handling both settle paths here
    // (rather than `.finally`) keeps this bookkeeping branch from surfacing as an unhandled
    // rejection — the real result/rejection still flows to callers through the returned promise.
    const clear = () => {
      if (pendingMint === request) pendingMint = null;
    };
    request.then(clear, clear);
  }
  return pendingMint;
}

/**
 * Mint a guest identity on mount and return it (or `null` until it arrives).
 *
 * `POST /api/session` is the first call the dashboard makes; the returned `session_id` keys every
 * later submit/chaos call and the `guest_handle`/`color` attribute this visitor in the feed.
 *
 * The mint is single-flighted (so StrictMode's double-mount sends one POST, not two) and self-heals
 * with capped exponential backoff (so a cold `docker compose up`, where the api is still migrating
 * when the page loads, recovers instead of stalling on "connecting…" forever — the live WebSocket
 * already reconnects this way, so the session shouldn't be the odd one out).
 */
export function useSession(): GuestIdentity | null {
  const [identity, setIdentity] = useState<GuestIdentity | null>(null);

  useEffect(() => {
    let isCancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let backoffMs = BASE_BACKOFF_MS;

    function attempt(): void {
      mintSession()
        .then((value) => {
          if (!isCancelled) setIdentity(value);
        })
        .catch(() => {
          // The api may not be accepting yet (cold start / redeploy). Retry until it is.
          if (isCancelled) return;
          retryTimer = setTimeout(attempt, backoffMs);
          backoffMs = Math.min(backoffMs * 2, MAX_BACKOFF_MS);
        });
    }

    attempt();

    return () => {
      isCancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, []);

  return identity;
}

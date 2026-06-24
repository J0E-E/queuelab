import { useEffect, useState } from 'react';

import { createSession, type GuestIdentity } from '../lib/api';

/**
 * Mint a guest identity once on mount and return it (or `null` until it arrives).
 *
 * `POST /api/session` is the first call the dashboard makes; the returned `session_id` keys every
 * later submit/chaos call and the `guest_handle`/`color` attribute this visitor in the feed.
 */
export function useSession(): GuestIdentity | null {
  const [identity, setIdentity] = useState<GuestIdentity | null>(null);

  useEffect(() => {
    let isCancelled = false;
    createSession()
      .then((value) => {
        if (!isCancelled) setIdentity(value);
      })
      .catch(() => {
        // A failed mint leaves the dashboard read-only until the next reload; the live stream
        // (which needs no session) still connects.
      });
    return () => {
      isCancelled = true;
    };
  }, []);

  return identity;
}

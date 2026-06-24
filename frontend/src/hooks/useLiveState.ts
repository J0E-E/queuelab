import { useEffect, useReducer } from 'react';

import type { Frame } from './liveState';
import { initialLiveState, liveStateReducer } from './liveState';
import { createWsClient } from '../lib/ws';

/**
 * Subscribe to the live dashboard stream and return the reduced `LiveState`.
 *
 * Opens one self-healing WebSocket for the component's lifetime, folding every frame through the
 * pure reducer; connection state drives the `● live` / `offline` chip. The socket (and any pending
 * reconnect) is torn down on unmount.
 */
export function useLiveState() {
  const [state, dispatch] = useReducer(liveStateReducer, initialLiveState);

  useEffect(() => {
    const client = createWsClient({
      onFrame: (frame) => dispatch({ kind: 'frame', frame: frame as Frame }),
      onOpen: () => dispatch({ kind: 'connected' }),
      onClose: () => dispatch({ kind: 'disconnected' }),
    });
    return () => client.close();
  }, []);

  return state;
}

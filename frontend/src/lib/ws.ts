/**
 * A small WebSocket client for the live dashboard stream (`WS /ws`).
 *
 * Connects, parses each JSON frame, and auto-reconnects with capped exponential backoff so a
 * transient drop (a redeploy, a blip) heals itself without a page reload. The backend sends
 * `snapshot` / `delta` / `metrics` / `activity` frames; this layer is frame-agnostic — it hands the
 * parsed object to `onFrame` and the reducer interprets it.
 */

export interface WsClientOptions {
  /** Called with each parsed JSON frame. */
  onFrame: (frame: unknown) => void;
  /** Called when a connection opens (live). */
  onOpen?: () => void;
  /** Called when a connection closes (offline; a reconnect is scheduled). */
  onClose?: () => void;
  /** Override the socket URL (defaults to same-origin `/ws`). */
  url?: string;
  /** First reconnect delay in ms (doubles each attempt up to `maxBackoffMs`). */
  baseBackoffMs?: number;
  maxBackoffMs?: number;
}

export interface WsClient {
  close: () => void;
}

function defaultUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/ws`;
}

/**
 * Open a self-healing connection to the live stream. Returns a handle whose `close()` stops both
 * the socket and any pending reconnect (call it from a React effect cleanup).
 */
export function createWsClient(options: WsClientOptions): WsClient {
  const url = options.url ?? defaultUrl();
  const baseBackoffMs = options.baseBackoffMs ?? 1000;
  const maxBackoffMs = options.maxBackoffMs ?? 10_000;

  let socket: WebSocket | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let backoffMs = baseBackoffMs;
  let isClosed = false;

  function connect(): void {
    socket = new WebSocket(url);

    socket.onopen = () => {
      backoffMs = baseBackoffMs; // a clean connect resets the backoff
      options.onOpen?.();
    };

    socket.onmessage = (message) => {
      try {
        options.onFrame(JSON.parse(message.data as string));
      } catch {
        // A malformed frame is skipped — one bad message never tears down the stream.
      }
    };

    socket.onclose = () => {
      options.onClose?.();
      if (!isClosed) scheduleReconnect();
    };

    socket.onerror = () => {
      // Let onclose drive the reconnect; closing here avoids a double-schedule.
      socket?.close();
    };
  }

  function scheduleReconnect(): void {
    reconnectTimer = setTimeout(connect, backoffMs);
    backoffMs = Math.min(backoffMs * 2, maxBackoffMs);
  }

  connect();

  return {
    close() {
      isClosed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
    },
  };
}

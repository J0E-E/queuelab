/**
 * Typed REST client for the QueueLab backend (Epic 5–12 endpoints).
 *
 * All calls are same-origin relative (`/api/...`) — the Vite dev proxy points them at the backend
 * in development, and nginx serves them same-origin in production (Epic 19). A non-2xx response is
 * surfaced as an `ApiError` carrying the backend's system-voice `detail` (`[ERR] ...`) so the UI can
 * render it inline.
 */

export interface GuestIdentity {
  session_id: string;
  guest_handle: string;
  color: string;
}

export interface SubmitJobsRequest {
  session_id: string;
  count: number;
  type: string;
  complexity: number;
  max_retries?: number;
  retry_delay_ms?: number;
}

export interface BatchSubmitResponse {
  batch_id: string;
  accepted: number;
}

export interface AutoscalerConfig {
  min_workers: number;
  max_workers: number;
  scale_up_threshold: number;
  scale_down_threshold: number;
  idle_timeout_seconds: number;
}

export interface ArchitectureSection {
  key: string;
  title: string;
  body: string;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    headers: { 'content-type': 'application/json', ...options.headers },
    ...options,
  });
  if (!response.ok) {
    throw new ApiError(response.status, await errorDetail(response));
  }
  return (await response.json()) as T;
}

async function errorDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string };
    if (body.detail) return body.detail;
  } catch {
    // Non-JSON error body — fall through to a generic message.
  }
  return `[ERR] request failed (${response.status})`;
}

export function createSession(): Promise<GuestIdentity> {
  return request<GuestIdentity>('/api/session', { method: 'POST' });
}

export function submitJobs(body: SubmitJobsRequest): Promise<BatchSubmitResponse> {
  return request<BatchSubmitResponse>('/api/jobs', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function destroyWorker(
  sessionId: string,
  workerId?: string,
): Promise<{ worker_id: string }> {
  return request<{ worker_id: string }>('/api/chaos/destroy-worker', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, worker_id: workerId }),
  });
}

export function injectFailures(
  sessionId: string,
  bias: number,
): Promise<{ bias: number; ttl_seconds: number }> {
  return request<{ bias: number; ttl_seconds: number }>('/api/chaos/inject-failures', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, bias }),
  });
}

export function getConfig(): Promise<AutoscalerConfig> {
  return request<AutoscalerConfig>('/api/config');
}

export function getArchitecture(): Promise<{ sections: ArchitectureSection[] }> {
  return request<{ sections: ArchitectureSection[] }>('/api/architecture');
}

export function updateConfig(patch: Partial<AutoscalerConfig>): Promise<AutoscalerConfig> {
  return request<AutoscalerConfig>('/api/config', {
    method: 'PUT',
    body: JSON.stringify(patch),
  });
}

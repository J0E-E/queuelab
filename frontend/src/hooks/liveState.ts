/**
 * The live-dashboard state and its pure reducer.
 *
 * The backend streams four frame types over `WS /ws` — `snapshot` (once on connect), `delta` (per
 * job state change), `metrics` (throttled vitals), `activity` (one readable line per event). This
 * reducer folds them into a single immutable `LiveState` the panes render from. It is pure and
 * side-effect-free, so the whole reduction is unit-tested with plain objects; the WS plumbing lives
 * in `useLiveState`.
 */
import type { WorkerStatus } from '../components/WorkerCell';

export interface QueueCounts {
  queued: number;
  running: number;
  completed: number;
  failed: number;
  retrying: number;
  /** Cumulative subset of `completed`: jobs that succeeded only after ≥1 failed attempt. */
  recovered: number;
}

export interface LiveJob {
  job_id: string;
  state: string;
  attempts: number;
  worker_id: string | null;
  type: string | null;
  complexity: number | null;
}

/** One registered worker's liveness, as the metrics frame reports it — the grid renders from these. */
export interface WorkerHealth {
  id: string;
  /** `false` once the heartbeat is stale; the grid paints such a worker as dying (✗). */
  healthy: boolean;
  /** Whether the worker is running a job (vs idle). */
  busy: boolean;
}

/**
 * One activity-feed entry — the structured shape the backend now sends (Epic 17b), so the frontend
 * can color each piece. `handle`/`color` are the acting guest (or the `autoscaler` system actor),
 * resolved server-side; `null` when unattributed. `state` is the job-state word (drives its hue and
 * the failures-only filter); `is_terminal` marks a dead job — retries exhausted. `line` is the flat
 * readable sentence kept for screen readers and as a back-compat fallback.
 */
export interface FeedEntry {
  time: string;
  handle: string | null;
  color: string | null;
  action: string;
  state: string | null;
  attempts: number | null;
  is_terminal: boolean;
  line: string;
}

export interface LiveState {
  isConnected: boolean;
  counts: QueueCounts;
  queueDepth: number;
  workerCount: number;
  /** Registered workers whose heartbeat is stale — rendered as dying (✗) cells in the grid. */
  unhealthyWorkerCount: number;
  /** Per-worker liveness for the grid, sorted by id; each cell is rendered from one of these. */
  workers: WorkerHealth[];
  /** Active jobs only (terminal ones are pruned), keyed by job id. */
  jobs: Record<string, LiveJob>;
  /** Recent activity entries, newest last, capped at FEED_CAP. */
  feed: FeedEntry[];
  /** Recent queue-depth samples for the sparkline, capped at DEPTH_CAP. */
  depthHistory: number[];
}

export type Frame =
  | { type: 'snapshot'; counts: QueueCounts; jobs: LiveJob[]; activity: FeedEntry[] }
  | { type: 'delta'; event: LiveJob }
  | {
      type: 'metrics';
      counts: QueueCounts;
      queue_depth: number;
      worker_count: number;
      unhealthy_worker_count: number;
      workers: WorkerHealth[];
    }
  | ({ type: 'activity' } & FeedEntry);

export type LiveAction =
  | { kind: 'connected' }
  | { kind: 'disconnected' }
  | { kind: 'frame'; frame: Frame };

export const FEED_CAP = 50;
export const DEPTH_CAP = 40;
const TERMINAL_STATES = new Set(['completed', 'failed']);

export const EMPTY_COUNTS: QueueCounts = {
  queued: 0,
  running: 0,
  completed: 0,
  failed: 0,
  retrying: 0,
  recovered: 0,
};

export const initialLiveState: LiveState = {
  isConnected: false,
  counts: EMPTY_COUNTS,
  queueDepth: 0,
  workerCount: 0,
  unhealthyWorkerCount: 0,
  workers: [],
  jobs: {},
  feed: [],
  depthHistory: [],
};

function capEnd<T>(items: T[], cap: number): T[] {
  return items.length > cap ? items.slice(items.length - cap) : items;
}

function jobsById(jobs: LiveJob[]): Record<string, LiveJob> {
  return Object.fromEntries(jobs.map((job) => [job.job_id, job]));
}

export function liveStateReducer(state: LiveState, action: LiveAction): LiveState {
  switch (action.kind) {
    case 'connected':
      return { ...state, isConnected: true };
    case 'disconnected':
      return { ...state, isConnected: false };
    case 'frame':
      return reduceFrame(state, action.frame);
  }
}

function reduceFrame(state: LiveState, frame: Frame): LiveState {
  switch (frame.type) {
    case 'snapshot':
      return {
        ...state,
        counts: frame.counts,
        jobs: jobsById(frame.jobs),
        feed: capEnd(frame.activity, FEED_CAP),
      };
    case 'delta': {
      const job = frame.event;
      const jobs = { ...state.jobs };
      if (TERMINAL_STATES.has(job.state)) {
        // A finished job leaves the hot record; drop it from the active map (it lives on in
        // the cumulative counts and the durable Postgres row).
        delete jobs[job.job_id];
      } else {
        jobs[job.job_id] = { ...jobs[job.job_id], ...job };
      }
      return { ...state, jobs };
    }
    case 'metrics':
      return {
        ...state,
        counts: frame.counts,
        queueDepth: frame.queue_depth,
        workerCount: frame.worker_count,
        unhealthyWorkerCount: frame.unhealthy_worker_count,
        workers: frame.workers,
        depthHistory: capEnd([...state.depthHistory, frame.queue_depth], DEPTH_CAP),
      };
    case 'activity': {
      const entry: FeedEntry = {
        time: frame.time,
        handle: frame.handle,
        color: frame.color,
        action: frame.action,
        state: frame.state,
        attempts: frame.attempts,
        is_terminal: frame.is_terminal,
        line: frame.line,
      };
      return { ...state, feed: capEnd([...state.feed, entry], FEED_CAP) };
    }
    default:
      // An unrecognized frame type is ignored — the stream is untyped at the boundary.
      return state;
  }
}

export interface WorkerCellModel {
  id: string;
  status: WorkerStatus;
  workerId?: string;
}

/**
 * Derive the worker grid from the live state — one cell per registered worker (`state.workers`),
 * keyed by its id so cells stay stable as the fleet grows and shrinks.
 *
 * A worker reads as `destroyed` (a ✗ cell) when the backend reports it unhealthy (stale heartbeat)
 * **or** when it is in `destroyedIds` — the ids the user just clicked destroy on, marked dead
 * immediately so a kill shows the instant it is identified, before the heartbeat even lapses. The
 * cell then clears on its own once the autoscaler replaces the worker and it drops out of
 * `state.workers`. A `busy` worker is `running`; the rest are `idle`.
 */
export function deriveWorkers(
  state: LiveState,
  destroyedIds: ReadonlySet<string> = new Set(),
): WorkerCellModel[] {
  return state.workers.map((worker) => {
    let status: WorkerStatus;
    if (!worker.healthy || destroyedIds.has(worker.id)) {
      status = 'destroyed';
    } else if (worker.busy) {
      status = 'running';
    } else {
      status = 'idle';
    }
    return { id: `worker-cell-${worker.id}`, status, workerId: worker.id };
  });
}

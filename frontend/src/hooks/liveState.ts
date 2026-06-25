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

export interface LiveState {
  isConnected: boolean;
  counts: QueueCounts;
  queueDepth: number;
  workerCount: number;
  /** Active jobs only (terminal ones are pruned), keyed by job id. */
  jobs: Record<string, LiveJob>;
  /** Recent activity lines, newest last, capped at FEED_CAP. */
  feed: string[];
  /** Recent queue-depth samples for the sparkline, capped at DEPTH_CAP. */
  depthHistory: number[];
}

export type Frame =
  | { type: 'snapshot'; counts: QueueCounts; jobs: LiveJob[]; activity: string[] }
  | { type: 'delta'; event: LiveJob }
  | { type: 'metrics'; counts: QueueCounts; queue_depth: number; worker_count: number }
  | { type: 'activity'; line: string };

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
        depthHistory: capEnd([...state.depthHistory, frame.queue_depth], DEPTH_CAP),
      };
    case 'activity':
      return { ...state, feed: capEnd([...state.feed, frame.line], FEED_CAP) };
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
 * Derive the worker grid from the live state. No per-worker frame exists, so workers running an
 * in-flight job are read from the jobs map (status `running`, with their id) and the remaining
 * `workerCount` cells are shown idle/anonymous. The grid still visibly grows and shrinks as the
 * autoscaler reacts, and a named running worker can be destroyed by clicking its cell.
 */
export function deriveWorkers(state: LiveState): WorkerCellModel[] {
  const runningWorkerIds = [
    ...new Set(
      Object.values(state.jobs)
        .filter((job) => job.state === 'running' && job.worker_id)
        .map((job) => job.worker_id as string),
    ),
  ];
  const total = Math.max(state.workerCount, runningWorkerIds.length);
  return Array.from({ length: total }, (_, index) => {
    const workerId = runningWorkerIds[index];
    return workerId
      ? { id: `worker-cell-${workerId}`, status: 'running' as WorkerStatus, workerId }
      : { id: `worker-cell-idle-${index}`, status: 'idle' as WorkerStatus };
  });
}

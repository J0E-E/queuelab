import {
  DEPTH_CAP,
  deriveWorkers,
  type FeedEntry,
  FEED_CAP,
  initialLiveState,
  liveStateReducer,
  type LiveJob,
  type LiveState,
} from './liveState';

function job(overrides: Partial<LiveJob> = {}): LiveJob {
  return {
    job_id: 'job-1',
    state: 'running',
    attempts: 0,
    worker_id: 'worker-1',
    type: 'email',
    complexity: 3,
    ...overrides,
  };
}

function feedEntry(overrides: Partial<FeedEntry> = {}): FeedEntry {
  return {
    time: '12:00:00',
    handle: null,
    color: null,
    action: 'job-1 queued',
    state: 'queued',
    attempts: null,
    is_terminal: false,
    line: 'job-1 queued',
    ...overrides,
  };
}

describe('liveStateReducer', () => {
  it('tracks connection state', () => {
    const connected = liveStateReducer(initialLiveState, { kind: 'connected' });
    expect(connected.isConnected).toBe(true);
    expect(liveStateReducer(connected, { kind: 'disconnected' }).isConnected).toBe(false);
  });

  it('replaces state from a snapshot frame', () => {
    const seeded = [feedEntry({ line: 'line-1' }), feedEntry({ line: 'line-2' })];
    const next = liveStateReducer(initialLiveState, {
      kind: 'frame',
      frame: {
        type: 'snapshot',
        counts: { queued: 5, running: 2, completed: 10, failed: 1, retrying: 0, recovered: 4 },
        jobs: [job({ job_id: 'job-a' }), job({ job_id: 'job-b' })],
        activity: seeded,
      },
    });
    expect(next.counts.queued).toBe(5);
    expect(Object.keys(next.jobs)).toEqual(['job-a', 'job-b']);
    expect(next.feed).toEqual(seeded);
  });

  it('appends an attributed activity entry, keeping its handle and color', () => {
    const next = liveStateReducer(initialLiveState, {
      kind: 'frame',
      frame: {
        type: 'activity',
        ...feedEntry({
          handle: 'guest-teal',
          color: '#2dd4bf',
          action: 'destroyed worker-3',
          state: null,
          line: 'guest-teal destroyed worker-3',
        }),
      },
    });
    expect(next.feed).toHaveLength(1);
    expect(next.feed[0].handle).toBe('guest-teal');
    expect(next.feed[0].color).toBe('#2dd4bf');
    expect(next.feed[0].action).toBe('destroyed worker-3');
  });

  it('upserts an active job on a delta and prunes it when terminal', () => {
    const withJob = liveStateReducer(initialLiveState, {
      kind: 'frame',
      frame: { type: 'delta', event: job({ job_id: 'job-x', state: 'running' }) },
    });
    expect(withJob.jobs['job-x'].state).toBe('running');

    const completed = liveStateReducer(withJob, {
      kind: 'frame',
      frame: { type: 'delta', event: job({ job_id: 'job-x', state: 'completed' }) },
    });
    expect(completed.jobs['job-x']).toBeUndefined();
  });

  it('updates vitals and appends to the depth history on a metrics frame', () => {
    const next = liveStateReducer(initialLiveState, {
      kind: 'frame',
      frame: {
        type: 'metrics',
        counts: { queued: 3, running: 1, completed: 0, failed: 0, retrying: 0, recovered: 0 },
        queue_depth: 3,
        worker_count: 4,
        unhealthy_worker_count: 1,
        workers: [],
      },
    });
    expect(next.queueDepth).toBe(3);
    expect(next.workerCount).toBe(4);
    expect(next.unhealthyWorkerCount).toBe(1);
    expect(next.depthHistory).toEqual([3]);
  });

  it('caps the feed and the depth history', () => {
    let state: LiveState = initialLiveState;
    for (let index = 0; index < FEED_CAP + 10; index += 1) {
      state = liveStateReducer(state, {
        kind: 'frame',
        frame: { type: 'activity', ...feedEntry({ line: `line-${index}` }) },
      });
    }
    expect(state.feed).toHaveLength(FEED_CAP);
    expect(state.feed[state.feed.length - 1].line).toBe(`line-${FEED_CAP + 9}`);

    for (let index = 0; index < DEPTH_CAP + 10; index += 1) {
      state = liveStateReducer(state, {
        kind: 'frame',
        frame: {
          type: 'metrics',
          counts: initialLiveState.counts,
          queue_depth: index,
          worker_count: 1,
          unhealthy_worker_count: 0,
          workers: [],
        },
      });
    }
    expect(state.depthHistory).toHaveLength(DEPTH_CAP);
  });

  it('ignores an unrecognized frame type', () => {
    const next = liveStateReducer(initialLiveState, {
      kind: 'frame',
      // @ts-expect-error — exercising the untyped-network boundary guard.
      frame: { type: 'bogus' },
    });
    expect(next).toEqual(initialLiveState);
  });
});

describe('deriveWorkers', () => {
  it('renders one cell per worker by status — running (busy), idle, and dying (unhealthy)', () => {
    const state: LiveState = {
      ...initialLiveState,
      workers: [
        { id: 'worker-1', healthy: true, busy: true },
        { id: 'worker-2', healthy: true, busy: false },
        { id: 'worker-3', healthy: false, busy: false },
      ],
    };
    const cells = deriveWorkers(state);
    expect(cells.map((cell) => cell.workerId)).toEqual(['worker-1', 'worker-2', 'worker-3']);
    expect(cells.map((cell) => cell.status)).toEqual(['running', 'idle', 'destroyed']);
  });

  it('marks an optimistically destroyed worker dead at once, even while still healthy', () => {
    const state: LiveState = {
      ...initialLiveState,
      workers: [
        { id: 'worker-1', healthy: true, busy: false },
        { id: 'worker-2', healthy: true, busy: false },
      ],
    };
    // worker-1 was just clicked: it reads as destroyed before its heartbeat has even gone stale.
    const cells = deriveWorkers(state, new Set(['worker-1']));
    expect(cells.find((cell) => cell.workerId === 'worker-1')?.status).toBe('destroyed');
    expect(cells.find((cell) => cell.workerId === 'worker-2')?.status).toBe('idle');
  });
});

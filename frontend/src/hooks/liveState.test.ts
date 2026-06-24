import {
  DEPTH_CAP,
  deriveWorkers,
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

describe('liveStateReducer', () => {
  it('tracks connection state', () => {
    const connected = liveStateReducer(initialLiveState, { kind: 'connected' });
    expect(connected.isConnected).toBe(true);
    expect(liveStateReducer(connected, { kind: 'disconnected' }).isConnected).toBe(false);
  });

  it('replaces state from a snapshot frame', () => {
    const next = liveStateReducer(initialLiveState, {
      kind: 'frame',
      frame: {
        type: 'snapshot',
        counts: { queued: 5, running: 2, completed: 10, failed: 1, retrying: 0 },
        jobs: [job({ job_id: 'job-a' }), job({ job_id: 'job-b' })],
        activity: ['line-1', 'line-2'],
      },
    });
    expect(next.counts.queued).toBe(5);
    expect(Object.keys(next.jobs)).toEqual(['job-a', 'job-b']);
    expect(next.feed).toEqual(['line-1', 'line-2']);
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
        counts: { queued: 3, running: 1, completed: 0, failed: 0, retrying: 0 },
        queue_depth: 3,
        worker_count: 4,
      },
    });
    expect(next.queueDepth).toBe(3);
    expect(next.workerCount).toBe(4);
    expect(next.depthHistory).toEqual([3]);
  });

  it('caps the feed and the depth history', () => {
    let state: LiveState = initialLiveState;
    for (let index = 0; index < FEED_CAP + 10; index += 1) {
      state = liveStateReducer(state, {
        kind: 'frame',
        frame: { type: 'activity', line: `line-${index}` },
      });
    }
    expect(state.feed).toHaveLength(FEED_CAP);
    expect(state.feed[state.feed.length - 1]).toBe(`line-${FEED_CAP + 9}`);

    for (let index = 0; index < DEPTH_CAP + 10; index += 1) {
      state = liveStateReducer(state, {
        kind: 'frame',
        frame: {
          type: 'metrics',
          counts: initialLiveState.counts,
          queue_depth: index,
          worker_count: 1,
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
  it('shows running workers by id and fills the rest as idle cells', () => {
    const state: LiveState = {
      ...initialLiveState,
      workerCount: 3,
      jobs: {
        'job-1': job({ job_id: 'job-1', state: 'running', worker_id: 'worker-1' }),
        'job-2': job({ job_id: 'job-2', state: 'running', worker_id: 'worker-2' }),
        'job-3': job({ job_id: 'job-3', state: 'queued', worker_id: null }),
      },
    };
    const cells = deriveWorkers(state);
    expect(cells).toHaveLength(3);
    expect(cells.filter((cell) => cell.status === 'running').map((cell) => cell.workerId)).toEqual([
      'worker-1',
      'worker-2',
    ]);
    expect(cells.filter((cell) => cell.status === 'idle')).toHaveLength(1);
  });
});

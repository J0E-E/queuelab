import { render } from '@testing-library/react';

// The App is wiring: mock the data hooks so the dashboard renders without a real WebSocket/fetch
// (jsdom has neither). The reducer, panes, and lib are covered by their own tests. The state is an
// inline literal — a vi.mock factory must not reference hoisted imports.
vi.mock('./hooks/useSession', () => ({
  useSession: () => ({ session_id: 's', guest_handle: 'guest-teal', color: '#2dd4bf' }),
}));
vi.mock('./hooks/useLiveState', () => ({
  useLiveState: () => ({
    isConnected: true,
    counts: { queued: 12, running: 3, completed: 0, failed: 0, retrying: 0 },
    queueDepth: 12,
    workerCount: 3,
    jobs: {},
    feed: ['worker-1 started job#1'],
    depthHistory: [4, 8, 12],
  }),
}));
vi.mock('./hooks/useSubmitJobs', () => ({
  useSubmitJobs: () => ({ submit: vi.fn(), isSubmitting: false, error: null, accepted: null }),
}));

import { App } from './App';

describe('App dashboard', () => {
  it('renders the dashboard panes wired to the live state', () => {
    render(<App />);
    expect(document.getElementById('scanlines-overlay')).toBeInTheDocument();
    expect(document.getElementById('app-guest')).toHaveTextContent('guest-teal');
    expect(document.getElementById('metric-queue-depth')).toHaveTextContent('0012');
    expect(document.getElementById('workers-pane')).toBeInTheDocument();
    expect(document.getElementById('submit-form')).toBeInTheDocument();
    expect(document.getElementById('feed-line-0')).toHaveTextContent('worker-1 started job#1');
  });
});

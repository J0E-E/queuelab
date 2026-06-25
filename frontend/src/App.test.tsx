import { fireEvent, render } from '@testing-library/react';

// The dashboard route pulls live data; mock its hooks so App renders without a real WebSocket/fetch
// (jsdom has neither). The reducer, panes, and pages are covered by their own tests.
vi.mock('./hooks/useSession', () => ({
  useSession: () => ({ session_id: 's', guest_handle: 'guest-teal', color: '#2dd4bf' }),
}));
vi.mock('./hooks/useLiveState', () => ({
  useLiveState: () => ({
    isConnected: true,
    counts: { queued: 12, running: 3, completed: 0, failed: 0, retrying: 0, recovered: 0 },
    queueDepth: 12,
    workerCount: 3,
    unhealthyWorkerCount: 0,
    workers: [
      { id: 'worker-1', healthy: true, busy: true },
      { id: 'worker-2', healthy: true, busy: false },
      { id: 'worker-3', healthy: false, busy: false },
    ],
    jobs: {},
    feed: [],
    depthHistory: [4, 8, 12],
  }),
}));
vi.mock('./hooks/useSubmitJobs', () => ({
  useSubmitJobs: () => ({ submit: vi.fn(), isSubmitting: false, error: null, accepted: null }),
}));
vi.mock('./hooks/useArchitecture', () => ({
  useArchitecture: () => [{ key: 'queue', title: 'Custom Redis queue', body: 'raw primitives' }],
}));

import { App } from './App';

describe('App routing', () => {
  it('renders the dashboard at / with the nav', () => {
    render(<App />);
    expect(document.getElementById('dashboard-guest')).toHaveTextContent('guest-teal');
    expect(document.getElementById('metric-queue-depth')).toHaveTextContent('0012');
    expect(document.getElementById('nav-link-how-it-works')).toBeInTheDocument();
  });

  it('navigates to the explainer pages from the header', () => {
    render(<App />);
    fireEvent.click(document.getElementById('nav-link-how-it-works') as HTMLElement);
    expect(document.getElementById('how-it-works')).toBeInTheDocument();

    fireEvent.click(document.getElementById('nav-link-how-i-work') as HTMLElement);
    expect(document.getElementById('how-i-work')).toBeInTheDocument();

    fireEvent.click(document.getElementById('nav-link-dashboard') as HTMLElement);
    expect(document.getElementById('dashboard')).toBeInTheDocument();
  });
});

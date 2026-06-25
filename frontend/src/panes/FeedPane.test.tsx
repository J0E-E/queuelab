import { fireEvent, render } from '@testing-library/react';

import type { FeedEntry } from '../hooks/liveState';
import { FeedPane } from './FeedPane';

function entry(overrides: Partial<FeedEntry> = {}): FeedEntry {
  return {
    time: '12:04:02',
    handle: null,
    color: null,
    action: 'worker-1 started job#1',
    state: 'running',
    attempts: null,
    is_terminal: false,
    line: 'worker-1 started job#1',
    ...overrides,
  };
}

describe('FeedPane', () => {
  it('renders each activity entry in an aria-live region', () => {
    render(
      <FeedPane
        entries={[
          entry({ action: 'worker-1 started job#1', line: 'worker-1 started job#1' }),
          entry({ action: 'scaled up to 4 workers', state: null, line: 'scaled up to 4 workers' }),
        ]}
      />,
    );
    expect(document.getElementById('feed-list')).toHaveAttribute('aria-live', 'polite');
    expect(document.getElementById('feed-line-0')).toHaveTextContent('worker-1 started job#1');
    expect(document.getElementById('feed-line-1')).toHaveTextContent('scaled up to 4 workers');
  });

  it('shows an honest empty state', () => {
    render(<FeedPane entries={[]} />);
    expect(document.getElementById('feed-empty')).toHaveTextContent('waiting for activity');
  });

  it('defaults to all, then failures-only hides non-failure lines but keeps dead and retrying', () => {
    render(
      <FeedPane
        entries={[
          entry({ action: 'worker-1 started job#1', state: 'running', line: 'worker-1 started job#1' }),
          entry({ action: 'scaled up to 4 workers', state: null, line: 'scaled up to 4 workers' }),
          entry({
            action: 'job-7 retrying (attempt 2)',
            state: 'retrying',
            line: 'job-7 retrying (attempt 2)',
          }),
          entry({
            action: 'job-7 failed after 3 attempts',
            state: 'failed',
            is_terminal: true,
            line: 'job-7 failed after 3 attempts',
          }),
        ]}
      />,
    );
    // Default (all) shows every line.
    expect(document.getElementById('feed-line-3')).toHaveTextContent('failed after 3 attempts');

    fireEvent.click(document.getElementById('feed-filter-failures')!);

    // Only the failure lifecycle survives: the will-retry line and the dead one — in that order.
    expect(document.getElementById('feed-line-0')).toHaveTextContent('job-7 retrying (attempt 2)');
    expect(document.getElementById('feed-line-1')).toHaveTextContent('job-7 failed after 3 attempts');
    expect(document.getElementById('feed-line-2')).toBeNull();
    // The active filter is reflected for assistive tech.
    expect(document.getElementById('feed-filter-failures')).toHaveAttribute('aria-pressed', 'true');
  });

  it('shows a no-failures empty state when failures-only matches nothing', () => {
    render(
      <FeedPane
        entries={[entry({ action: 'worker-1 started job#1', state: 'running' })]}
      />,
    );
    fireEvent.click(document.getElementById('feed-filter-failures')!);
    expect(document.getElementById('feed-empty')).toHaveTextContent('no failures');
  });
});

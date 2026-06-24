import { render } from '@testing-library/react';

import { FeedPane } from './FeedPane';

describe('FeedPane', () => {
  it('renders each activity line in an aria-live region', () => {
    render(<FeedPane lines={['worker-1 started job#1', 'scaled up to 4 workers']} />);
    expect(document.getElementById('feed-list')).toHaveAttribute('aria-live', 'polite');
    expect(document.getElementById('feed-line-0')).toHaveTextContent('worker-1 started job#1');
    expect(document.getElementById('feed-line-1')).toHaveTextContent('scaled up to 4 workers');
  });

  it('shows an honest empty state', () => {
    render(<FeedPane lines={[]} />);
    expect(document.getElementById('feed-empty')).toHaveTextContent('waiting for activity');
  });
});

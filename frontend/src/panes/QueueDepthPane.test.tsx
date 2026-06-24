import { render } from '@testing-library/react';

import { EMPTY_COUNTS } from '../hooks/liveState';
import { QueueDepthPane } from './QueueDepthPane';

describe('QueueDepthPane', () => {
  it('renders a bar per active state and the depth sparkline', () => {
    render(
      <QueueDepthPane
        counts={{ ...EMPTY_COUNTS, queued: 6, running: 2, retrying: 2 }}
        depthHistory={[1, 4, 8, 6]}
      />,
    );
    expect(document.getElementById('queue-depth-bar-queued')).toBeInTheDocument();
    expect(document.getElementById('queue-depth-bar-running')).toBeInTheDocument();
    expect(document.getElementById('queue-depth-bar-retrying')).toBeInTheDocument();
    expect(document.getElementById('queue-depth-sparkline')).toHaveTextContent('6');
  });

  it('does not divide by zero when the queue is empty', () => {
    render(<QueueDepthPane counts={EMPTY_COUNTS} depthHistory={[]} />);
    expect(document.getElementById('queue-depth-bar-queued')).toHaveTextContent('0%');
  });
});

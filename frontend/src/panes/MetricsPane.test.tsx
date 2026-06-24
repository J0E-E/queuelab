import { render } from '@testing-library/react';

import { EMPTY_COUNTS } from '../hooks/liveState';
import { MetricsPane } from './MetricsPane';

describe('MetricsPane', () => {
  it('renders the live vitals in an aria-live region', () => {
    render(
      <MetricsPane
        counts={{ ...EMPTY_COUNTS, completed: 40, failed: 3 }}
        queueDepth={142}
        workerCount={8}
        isConnected
      />,
    );
    expect(document.getElementById('metric-queue-depth')).toHaveTextContent('0142');
    expect(document.getElementById('metric-workers')).toHaveTextContent('8');
    expect(document.getElementById('metric-done')).toHaveTextContent('40');
    expect(document.getElementById('metrics-counters')).toHaveAttribute('aria-live', 'polite');
    expect(document.getElementById('metrics-pane-title')).toHaveTextContent('● live');
  });

  it('shows an offline chip when disconnected', () => {
    render(
      <MetricsPane counts={EMPTY_COUNTS} queueDepth={0} workerCount={0} isConnected={false} />,
    );
    expect(document.getElementById('metrics-pane-title')).toHaveTextContent('offline');
  });
});

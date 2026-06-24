import { render } from '@testing-library/react';

import { ArchitecturePane } from './ArchitecturePane';

describe('ArchitecturePane', () => {
  it('renders each note keyed to its pane', () => {
    render(
      <ArchitecturePane
        sections={[
          { key: 'queue', title: 'Custom Redis queue', body: 'raw primitives' },
          { key: 'workers', title: 'Autoscaler', body: 'a control loop' },
        ]}
      />,
    );
    expect(document.getElementById('architecture-title-queue')).toHaveTextContent(
      'Custom Redis queue',
    );
    expect(document.getElementById('architecture-body-workers')).toHaveTextContent(
      'a control loop',
    );
  });

  it('shows a loading state until the notes arrive', () => {
    render(<ArchitecturePane sections={[]} />);
    expect(document.getElementById('architecture-empty')).toHaveTextContent('loading notes');
  });
});

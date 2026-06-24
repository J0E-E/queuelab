import { render } from '@testing-library/react';

import { PaneTitle } from './PaneTitle';

describe('PaneTitle', () => {
  it('renders the bracketed ALL-CAPS title with its id', () => {
    render(<PaneTitle id="qd-title" title="queue depth" />);
    const title = document.getElementById('qd-title');
    expect(title).toBeInTheDocument();
    expect(title).toHaveTextContent('[ queue depth ]');
    expect(title).toHaveClass('uppercase', 'bg-bg-invert');
  });

  it('renders a status chip when given', () => {
    render(<PaneTitle id="t" title="workers" chip="● live" />);
    expect(document.getElementById('t')).toHaveTextContent('● live');
  });
});

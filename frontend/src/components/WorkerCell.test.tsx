import { render } from '@testing-library/react';

import { WorkerCell } from './WorkerCell';

describe('WorkerCell', () => {
  it('renders the glyph and color for the status, with the worker id as a tooltip', () => {
    render(<WorkerCell id="c" status="running" workerId="worker-1" />);
    const cell = document.getElementById('c');
    expect(cell).toHaveTextContent('[R]');
    expect(cell).toHaveClass('text-state-running');
    expect(cell).toHaveAttribute('title', 'worker-1');
  });

  it('renders a destroyed worker in the failed phosphor', () => {
    render(<WorkerCell id="d" status="destroyed" />);
    expect(document.getElementById('d')).toHaveClass('text-state-failed');
  });
});

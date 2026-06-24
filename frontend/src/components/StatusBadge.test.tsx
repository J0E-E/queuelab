import { render } from '@testing-library/react';

import { StatusBadge } from './StatusBadge';

describe('StatusBadge', () => {
  it('shows the code, glyph and state color (never color alone)', () => {
    render(<StatusBadge id="b" state="running" />);
    const badge = document.getElementById('b');
    expect(badge).toHaveTextContent('► [RUN]');
    expect(badge).toHaveClass('text-state-running');
  });

  it('maps each state to its own badge', () => {
    const { rerender } = render(<StatusBadge id="b" state="failed" />);
    expect(document.getElementById('b')).toHaveTextContent('✗ [FAIL]');
    rerender(<StatusBadge id="b" state="retrying" />);
    expect(document.getElementById('b')).toHaveTextContent('↻ [RETRY]');
  });
});

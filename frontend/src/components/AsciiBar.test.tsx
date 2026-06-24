import { render } from '@testing-library/react';

import { AsciiBar } from './AsciiBar';

describe('AsciiBar', () => {
  it('fills the bar in proportion to the value and prints the percent', () => {
    render(<AsciiBar id="bar" value={0.5} width={10} />);
    const bar = document.getElementById('bar');
    // Half of ten cells filled, the rest empty, bracketed, with the percent.
    expect(bar).toHaveTextContent('[|||||.....] 50%');
  });

  it('clamps out-of-range values', () => {
    render(<AsciiBar id="full" value={2} width={4} />);
    expect(document.getElementById('full')).toHaveTextContent('[||||] 100%');
  });
});

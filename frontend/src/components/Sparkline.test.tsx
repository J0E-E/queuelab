import { render } from '@testing-library/react';

import { Sparkline } from './Sparkline';

describe('Sparkline', () => {
  it('plots the series as blocks and prints the current value', () => {
    render(<Sparkline id="s" values={[0, 5, 10]} />);
    const spark = document.getElementById('s');
    // Lowest maps to the bottom block, highest to the top, current value printed beside.
    expect(spark?.textContent).toContain('▁');
    expect(spark?.textContent).toContain('█');
    expect(spark).toHaveTextContent('10');
  });

  it('handles an empty series without crashing', () => {
    render(<Sparkline id="empty" values={[]} />);
    expect(document.getElementById('empty')).toHaveTextContent('0');
  });
});

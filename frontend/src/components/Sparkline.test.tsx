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

  it('spaces the block glyphs so each time bucket reads as its own unit', () => {
    render(<Sparkline id="spaced" values={[0, 5, 10]} />);
    // The glyph run (not the printed current value) carries letter spacing.
    const glyphRun = document.querySelector('#spaced .tracking-\\[0\\.2em\\]');
    expect(glyphRun).not.toBeNull();
    expect(glyphRun?.textContent).toContain('█');
  });

  it('caps the drawn series to the last 30 samples while still printing the latest value', () => {
    // 40 ascending samples (0..39): only the last 30 are plotted, but the newest value shows.
    const values = Array.from({ length: 40 }, (_, index) => index);
    render(<Sparkline id="capped" values={values} />);
    const glyphRun = document.querySelector('#capped .tracking-\\[0\\.2em\\]');
    expect(glyphRun?.textContent?.length).toBeLessThanOrEqual(30);
    expect(document.getElementById('capped')).toHaveTextContent('39');
  });

  it('handles an empty series without crashing', () => {
    render(<Sparkline id="empty" values={[]} />);
    expect(document.getElementById('empty')).toHaveTextContent('0');
  });
});

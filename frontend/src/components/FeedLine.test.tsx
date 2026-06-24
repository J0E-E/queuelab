import { render } from '@testing-library/react';

import { FeedLine } from './FeedLine';

describe('FeedLine', () => {
  it('renders the timestamp, handle and action text', () => {
    render(
      <FeedLine id="f" time="12:04:02" handle="guest-teal">
        destroyed worker-3
      </FeedLine>,
    );
    const line = document.getElementById('f');
    expect(line).toHaveTextContent('12:04:02');
    expect(line).toHaveTextContent('guest-teal');
    expect(line).toHaveTextContent('destroyed worker-3');
  });

  it('colors a known guest handle with its palette color', () => {
    render(
      <FeedLine id="f2" time="00:00:00" handle="guest-teal">
        +50
      </FeedLine>,
    );
    // teal #2dd4bf — rendered as an inline color (rgb form in jsdom).
    const handle = document.getElementById('f2')?.querySelector('span[style]');
    expect(handle).toHaveStyle({ color: '#2dd4bf' });
  });
});

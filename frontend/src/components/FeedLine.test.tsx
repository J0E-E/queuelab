import { render } from '@testing-library/react';

import type { FeedEntry } from '../hooks/liveState';
import { FeedLine } from './FeedLine';

function entry(overrides: Partial<FeedEntry> = {}): FeedEntry {
  return {
    time: '12:04:02',
    handle: 'guest-teal',
    color: '#2dd4bf',
    action: 'destroyed worker-3',
    state: null,
    attempts: null,
    is_terminal: false,
    line: 'guest-teal destroyed worker-3',
    ...overrides,
  };
}

describe('FeedLine', () => {
  it('renders the timestamp, handle and action text', () => {
    render(<FeedLine id="f" entry={entry()} />);
    const line = document.getElementById('f');
    expect(line).toHaveTextContent('12:04:02');
    expect(line).toHaveTextContent('guest-teal');
    expect(line).toHaveTextContent('destroyed worker-3');
  });

  it('colors the handle and marks the line with the backend-sent actor color', () => {
    render(<FeedLine id="f2" entry={entry({ color: '#2dd4bf' })} />);
    // teal #2dd4bf — rendered as an inline color on the handle (rgb form in jsdom).
    expect(document.getElementById('f2-handle')).toHaveStyle({ color: '#2dd4bf' });
    // The whole line is marked to the actor via a left accent in the same color.
    expect(document.getElementById('f2')).toHaveStyle({ borderColor: '#2dd4bf' });
  });

  it('renders an unattributed line dimmed, with no inline color', () => {
    render(<FeedLine id="f3" entry={entry({ handle: null, color: null })} />);
    // No handle span at all when there is no actor.
    expect(document.getElementById('f3-handle')).toBeNull();
    expect(document.getElementById('f3')).not.toHaveStyle({ borderColor: '#2dd4bf' });
  });

  it('tags a dead job with the failed glyph in the failure hue, distinct from a retry', () => {
    render(
      <FeedLine
        id="dead"
        entry={entry({ state: 'failed', is_terminal: true, action: 'job-7 failed after 3 attempts' })}
      />,
    );
    render(
      <FeedLine
        id="retry"
        entry={entry({ state: 'retrying', is_terminal: false, action: 'job-7 retrying (attempt 2)' })}
      />,
    );
    // A dead job reads with the red failure glyph; a will-retry one with the violet retry glyph —
    // distinct by glyph + hue, not color alone.
    const dead = document.getElementById('dead-state');
    const retry = document.getElementById('retry-state');
    expect(dead).toHaveTextContent('✗');
    expect(dead).toHaveClass('text-state-failed');
    expect(retry).toHaveTextContent('↻');
    expect(retry).toHaveClass('text-state-retrying');
  });
});

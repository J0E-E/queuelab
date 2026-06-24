import { render } from '@testing-library/react';

import { App } from './App';

describe('App showcase', () => {
  it('renders the primitive showcase with the scanline overlay and key primitives', () => {
    render(<App />);
    expect(document.getElementById('scanlines-overlay')).toBeInTheDocument();
    expect(document.getElementById('queue-depth-counter')).toHaveTextContent('0142');
    expect(document.getElementById('badge-failed')).toHaveTextContent('[FAIL]');
    expect(document.getElementById('destroy-button')).toHaveTextContent('[ destroy worker ]');
    expect(document.getElementById('feed-line-1')).toHaveTextContent('guest-teal');
  });
});

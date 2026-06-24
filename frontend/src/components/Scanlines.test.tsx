import { render } from '@testing-library/react';

import { Scanlines } from './Scanlines';

describe('Scanlines', () => {
  it('renders a decorative, non-interactive overlay hidden from assistive tech', () => {
    render(<Scanlines />);
    const overlay = document.getElementById('scanlines-overlay');
    expect(overlay).toBeInTheDocument();
    expect(overlay).toHaveClass('scanlines');
    expect(overlay).toHaveAttribute('aria-hidden', 'true');
  });
});

import { fireEvent, render } from '@testing-library/react';

import { SubmitPane } from './SubmitPane';

function renderPane(overrides: Partial<Parameters<typeof SubmitPane>[0]> = {}) {
  const onSubmit = vi.fn();
  render(
    <SubmitPane
      guestHandle="guest-amber"
      onSubmit={onSubmit}
      isSubmitting={false}
      error={null}
      accepted={null}
      isDisabled={false}
      {...overrides}
    />,
  );
  return { onSubmit };
}

describe('SubmitPane', () => {
  it('submits the current flag values', () => {
    const { onSubmit } = renderPane();
    fireEvent.change(document.getElementById('submit-count') as HTMLInputElement, {
      target: { value: '25' },
    });
    fireEvent.change(document.getElementById('submit-type') as HTMLSelectElement, {
      target: { value: 'report' },
    });
    fireEvent.submit(document.getElementById('submit-form') as HTMLFormElement);
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ count: 25, type: 'report', complexity: 3 }),
    );
  });

  it('renders a system-voice error inline', () => {
    renderPane({ error: '[ERR] --count exceeds cap (max 100)' });
    expect(document.getElementById('submit-error')).toHaveTextContent('exceeds cap');
  });

  it('shows the seconds left on a rate-limit error, hidden from assistive tech', () => {
    renderPane({ error: '[WARN] rate limit: 1 / 3s', errorSecondsLeft: 2 });
    const countdown = document.getElementById('submit-error-countdown');
    expect(countdown).toHaveTextContent('retry in 2s');
    // aria-hidden so the per-second tick isn't re-announced by the live region.
    expect(countdown).toHaveAttribute('aria-hidden', 'true');
  });

  it('omits the countdown when the error is not counting down', () => {
    renderPane({ error: '[ERR] --count exceeds cap (max 100)', errorSecondsLeft: null });
    expect(document.getElementById('submit-error-countdown')).not.toBeInTheDocument();
  });

  it('reserves the outcome space so a message appearing or clearing never shifts the layout', () => {
    renderPane({ error: null, accepted: null });
    const status = document.getElementById('submit-status');
    // Space is held up front (min height + aria-live) even with no message showing.
    expect(status).toBeInTheDocument();
    expect(status).toHaveAttribute('aria-live', 'polite');
    expect(status?.className).toContain('min-h-6');
  });

  it('disables execute until a session exists', () => {
    renderPane({ isDisabled: true });
    expect(document.getElementById('submit-execute')).toBeDisabled();
  });

  it('labels every input for assistive tech', () => {
    renderPane();
    // htmlFor ↔ id wiring: querying by label finds the control.
    expect(document.querySelector('label[for="submit-count"]')).toBeInTheDocument();
    expect(document.querySelector('label[for="submit-type"]')).toBeInTheDocument();
  });
});

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

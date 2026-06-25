import { fireEvent, render } from '@testing-library/react';

import type { WorkerCellModel } from '../hooks/liveState';
import { WorkersPane } from './WorkersPane';

const WORKERS: WorkerCellModel[] = [
  { id: 'worker-cell-worker-1', status: 'running', workerId: 'worker-1' },
  { id: 'worker-cell-idle-1', status: 'idle' },
];

function renderPane(overrides: Partial<Parameters<typeof WorkersPane>[0]> = {}) {
  const onDestroy = vi.fn();
  const onInjectFailures = vi.fn();
  render(
    <WorkersPane
      workers={WORKERS}
      onDestroy={onDestroy}
      onInjectFailures={onInjectFailures}
      {...overrides}
    />,
  );
  return { onDestroy, onInjectFailures };
}

describe('WorkersPane', () => {
  it('destroys a specific worker when its running cell is clicked', () => {
    const { onDestroy } = renderPane();
    fireEvent.click(document.getElementById('destroy-cell-worker-1') as HTMLElement);
    expect(onDestroy).toHaveBeenCalledWith('worker-1');
  });

  it('destroys a random worker from the generic button (no id)', () => {
    const { onDestroy } = renderPane();
    fireEvent.click(document.getElementById('destroy-worker-button') as HTMLElement);
    expect(onDestroy).toHaveBeenCalledOnce();
    expect(onDestroy.mock.calls[0][0]).toBeUndefined();
  });

  it('injects failures from the chaos control', () => {
    const { onInjectFailures } = renderPane();
    fireEvent.click(document.getElementById('inject-failures-button') as HTMLElement);
    expect(onInjectFailures).toHaveBeenCalledOnce();
  });

  it('has no scale controls', () => {
    renderPane();
    expect(document.getElementById('scale-up-button')).not.toBeInTheDocument();
    expect(document.getElementById('scale-down-button')).not.toBeInTheDocument();
  });

  it('shows an empty state with no workers', () => {
    renderPane({ workers: [] });
    expect(document.getElementById('worker-grid-empty')).toBeInTheDocument();
  });

  it('renders the success and warning lines independently so one never replaces the other', () => {
    renderPane({
      chaosSuccess: '[OK] destroyed worker-1',
      chaosWarning: '[WARN] rate limit: 1 chaos action / 10s',
    });
    const success = document.getElementById('worker-chaos-success');
    const warning = document.getElementById('worker-chaos-warning');
    expect(success).toHaveTextContent('[OK] destroyed worker-1');
    expect(success).toHaveClass('text-ok');
    expect(warning).toHaveTextContent('[WARN] rate limit: 1 chaos action / 10s');
    expect(warning).toHaveClass('text-error');
  });

  it('shows the seconds left on a rate-limit warning, hidden from assistive tech', () => {
    renderPane({
      chaosWarning: '[WARN] rate limit: 1 chaos action / 10s',
      chaosWarningSecondsLeft: 7,
    });
    const countdown = document.getElementById('worker-chaos-countdown');
    expect(countdown).toHaveTextContent('retry in 7s');
    // aria-hidden so the per-second tick isn't re-announced by the live region.
    expect(countdown).toHaveAttribute('aria-hidden', 'true');
  });

  it('omits the countdown when the warning is not counting down', () => {
    renderPane({ chaosWarning: '[WARN] no workers to destroy', chaosWarningSecondsLeft: null });
    expect(document.getElementById('worker-chaos-countdown')).not.toBeInTheDocument();
  });

  it('omits the notice lines when there are none', () => {
    renderPane();
    expect(document.getElementById('worker-chaos-success')).not.toBeInTheDocument();
    expect(document.getElementById('worker-chaos-warning')).not.toBeInTheDocument();
  });
});

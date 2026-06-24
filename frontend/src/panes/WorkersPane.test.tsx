import { fireEvent, render } from '@testing-library/react';

import type { WorkerCellModel } from '../hooks/liveState';
import { WorkersPane } from './WorkersPane';

const WORKERS: WorkerCellModel[] = [
  { id: 'worker-cell-worker-1', status: 'running', workerId: 'worker-1' },
  { id: 'worker-cell-idle-1', status: 'idle' },
];

function renderPane(overrides: Partial<Parameters<typeof WorkersPane>[0]> = {}) {
  const onScaleUp = vi.fn();
  const onScaleDown = vi.fn();
  const onDestroy = vi.fn();
  const onInjectFailures = vi.fn();
  render(
    <WorkersPane
      workers={WORKERS}
      onScaleUp={onScaleUp}
      onScaleDown={onScaleDown}
      onDestroy={onDestroy}
      onInjectFailures={onInjectFailures}
      {...overrides}
    />,
  );
  return { onScaleUp, onScaleDown, onDestroy, onInjectFailures };
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

  it('scales via the scale controls', () => {
    const { onScaleUp, onScaleDown } = renderPane();
    fireEvent.click(document.getElementById('scale-up-button') as HTMLElement);
    fireEvent.click(document.getElementById('scale-down-button') as HTMLElement);
    expect(onScaleUp).toHaveBeenCalledOnce();
    expect(onScaleDown).toHaveBeenCalledOnce();
  });

  it('injects failures from the chaos control', () => {
    const { onInjectFailures } = renderPane();
    fireEvent.click(document.getElementById('inject-failures-button') as HTMLElement);
    expect(onInjectFailures).toHaveBeenCalledOnce();
  });

  it('shows an empty state with no workers', () => {
    renderPane({ workers: [] });
    expect(document.getElementById('worker-grid-empty')).toBeInTheDocument();
  });
});

/** Worker liveness as the grid renders it (Guide §8 worker grid). */
export type WorkerStatus = 'running' | 'idle' | 'spawning' | 'destroyed';

const WORKER_CELLS: Record<WorkerStatus, { glyph: string; color: string }> = {
  running: { glyph: '[R]', color: 'text-state-running' },
  idle: { glyph: '[I]', color: 'text-fg-dim' },
  spawning: { glyph: '[·]', color: 'text-muted' },
  destroyed: { glyph: ' ✗ ', color: 'text-state-failed' },
};

export interface WorkerCellProps {
  /** Unique, descriptive id (project CLAUDE.md). */
  id: string;
  status: WorkerStatus;
  /** The worker id, surfaced as a tooltip so a cell stays identifiable. */
  workerId?: string;
}

/**
 * One cell of the worker grid (Guide §8). Each worker is a glyph in its status color, so scaling
 * is *visible* as cells appearing, flipping state, and disappearing.
 */
export function WorkerCell({ id, status, workerId }: WorkerCellProps) {
  const cell = WORKER_CELLS[status];
  return (
    <span id={id} title={workerId} className={cell.color}>
      {cell.glyph}
    </span>
  );
}

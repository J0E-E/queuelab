import { BracketButton } from '../components/BracketButton';
import { Pane } from '../components/Pane';
import { PaneTitle } from '../components/PaneTitle';
import { WorkerCell } from '../components/WorkerCell';
import type { WorkerCellModel } from '../hooks/liveState';

export interface WorkersPaneProps {
  workers: WorkerCellModel[];
  /** Raise the autoscaler floor (PUT /api/config min_workers). */
  onScaleUp: () => void;
  /** Lower the autoscaler floor. */
  onScaleDown: () => void;
  /** Destroy a worker — a specific id from a clicked cell, or undefined to let the API pick. */
  onDestroy: (workerId?: string) => void;
  /** Inject a burst of simulated failures (chaos). */
  onInjectFailures: () => void;
}

/**
 * The workers pane: the live worker grid (Guide §8) plus scale and destroy controls. A running
 * worker's cell is a button that destroys that worker; the generic destroy button breaks a random
 * one. Scaling nudges the autoscaler floor via the config API (no manual-scale endpoint exists).
 */
export function WorkersPane({
  workers,
  onScaleUp,
  onScaleDown,
  onDestroy,
  onInjectFailures,
}: WorkersPaneProps) {
  return (
    <Pane id="workers-pane">
      <PaneTitle id="workers-pane-title" title={`workers · ${workers.length}`} />
      <div id="worker-grid" className="flex flex-wrap gap-2 pt-3 text-lg">
        {workers.length === 0 ? (
          <p id="worker-grid-empty" className="text-fg-dim">
            &gt; no workers running
          </p>
        ) : (
          workers.map((cell) =>
            cell.workerId ? (
              <button
                key={cell.id}
                id={`destroy-cell-${cell.workerId}`}
                type="button"
                title={`destroy ${cell.workerId}`}
                onClick={() => onDestroy(cell.workerId)}
              >
                <WorkerCell id={cell.id} status={cell.status} workerId={cell.workerId} />
              </button>
            ) : (
              <WorkerCell key={cell.id} id={cell.id} status={cell.status} />
            ),
          )
        )}
      </div>
      <div id="worker-controls" className="flex flex-wrap gap-3 pt-4">
        <BracketButton id="scale-up-button" onClick={onScaleUp}>
          + scale
        </BracketButton>
        <BracketButton id="scale-down-button" onClick={onScaleDown}>
          - scale
        </BracketButton>
        <BracketButton id="destroy-worker-button" variant="destructive" onClick={() => onDestroy()}>
          destroy worker
        </BracketButton>
        <BracketButton id="inject-failures-button" variant="destructive" onClick={onInjectFailures}>
          inject failures
        </BracketButton>
      </div>
    </Pane>
  );
}

import { BracketButton } from '../components/BracketButton';
import { Pane } from '../components/Pane';
import { PaneTitle } from '../components/PaneTitle';
import { WorkerCell } from '../components/WorkerCell';
import type { WorkerCellModel } from '../hooks/liveState';

export interface WorkersPaneProps {
  workers: WorkerCellModel[];
  /** Destroy a worker — a specific id from a clicked cell, or undefined to let the API pick. */
  onDestroy: (workerId?: string) => void;
  /** Inject a burst of simulated failures (chaos). */
  onInjectFailures: () => void;
  /** The last successful chaos action (`[OK]` line), or null. */
  chaosSuccess?: string | null;
  /** The last rejected chaos action (`[WARN]`/`[ERR]` line), or null. */
  chaosWarning?: string | null;
}

/**
 * The workers pane: the live worker grid (Guide §8) plus the chaos controls. A running worker's
 * cell is a button that destroys that worker; the generic destroy button breaks a random one. The
 * fleet size is driven by the autoscaler, so there is no manual scale control here.
 */
export function WorkersPane({
  workers,
  onDestroy,
  onInjectFailures,
  chaosSuccess = null,
  chaosWarning = null,
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
            cell.status === 'running' && cell.workerId ? (
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
              <WorkerCell key={cell.id} id={cell.id} status={cell.status} workerId={cell.workerId} />
            ),
          )
        )}
      </div>
      <div id="worker-chaos-controls" className="pt-4">
        <p id="worker-chaos-label" className="text-lg font-bold text-error">
          &gt; CHAOS Actions
        </p>
        <div id="worker-controls" className="flex flex-wrap gap-3 pt-2">
          <BracketButton
            id="destroy-worker-button"
            variant="destructive"
            onClick={() => onDestroy()}
          >
            destroy worker
          </BracketButton>
          <BracketButton
            id="inject-failures-button"
            variant="destructive"
            onClick={onInjectFailures}
          >
            inject failures
          </BracketButton>
        </div>
      </div>
      {/* Reserve the chaos-outcome space up front (min height for both lines) so a `[WARN]`/`[OK]`
          appearing or clearing never shifts the pane below it. `aria-live` announces each outcome. */}
      <div
        id="worker-chaos-status"
        aria-live="polite"
        className="min-h-14 space-y-1 pt-3 text-sm"
      >
        {chaosSuccess ? (
          <p id="worker-chaos-success" className="text-ok">
            {chaosSuccess}
          </p>
        ) : null}
        {chaosWarning ? (
          <p id="worker-chaos-warning" className="text-error">
            {chaosWarning}
          </p>
        ) : null}
      </div>
    </Pane>
  );
}

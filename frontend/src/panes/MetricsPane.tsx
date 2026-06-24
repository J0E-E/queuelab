import { Counter } from '../components/Counter';
import { Pane } from '../components/Pane';
import { PaneTitle } from '../components/PaneTitle';
import type { QueueCounts } from '../hooks/liveState';

export interface MetricsPaneProps {
  counts: QueueCounts;
  queueDepth: number;
  workerCount: number;
  isConnected: boolean;
}

/** The live vitals pane: big tick-flashing counters in an `aria-live` region (Guide §8 / §12). */
export function MetricsPane({ counts, queueDepth, workerCount, isConnected }: MetricsPaneProps) {
  return (
    <Pane id="metrics-pane" isActive>
      <PaneTitle id="metrics-pane-title" title="vitals" chip={isConnected ? '● live' : 'offline'} />
      <div id="metrics-counters" aria-live="polite" className="flex flex-wrap gap-8 pt-3">
        <Counter id="metric-queue-depth" value={queueDepth} pad={4} label="queued" />
        <Counter id="metric-workers" value={workerCount} label="workers" />
        <Counter id="metric-done" value={counts.completed} label="done" />
        <Counter id="metric-failed" value={counts.failed} label="failed" />
      </div>
    </Pane>
  );
}

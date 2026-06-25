import { AsciiBar, type BarState } from '../components/AsciiBar';
import { Pane } from '../components/Pane';
import { PaneTitle } from '../components/PaneTitle';
import { Sparkline } from '../components/Sparkline';
import { StatusBadge } from '../components/StatusBadge';
import type { JobState } from '../components/stateBadges';
import type { QueueCounts } from '../hooks/liveState';

export interface QueueDepthPaneProps {
  counts: QueueCounts;
  depthHistory: number[];
}

// The in-flight states, shown as a proportional mix (cumulative done/failed are vitals, not depth).
const ACTIVE_STATES: JobState[] = ['queued', 'running', 'retrying'];

/** The queue-depth pane: a per-state ASCII mix bar plus a depth-over-time sparkline (Guide §8). */
export function QueueDepthPane({ counts, depthHistory }: QueueDepthPaneProps) {
  const activeTotal = Math.max(counts.queued + counts.running + counts.retrying, 1);
  return (
    <Pane id="queue-depth-pane">
      <PaneTitle id="queue-depth-pane-title" title="queue depth" />
      <div id="queue-depth-rows" className="space-y-2 pt-3">
        {ACTIVE_STATES.map((state) => (
          <div key={state} id={`queue-depth-row-${state}`} className="flex items-center gap-3">
            <StatusBadge id={`queue-depth-badge-${state}`} state={state} />
            <AsciiBar
              id={`queue-depth-bar-${state}`}
              value={counts[state] / activeTotal}
              width={20}
              state={state as BarState}
            />
          </div>
        ))}
        <div id="queue-depth-trend" className="flex items-center gap-3 pt-2 text-fg-dim">
          trend
          {/* Backstop: clip the glyph run to the pane, right-anchored so the newest buckets stay
              visible. dir="rtl" makes overflow clip off the left (oldest); dir="ltr" inner keeps
              the glyphs reading left-to-right. */}
          <div
            id="queue-depth-trend-clip"
            dir="rtl"
            className="min-w-0 flex-1 overflow-hidden whitespace-nowrap"
          >
            <span id="queue-depth-trend-inner" dir="ltr">
              <Sparkline id="queue-depth-sparkline" values={depthHistory} />
            </span>
          </div>
        </div>
      </div>
    </Pane>
  );
}

import { AsciiBar } from './components/AsciiBar';
import { BracketButton } from './components/BracketButton';
import { Counter } from './components/Counter';
import { FeedLine } from './components/FeedLine';
import { Pane } from './components/Pane';
import { PaneTitle } from './components/PaneTitle';
import { Prompt } from './components/Prompt';
import { Scanlines } from './components/Scanlines';
import { Sparkline } from './components/Sparkline';
import { StatusBadge, type JobState } from './components/StatusBadge';
import { WorkerCell, type WorkerStatus } from './components/WorkerCell';

const JOB_STATES: JobState[] = ['queued', 'running', 'completed', 'failed', 'retrying'];
const WORKER_GRID: { id: string; status: WorkerStatus; workerId: string }[] = [
  { id: 'worker-cell-1', status: 'running', workerId: 'worker-1' },
  { id: 'worker-cell-2', status: 'running', workerId: 'worker-2' },
  { id: 'worker-cell-3', status: 'idle', workerId: 'worker-3' },
  { id: 'worker-cell-4', status: 'spawning', workerId: 'worker-4' },
  { id: 'worker-cell-5', status: 'destroyed', workerId: 'worker-5' },
];

/**
 * The Epic 13 primitive showcase: every style-guide primitive rendered once in the Terminal-CLI
 * theme, so the foundation can be eyeballed in the dark theme. The live dashboard replaces this in
 * Epic 14.
 */
export function App() {
  return (
    <>
      <Scanlines />
      <main id="app-main" className="mx-auto max-w-4xl space-y-6 p-6">
        <header id="app-header" className="glow text-lg uppercase tracking-[0.02em] text-fg">
          [ QUEUELAB · primitive showcase ]
        </header>

        <Pane id="metrics-pane" isActive>
          <PaneTitle id="metrics-title" title="data viz" chip="● live" />
          <div id="metrics-body" className="space-y-3 pt-3">
            <div id="counters-row" className="flex gap-8">
              <Counter id="queue-depth-counter" value={142} delta={12} pad={4} label="queued" />
              <Counter id="worker-count-counter" value={8} label="workers" />
            </div>
            <AsciiBar id="capacity-bar" value={0.62} width={24} state="running" />
            <Sparkline id="depth-sparkline" values={[2, 5, 9, 14, 11, 7, 4, 3]} />
          </div>
        </Pane>

        <Pane id="states-pane">
          <PaneTitle id="states-title" title="job states" />
          <div id="states-row" className="flex flex-wrap gap-4 pt-3">
            {JOB_STATES.map((state) => (
              <StatusBadge key={state} id={`badge-${state}`} state={state} />
            ))}
          </div>
        </Pane>

        <Pane id="workers-pane">
          <PaneTitle id="workers-title" title="workers" />
          <div id="worker-grid" className="flex gap-3 pt-3 text-lg">
            {WORKER_GRID.map((cell) => (
              <WorkerCell
                key={cell.id}
                id={cell.id}
                status={cell.status}
                workerId={cell.workerId}
              />
            ))}
          </div>
        </Pane>

        <Pane id="controls-pane">
          <PaneTitle id="controls-title" title="controls" />
          <div id="controls-row" className="flex flex-wrap items-center gap-4 pt-3">
            <BracketButton id="scale-button">+ scale up</BracketButton>
            <BracketButton id="destroy-button" variant="destructive">
              destroy worker
            </BracketButton>
            <BracketButton id="disabled-button" isDisabled>
              execute
            </BracketButton>
          </div>
          <div id="prompt-row" className="pt-3">
            <Prompt id="submit-prompt" user="guest-amber" hasCursor />
          </div>
        </Pane>

        <Pane id="feed-pane">
          <PaneTitle id="feed-title" title="activity feed" />
          <div id="feed-body" className="space-y-1 pt-3">
            <FeedLine id="feed-line-1" time="12:04:02" handle="guest-teal">
              submitted +50 jobs
            </FeedLine>
            <FeedLine id="feed-line-2" time="12:04:05" handle="guest-amber">
              destroyed worker-3
            </FeedLine>
            <FeedLine id="feed-line-3" time="12:04:06" handle="sys">
              scaled up to 4 workers
            </FeedLine>
          </div>
        </Pane>
      </main>
    </>
  );
}

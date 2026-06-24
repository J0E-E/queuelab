import { destroyWorker, injectFailures, updateConfig } from '../lib/api';
import { deriveWorkers } from '../hooks/liveState';
import { useArchitecture } from '../hooks/useArchitecture';
import { useLiveState } from '../hooks/useLiveState';
import { useSession } from '../hooks/useSession';
import { useSubmitJobs } from '../hooks/useSubmitJobs';
import { ArchitecturePane } from '../panes/ArchitecturePane';
import { FeedPane } from '../panes/FeedPane';
import { MetricsPane } from '../panes/MetricsPane';
import { QueueDepthPane } from '../panes/QueueDepthPane';
import { SubmitPane, type SubmitFields } from '../panes/SubmitPane';
import { WorkersPane } from '../panes/WorkersPane';

const CHAOS_BIAS = 0.5;

/**
 * The live QueueLab dashboard route: a tmux-style grid of panes driven by the WebSocket state, with
 * the submit / scale / destroy / chaos controls wired to the backend (Guide §2 "one pane, one job").
 */
export function Dashboard() {
  const identity = useSession();
  const state = useLiveState();
  const architecture = useArchitecture();
  const { submit, isSubmitting, error, accepted } = useSubmitJobs();
  const sessionId = identity?.session_id;
  const workers = deriveWorkers(state);

  function handleSubmit(fields: SubmitFields) {
    if (!sessionId) return;
    void submit({ session_id: sessionId, ...fields });
  }

  function handleDestroy(workerId?: string) {
    if (!sessionId) return;
    void destroyWorker(sessionId, workerId).catch(() => undefined);
  }

  function handleInjectFailures() {
    if (!sessionId) return;
    void injectFailures(sessionId, CHAOS_BIAS).catch(() => undefined);
  }

  // Scaling nudges the autoscaler floor relative to the running fleet (no manual-scale endpoint).
  function handleScaleUp() {
    void updateConfig({ min_workers: state.workerCount + 1 }).catch(() => undefined);
  }

  function handleScaleDown() {
    void updateConfig({ min_workers: Math.max(0, state.workerCount - 1) }).catch(() => undefined);
  }

  return (
    <div id="dashboard" className="space-y-6">
      <p id="dashboard-guest" className="text-sm text-fg-dim">
        you are {identity ? identity.guest_handle : 'connecting…'}
      </p>

      <MetricsPane
        counts={state.counts}
        queueDepth={state.queueDepth}
        workerCount={state.workerCount}
        isConnected={state.isConnected}
      />

      <div id="dashboard-grid" className="grid gap-6 lg:grid-cols-2">
        <QueueDepthPane counts={state.counts} depthHistory={state.depthHistory} />
        <WorkersPane
          workers={workers}
          onScaleUp={handleScaleUp}
          onScaleDown={handleScaleDown}
          onDestroy={handleDestroy}
          onInjectFailures={handleInjectFailures}
        />
        <SubmitPane
          guestHandle={identity?.guest_handle}
          onSubmit={handleSubmit}
          isSubmitting={isSubmitting}
          error={error}
          accepted={accepted}
          isDisabled={!sessionId}
        />
        <FeedPane lines={state.feed} />
      </div>

      <ArchitecturePane sections={architecture} />
    </div>
  );
}

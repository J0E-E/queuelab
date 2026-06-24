/** The five job states (mirrors the backend `JobState` vocabulary). */
export type JobState = 'queued' | 'running' | 'completed' | 'failed' | 'retrying';

/**
 * State → its status code, glyph, and phosphor color (Guide §3.2). State is conveyed by glyph +
 * code + color together, never color alone, so a colorblind or monochrome reader loses nothing.
 */
const STATE_BADGES: Record<JobState, { code: string; glyph: string; color: string }> = {
  queued: { code: 'QUEUED', glyph: '░', color: 'text-state-queued' },
  running: { code: 'RUN', glyph: '►', color: 'text-state-running' },
  completed: { code: 'DONE', glyph: '✓', color: 'text-state-completed' },
  failed: { code: 'FAIL', glyph: '✗', color: 'text-state-failed' },
  retrying: { code: 'RETRY', glyph: '↻', color: 'text-state-retrying' },
};

export interface StatusBadgeProps {
  /** Unique, descriptive id (project CLAUDE.md). */
  id: string;
  state: JobState;
}

/** A bracketed status badge — `► [RUN]` in the running phosphor (Guide §7.4). */
export function StatusBadge({ id, state }: StatusBadgeProps) {
  const badge = STATE_BADGES[state];
  return (
    <span id={id} className={`${badge.color} tracking-[0.02em]`}>
      {badge.glyph} [{badge.code}]
    </span>
  );
}

/** The five job states (mirrors the backend `JobState` vocabulary). */
export type JobState = 'queued' | 'running' | 'completed' | 'failed' | 'retrying';

/**
 * State → its status code, glyph, and phosphor color class (Guide §3.2). State is conveyed by glyph
 * + code + color together, never color alone, so a colorblind or monochrome reader loses nothing.
 *
 * Lives in its own module (not alongside a component) so both `StatusBadge` and the activity
 * `FeedLine` can share the one mapping without tripping react-refresh's component-only-exports rule.
 */
export const STATE_BADGES: Record<JobState, { code: string; glyph: string; color: string }> = {
  queued: { code: 'QUEUED', glyph: '░', color: 'text-state-queued' },
  running: { code: 'RUN', glyph: '►', color: 'text-state-running' },
  completed: { code: 'DONE', glyph: '✓', color: 'text-state-completed' },
  failed: { code: 'FAIL', glyph: '✗', color: 'text-state-failed' },
  retrying: { code: 'RETRY', glyph: '↻', color: 'text-state-retrying' },
};

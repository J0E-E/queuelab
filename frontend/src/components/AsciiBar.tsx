import type { JobState } from './stateBadges';

/** A bar's fill color: a job-state phosphor, or the default terminal green. */
export type BarState = JobState | 'default';

const FILL_COLORS: Record<BarState, string> = {
  default: 'text-fg',
  queued: 'text-state-queued',
  running: 'text-state-running',
  completed: 'text-state-completed',
  failed: 'text-state-failed',
  retrying: 'text-state-retrying',
};

export interface AsciiBarProps {
  /** Unique, descriptive id (project CLAUDE.md). */
  id: string;
  /** Proportion filled, `0..1` (clamped). */
  value: number;
  /** Total bar width in characters. */
  width?: number;
  /** Color the fill with a state hue (Guide §8). */
  state?: BarState;
}

/**
 * A raw ASCII proportion bar — `[||||||||......]  62%` (Guide §8). Filled cells are `|`, empty are
 * `.`, bracketed ends; the fill takes the relevant state hue. The terminal-native alternative to a
 * chart widget.
 */
export function AsciiBar({ id, value, width = 16, state = 'default' }: AsciiBarProps) {
  const clamped = Math.max(0, Math.min(1, value));
  const filled = Math.round(clamped * width);
  const bar = '|'.repeat(filled) + '.'.repeat(width - filled);
  const percent = Math.round(clamped * 100);
  return (
    <span id={id} className="tabular-nums">
      [<span className={FILL_COLORS[state]}>{bar}</span>]
      <span className="text-fg-dim"> {percent}%</span>
    </span>
  );
}

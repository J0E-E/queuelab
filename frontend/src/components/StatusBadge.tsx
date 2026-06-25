import { STATE_BADGES, type JobState } from './stateBadges';

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

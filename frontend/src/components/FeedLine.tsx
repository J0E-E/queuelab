import type { FeedEntry } from '../hooks/liveState';
import { STATE_BADGES, type JobState } from './stateBadges';

const KNOWN_STATES: readonly JobState[] = ['queued', 'running', 'completed', 'failed', 'retrying'];

function isJobState(state: string | null): state is JobState {
  return state !== null && (KNOWN_STATES as readonly string[]).includes(state);
}

export interface FeedLineProps {
  /** Unique, descriptive id (project CLAUDE.md). */
  id: string;
  /** The structured feed entry to render (Epic 17b). */
  entry: FeedEntry;
}

/**
 * One activity-feed line — `12:04:02  guest-teal  ✗ job-7 failed after 3 attempts` (Guide §7.6).
 *
 * Timestamp dim, the actor handle in its own color, the action in body color, and a leading state
 * glyph in that state's hue for a job line. The line is marked to its actor with a left accent in
 * the same color, so different visitors are separable at a glance (Epic 17b). The color is sent by
 * the backend (the palette has one home, `app.services.identity`), so this primitive holds no hex.
 *
 * Color only ever *reinforces*: the state is still carried by its glyph and the action's own words,
 * and red stays reserved for failure/dead (Guide §3.5 / §12) — a monochrome reader loses nothing.
 */
export function FeedLine({ id, entry }: FeedLineProps) {
  const { time, handle, color, action, state } = entry;
  const badge = isJobState(state) ? STATE_BADGES[state] : null;
  return (
    <div
      id={id}
      className={`border-l-2 pl-2 text-sm ${color ? '' : 'border-muted'}`}
      style={color ? { borderColor: color } : undefined}
    >
      <span id={`${id}-time`} className="text-fg-dim">
        {time}
      </span>{' '}
      {handle ? (
        <span
          id={`${id}-handle`}
          style={color ? { color } : undefined}
          className={color ? undefined : 'text-fg-dim'}
        >
          {handle}
        </span>
      ) : null}{' '}
      {badge ? (
        <span id={`${id}-state`} className={badge.color}>
          {badge.glyph}
        </span>
      ) : null}{' '}
      <span id={`${id}-action`} className="text-fg">
        {action}
      </span>
    </div>
  );
}

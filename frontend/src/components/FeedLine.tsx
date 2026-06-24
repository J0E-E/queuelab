import type { ReactNode } from 'react';

/**
 * The fixed, named guest-handle palette (Guide §3.4) — kept distinct from the job-state hues so a
 * handle is never confused for a state. A handle renders in its own color.
 */
const GUEST_COLORS: Record<string, string> = {
  teal: '#2dd4bf',
  pink: '#ff5fd2',
  lime: '#aaff00',
  sky: '#5ab0ff',
  orange: '#ff8c42',
  lavender: '#c77dff',
};

function guestColor(handle: string | undefined): string | undefined {
  if (!handle) return undefined;
  return GUEST_COLORS[handle.replace(/^guest-/, '')];
}

export interface FeedLineProps {
  /** Unique, descriptive id (project CLAUDE.md). */
  id: string;
  /** Timestamp, dim — `HH:MM:SS` (Guide §7.6). */
  time: string;
  /** Actor handle (`guest-teal`, `sys`, `worker-4`); a known guest renders in its color. */
  handle?: string;
  /** The action text, in body color. */
  children: ReactNode;
}

/**
 * One activity-feed line — `12:04:02  guest-teal  destroyed worker-3` (Guide §7.6). Timestamp dim,
 * handle in its guest color, action in body color. Lines stay static once shown (never animate the
 * whole log).
 */
export function FeedLine({ id, time, handle, children }: FeedLineProps) {
  const color = guestColor(handle);
  return (
    <div id={id} className="text-base">
      <span className="text-fg-dim">{time}</span>{' '}
      {handle ? (
        <span style={color ? { color } : undefined} className={color ? undefined : 'text-fg-dim'}>
          {handle}
        </span>
      ) : null}{' '}
      <span className="text-fg">{children}</span>
    </div>
  );
}

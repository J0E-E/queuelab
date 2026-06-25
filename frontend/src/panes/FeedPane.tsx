import { useEffect, useMemo, useRef, useState } from 'react';

import { FeedLine } from '../components/FeedLine';
import { Pane } from '../components/Pane';
import { PaneTitle } from '../components/PaneTitle';
import type { FeedEntry } from '../hooks/liveState';

/**
 * The failure lifecycle the failures-only view surfaces (Epic 17b): a will-retry failure
 * (`retrying`) and a dead one (`failed`, which this queue only emits once retries are exhausted).
 */
const FAILURE_STATES = new Set(['failed', 'retrying']);

function toggleClasses(isActive: boolean): string {
  const base =
    'uppercase tracking-[0.02em] focus-visible:outline focus-visible:outline-1 ' +
    'focus-visible:outline-accent';
  return isActive ? `${base} text-fg underline underline-offset-2` : `${base} text-fg-dim hover:text-fg`;
}

export interface FeedPaneProps {
  /** Structured activity entries from the backend, newest last. */
  entries: FeedEntry[];
}

/**
 * The activity feed pane (Guide §7.6). Append-only structured lines in an `aria-live` region so a
 * screen reader hears each system event. Each entry renders through `FeedLine`, which colors the
 * actor handle, marks the line to its actor, and tints the state glyph.
 *
 * An all / failures-only toggle filters the one pane down to the failure lifecycle (Epic 17b) —
 * will-retry and dead lines — without a second pane. An empty feed shows an honest waiting state
 * (Guide §2 "honest states").
 */
export function FeedPane({ entries }: FeedPaneProps) {
  const [failuresOnly, setFailuresOnly] = useState(false);
  const shown = useMemo(
    () =>
      failuresOnly
        ? entries.filter((entry) => entry.state !== null && FAILURE_STATES.has(entry.state))
        : entries,
    [entries, failuresOnly],
  );
  const emptyMessage = failuresOnly ? '> no failures yet' : '> waiting for activity…';

  // Tail the feed like a log: scroll to the newest line whenever the visible list changes (a new
  // entry arrives, or the filter toggles). Memoizing `shown` keeps this from firing on unrelated
  // re-renders (e.g. a metrics tick), so it only yanks to the bottom when the feed actually grows.
  const feedListRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const list = feedListRef.current;
    if (list && shown.length > 0) {
      list.scrollTop = list.scrollHeight;
    }
  }, [shown]);

  return (
    <Pane id="feed-pane">
      <PaneTitle id="feed-pane-title" title="activity feed" />
      <div id="feed-filter" role="group" aria-label="activity filter" className="flex gap-3 pt-2 pb-2 text-sm">
        <button
          id="feed-filter-all"
          type="button"
          aria-pressed={!failuresOnly}
          onClick={() => setFailuresOnly(false)}
          className={toggleClasses(!failuresOnly)}
        >
          all
        </button>
        <button
          id="feed-filter-failures"
          type="button"
          aria-pressed={failuresOnly}
          onClick={() => setFailuresOnly(true)}
          className={toggleClasses(failuresOnly)}
        >
          failures-only
        </button>
      </div>
      <div
        id="feed-list"
        ref={feedListRef}
        aria-live="polite"
        className="max-h-64 space-y-1 overflow-auto pt-3 text-sm"
      >
        {shown.length === 0 ? (
          <p id="feed-empty" className="text-fg-dim">
            {emptyMessage}
          </p>
        ) : (
          shown.map((entry, index) => (
            <FeedLine key={`${index}-${entry.line}`} id={`feed-line-${index}`} entry={entry} />
          ))
        )}
      </div>
    </Pane>
  );
}

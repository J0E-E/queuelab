import { Pane } from '../components/Pane';
import { PaneTitle } from '../components/PaneTitle';

export interface FeedPaneProps {
  /** Pre-formatted activity lines from the backend, newest last. */
  lines: string[];
}

/**
 * The activity feed pane (Guide §7.6). Append-only readable lines in an `aria-live` region so a
 * screen reader hears each system event. The backend formats each line, so this renders them
 * verbatim; an empty feed shows an honest waiting state (Guide §2 "honest states").
 */
export function FeedPane({ lines }: FeedPaneProps) {
  return (
    <Pane id="feed-pane">
      <PaneTitle id="feed-pane-title" title="activity feed" />
      <div
        id="feed-list"
        aria-live="polite"
        className="max-h-64 space-y-1 overflow-auto pt-3 text-base"
      >
        {lines.length === 0 ? (
          <p id="feed-empty" className="text-fg-dim">
            &gt; waiting for activity…
          </p>
        ) : (
          lines.map((line, index) => (
            <div key={`${index}-${line}`} id={`feed-line-${index}`} className="text-fg">
              {line}
            </div>
          ))
        )}
      </div>
    </Pane>
  );
}

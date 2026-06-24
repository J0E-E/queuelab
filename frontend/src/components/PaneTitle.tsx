import type { ReactNode } from 'react';

export interface PaneTitleProps {
  /** Unique, descriptive id (project CLAUDE.md). */
  id: string;
  /** Title text, rendered ALL-CAPS in brackets (Guide §4.2, §5.2). */
  title: string;
  /** Optional live status chip shown on the right, e.g. `● live` / `[ DRAINING ]` (Guide §7.2). */
  chip?: ReactNode;
}

/**
 * A pane's inverted-video title bar (Guide §5.2 / §7.2): a solid phosphor strip with near-black
 * text. One inverted block per pane, so the title reads as the window chrome.
 */
export function PaneTitle({ id, title, chip }: PaneTitleProps) {
  return (
    <header
      id={id}
      className="flex items-center justify-between bg-bg-invert px-2 text-sm uppercase tracking-[0.02em] text-bg"
    >
      <span>[ {title} ]</span>
      {chip ? <span>{chip}</span> : null}
    </header>
  );
}

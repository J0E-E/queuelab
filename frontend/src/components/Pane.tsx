import type { ReactNode } from 'react';

export interface PaneProps {
  /** Unique, descriptive id — required on every element (project CLAUDE.md). */
  id: string;
  /** Pane contents (padded monospaced columns/text). */
  children: ReactNode;
  /** Extra utility classes for the pane body. */
  className?: string;
  /** The focused pane's border brightens from muted to full phosphor (Guide §5.2). */
  isActive?: boolean;
}

/**
 * A bordered window — the Terminal-CLI "pane" every screen is laid out from (Guide §7.2).
 *
 * Depth comes from a 1px border (never a shadow) on a near-black raised surface; corners are
 * square (radius is disabled project-wide). The title bar is a separate primitive (`PaneTitle`)
 * composed inside when a pane needs one.
 */
export function Pane({ id, children, className, isActive = false }: PaneProps) {
  const borderColor = isActive ? 'border-fg' : 'border-muted';
  return (
    <section
      id={id}
      className={`border border-solid ${borderColor} bg-bg-raised p-4 ${className ?? ''}`}
    >
      {children}
    </section>
  );
}

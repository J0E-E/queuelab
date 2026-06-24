import type { ArchitectureSection } from '../lib/api';
import { Pane } from '../components/Pane';
import { PaneTitle } from '../components/PaneTitle';

export interface ArchitecturePaneProps {
  sections: ArchitectureSection[];
}

/**
 * The in-context architecture pane (Epic 15): the server-served notes that explain each mechanic
 * the live panes show, rendered beside them so the explanation is where the visitor is looking.
 */
export function ArchitecturePane({ sections }: ArchitecturePaneProps) {
  return (
    <Pane id="architecture-pane">
      <PaneTitle id="architecture-pane-title" title="architecture" />
      <div id="architecture-sections" className="space-y-4 pt-3">
        {sections.length === 0 ? (
          <p id="architecture-empty" className="text-fg-dim">
            &gt; loading notes…
          </p>
        ) : (
          sections.map((section) => (
            <div key={section.key} id={`architecture-section-${section.key}`}>
              <h3
                id={`architecture-title-${section.key}`}
                className="glow text-lg uppercase tracking-[0.02em] text-fg"
              >
                {section.title}
              </h3>
              <p id={`architecture-body-${section.key}`} className="text-sm text-fg-dim">
                {section.body}
              </p>
            </div>
          ))
        )}
      </div>
    </Pane>
  );
}

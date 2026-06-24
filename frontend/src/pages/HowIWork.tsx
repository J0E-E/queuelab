import { Pane } from '../components/Pane';
import { PaneTitle } from '../components/PaneTitle';

interface Section {
  key: string;
  heading: string;
  body: string;
}

const SECTIONS: Section[] = [
  {
    key: 'spec-driven',
    heading: 'Spec before code',
    body: 'Every feature starts as a brief, hardens into a technical design, then decomposes into small, independently reviewable epics with explicit dependencies. Nothing gets built until the open questions are closed — ambiguity is resolved on paper, where it is cheap.',
  },
  {
    key: 'thin-thread',
    heading: 'A thin thread, end to end',
    body: 'The first slice pierces every layer — a walking skeleton or a tracer bullet — and keeps its code. Real behavior, edge cases, and polish layer onto a structure that already holds together, so the system is demonstrable from the first epic.',
  },
  {
    key: 'review-loop',
    heading: 'A review loop with teeth',
    body: 'Each epic is planned, implemented, then reviewed against its deliverables and a green gate of build, lint, and tests. Findings are triaged and fixed before it lands. The reviewer is adversarial on purpose — a clean review means the gate passed on the final state, not the first draft.',
  },
  {
    key: 'git-history',
    heading: 'The proof is in the history',
    body: 'Every epic lands as one small, titled, reviewable commit. The git log reads as the build narrative — scaffold, core mechanics, real-time layer, frontend, infrastructure — each step green before the next began. The history is the receipt.',
  },
];

/** The "How I Work" explainer: the builder's process narrative (Epic 16, §5.11). */
export function HowIWork() {
  return (
    <main id="how-i-work" aria-labelledby="how-i-work-heading">
      <Pane id="how-i-work-pane">
        <PaneTitle id="how-i-work-title" title="how i work" />
        <h1 id="how-i-work-heading" className="sr-only">
          How I work
        </h1>
        <div id="how-i-work-sections" className="space-y-6 pt-3">
          {SECTIONS.map((section) => (
            <section key={section.key} id={`how-i-work-section-${section.key}`}>
              <h2
                id={`how-i-work-section-${section.key}-heading`}
                className="glow text-lg uppercase tracking-[0.02em] text-fg"
              >
                {section.heading}
              </h2>
              <p
                id={`how-i-work-section-${section.key}-body`}
                className="max-w-3xl pt-1 text-base text-fg-dim"
              >
                {section.body}
              </p>
            </section>
          ))}
        </div>
      </Pane>
    </main>
  );
}

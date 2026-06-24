import { Pane } from '../components/Pane';
import { PaneTitle } from '../components/PaneTitle';

interface Section {
  key: string;
  heading: string;
  body: string;
}

const SECTIONS: Section[] = [
  {
    key: 'queue',
    heading: 'A real queue, built from primitives',
    body: "QueueLab doesn't reach for a managed broker. The queue is assembled from raw Redis data structures — a ready list, a delayed sorted-set, per-worker processing lists, and a leases set — wired together with atomic Lua. Claiming, time-limited leases, retries with backoff, and recovery are all real, not simulated.",
  },
  {
    key: 'workers',
    heading: 'Workers that actually scale',
    body: 'Container workers claim jobs, run them, and ack or nack the result. A separate autoscaler reads the queue depth a couple of times a second and grows or trims the fleet — spawning real containers under load and retiring idle ones once the queue goes quiet.',
  },
  {
    key: 'chaos',
    heading: 'Break it, watch it heal',
    body: 'Destroy a worker mid-job and its lease lapses; the reaper requeues the job and the autoscaler stands up a replacement. Inject failures and the simulated work starts failing, then recovers on its own when the burst expires. The dashboard narrates the whole thing live.',
  },
  {
    key: 'payoff',
    heading: 'The point',
    body: 'Distributed-systems mechanics are usually invisible. Here they are on screen, moving, multiplayer, and honest — queues filling, workers claiming, retries firing, the autoscaler reacting — so you can see how the parts actually behave under load and under chaos.',
  },
];

/** The "How It Works" explainer: the product/architecture narrative (Epic 16, §5.11). */
export function HowItWorks() {
  return (
    <main id="how-it-works" aria-labelledby="how-it-works-heading">
      <Pane id="how-it-works-pane">
        <PaneTitle id="how-it-works-title" title="how it works" />
        <h1 id="how-it-works-heading" className="sr-only">
          How QueueLab works
        </h1>
        <div id="how-it-works-sections" className="space-y-6 pt-3">
          {SECTIONS.map((section) => (
            <section key={section.key} id={`how-it-works-section-${section.key}`}>
              <h2
                id={`how-it-works-section-${section.key}-heading`}
                className="glow text-lg uppercase tracking-[0.02em] text-fg"
              >
                {section.heading}
              </h2>
              <p
                id={`how-it-works-section-${section.key}-body`}
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

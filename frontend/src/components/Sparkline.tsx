/** Block ramp from lowest to highest (Guide §8 sparkline). */
const TICKS = ['▁', '▂', '▃', '▄', '▅', '▆', '▇', '█'];

export interface SparklineProps {
  /** Unique, descriptive id (project CLAUDE.md). */
  id: string;
  /** The series to plot; each value maps to one block, scaled across the series' own range. */
  values: number[];
}

/** Display-only window: show at most the last N buckets so a long session never overflows. */
const VISIBLE_BUCKETS = 30;

/**
 * A block sparkline — `▁▂▃▅▇▆▃▂` with the current value printed beside it (Guide §8). Used for a
 * metric over time (e.g. queue depth) without a chart library. Only the last `VISIBLE_BUCKETS`
 * samples are drawn (display-only; the stored history is untouched), each glyph given letter
 * spacing so individual time buckets read as distinct units rather than one smear.
 */
export function Sparkline({ id, values }: SparklineProps) {
  const shown = values.slice(-VISIBLE_BUCKETS);
  const max = Math.max(...shown, 1);
  const min = Math.min(...shown, 0);
  const range = max - min || 1;
  const spark = shown
    .map((value) => {
      const index = Math.floor(((value - min) / range) * (TICKS.length - 1));
      return TICKS[Math.max(0, Math.min(TICKS.length - 1, index))];
    })
    .join('');
  // Current value is always the newest stored sample, even though only the last window is plotted.
  const current = values.length ? values[values.length - 1] : 0;
  return (
    <span id={id} className="tabular-nums">
      <span className="glow text-fg tracking-[0.2em]">{spark}</span>{' '}
      <span className="text-fg-dim">{current}</span>
    </span>
  );
}

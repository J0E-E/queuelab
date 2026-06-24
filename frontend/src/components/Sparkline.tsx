/** Block ramp from lowest to highest (Guide §8 sparkline). */
const TICKS = ['▁', '▂', '▃', '▄', '▅', '▆', '▇', '█'];

export interface SparklineProps {
  /** Unique, descriptive id (project CLAUDE.md). */
  id: string;
  /** The series to plot; each value maps to one block, scaled across the series' own range. */
  values: number[];
}

/**
 * A block sparkline — `▁▂▃▅▇▆▃▂` with the current value printed beside it (Guide §8). Used for a
 * metric over time (e.g. queue depth) without a chart library.
 */
export function Sparkline({ id, values }: SparklineProps) {
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const range = max - min || 1;
  const spark = values
    .map((value) => {
      const index = Math.floor(((value - min) / range) * (TICKS.length - 1));
      return TICKS[Math.max(0, Math.min(TICKS.length - 1, index))];
    })
    .join('');
  const current = values.length ? values[values.length - 1] : 0;
  return (
    <span id={id} className="tabular-nums">
      <span className="glow text-fg">{spark}</span> <span className="text-fg-dim">{current}</span>
    </span>
  );
}

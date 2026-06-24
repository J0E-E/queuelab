import { useEffect, useRef, useState } from 'react';

export interface CounterProps {
  /** Unique, descriptive id (project CLAUDE.md). */
  id: string;
  /** The live value. */
  value: number;
  /** Optional inline delta — rendered `(+12)` / `(-3)` (Guide §8). */
  delta?: number;
  /** Optional trailing label. */
  label?: string;
  /** Zero-pad the value to this width (the dashboard shows `0142`). */
  pad?: number;
}

function prefersReducedMotion(): boolean {
  return Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches);
}

/**
 * A large live counter — `tabular-nums`, phosphor glow, with a brief amber tick-flash when the
 * value changes to signal "this is live" (Guide §8 / §9). The flash is suppressed under
 * `prefers-reduced-motion`.
 */
export function Counter({ id, value, delta, label, pad = 0 }: CounterProps) {
  const previousValue = useRef(value);
  const [isFlashing, setIsFlashing] = useState(false);

  useEffect(() => {
    if (previousValue.current === value) return;
    previousValue.current = value;
    if (prefersReducedMotion()) return;
    setIsFlashing(true);
    const timer = setTimeout(() => setIsFlashing(false), 120);
    return () => clearTimeout(timer);
  }, [value]);

  const text = pad > 0 ? String(value).padStart(pad, '0') : String(value);

  return (
    <span id={id} className="text-xl tabular-nums">
      <span className={isFlashing ? 'glow text-state-running' : 'glow text-fg'}>{text}</span>
      {delta !== undefined ? (
        <span className="text-sm text-fg-dim">
          {' '}
          ({delta >= 0 ? '+' : ''}
          {delta})
        </span>
      ) : null}
      {label ? <span className="text-sm text-fg-dim"> {label}</span> : null}
    </span>
  );
}

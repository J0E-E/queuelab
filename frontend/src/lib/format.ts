/** Small formatting helpers for the terminal-CLI dashboard. */

/** Format a Date as a `HH:MM:SS` shell-log clock (Guide §7.6). */
export function formatClock(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

/** Zero-pad a non-negative integer to a fixed column width (the dashboard shows `0142`). */
export function padCount(value: number, width: number): string {
  return String(value).padStart(width, '0');
}

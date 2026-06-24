/**
 * The CRT scanline overlay (Guide §9). A single fixed, `pointer-events-none`, decorative layer
 * mounted once at the app root. It carries no meaning (`aria-hidden`) and is zeroed out under
 * `prefers-reduced-motion` via the `.scanlines` rule in index.css.
 */
export function Scanlines() {
  return <div id="scanlines-overlay" className="scanlines" aria-hidden="true" />;
}

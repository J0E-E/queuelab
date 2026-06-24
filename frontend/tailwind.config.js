/**
 * Tailwind theme for the QueueLab terminal-CLI dashboard.
 *
 * The design tokens live as CSS custom properties in src/index.css (the single source of truth,
 * transcribed from .development-docs/ui-ux-style-guide.md §13). This theme only maps Tailwind
 * utility names onto those variables, so a component writes `text-fg` / `border-state-failed`
 * and never a hardcoded hex. Radius is forced to 0 everywhere (the Guide: no rounded corners).
 */
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: 'var(--color-bg)',
        'bg-raised': 'var(--color-bg-raised)',
        'bg-invert': 'var(--color-bg-invert)',
        fg: 'var(--color-fg)',
        'fg-dim': 'var(--color-fg-dim)',
        muted: 'var(--color-muted)',
        accent: 'var(--color-accent)',
        error: 'var(--color-error)',
        warn: 'var(--color-warn)',
        ok: 'var(--color-ok)',
        info: 'var(--color-info)',
        state: {
          queued: 'var(--state-queued)',
          running: 'var(--state-running)',
          completed: 'var(--state-completed)',
          failed: 'var(--state-failed)',
          retrying: 'var(--state-retrying)',
        },
      },
      fontFamily: {
        mono: 'var(--font-mono)',
      },
      fontSize: {
        hero: ['2.5rem', '1.1'],
        xl: ['1.75rem', '1.2'],
        lg: ['1.25rem', '1.3'],
        base: ['0.9375rem', '1.5'],
        sm: ['0.8125rem', '1.45'],
        xs: ['0.6875rem', '1.4'],
      },
      spacing: {
        1: '4px',
        2: '8px',
        3: '12px',
        4: '16px',
        6: '24px',
        8: '32px',
        12: '48px',
      },
      boxShadow: {
        // The Guide bans drop shadows; "glow" is a text-shadow token used via the .glow utility.
        none: 'none',
      },
    },
  },
  corePlugins: {
    // No rounded corners anywhere, ever (Guide §6) — drop the radius utilities entirely.
    borderRadius: false,
  },
  plugins: [],
};

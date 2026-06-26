import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// The brand logo ships as a standalone SVG used in an <img> (navbar + favicon) and copied to the
// joeys-hub portfolio. A browser renders an <img>-loaded SVG with a STRICT XML parser, so any
// well-formedness error (e.g. a forbidden "--" inside an XML comment) makes it fail to decode and
// show a broken-image icon. The build/test gate never parses the asset as XML, so guard it here.
// vitest runs with the frontend package root as the working directory.
const logoPath = resolve(process.cwd(), 'public/queuelab-logo.svg');

describe('brand logo asset', () => {
  it('is well-formed XML that a browser can decode', () => {
    const svg = readFileSync(logoPath, 'utf8');
    const parsed = new DOMParser().parseFromString(svg, 'image/svg+xml');
    // jsdom/browsers surface a <parsererror> element on malformed XML rather than throwing.
    expect(parsed.querySelector('parsererror')).toBeNull();
    expect(parsed.documentElement.tagName.toLowerCase()).toBe('svg');
  });

  it('has no forbidden double-hyphen inside XML comments', () => {
    const svg = readFileSync(logoPath, 'utf8');
    for (const comment of svg.match(/<!--[\s\S]*?-->/g) ?? []) {
      const inner = comment.slice(4, -3);
      expect(inner).not.toContain('--');
    }
  });
});

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { render, screen } from '@testing-library/react';

import { HowItWorks } from './HowItWorks';

describe('HowItWorks', () => {
  it('renders the narrative with a landmark and the closing payoff section', () => {
    render(<HowItWorks />);
    expect(document.getElementById('how-it-works')).toBeInTheDocument();
    expect(document.getElementById('how-it-works-heading')).toHaveTextContent('How QueueLab works');
    expect(document.getElementById('how-it-works-section-payoff-heading')).toBeInTheDocument();
  });

  it('shows the running-stack screenshot as proof, with its alt text', () => {
    render(<HowItWorks />);
    expect(document.getElementById('how-it-works-section-proof-heading')).toHaveTextContent(
      'Here it is, actually running',
    );
    const screenshot = screen.getByAltText(/running queuelab Docker Compose stack/i);
    expect(screenshot).toBe(document.getElementById('how-it-works-stack-screenshot'));
    expect(screenshot).toHaveAttribute('src', '/compose-stack.png');
  });
});

// The screenshot is a served static asset, so the jsdom <img> above never loads its bytes — a
// missing or empty public/compose-stack.png would still pass that test but ship a broken image.
// Guard the real file at gate time (mirrors brandLogo.test.ts). vitest's cwd is the package root.
const screenshotPath = resolve(process.cwd(), 'public/compose-stack.png');

describe('compose-stack screenshot asset', () => {
  it('is a non-empty PNG', () => {
    const bytes = readFileSync(screenshotPath);
    expect(bytes.length).toBeGreaterThan(0);
    // PNG signature: the first bytes are 0x89 'P' 'N' 'G'.
    expect(bytes.subarray(0, 4)).toEqual(Buffer.from([0x89, 0x50, 0x4e, 0x47]));
  });
});

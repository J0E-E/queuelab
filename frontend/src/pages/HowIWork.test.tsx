import { render } from '@testing-library/react';

import { HowIWork } from './HowIWork';

describe('HowIWork', () => {
  it('renders the process narrative with the git-history proof point', () => {
    render(<HowIWork />);
    expect(document.getElementById('how-i-work')).toBeInTheDocument();
    expect(document.getElementById('how-i-work-section-git-history-heading')).toHaveTextContent(
      'The proof is in the history',
    );
  });

  it('renders all six pipeline sections in narrative order', () => {
    render(<HowIWork />);
    const sectionKeys = [
      'spec-driven',
      'sliced-epics',
      'thin-thread',
      'generate',
      'review-loop',
      'git-history',
    ];
    for (const key of sectionKeys) {
      expect(document.getElementById(`how-i-work-section-${key}`)).toBeInTheDocument();
    }
  });

  it('keeps the bookend headings intact', () => {
    render(<HowIWork />);
    expect(document.getElementById('how-i-work-section-spec-driven-heading')).toHaveTextContent(
      'Spec before code',
    );
    expect(document.getElementById('how-i-work-section-git-history-heading')).toHaveTextContent(
      'The proof is in the history',
    );
  });

  it('frames the work as an AI-assisted, human-in-the-loop workflow', () => {
    render(<HowIWork />);
    const generateBody = document.getElementById('how-i-work-section-generate-body');
    expect(generateBody).toHaveTextContent(/AI-assisted workflow with a human in the loop/i);
  });

  it('omits the commit-history link while no href is set', () => {
    render(<HowIWork />);
    expect(document.getElementById('how-i-work-section-git-history-link')).not.toBeInTheDocument();
  });
});

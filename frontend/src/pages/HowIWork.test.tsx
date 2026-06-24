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
});

import { render } from '@testing-library/react';

import { HowItWorks } from './HowItWorks';

describe('HowItWorks', () => {
  it('renders the narrative with a landmark and the closing payoff section', () => {
    render(<HowItWorks />);
    expect(document.getElementById('how-it-works')).toBeInTheDocument();
    expect(document.getElementById('how-it-works-heading')).toHaveTextContent('How QueueLab works');
    expect(document.getElementById('how-it-works-section-payoff-heading')).toBeInTheDocument();
  });
});

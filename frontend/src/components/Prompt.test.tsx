import { render } from '@testing-library/react';

import { Prompt } from './Prompt';

describe('Prompt', () => {
  it('builds a shell prompt from the user, host, path and symbol', () => {
    render(<Prompt id="p" user="guest-amber" />);
    expect(document.getElementById('p')).toHaveTextContent('guest-amber@queuelab:~$');
  });

  it('omits the user@ segment when no user is given', () => {
    render(<Prompt id="p2" symbol=">" />);
    const prompt = document.getElementById('p2');
    expect(prompt).toHaveTextContent('queuelab:~>');
    expect(prompt).not.toHaveTextContent('@');
  });

  it('appends a blinking cursor only when requested', () => {
    const { rerender } = render(<Prompt id="p3" />);
    expect(document.getElementById('p3')).not.toHaveTextContent('█');
    rerender(<Prompt id="p3" hasCursor />);
    expect(document.getElementById('p3')).toHaveTextContent('█');
  });
});

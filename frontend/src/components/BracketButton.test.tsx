import { fireEvent, render } from '@testing-library/react';

import { BracketButton } from './BracketButton';

describe('BracketButton', () => {
  it('wraps its label in brackets and fires onClick', () => {
    const onClick = vi.fn();
    render(
      <BracketButton id="exec" onClick={onClick}>
        execute
      </BracketButton>,
    );
    const button = document.getElementById('exec') as HTMLButtonElement;
    expect(button).toHaveTextContent('[ execute ]');
    fireEvent.click(button);
    expect(onClick).toHaveBeenCalledOnce();
  });

  it('does not fire when disabled', () => {
    const onClick = vi.fn();
    render(
      <BracketButton id="b" onClick={onClick} isDisabled>
        go
      </BracketButton>,
    );
    const button = document.getElementById('b') as HTMLButtonElement;
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it('uses the red destructive styling for chaos actions', () => {
    render(
      <BracketButton id="d" variant="destructive">
        destroy
      </BracketButton>,
    );
    expect(document.getElementById('d')).toHaveClass('border-error', 'text-error');
  });
});

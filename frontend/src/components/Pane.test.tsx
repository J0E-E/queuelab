import { render, screen } from '@testing-library/react';

import { Pane } from './Pane';

describe('Pane', () => {
  it('renders its children inside the bordered window with the given id', () => {
    render(<Pane id="test-pane">hello queue</Pane>);
    const pane = document.getElementById('test-pane');
    expect(pane).toBeInTheDocument();
    expect(pane).toHaveTextContent('hello queue');
    expect(screen.getByText('hello queue')).toBeInTheDocument();
  });

  it('uses the muted border by default and the bright phosphor border when active', () => {
    const { rerender } = render(<Pane id="p">x</Pane>);
    expect(document.getElementById('p')).toHaveClass('border-muted');

    rerender(
      <Pane id="p" isActive>
        x
      </Pane>,
    );
    expect(document.getElementById('p')).toHaveClass('border-fg');
  });
});

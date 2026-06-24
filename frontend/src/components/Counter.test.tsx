import { render } from '@testing-library/react';

import { Counter } from './Counter';

describe('Counter', () => {
  it('zero-pads the value and renders the delta', () => {
    render(<Counter id="c" value={142} delta={12} pad={4} />);
    const counter = document.getElementById('c');
    expect(counter).toHaveTextContent('0142');
    expect(counter).toHaveTextContent('(+12)');
  });

  it('renders a negative delta with its sign', () => {
    render(<Counter id="c2" value={3} delta={-2} />);
    expect(document.getElementById('c2')).toHaveTextContent('(-2)');
  });

  it('renders an optional label', () => {
    render(<Counter id="c3" value={7} label="workers" />);
    expect(document.getElementById('c3')).toHaveTextContent('workers');
  });
});

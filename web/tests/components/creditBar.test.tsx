// web/tests/components/creditBar.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { CreditBar } from '@/components/CreditBar';

const segs = [
  { key: 'used', label: 'used', value: 200, color: '#fff' },
  { key: 'donatedC', label: 'donated', value: 50, color: 'green', opacity: 1 },
  { key: 'donatedR', label: 'donated-reserved', value: 100, color: 'green', opacity: 0.4 },
  { key: 'pledgedC', label: 'pledged', value: 100, color: 'orange', opacity: 1 },
  { key: 'pledgedR', label: 'pledged-reserved', value: 200, color: 'orange', opacity: 0.4 },
  { key: 'left', label: 'left', value: 350, color: 'blue' },
];

describe('CreditBar', () => {
  it('renders a segment per entry with proportional width and opacity', () => {
    const { container } = render(<CreditBar segments={segs} max={1000} />);
    const bars = container.querySelectorAll('[data-seg]');
    expect(bars.length).toBe(6);
    const used = container.querySelector('[data-seg="used"]') as HTMLElement;
    expect(used.style.flexBasis).toBe('20%');                  // 200/1000
    const pr = container.querySelector('[data-seg="pledgedR"]') as HTMLElement;
    expect(pr.style.opacity).toBe('0.4');
  });

  it('slider mode passes the numeric value via onChange and fires onCommit on mouseup', () => {
    const onChange = vi.fn(); const onCommit = vi.fn();
    render(<CreditBar segments={segs} max={1000}
      slider={{ value: 300, min: 100, max: 600, onChange, onCommit }} />);
    const range = screen.getByRole('slider') as HTMLInputElement;
    fireEvent.change(range, { target: { value: '450' } });
    expect(onChange).toHaveBeenLastCalledWith(450);
    fireEvent.mouseUp(range, { target: { value: '450' } });
    expect(onCommit).toHaveBeenLastCalledWith(450);
  });

  it('slider trackStart positions the input over the movable region only', () => {
    render(<CreditBar segments={segs} max={1000}
      slider={{ value: 300, min: 100, max: 600, trackStart: 0.6, onChange: () => {}, onCommit: () => {} }} />);
    const range = screen.getByRole('slider') as HTMLInputElement;
    expect(range.style.left).toBe('60%');
    expect(range.style.width).toBe('40%');   // 1 - trackStart
  });

  it('normalizes widths so an over-max segment set never exceeds 100%', () => {
    const over = [
      { key: 'a', label: 'a', value: 800, color: '#fff' },
      { key: 'b', label: 'b', value: 800, color: 'green' },
    ]; // sum 1600 > max 1000
    const { container } = render(<CreditBar segments={over} max={1000} />);
    const widths = Array.from(container.querySelectorAll('[data-seg]'))
      .map((el) => parseFloat((el as HTMLElement).style.flexBasis));
    const sum = widths.reduce((s, w) => s + w, 0);
    expect(sum).toBeLessThanOrEqual(100 + 0.01);
    // proportions preserved: a and b equal
    expect(widths[0]).toBeCloseTo(widths[1], 5);
  });
});

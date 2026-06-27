import { describe, it, expect } from 'vitest';
import { useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { NumberInput } from '@/components/NumberInput';

function Harness({ initial = 0, allowFloat = false }: { initial?: number; allowFloat?: boolean }) {
  const [v, setV] = useState(initial);
  return (
    <>
      <NumberInput aria-label="amt" value={v} onChange={setV} allowFloat={allowFloat} />
      <span data-testid="val">{String(v)}</span>
    </>
  );
}

describe('NumberInput', () => {
  it('does not keep a leading zero: typing 1 after 0 yields 1, not 01', async () => {
    render(<Harness initial={0} />);
    const input = screen.getByLabelText('amt') as HTMLInputElement;
    expect(input.value).toBe('0');
    await userEvent.type(input, '1');
    expect(input.value).toBe('1');
    expect(screen.getByTestId('val').textContent).toBe('1');
  });

  it('lets the field be cleared (the 0 char can be removed)', async () => {
    render(<Harness initial={5} />);
    const input = screen.getByLabelText('amt') as HTMLInputElement;
    await userEvent.clear(input);
    expect(input.value).toBe('');
    // cleared field reports the empty value (0) but is visually empty so the
    // user can type a fresh number
    expect(screen.getByTestId('val').textContent).toBe('0');
    await userEvent.type(input, '7');
    expect(input.value).toBe('7');
    expect(screen.getByTestId('val').textContent).toBe('7');
  });

  it('collapses multiple leading zeros while typing', async () => {
    render(<Harness initial={0} />);
    const input = screen.getByLabelText('amt') as HTMLInputElement;
    await userEvent.type(input, '0');   // "00" -> "0"
    expect(input.value).toBe('0');
    await userEvent.type(input, '25');  // "025" -> "25"
    expect(input.value).toBe('25');
    expect(screen.getByTestId('val').textContent).toBe('25');
  });

  it('resyncs the display when the value changes from outside', async () => {
    function ExternalHarness() {
      const [v, setV] = useState(3);
      return (
        <>
          <NumberInput aria-label="amt" value={v} onChange={setV} />
          <button onClick={() => setV(42)}>set</button>
        </>
      );
    }
    render(<ExternalHarness />);
    const input = screen.getByLabelText('amt') as HTMLInputElement;
    expect(input.value).toBe('3');
    await userEvent.click(screen.getByRole('button', { name: 'set' }));
    expect(input.value).toBe('42');
  });
});

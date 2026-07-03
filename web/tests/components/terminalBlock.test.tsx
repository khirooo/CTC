import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TerminalBlock } from '@/components/TerminalBlock';

describe('TerminalBlock', () => {
  it('renders the command, a copy affordance, and the terminal label', () => {
    render(<TerminalBlock command="curl -fsSL https://x/install.sh | sh" />);
    expect(screen.getByText(/curl -fsSL/)).toBeInTheDocument();
    expect(screen.getByText('Terminal')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /copy/i })).toBeInTheDocument();
  });

  it('renders the caption when given', () => {
    render(<TerminalBlock command="ctc" caption="Starts Copilot through CTC." />);
    expect(screen.getByText('Starts Copilot through CTC.')).toBeInTheDocument();
  });
});

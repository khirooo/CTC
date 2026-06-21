import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PatHelp } from '@/components/PatHelp';

afterEach(() => vi.unstubAllEnvs());

describe('PatHelp', () => {
  it('links the Generate button to the fine-grained token page when VITE_GHE_HOST is set', () => {
    vi.stubEnv('VITE_GHE_HOST', 'https://ghe.example.com/');
    render(<PatHelp />);
    const link = screen.getByRole('link', { name: /generate a token/i });
    // trailing slash on the host is trimmed
    expect(link).toHaveAttribute('href', 'https://ghe.example.com/settings/personal-access-tokens/new');
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('lists the required Copilot permissions', () => {
    vi.stubEnv('VITE_GHE_HOST', 'https://ghe.example.com');
    render(<PatHelp />);
    expect(screen.getByText(/Copilot Requests/)).toBeInTheDocument();
    expect(screen.getByText(/Copilot Editor Context/)).toBeInTheDocument();
    expect(screen.getByText(/Gists/)).toBeInTheDocument();
  });

  it('hides the Generate button but still shows steps when VITE_GHE_HOST is unset', () => {
    vi.stubEnv('VITE_GHE_HOST', '');
    render(<PatHelp />);
    expect(screen.queryByRole('link', { name: /generate a token/i })).toBeNull();
    expect(screen.getByText(/Copilot Requests/)).toBeInTheDocument();
  });
});

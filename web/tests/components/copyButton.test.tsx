// web/tests/components/copyButton.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { CopyButton } from '@/components/CopyButton';

beforeEach(() => {
  Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
});

describe('CopyButton', () => {
  it('copies text and shows Copied ✓', async () => {
    render(<CopyButton text="curl -fsSL https://x/install.sh | sh" />);
    const btn = screen.getByRole('button', { name: /copy/i });
    fireEvent.click(btn);
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('curl -fsSL https://x/install.sh | sh');
    await waitFor(() => expect(screen.getByText(/copied/i)).toBeInTheDocument());
  });
});

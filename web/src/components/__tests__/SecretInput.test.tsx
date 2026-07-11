import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SecretInput } from '../SecretInput';

describe('SecretInput', () => {
  it('masks by default with autofill/spellcheck off, and toggles visibility', async () => {
    const onChange = vi.fn();
    render(<SecretInput aria-label="Copilot license" value="github_pat_secret" onChange={onChange} />);

    const input = screen.getByLabelText('Copilot license') as HTMLInputElement;
    // Masked (password) with browser storage/autocorrect disabled.
    expect(input.type).toBe('password');
    expect(input.getAttribute('autocomplete')).toBe('off');
    expect(input.getAttribute('autocorrect')).toBe('off');
    expect(input.getAttribute('autocapitalize')).toBe('off');
    expect(input.getAttribute('spellcheck')).toBe('false');

    const toggle = screen.getByRole('button', { name: /show token/i });
    expect(toggle).toHaveAttribute('aria-pressed', 'false');

    await userEvent.click(toggle);
    expect(input.type).toBe('text');
    expect(screen.getByRole('button', { name: /hide token/i })).toHaveAttribute('aria-pressed', 'true');

    await userEvent.click(screen.getByRole('button', { name: /hide token/i }));
    expect(input.type).toBe('password');
  });

  it('reports typed characters through onChange', async () => {
    const onChange = vi.fn();
    render(<SecretInput aria-label="token" value="" onChange={onChange} />);
    await userEvent.type(screen.getByLabelText('token'), 'x');
    expect(onChange).toHaveBeenCalledWith('x');
  });
});

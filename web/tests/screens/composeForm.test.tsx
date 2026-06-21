import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ComposeForm } from '@/screens/Marketplace/ComposeForm';
import { ThemeProvider } from '@/theme/ThemeProvider';
import { NANO_PER_AIU } from '@/domain/credit';

function renderForm(onSubmit = vi.fn().mockResolvedValue(undefined)) {
  render(
    <ThemeProvider>
      <ComposeForm onSubmit={onSubmit} onCancel={vi.fn()} />
    </ThemeProvider>,
  );
  return onSubmit;
}

describe('ComposeForm expiry', () => {
  it('defaults expiryHours to 24 in the submitted input', async () => {
    const onSubmit = renderForm();
    await userEvent.click(screen.getByRole('button', { name: /^post request$/i }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ expiryHours: 24 }));
  });

  it('submits the chosen expiry preset', async () => {
    const onSubmit = renderForm();
    await userEvent.selectOptions(screen.getByLabelText(/expires in/i), '6');
    await userEvent.click(screen.getByRole('button', { name: /^post request$/i }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ expiryHours: 6, amountNeeded: 50 * NANO_PER_AIU }),
    );
  });
});

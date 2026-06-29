import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ComposeForm } from '@/screens/Marketplace/ComposeForm';
import { ThemeProvider } from '@/theme/ThemeProvider';
import { AppProvider } from '@/store/AppContext';
import { createMockApi } from '@/api/mockApi';
import { NANO_PER_AIU } from '@/domain/credit';

async function renderForm(onSubmit = vi.fn().mockResolvedValue(undefined)) {
  const api = createMockApi({ latencyMs: 0, storageKey: 'composeForm.test' });
  await api.signIn('ada@example.com', 'x');
  render(
    <ThemeProvider>
      <AppProvider api={api}>
        <ComposeForm onSubmit={onSubmit} onCancel={vi.fn()} />
      </AppProvider>
    </ThemeProvider>,
  );
  return onSubmit;
}

describe('ComposeForm expiry', () => {
  it('defaults expiryHours to 24 in the submitted input', async () => {
    const onSubmit = await renderForm();
    await userEvent.click(screen.getByRole('button', { name: /^post request$/i }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ expiryHours: 24 }));
  });

  it('submits the chosen expiry preset', async () => {
    const onSubmit = await renderForm();
    await userEvent.selectOptions(screen.getByLabelText(/expires in/i), '6');
    await userEvent.click(screen.getByRole('button', { name: /^post request$/i }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ expiryHours: 6, amountNeeded: 200 * NANO_PER_AIU }),
    );
  });
});

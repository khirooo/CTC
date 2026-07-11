import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ComposeForm } from '@/screens/Marketplace/ComposeForm';
import { ThemeProvider } from '@/theme/ThemeProvider';
import { AppProvider } from '@/store/AppContext';
import { makeFakeApi } from '../helpers/fakeApi';
import { NANO_PER_AIU } from '@/domain/credit';

async function renderForm(
  onSubmit = vi.fn().mockResolvedValue(undefined),
  api = makeFakeApi({ latencyMs: 0, storageKey: 'composeForm.test' }),
) {
  await api.signIn('ada@example.com', 'x');
  render(
    <ThemeProvider>
      <AppProvider api={api}>
        <ComposeForm onSubmit={onSubmit} onCancel={vi.fn()} />
      </AppProvider>
    </ThemeProvider>,
  );
  return { onSubmit, api };
}

describe('ComposeForm expiry', () => {
  it('defaults expiryHours to 24 in the submitted input', async () => {
    const { onSubmit } = await renderForm();
    await userEvent.click(screen.getByRole('button', { name: /^post request$/i }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ expiryHours: 24 }));
  });

  it('submits the chosen expiry preset', async () => {
    const { onSubmit } = await renderForm();
    await userEvent.selectOptions(screen.getByLabelText(/expires in/i), '6');
    await userEvent.click(screen.getByRole('button', { name: /^post request$/i }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ expiryHours: 6, amountNeeded: 200 * NANO_PER_AIU }),
    );
  });

  it('clamps the expiry options to the admin-set max (no preset above it, default snapped down)', async () => {
    // Admin caps expiry at 12h; default is 24h → should snap down to 12h and
    // offer no preset above 12h.
    const api = makeFakeApi({ latencyMs: 0, storageKey: 'composeForm.clamp' });
    await api.updateAdminSettings({ requestExpiryMaxHours: 12, requestExpiryHours: 24 });
    const { onSubmit } = await renderForm(vi.fn().mockResolvedValue(undefined), api);
    const select = screen.getByLabelText(/expires in/i) as HTMLSelectElement;
    // Session (hence the clamp) resolves after mount; wait for the options to trim.
    await waitFor(() => {
      const values = Array.from(select.options).map(o => Number(o.value));
      expect(values.every(v => v <= 12)).toBe(true);
      expect(values).not.toContain(24);
    });
    await userEvent.click(screen.getByRole('button', { name: /^post request$/i }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ expiryHours: 12 }));
  });
});

describe('ComposeForm directed target', () => {
  it('sends the selected giver as a userId, not a display name', async () => {
    const { onSubmit } = await renderForm();
    // Standings load async; wait for the seeded giver option (Yuki Tanaka = u_kef).
    const option = await screen.findByRole('option', { name: 'Yuki Tanaka' });
    const select = screen.getByLabelText(/ask/i) as HTMLSelectElement;
    await userEvent.selectOptions(select, option);
    await userEvent.click(screen.getByRole('button', { name: /^post request$/i }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ target: 'u_kef' }));
  });
});

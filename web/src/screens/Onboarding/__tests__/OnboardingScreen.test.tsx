import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { OnboardingScreen } from '../OnboardingScreen';
import * as AppCtx from '@/store/AppContext';

const NANO = 1_000_000_000;

/**
 * Discriminating test: backend `usedNano` = 3000 AIU, but the naive formula
 * (entitlement - remaining) = 4000 - 1200 = 2800 AIU.
 *
 * If the component reads the backend field, the legend shows "3,000.00 AIU".
 * If it falls back to the formula, it shows "2,800.00 AIU".
 * The test asserts the backend value (3000) is shown, not the formula (2800).
 * This proves the `used` figure is the backend's single source, not a TS recompute.
 */
describe('OnboardingScreen pledge step: used renders backend field', () => {
  it('renders backend used (3000 AIU), not entitlement−remaining formula (2800 AIU)', async () => {
    // Stub useApp so the screen sees a valid non-onboarded giver session.
    vi.spyOn(AppCtx, 'useApp').mockReturnValue({
      session: {
        userId: 'u1',
        name: 'Test User',
        role: 'giver' as const,
        onboarded: false,
        sharedPoolEnabled: true,
      },
      signIn: vi.fn(),
      signOut: vi.fn(),
      refresh: vi.fn(),
      api: {
        validatePat: vi.fn().mockResolvedValue({
          gheLogin: 'testuser',
          quotaAiu: 1200,
          entitlementAiu: 4000,
          remainingAiu: 1200,
          resetDate: null,
          pledgedNano: 0,
          // Backend says 3000 AIU used — NOT 4000 - 1200 = 2800.
          usedNano: 3000 * NANO,
        }),
        updateSettings: vi.fn().mockResolvedValue({}),
        markOnboarded: vi.fn().mockResolvedValue(undefined),
        getCliCredentials: vi.fn().mockResolvedValue({
          token: 'tok', proxyHost: 'localhost:8080',
          installCommand: 'ctc install', caFingerprint: null,
        }),
      } as any,
    } as any);

    render(
      <MemoryRouter initialEntries={['/onboarding']}>
        <Routes>
          <Route path="/onboarding" element={<OnboardingScreen />} />
          <Route path="/app/dashboard" element={<div>DASH</div>} />
          <Route path="/signin" element={<div>SIGNIN</div>} />
        </Routes>
      </MemoryRouter>,
    );

    // Navigate: role (giver is default) → Continue → PAT step
    await userEvent.click(screen.getByRole('button', { name: /continue/i }));

    // Enter PAT and validate
    await userEvent.type(screen.getByPlaceholderText(/github_pat/i), 'github_pat_abc');
    await userEvent.click(screen.getByRole('button', { name: /validate/i }));

    // Wait for the pledge step (CreditBar slider) to appear.
    await waitFor(() => expect(screen.getByRole('slider')).toBeInTheDocument());

    // The legend must show 3,000.00 (backend used), not 2,800.00 (formula).
    const legend = screen.getByTestId('credit-legend');
    expect(legend.textContent).toMatch(/3[,.]?000\.00/);
    expect(legend.textContent).not.toMatch(/2[,.]?800\.00/);
  });
});

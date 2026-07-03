import { type ReactNode } from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { OnboardingScreen } from '@/screens/Onboarding/OnboardingScreen';
import { AppProvider, useApp } from '@/store/AppContext';
import { RequireSession } from '@/app/guards';
import { ThemeProvider } from '@/theme/ThemeProvider';
import * as AppCtx from '@/store/AppContext';

function stubApp(api: any) {
  vi.spyOn(AppCtx, 'useApp').mockReturnValue({
    session: { userId: 'u1', name: 'Ada Lovelace', role: 'consumer', onboarded: false },
    signIn: vi.fn(), signUp: vi.fn(), completeOnboarding: vi.fn(),
    signOut: vi.fn(), api, refresh: vi.fn(),
  } as any);
}

function renderScreen() {
  render(
    <ThemeProvider>
      <MemoryRouter initialEntries={['/onboarding']}>
        <Routes>
          <Route path="/onboarding" element={<OnboardingScreen />} />
          <Route path="/app/dashboard" element={<div>DASH</div>} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

/**
 * Suppresses children until AppProvider has loaded the session (session !== null).
 * Without this, OnboardingScreen's `if (!session) <Navigate to="/signin">` fires on
 * the very first render (before getSession resolves) and we never see the wizard.
 */
function WaitForSession({ children }: { children: ReactNode }) {
  const { session } = useApp();
  if (session === null) return null;
  return <>{children}</>;
}

/**
 * Renders with the REAL AppProvider + RequireSession guard so the guard and the
 * wizard share one real React context. This is the only setup that exercises the
 * actual async race: if navigate('/app/dashboard') runs before the context session
 * is updated, RequireSession sees onboarded:false and bounces back to /onboarding.
 */
function renderWithRealGuard(mockApi: any) {
  render(
    <ThemeProvider>
      <AppProvider api={mockApi}>
        <WaitForSession>
          <MemoryRouter initialEntries={['/onboarding']}>
            <Routes>
              <Route path="/onboarding" element={<OnboardingScreen />} />
              {/* RequireSession is a layout route that uses <Outlet /> */}
              <Route element={<RequireSession />}>
                <Route path="/app/dashboard" element={<div>DASH</div>} />
              </Route>
              <Route path="/signin" element={<div>SIGNIN</div>} />
            </Routes>
          </MemoryRouter>
        </WaitForSession>
      </AppProvider>
    </ThemeProvider>,
  );
}

beforeEach(() => vi.restoreAllMocks());

const fakeSessionUserId = 'u1';

function defaultOnboardingApi(overrides: Record<string, unknown> = {}) {
  return {
    validatePat: vi.fn().mockResolvedValue({ gheLogin: 'ada', quotaAiu: 1500, pledgedNano: 150 * 1_000_000_000 }),
    updateSettings: vi.fn().mockResolvedValue({}),
    markOnboarded: vi.fn().mockResolvedValue(undefined),
    getCliCredentials: vi.fn().mockResolvedValue({
      token: 'github_pat_TOK', proxyHost: 'localhost:8080',
      installCommand: 'curl -fsSL https://localhost/install.sh | sh -s -- --token github_pat_TOK',
    }),
    ...overrides,
  };
}

function renderOnboarding(apiOverrides: Record<string, unknown> = {}) {
  stubApp(defaultOnboardingApi(apiOverrides));
  renderScreen();
}

describe('OnboardingScreen wizard', () => {
  it('giver path: validates PAT, shows quota, caps pledge slider to quota', async () => {
    const api = {
      validatePat: vi.fn().mockResolvedValue({ gheLogin: 'ada', quotaAiu: 1500, pledgedNano: 150 * 1_000_000_000 }),
      updateSettings: vi.fn().mockResolvedValue({}),
      markOnboarded: vi.fn().mockResolvedValue(undefined),
      getCliCredentials: vi.fn().mockResolvedValue({
        token: 'github_pat_TOK', proxyHost: 'localhost:8080',
        installCommand: 'curl -fsSL https://localhost/install.sh | sh -s -- --token github_pat_TOK',
      }),
    };
    stubApp(api);
    renderScreen();
    await userEvent.click(screen.getByRole("button", { name: /join as a host/i }));
    await userEvent.click(screen.getByRole('button', { name: /continue|next/i }));
    await userEvent.type(screen.getByPlaceholderText(/github_pat/i), 'github_pat_abc');
    await userEvent.click(screen.getByRole('button', { name: /validate|verify/i }));
    await waitFor(() => expect(screen.getByText(/@ada/)).toBeInTheDocument());
    expect(screen.getByText(/1,?500/)).toBeInTheDocument();
    const slider = await screen.findByRole('slider');
    expect(slider).toHaveAttribute('max', String(1500 * 1_000_000_000));
  });

  it('consumer path skips PAT/pledge and shows the install one-liner', async () => {
    const api = {
      validatePat: vi.fn(),
      updateSettings: vi.fn(),
      markOnboarded: vi.fn().mockResolvedValue(undefined),
      getCliCredentials: vi.fn().mockResolvedValue({
        token: 'github_pat_TOK', proxyHost: 'localhost:8080',
        installCommand: 'curl -fsSL https://localhost/install.sh | sh -s -- --token github_pat_TOK',
      }),
    };
    stubApp(api);
    renderScreen();
    await userEvent.click(screen.getByRole('button', { name: /guest/i }));
    await userEvent.click(screen.getByRole('button', { name: /continue|next/i }));
    await waitFor(() => expect(screen.getByText(/--token github_pat_TOK/)).toBeInTheDocument());
    expect(api.validatePat).not.toHaveBeenCalled();
  });

  it('Skip marks onboarded and navigates to the dashboard', async () => {
    const api = {
      validatePat: vi.fn(), updateSettings: vi.fn(),
      markOnboarded: vi.fn().mockResolvedValue(undefined),
      getCliCredentials: vi.fn().mockResolvedValue({ token: 't', proxyHost: 'p', installCommand: 'c' }),
    };
    stubApp(api);
    renderScreen();
    await userEvent.click(screen.getByRole('button', { name: /skip/i }));
    await waitFor(() => expect(screen.getByText('DASH')).toBeInTheDocument());
    expect(api.markOnboarded).toHaveBeenCalledOnce();
  });

  it('surfaces a PAT owner-mismatch error inline and stays on the step', async () => {
    const { CtcApiError } = await import('@/api/http');
    const api = {
      validatePat: vi.fn().mockRejectedValue(new CtcApiError('conflict', 'PAT belongs to bob, not ada', 409)),
      updateSettings: vi.fn(), markOnboarded: vi.fn(),
      getCliCredentials: vi.fn().mockResolvedValue({ token: 't', proxyHost: 'p', installCommand: 'c' }),
    };
    stubApp(api);
    renderScreen();
    await userEvent.click(screen.getByRole("button", { name: /join as a host/i }));
    await userEvent.click(screen.getByRole('button', { name: /continue|next/i }));
    await userEvent.type(screen.getByPlaceholderText(/github_pat/i), 'github_pat_x');
    await userEvent.click(screen.getByRole('button', { name: /validate|verify/i }));
    await waitFor(() => expect(screen.getByText(/belongs to bob/i)).toBeInTheDocument());
    expect(screen.getByPlaceholderText(/github_pat/i)).toBeInTheDocument(); // still on PAT step
  });

  it('shows an error if loading CLI setup fails on the consumer path', async () => {
    const { CtcApiError } = await import('@/api/http');
    const api = {
      validatePat: vi.fn(), updateSettings: vi.fn(),
      markOnboarded: vi.fn(),
      getCliCredentials: vi.fn().mockRejectedValue(new CtcApiError('error', 'CLI setup unavailable', 500)),
    };
    stubApp(api);
    renderScreen();
    await userEvent.click(screen.getByRole('button', { name: /guest/i }));
    await userEvent.click(screen.getByRole('button', { name: /continue|next/i }));
    await waitFor(() => expect(screen.getByText(/CLI setup unavailable/i)).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /guest/i })).toBeInTheDocument(); // still on role step
  });

  it('guard-inclusive: finish navigates through RequireSession without bouncing back to /onboarding', async () => {
    // Uses the REAL AppProvider + RequireSession so they share one React context —
    // the same session state that finish() writes to is the one RequireSession reads.
    //
    // In jsdom, Promise microtasks flush synchronously within userEvent.click() so the
    // browser-only race (navigate before context updates) doesn't manifest here; both
    // the old fire-and-forget and the new await-refresh paths eventually settle on DASH.
    // What this test locks down: the guard-inclusive round-trip works end-to-end —
    // RequireSession is satisfied after finish(), and DASH renders (no permanent loop).
    // A regression that breaks session propagation (e.g. markOnboarded not flipping
    // onboarded:true, or refresh not calling getSession) would cause an infinite loop
    // and this test would time out.
    let onboarded = false;
    const mockApi = {
      getSession: vi.fn().mockImplementation(() =>
        Promise.resolve({ userId: 'u1', name: 'Ada Lovelace', role: 'consumer' as const, onboarded }),
      ),
      markOnboarded: vi.fn().mockImplementation(() => {
        onboarded = true;
        return Promise.resolve();
      }),
      signIn: vi.fn(), signUp: vi.fn(), signOut: vi.fn(),
      completeOnboarding: vi.fn(),
      validatePat: vi.fn(), updateSettings: vi.fn(),
      getCliCredentials: vi.fn().mockResolvedValue({ token: 't', proxyHost: 'p', installCommand: 'c' }),
    };

    renderWithRealGuard(mockApi);

    // Wait for AppProvider to load the session (WaitForSession suppresses Router until then)
    // then the wizard shows (onboarded:false → /onboarding renders OnboardingScreen)
    await waitFor(() => expect(screen.getByRole('button', { name: /skip/i })).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /skip/i }));

    // After finish, we must land on the dashboard — NOT bounce back to onboarding
    await waitFor(() => expect(screen.getByText('DASH')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /skip/i })).not.toBeInTheDocument();
  });

  it('pledge step renders CreditBar slider with max=remainingAiu*NANO when entitlementAiu/remainingAiu differ', async () => {
    const NANO = 1_000_000_000;
    const api = {
      validatePat: vi.fn().mockResolvedValue({
        gheLogin: 'ada', quotaAiu: 1000,
        entitlementAiu: 1200, remainingAiu: 800,
      }),
      updateSettings: vi.fn().mockResolvedValue({}),
      markOnboarded: vi.fn().mockResolvedValue(undefined),
      getCliCredentials: vi.fn().mockResolvedValue({
        token: 't', proxyHost: 'p', installCommand: 'c',
      }),
    };
    stubApp(api);
    renderScreen();
    await userEvent.click(screen.getByRole("button", { name: /join as a host/i }));
    await userEvent.click(screen.getByRole('button', { name: /continue|next/i }));
    await userEvent.type(screen.getByPlaceholderText(/github_pat/i), 'github_pat_abc');
    await userEvent.click(screen.getByRole('button', { name: /validate|verify/i }));
    await waitFor(() => expect(screen.getByRole('slider')).toBeInTheDocument());
    const slider = screen.getByRole('slider');
    // max must equal remainingAiu * NANO (800 AIU), not quotaAiu or entitlementAiu
    expect(slider).toHaveAttribute('max', String(800 * NANO));
  });

  it('giver pledge-persist: updateSettings is called with the pledged nano amount', async () => {
    const api = {
      validatePat: vi.fn().mockResolvedValue({ gheLogin: 'ada', quotaAiu: 1000 }),
      updateSettings: vi.fn().mockResolvedValue({}),
      markOnboarded: vi.fn().mockResolvedValue(undefined),
      getCliCredentials: vi.fn().mockResolvedValue({
        token: 'github_pat_TOK', proxyHost: 'localhost:8080',
        installCommand: 'curl install',
      }),
    };
    stubApp(api);
    renderScreen();

    // Navigate to giver → PAT step
    await userEvent.click(screen.getByRole("button", { name: /join as a host/i }));
    await userEvent.click(screen.getByRole('button', { name: /continue|next/i }));

    // Enter PAT and validate
    await userEvent.type(screen.getByPlaceholderText(/github_pat/i), 'github_pat_abc');
    await userEvent.click(screen.getByRole('button', { name: /validate|verify/i }));

    // Wait for pledge step
    await waitFor(() => expect(screen.getByRole('slider')).toBeInTheDocument());

    // Click Save
    await userEvent.click(screen.getByRole('button', { name: /^Save/i }));

    // updateSettings must be called with a pledgedSurplus number
    await waitFor(() => expect(api.updateSettings).toHaveBeenCalledOnce());
    const [patch] = api.updateSettings.mock.calls[0];
    expect(patch).toHaveProperty('pledgedSurplus');
    expect(typeof patch.pledgedSurplus).toBe('number');
  });

  it('frames the role choice around having a license', async () => {
    renderOnboarding();
    expect(await screen.findByText('Do you have a GitHub Copilot license?')).toBeInTheDocument();
    expect(screen.getByText('Yes — join as a Host')).toBeInTheDocument();
    expect(screen.getByText('No — join as a Guest')).toBeInTheDocument();
    expect(screen.getByText(/If you can use Copilot in your IDE today/)).toBeInTheDocument();
  });

  it('shows a step indicator', async () => {
    renderOnboarding();
    expect(await screen.findByText(/Step 1 of/)).toBeInTheDocument();
  });

  it('explains why the PAT is needed before the input', async () => {
    renderOnboarding();
    fireEvent.click(await screen.findByText('Yes — join as a Host'));
    fireEvent.click(screen.getByRole('button', { name: /Continue/ }));
    expect(await screen.findByText(/measure your monthly quota/)).toBeInTheDocument();
  });

  it('install step is a numbered terminal ritual with explicit CTAs', async () => {
    renderOnboarding(); // as a consumer/Guest path
    fireEvent.click(await screen.findByText('No — join as a Guest'));
    fireEvent.click(screen.getByRole('button', { name: /Continue/ }));
    expect(await screen.findByText('Open a terminal on your laptop')).toBeInTheDocument();
    expect(screen.getByText('Paste this command and press Enter')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /I ran it — enter CTC/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /I'll do it later/ })).toBeInTheDocument();
  });

  it('"I ran it" persists installAck=true', async () => {
    localStorage.clear();
    renderOnboarding();
    fireEvent.click(await screen.findByText('No — join as a Guest'));
    fireEvent.click(screen.getByRole('button', { name: /Continue/ }));
    fireEvent.click(await screen.findByRole('button', { name: /I ran it — enter CTC/ }));
    await waitFor(() => {
      const uid = fakeSessionUserId;
      expect(JSON.parse(localStorage.getItem(`ctc:setup:${uid}`)!)?.installAck).toBe(true);
    });
  });
});

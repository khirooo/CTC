import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { AppShell } from '@/app/AppShell';
import { DashboardScreen } from '@/screens/Dashboard/DashboardScreen';
import { ThemeProvider } from '@/theme/ThemeProvider';
import { AppProvider } from '@/store/AppContext';
import { makeFakeApi } from '../helpers/fakeApi';

beforeEach(() => localStorage.clear());

async function setup(opts?: Parameters<typeof makeFakeApi>[0]) {
  const api = makeFakeApi({ now: () => 1_700_000_000_000, latencyMs: 0, storageKey: 'dash.test', ...opts });
  await api.signIn('ada@example.com', 'x');
  await api.completeOnboarding({ name: 'Ada', email: 'ada@example.com', role: 'giver', pledgedSurplus: 2000 });
  render(
    <ThemeProvider><AppProvider api={api}>
      <MemoryRouter initialEntries={['/app/dashboard']}>
        <Routes>
          <Route path="/app" element={<AppShell />}>
            <Route path="dashboard" element={<DashboardScreen />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </AppProvider></ThemeProvider>,
  );
  return api;
}

describe('dashboard', () => {
  it('renders the marketplace hero with the open-request count', async () => {
    await setup();
    await waitFor(() => expect(screen.getByText(/Credit marketplace/i)).toBeInTheDocument());
    // 3 open requests in seed (Lena, Diego, Priya unfunded/partial) — scoped to the hero
    expect(screen.getByTestId('hero-open-count')).toHaveTextContent('3');
    expect(screen.getByRole('heading', { name: /Overview/i })).toBeInTheDocument(); // topbar title
    // Cycle banner: number + label + reset countdown
    expect(screen.getByText('#7')).toBeInTheDocument();
    expect(screen.getByText(/July 2026/)).toBeInTheDocument();
    expect(screen.getByText(/resets in 12 days/i)).toBeInTheDocument();
    // Activity feed renamed to encompass pool + marketplace streams
    expect(screen.getByText('Live activity')).toBeInTheDocument();
  });

  it('givers_only + no PAT shows the license CTA instead of the dashboard', async () => {
    // Sign in as priya (no PAT in seed) in givers_only deployment mode
    const api = makeFakeApi({ latencyMs: 0, storageKey: 'dash.gonly', participantsMode: 'givers_only' });
    await api.signIn('priya@example.com', 'x');
    render(
      <ThemeProvider><AppProvider api={api}>
        <MemoryRouter initialEntries={['/app/dashboard']}>
          <Routes>
            <Route path="/app" element={<AppShell />}>
              <Route path="dashboard" element={<DashboardScreen />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </AppProvider></ThemeProvider>,
    );
    await waitFor(() =>
      expect(screen.getByText(/Add a license to continue/i)).toBeInTheDocument(),
    );
    // The normal marketplace hero should NOT be shown
    expect(screen.queryByText(/Credit marketplace/i)).not.toBeInTheDocument();
  });

  it('givers_only + user HAS a PAT shows the normal dashboard', async () => {
    // Sign in as ada (has PAT in seed) in givers_only deployment mode
    await setup({ storageKey: 'dash.gonly2', participantsMode: 'givers_only' });
    await waitFor(() => expect(screen.getByText(/Credit marketplace/i)).toBeInTheDocument());
    expect(screen.queryByText(/Add a license to continue/i)).not.toBeInTheDocument();
  });
});

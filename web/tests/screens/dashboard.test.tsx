import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { AppShell } from '@/app/AppShell';
import { DashboardScreen } from '@/screens/Dashboard/DashboardScreen';
import { ThemeProvider } from '@/theme/ThemeProvider';
import { AppProvider } from '@/store/AppContext';
import { createMockApi } from '@/api/mockApi';

async function setup() {
  const api = createMockApi({ now: () => 1_700_000_000_000, latencyMs: 0, storageKey: 'dash.test' });
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
}

describe('dashboard', () => {
  it('renders the marketplace hero with the open-request count', async () => {
    await setup();
    await waitFor(() => expect(screen.getByText(/Credit marketplace/i)).toBeInTheDocument());
    // 3 open requests in seed (Lena, Diego, Priya unfunded/partial) — scoped to the hero
    expect(screen.getByTestId('hero-open-count')).toHaveTextContent('3');
    expect(screen.getByRole('heading', { name: /Overview/i })).toBeInTheDocument(); // topbar title
  });
});

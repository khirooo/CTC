import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AppProvider } from '@/store/AppContext';
import { ThemeProvider } from '@/theme/ThemeProvider';
import { AdminScreen } from '@/screens/Admin/AdminScreen';
import { AppRoutes } from '@/app/routes';
import { createMockApi } from '@/api/mockApi';

function renderAdmin() {
  const api = createMockApi({ now: () => 1_700_000_000_000, latencyMs: 0, storageKey: 'admin.scr' });
  return render(
    <ThemeProvider>
      <AppProvider api={api}>
        <MemoryRouter><AdminScreen /></MemoryRouter>
      </AppProvider>
    </ThemeProvider>,
  );
}

beforeEach(() => localStorage.clear());

describe('AdminScreen', () => {
  it('renders the user list', async () => {
    renderAdmin();
    await waitFor(() => expect(screen.getAllByText(/host|guest/i).length).toBeGreaterThan(0));
  });

  it('reveals a PAT on click', async () => {
    renderAdmin();
    const btn = await screen.findAllByRole('button', { name: /reveal/i });
    fireEvent.click(btn[0]);
    await waitFor(() => expect(screen.getByText(/github_pat_mock_/)).toBeInTheDocument());
  });

  it('shows the settings form', async () => {
    renderAdmin();
    await waitFor(() => expect(screen.getByLabelText(/free allowance/i)).toBeInTheDocument());
  });
});

describe('RequireAdmin guard', () => {
  it('redirects a non-admin user away from /app/admin to /app/dashboard', async () => {
    // u_kef has no isAdmin — sign in as kef, then navigate to /app/admin
    const api = createMockApi({ now: () => 1_700_000_000_000, latencyMs: 0, storageKey: 'admin.guard' });
    await act(async () => {
      await api.signIn('kef@example.com', 'any');
    });
    render(
      <ThemeProvider>
        <AppProvider api={api}>
          <MemoryRouter initialEntries={['/app/admin']}>
            <AppRoutes />
          </MemoryRouter>
        </AppProvider>
      </ThemeProvider>,
    );
    // Should redirect to dashboard — users table must not be visible
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /reveal/i })).not.toBeInTheDocument(),
    );
  });
});

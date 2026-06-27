import { describe, it, expect, beforeEach, vi } from 'vitest';
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

  it('renders the participants mode select and shared pool toggle', async () => {
    renderAdmin();
    await waitFor(() => expect(screen.getByLabelText(/participants mode/i)).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /toggle shared pool/i })).toBeInTheDocument();
  });

  it('toggling shared pool and saving calls updateAdminSettings with sharedPoolEnabled', async () => {
    const api = createMockApi({ latencyMs: 0, storageKey: 'admin.toggle' });
    const spy = vi.spyOn(api, 'updateAdminSettings');
    render(
      <ThemeProvider>
        <AppProvider api={api}>
          <MemoryRouter><AdminScreen /></MemoryRouter>
        </AppProvider>
      </ThemeProvider>,
    );
    // Wait for the toggle button to appear (pool is ON by default)
    const toggleBtn = await screen.findByRole('button', { name: /toggle shared pool/i });
    expect(toggleBtn).toHaveTextContent('ON');

    // Click to toggle OFF
    fireEvent.click(toggleBtn);
    await waitFor(() => expect(toggleBtn).toHaveTextContent('OFF'));

    // Click save
    const saveBtn = screen.getByRole('button', { name: /save settings/i });
    fireEvent.click(saveBtn);
    await waitFor(() => expect(spy).toHaveBeenCalledWith(
      expect.objectContaining({ sharedPoolEnabled: false }),
    ));
  });

  it('changing participants mode and saving calls updateAdminSettings with participantsMode', async () => {
    const api = createMockApi({ latencyMs: 0, storageKey: 'admin.mode' });
    const spy = vi.spyOn(api, 'updateAdminSettings');
    render(
      <ThemeProvider>
        <AppProvider api={api}>
          <MemoryRouter><AdminScreen /></MemoryRouter>
        </AppProvider>
      </ThemeProvider>,
    );
    const modeSelect = await screen.findByLabelText(/participants mode/i);
    // Change from default to givers_only
    fireEvent.change(modeSelect, { target: { value: 'givers_only' } });

    const saveBtn = screen.getByRole('button', { name: /save settings/i });
    fireEvent.click(saveBtn);
    await waitFor(() => expect(spy).toHaveBeenCalledWith(
      expect.objectContaining({ participantsMode: 'givers_only' }),
    ));
  });

  it('renders the boot config card with web_transport', async () => {
    renderAdmin();
    await waitFor(() => expect(screen.getByText(/boot config/i)).toBeInTheDocument());
    expect(screen.getByText(/set in .env/i)).toBeInTheDocument();
    expect(screen.getByText('web_transport')).toBeInTheDocument();
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

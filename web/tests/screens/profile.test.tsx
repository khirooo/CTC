// web/tests/screens/profile.test.tsx
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AppProvider } from '@/store/AppContext';
import { ThemeProvider } from '@/theme/ThemeProvider';
import { ProfileScreen } from '@/screens/Profile/ProfileScreen';
import { createMockApi } from '@/api/mockApi';
import { CtcApiError } from '@/api/http';

function renderProfile(api: ReturnType<typeof createMockApi>) {
  render(
    <ThemeProvider><AppProvider api={api}>
      <MemoryRouter><ProfileScreen /></MemoryRouter>
    </AppProvider></ThemeProvider>);
}

beforeEach(() => localStorage.clear());

describe('ProfileScreen (merged profile + settings)', () => {
  it('Host: shows the credit bar legend with used/chipped in/pledged and a reset line', async () => {
    const api = createMockApi({ now: () => 1_700_000_000_000, latencyMs: 0, storageKey: 'prof.scr' });
    await api.signIn('ada@example.com', 'x');
    renderProfile(api);
    // legend swatch labels (exact, so the "(N used)" value text doesn't double-match)
    await waitFor(() => expect(screen.getByText('used')).toBeInTheDocument());
    expect(screen.getByText('pledged')).toBeInTheDocument();
    expect(screen.getByText('chipped in')).toBeInTheDocument();
    expect(screen.getByText(/resets/i)).toBeInTheDocument();
  });

  it('shows the GHE login as the immutable identity headline (no email field)', async () => {
    const api = createMockApi({ latencyMs: 0, storageKey: 'prof.login' });
    await api.signIn('ada@example.com', 'x');
    const login = (await api.getSettings()).login; // whatever identity the API reports
    renderProfile(api);
    await waitFor(() => expect(screen.getByText(login)).toBeInTheDocument());
    // the old editable Name/Email inputs are gone
    expect(screen.queryByRole('textbox', { name: /email/i })).toBeNull();
    expect(screen.queryByRole('textbox', { name: /name/i })).toBeNull();
  });

  it('connecting a license calls updateSettings({pat})', async () => {
    const api = createMockApi({ latencyMs: 0, storageKey: 's.pat' });
    await api.signIn('priya@example.com', 'x'); // a Guest in the seed (no license yet)
    const spy = vi.spyOn(api, 'updateSettings');
    renderProfile(api);
    const input = await screen.findByPlaceholderText(/github_pat_/i);
    fireEvent.change(input, { target: { value: 'ghp_newtoken' } });
    fireEvent.click(screen.getByRole('button', { name: /connect license/i }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ pat: 'ghp_newtoken' }));
  });

  it('giver: pledge slider commit calls updateSettings({pledgedSurplus})', async () => {
    const api = createMockApi({ latencyMs: 0, storageKey: 's.slider' });
    await api.signIn('ada@example.com', 'x'); // seed giver
    const profile = await api.getOwnProfile();
    const expectedMax = Math.max(
      profile.pledgedConsumed ?? 0,
      (profile.entitlement ?? 0) - (profile.used ?? 0) - (profile.donated ?? 0),
    );
    const spy = vi.spyOn(api, 'updateSettings');
    renderProfile(api);
    const slider = await screen.findByRole('slider');
    // max reflects entitlement − used − donated (not a hardcoded value)
    await waitFor(() => expect(Number(slider.getAttribute('max'))).toBe(expectedMax));
    const newVal = Math.floor(expectedMax / 2);
    fireEvent.change(slider, { target: { value: String(newVal) } });
    fireEvent.mouseUp(slider);
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(expect.objectContaining({ pledgedSurplus: newVal })),
    );
  });

  it('shows inline error and does not crash when a pledge save rejects', async () => {
    const api = createMockApi({ latencyMs: 0, storageKey: 'set.err.test' });
    await api.signIn('ada@example.com', 'x'); // seed giver already has a pledge
    const failingApi = Object.assign(Object.create(Object.getPrototypeOf(api)), api, {
      updateSettings: async () => {
        throw new CtcApiError('invalid_pledge', 'Cannot pledge more than your quota.', 422);
      },
    });
    renderProfile(failingApi as ReturnType<typeof createMockApi>);
    const slider = await screen.findByRole('slider');
    fireEvent.change(slider, { target: { value: '1000000000' } });
    fireEvent.mouseUp(slider);
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Cannot pledge more than your quota.');
    });
    // still rendered (no crash)
    expect(screen.getByRole('slider')).toBeInTheDocument();
  });

  it('pool OFF: hides the pledge slider for a giver when sharedPoolEnabled is false', async () => {
    const api = createMockApi({ latencyMs: 0, storageKey: 'prof.pool-off', sharedPoolEnabled: false });
    await api.signIn('ada@example.com', 'x'); // seed giver
    renderProfile(api);
    // Wait for data to load (identity card is always shown — login for u_ada is 'u_ada' since no email)
    await waitFor(() => expect(screen.getByText('u_ada')).toBeInTheDocument());
    // The pledge slider should NOT be present when pool is disabled
    expect(screen.queryByRole('slider')).not.toBeInTheDocument();
  });
});

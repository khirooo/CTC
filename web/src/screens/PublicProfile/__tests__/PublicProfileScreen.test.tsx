import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AppProvider } from '@/store/AppContext';
import { PublicProfileScreen } from '../PublicProfileScreen';
import type { PatHealth } from '@/domain/types';

const N = 1_000_000_000;

const hostProfile = {
  id: 'u_ada',
  name: 'Ada Lovelace',
  login: 'ada',
  initials: 'AL',
  role: 'giver' as const,
  tier: 'baron',
  net: 200 * N,
  donated: 300 * N,
  donationsMade: 2,
  entitlement: 4000 * N,
  used: 2800 * N,
  pledged: 120 * N,
  pledgedConsumed: 0,
  pledgedRemaining: 120 * N,
  donatedConsumed: 0,
  donatedRemaining: 300 * N,
  left: 780 * N,
  unlimited: false,
  patHealth: null as PatHealth | null,
  patHealthCheckedAt: null as number | null,
};

const session = {
  userId: 'u_visitor',
  name: 'Visitor',
  role: 'consumer' as const,
  onboarded: true,
};

function renderProfile(profile: Record<string, unknown>) {
  const api = {
    getSession: vi.fn(async () => session),
    getUserProfile: vi.fn(async () => profile),
  };
  render(
    <MemoryRouter initialEntries={['/app/users/u_ada']}>
      <AppProvider api={api as any}>
        <PublicProfileScreen />
      </AppProvider>
    </MemoryRouter>,
  );
  return api;
}

describe('PublicProfileScreen license state', () => {
  it('flags a host whose Copilot license expired', async () => {
    renderProfile({ ...hostProfile, patHealth: 'expired', patHealthCheckedAt: 1_770_000_000 });

    expect(await screen.findByText('Expired')).toBeInTheDocument();
    const warning = document.querySelector('[data-license-warning]');
    expect(warning?.textContent).toMatch(/stopped working/);
    // The visitor is told the numbers are historical, not spendable.
    expect(warning?.textContent).toMatch(/last state CTC could read/);
    expect(document.querySelector('[data-public-credit-bar]')?.textContent)
      .toMatch(/last known/);
  });

  it.each<[PatHealth, RegExp]>([
    ['forbidden', /missing the permissions/],
    ['no_entitlement', /no Copilot quota/],
    ['no_copilot_permission', /missing the Copilot Requests permission/],
    ['unreachable', /couldn't reach GitHub/],
  ])('explains the %s state', async (health, expected) => {
    renderProfile({ ...hostProfile, patHealth: health });

    await waitFor(() => expect(document.querySelector('[data-license-warning]')).toBeTruthy());
    expect(document.querySelector('[data-license-warning]')?.textContent).toMatch(expected);
  });

  it('replaces the tier badge rather than showing an Unranked one', async () => {
    // The backend drops a dead-license host from the standings, so tier arrives
    // null; showing "Unranked" next to "Expired" would say the same thing twice.
    renderProfile({ ...hostProfile, tier: null, net: null, patHealth: 'expired' });

    expect(await screen.findByText('Expired')).toBeInTheDocument();
    expect(screen.queryByText('Unranked')).toBeNull();
    expect(screen.queryByText(/Not yet ranked/)).toBeNull();
    expect(document.querySelector('[data-license-warning]')?.textContent)
      .toMatch(/out of the standings/);
  });

  it('keeps the tier badge for a host CTC merely could not reach', async () => {
    // Unreachable is not a verdict: the host is still ranked, so the badge stays.
    renderProfile({ ...hostProfile, patHealth: 'unreachable' });

    expect(await screen.findByText('Baron')).toBeInTheDocument();
    expect(document.querySelector('[data-license-warning]')?.textContent)
      .not.toMatch(/out of the standings/);
  });

  it('stays quiet for a healthy license', async () => {
    renderProfile({ ...hostProfile, patHealth: 'valid' });

    expect(await screen.findByText('Ada Lovelace')).toBeInTheDocument();
    expect(document.querySelector('[data-license-warning]')).toBeNull();
    expect(screen.queryByText('Valid')).toBeNull();   // healthy is the assumption
    expect(document.querySelector('[data-public-credit-bar]')?.textContent)
      .not.toMatch(/last known/);
  });

  it('stays quiet when the license was never checked', async () => {
    renderProfile(hostProfile);   // patHealth: null

    expect(await screen.findByText('Ada Lovelace')).toBeInTheDocument();
    expect(document.querySelector('[data-license-warning]')).toBeNull();
  });

  it('never flags a guest', async () => {
    renderProfile({
      id: 'u_bob', name: 'Bob', login: 'bob', initials: 'B', role: 'consumer',
      tier: null, net: null, donated: null, donationsMade: null, patHealth: null,
    });

    expect(await screen.findByText('Bob')).toBeInTheDocument();
    expect(document.querySelector('[data-license-warning]')).toBeNull();
  });
});

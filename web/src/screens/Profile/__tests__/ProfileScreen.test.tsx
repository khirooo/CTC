import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AppProvider } from '@/store/AppContext';
import { ProfileScreen } from '../ProfileScreen';

const N = 1_000_000_000;

/**
 * Discriminating DTO: backend `left` is intentionally clamped to 900 AIU,
 * while the naive JS formula (E - used - donated - pledged) = 4000 - 2800 - 0 - 120 = 1080.
 * If the component recomputes, it renders 1,080.00 AIU; if it reads the backend field,
 * it renders 900.00 AIU.  The test asserts the backend value appears in the legend.
 */
const giverProfile = {
  user: { id: 'u1', name: 'Alice', login: 'alice', initials: 'AL', role: 'giver' as const },
  totalCredit: 4000 * N,
  pledgedSurplus: 120 * N,
  retained: null,
  donatedSoFar: 0,
  allowance: null,
  consumed: 0,
  donationsReceived: 0,
  entitlement: 4000 * N,
  remaining: 900 * N,
  used: 2800 * N,
  pledged: 120 * N,
  donated: 0,
  left: 900 * N,           // backend-clamped; naive formula would produce 1080
  pledgedConsumed: 0,
  donatedConsumed: 0,
  donatedRemaining: 0,
  pledgedRemaining: 120 * N,
  allowanceMax: null,
  allowanceUsed: null,
  allowanceLeft: null,
  resetDate: null,
  unlimited: false,
  quotaStale: false,
  tier: null,
  net: null,
  netToNext: null,
};

const giverSettings = {
  name: 'Alice',
  login: 'alice',
  role: 'giver' as const,
  hasPat: true,
  totalCredit: 4000 * N,
  pledgedSurplus: 120 * N,
  allowance: null,
};

const giverSession = {
  userId: 'u1',
  name: 'Alice',
  role: 'giver' as const,
  onboarded: true,
  sharedPoolEnabled: true,
};

function makeApi(overrides?: Partial<Record<string, unknown>>) {
  return {
    getSession: vi.fn(async () => giverSession),
    getOwnProfile: vi.fn(async () => giverProfile),
    getSettings: vi.fn(async () => giverSettings),
    getCliCredentials: vi.fn(async () => ({ token: 'tok', proxyHost: 'localhost:8080', installCommand: 'ctc install', caFingerprint: null })),
    ...overrides,
  };
}

function renderProfile(api = makeApi()) {
  return render(
    <MemoryRouter>
      <AppProvider api={api as any}>
        <ProfileScreen />
      </AppProvider>
    </MemoryRouter>,
  );
}

describe('ProfileScreen credit figures', () => {
  it('renders backend left verbatim (900 AIU), not the naive JS recompute (1,080 AIU)', async () => {
    renderProfile();

    // The backend `left` field is 900 AIU; the naive formula (E - used - donated - pledged)
    // gives 1,080.  The legend "available" entry must show the backend value.
    const legend = await screen.findByTestId('credit-legend');

    // 900.00 AIU must appear (backend field rendered)
    expect(legend.textContent).toMatch(/900\.00/);

    // 1,080.00 must NOT appear (client recompute absent)
    expect(legend.textContent).not.toMatch(/1,080\.00|1080\.00/);
  });

  it('renders backend pledgedRemaining in the legend while not editing', async () => {
    renderProfile();
    const legend = await screen.findByTestId('credit-legend');
    // pledgedRemaining = 120 AIU (same as pledgedValue here; just verify it renders)
    expect(legend.textContent).toMatch(/120\.00/);
  });
});

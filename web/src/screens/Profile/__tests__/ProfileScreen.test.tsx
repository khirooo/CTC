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

  /**
   * Discriminating test for the pledgedR bar segment.
   *
   * DTO: pledged=120*N, pledgedConsumed=0, pledgedRemaining=90*N (backend-clamped).
   * The old client recompute (pledged - pledgedConsumed) = 120*N → flexBasis ~3%.
   * The backend field pledgedRemaining = 90*N → flexBasis ~2.25%.
   *
   * pledgedRemaining only feeds the pledgedR bar segment (visual width); it is not
   * rendered as a text figure anywhere in the legend. The discriminating assertion
   * therefore checks the data-seg="pledgedR" element's inline flexBasis style:
   * 2.25% (backend field) vs 3% (old recompute). The test renders with poolOn and
   * localPledged===null (no drag — default render state, no user interaction needed).
   */
  it('pledgedR segment reads backend pledgedRemaining (2.25%), not client recompute (3%)', async () => {
    // Override giverProfile: pledgedRemaining=90*N, pledged=120*N, pledgedConsumed=0.
    // old formula: 120-0 = 120 → 3.00%; backend field: 90 → 2.25%.
    const api = makeApi({
      getOwnProfile: vi.fn(async () => ({
        ...giverProfile,
        pledgedRemaining: 90 * N,   // backend-clamped value
        pledged: 120 * N,
        pledgedConsumed: 0,
      })),
    });
    const { container } = renderProfile(api);

    // Wait for async data to load (legend is rendered after profile resolves)
    await screen.findByTestId('credit-legend');

    const pledgedRSeg = container.querySelector('[data-seg="pledgedR"]') as HTMLElement | null;
    expect(pledgedRSeg).not.toBeNull();

    // With E=4000*N as max/denom, pledgedRemaining=90*N → 90/4000*100 = 2.25%
    // If the component recomputed (120*N / 4000*N)*100 = 3% instead.
    const flexBasis = pledgedRSeg!.style.flexBasis;
    expect(flexBasis).toBe('2.25%');   // backend field
    expect(flexBasis).not.toBe('3%');  // old recompute absent
  });
});

import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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
    listProxyTokens: vi.fn(async () => []),
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

describe('ProfileScreen CLI setup: mint only on explicit action', () => {
  it('does not mint a proxy token on mount, and mints exactly once per click', async () => {
    const api = makeApi();
    render(
      <MemoryRouter>
        <AppProvider api={api as any}>
          <ProfileScreen />
        </AppProvider>
      </MemoryRouter>,
    );

    // The "Generate install command" button appears once data loads.
    const btn = await screen.findByRole('button', { name: /generate install command/i });
    // No mint happened on mount — only the read-only token list was fetched.
    expect(api.getCliCredentials).not.toHaveBeenCalled();
    expect(api.listProxyTokens).toHaveBeenCalledTimes(1);

    await userEvent.click(btn);
    await waitFor(() => expect(api.getCliCredentials).toHaveBeenCalledTimes(1));
  });

  it('lists only non-revoked tokens as active (revoked rows are kept for history)', async () => {
    // 2 active + 3 revoked → header says "2", and 3 shown as hidden/revoked.
    const api = makeApi({
      listProxyTokens: vi.fn(async () => [
        { id: 'a', fingerprint: 'aaaa1111', createdAt: 1, revoked: false },
        { id: 'b', fingerprint: 'bbbb2222', createdAt: 2, revoked: true },
        { id: 'c', fingerprint: 'cccc3333', createdAt: 3, revoked: true },
        { id: 'd', fingerprint: 'dddd4444', createdAt: 4, revoked: false },
        { id: 'e', fingerprint: 'eeee5555', createdAt: 5, revoked: true },
      ]),
    });
    renderProfile(api);
    const msg = await screen.findByText(/active install token/i);
    expect(msg.textContent).toMatch(/2 active install tokens/);
    expect(msg.textContent).not.toMatch(/5 active/);
    // active fingerprints listed, revoked ones not
    expect(screen.getByText('aaaa1111')).toBeTruthy();
    expect(screen.getByText('dddd4444')).toBeTruthy();
    expect(screen.queryByText('bbbb2222')).toBeNull();
    expect(screen.getByText(/3 revoked tokens \(hidden\)/)).toBeTruthy();
  });

  it('revokes a token and drops it from the active list', async () => {
    const revokeProxyToken = vi.fn(async () => {});
    let listCall = 0;
    const api = makeApi({
      revokeProxyToken,
      // first load returns two active; after revoke, reload returns one
      listProxyTokens: vi.fn(async () => {
        listCall += 1;
        return listCall === 1
          ? [
              { id: 'a', fingerprint: 'aaaa1111', createdAt: 1, revoked: false },
              { id: 'd', fingerprint: 'dddd4444', createdAt: 4, revoked: false },
            ]
          : [{ id: 'd', fingerprint: 'dddd4444', createdAt: 4, revoked: false }];
      }),
    });
    renderProfile(api);
    const revokeBtn = await screen.findByRole('button', { name: /revoke token aaaa1111/i });
    await userEvent.click(revokeBtn);
    await waitFor(() => expect(revokeProxyToken).toHaveBeenCalledWith('a'));
    await waitFor(() => expect(screen.queryByText('aaaa1111')).toBeNull());
    expect(screen.getByText('dddd4444')).toBeTruthy();
  });
});

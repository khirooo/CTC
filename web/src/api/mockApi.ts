import type { CtcApi, ListRequestsResult } from '@/api/CtcApi';
import type {
  PublicRequest,
  CreateRequestInput,
  DashboardData,
  Leaderboard,
  OwnProfile,
  SettingsData,
  SettingsPatch,
  Session,
  OnboardingInput,
  CycleReport,
  ActivityEntry,
  LeaderboardEntry,
  AdminUser,
  AdminUserDetail,
  AdminSettings,
  AdminSettingsPatch,
  AdminBootConfig,
} from '@/domain/types';
import { deriveStatus, donationKind, NANO_PER_AIU } from '@/domain/credit';
import { CtcApiError } from './http';
import { makeSeed, type StoreState, type SeedRequest, type SeedUser } from '@/api/seed';
import type { Donation } from '@/domain/types';
import { load, save } from '@/api/persist';

const SESSION_KEY = 'ctc.session.v1';
const DEFAULT_STORE_KEY = 'ctc.store.v1';

// Deterministic 8-char fingerprint for a user id (no real crypto needed in mock).
function fp(id: string): string {
  let h = 0;
  for (let i = 0; i < id.length; i++) {
    h = Math.imul(31, h) + id.charCodeAt(i) | 0;
  }
  return (h >>> 0).toString(16).padStart(8, '0').slice(0, 8);
}

// DEV-ONLY mirror of backend assign_tiers (ctc/accounting/tiers.py).
// The real app gets standings/tier from the API; this only powers the mock.
function mockAssignTiers(
  givers: { name: string; net: number; active: boolean }[],
): { name: string; net: number; tier: string }[] {
  const pos = givers.filter(g => g.active && g.net >= 0).sort((a, b) => b.net - a.net || a.name.localeCompare(b.name));
  const neg = givers.filter(g => g.active && g.net < 0).sort((a, b) => a.net - b.net || a.name.localeCompare(b.name));
  const newc = givers.filter(g => !g.active).sort((a, b) => a.name.localeCompare(b.name));
  const POS = ['aristocrat', 'baron', 'bourgeois', 'commoner'];
  const NEG = ['beggar', 'peasant'];
  const out: { name: string; net: number; tier: string }[] = [];
  pos.forEach((g, i) => out.push({ name: g.name, net: g.net, tier: POS[Math.floor((i * 4) / pos.length)] }));
  neg.forEach((g, j) => out.push({ name: g.name, net: g.net, tier: NEG[Math.floor((j * 2) / neg.length)] }));
  out.sort((a, b) => b.net - a.net || a.name.localeCompare(b.name));
  newc.forEach(g => out.push({ name: g.name, net: 0, tier: 'newcomer' }));
  return out;
}

const DEFAULT_BOOT_CONFIG: AdminBootConfig = {
  webTransport: 'http',
};

const DEFAULT_ADMIN_SETTINGS: AdminSettings = {
  freeAllowanceAiu:      { value: 300,   isOverride: false },
  defaultPledgePct:      { value: 0,     isOverride: false },
  requestExpiryHours:    { value: 24,    isOverride: false },
  requestExpiryMaxHours: { value: 168,   isOverride: false },
  creditToEuroRate:      { value: 0.1,   isOverride: false },
  participantsMode:      { value: 'givers_and_consumers', isOverride: false },
  sharedPoolEnabled:     { value: true,  isOverride: false },
  boot:                  DEFAULT_BOOT_CONFIG,
};

interface MockApiOpts {
  now?: () => number;
  latencyMs?: number;
  storageKey?: string;
  /** Deployment mode flags — defaults match "full-featured" mode */
  participantsMode?: 'givers_only' | 'givers_and_consumers';
  sharedPoolEnabled?: boolean;
}

function toPublic(r: SeedRequest, now: number, viewerId?: string): PublicRequest {
  return {
    id: r.id,
    requesterName: r.requesterName,
    initials: r.initials,
    requesterRole: r.requesterRole,
    amountNeeded: r.amountNeeded,
    amountFunded: r.amountFunded,
    reason: r.reason,
    target: r.target,
    createdAt: r.createdAt,
    expiresAt: r.expiresAt,
    status: deriveStatus(r.amountFunded, r.amountNeeded, r.expiresAt, now),
    donorCount: r.donorCount,
    isOwn: !!viewerId && r.requesterId === viewerId,
  };
}

// Map email to known user id; default to u_ada for any ada@ address
function emailToUserId(email: string): string {
  const lower = email.toLowerCase();
  if (lower.includes('ada') || lower === 'ada@example.com') return 'u_ada';
  if (lower.includes('kef') || lower.includes('yuki')) return 'u_kef';
  if (lower.includes('sofia') || lower.includes('sl')) return 'u_sl';
  if (lower.includes('marco') || lower.includes('mb')) return 'u_mb';
  if (lower.includes('amine') || lower.includes('at')) return 'u_at';
  if (lower.includes('lena') || lower.includes('lh')) return 'u_lh';
  if (lower.includes('diego') || lower.includes('dr')) return 'u_dr';
  if (lower.includes('priya') || lower.includes('pn')) return 'u_pn';
  // Default to ada for any unrecognized address
  return 'u_ada';
}

let _idCounter = 0;
function newId(prefix: string): string {
  return `${prefix}_${Date.now()}_${++_idCounter}`;
}

export function createMockApi(opts?: MockApiOpts): CtcApi & { _state(): StoreState } {
  const getNow = opts?.now ?? (() => Date.now());
  const latencyMs = opts?.latencyMs ?? 0;
  const storageKey = opts?.storageKey ?? DEFAULT_STORE_KEY;
  const deployParticipantsMode: 'givers_only' | 'givers_and_consumers' = opts?.participantsMode ?? 'givers_and_consumers';
  const deploySharedPoolEnabled: boolean = opts?.sharedPoolEnabled ?? true;

  // Load or seed
  let state: StoreState = load(storageKey) ?? makeSeed(getNow());
  // Save initial state if freshly seeded
  save(storageKey, state);

  // In-memory session (not persisted in storageKey; uses separate key)
  let session: Session | null = (() => {
    try {
      const raw = localStorage.getItem(SESSION_KEY);
      if (!raw) return null;
      return JSON.parse(raw) as Session;
    } catch {
      return null;
    }
  })();

  function persistSession(s: Session | null): void {
    if (s === null) {
      localStorage.removeItem(SESSION_KEY);
    } else {
      localStorage.setItem(SESSION_KEY, JSON.stringify(s));
    }
  }

  function persistState(): void {
    save(storageKey, state);
  }

  async function delay<T>(val: T): Promise<T> {
    if (latencyMs > 0) {
      await new Promise(r => setTimeout(r, latencyMs));
    }
    return val;
  }

  function requireSession(): SeedUser {
    if (!session) throw new Error('Not authenticated');
    const user = state.users.find(u => u.id === session!.userId);
    if (!user) throw new Error('Session user not found');
    return user;
  }

  function buildSession(user: SeedUser): Session {
    return {
      userId: user.id,
      name: user.name,
      role: user.role,
      onboarded: true,
      isAdmin: Boolean(user.isAdmin),
      hasPat: Boolean(user.hasPat),
      participantsMode: deployParticipantsMode,
      sharedPoolEnabled: deploySharedPoolEnabled,
      creditToEuroRate: (state.adminSettings ?? DEFAULT_ADMIN_SETTINGS).creditToEuroRate.value,
      webTransport: 'http',
    };
  }

  const api: CtcApi & { _state(): StoreState } = {
    _state(): StoreState {
      return state;
    },

    async signIn(email: string, _password: string): Promise<Session> {
      const userId = emailToUserId(email);
      const user = state.users.find(u => u.id === userId) ?? state.users[0];
      const s = buildSession(user);
      session = s;
      persistSession(s);
      return delay(s);
    },

    async signOut(): Promise<void> {
      session = null;
      persistSession(null);
      return delay(undefined);
    },

    async getSession(): Promise<Session | null> {
      return delay(session);
    },

    async completeOnboarding(input: OnboardingInput): Promise<Session> {
      const user = requireSession();
      const idx = state.users.findIndex(u => u.id === user.id);
      const updated: SeedUser = {
        ...user,
        name: input.name,
        role: input.role,
        hasPat: input.pat !== undefined,
        pledgedSurplus: input.pledgedSurplus ?? user.pledgedSurplus,
      };
      const users = [...state.users];
      users[idx] = updated;
      state = { ...state, users };
      const s: Session = { userId: user.id, name: input.name, role: input.role, onboarded: true, isAdmin: Boolean(updated.isAdmin) };
      session = s;
      persistSession(s);
      persistState();
      return delay(s);
    },

    async validatePat(pat: string): Promise<{ gheLogin: string; quotaAiu: number; entitlementAiu: number; remainingAiu: number; resetDate: string | null; pledgedNano: number }> {
      const user = requireSession();
      if (!pat || !pat.startsWith('github_pat_')) {
        throw new CtcApiError('bad_request', 'invalid token format', 400);
      }
      // Simulate GHE: derive a plausible login + quota; promote to giver locally.
      const idx = state.users.findIndex(u => u.id === user.id);
      const users = [...state.users];
      users[idx] = { ...user, role: 'giver', hasPat: true, totalCredit: 2000 * NANO_PER_AIU };
      state = { ...state, users };
      persistState();
      const quotaAiu = 2000;
      const nowMs = getNow();
      const d = new Date(nowMs);
      const resetDate = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1))
        .toISOString().slice(0, 10);
      return delay({
        gheLogin: user.name.split(' ')[0].toLowerCase(),
        quotaAiu,
        entitlementAiu: quotaAiu + 200,
        remainingAiu: quotaAiu,
        resetDate,
        // default pledge = 10% of remaining (mirrors backend CTC_DEFAULT_PLEDGE_PCT)
        pledgedNano: Math.floor(quotaAiu / 10) * NANO_PER_AIU,
      });
    },
    async revokePat(): Promise<void> {
      const user = requireSession();
      // Full disconnect: drop the PAT, zero credit, revert to consumer.
      const idx = state.users.findIndex(u => u.id === user.id);
      const users = [...state.users];
      users[idx] = { ...user, role: 'consumer', hasPat: false, totalCredit: 0 };
      state = { ...state, users };
      persistState();
      return delay(undefined);
    },
    async markOnboarded(): Promise<void> {
      requireSession();
      session = { ...session!, onboarded: true };
      persistSession(session);
      return delay(undefined);
    },

    async listRequests(filter: 'all' | 'pro' | 'noob'): Promise<ListRequestsResult> {
      const now = getNow();
      const all = state.requests;
      const filtered = filter === 'all' ? all : all.filter(r => r.requesterRole === filter);
      const proCount = all.filter(r => r.requesterRole === 'pro').length;
      const noobCount = all.filter(r => r.requesterRole === 'noob').length;
      return delay({
        requests: filtered.map(r => toPublic(r, now, session?.userId)),
        counts: { all: all.length, pro: proCount, noob: noobCount },
      });
    },

    async createRequest(input: CreateRequestInput): Promise<PublicRequest> {
      const user = requireSession();
      const now = getNow();
      const requesterRole = user.role === 'giver' ? 'pro' : 'noob';
      const newReq: SeedRequest = {
        id: newId('req'),
        requesterId: user.id,
        requesterName: user.name,
        initials: user.initials,
        requesterRole,
        amountNeeded: input.amountNeeded,
        amountFunded: 0,
        reason: input.reason,
        target: input.target,
        createdAt: now,
        expiresAt: now + input.expiryHours * 3_600_000,
        donorCount: 0,
      };
      // Prepend
      state = { ...state, requests: [newReq, ...state.requests] };
      persistState();
      return delay(toPublic(newReq, now, user.id));
    },

    async donate(requestId: string, amount: number): Promise<PublicRequest> {
      const giver = requireSession();
      const now = getNow();

      const reqIdx = state.requests.findIndex(r => r.id === requestId);
      if (reqIdx === -1) throw new Error('Request not found');
      const req = state.requests[reqIdx];
      if (req.requesterId === giver.id) throw new Error('cannot fund your own request');

      // Find the requester user to update their credit
      const recipientIdx = state.users.findIndex(u => u.name === req.requesterName);

      // Compute giver's personal available credit
      const retained =
        giver.totalCredit !== null && giver.pledgedSurplus !== null
          ? giver.totalCredit - giver.pledgedSurplus
          : null;
      const personalAvailable = retained !== null ? retained - giver.donatedSoFar : Infinity;

      // Clamp amount
      const remainingNeed = req.amountNeeded - req.amountFunded;
      const actual = Math.min(amount, remainingNeed, personalAvailable);
      if (actual <= 0) throw new Error('Nothing to donate or insufficient credit');

      // Update request
      const updatedReq: SeedRequest = {
        ...req,
        amountFunded: req.amountFunded + actual,
        donorCount: req.donorCount + 1,
      };
      const requests = [...state.requests];
      requests[reqIdx] = updatedReq;

      // Update giver's donatedSoFar
      const giverIdx = state.users.findIndex(u => u.id === giver.id);
      const users = [...state.users];
      users[giverIdx] = { ...users[giverIdx], donatedSoFar: users[giverIdx].donatedSoFar + actual };

      // Update recipient's donationsReceived and consumed
      if (recipientIdx !== -1) {
        users[recipientIdx] = {
          ...users[recipientIdx],
          donationsReceived: users[recipientIdx].donationsReceived + actual,
        };
      }

      // Create donation record
      const donation: Donation = {
        id: newId('don'),
        requestId,
        fromUserId: giver.id,
        toUserId: recipientIdx !== -1 ? users[recipientIdx].id : 'unknown',
        amount: actual,
        kind: donationKind(
          giver.role === 'giver' ? 'pro' : 'noob',
          req.requesterRole,
        ),
        createdAt: now,
      };

      // Update aggregates
      const aggregates = { ...state.aggregates };
      if (req.requesterRole === 'pro') {
        aggregates.rotated = aggregates.rotated + actual;
      } else {
        aggregates.donatedToNonPat = aggregates.donatedToNonPat + actual;
      }
      aggregates.donatedThisWeek = aggregates.donatedThisWeek + actual;

      state = {
        ...state,
        requests,
        users,
        donations: [...state.donations, donation],
        aggregates,
      };
      persistState();

      return delay(toPublic(updatedReq, now, giver.id));
    },

    async getDashboard(): Promise<DashboardData> {
      const now = getNow();
      const { aggregates, requests } = state;

      const openCount = requests.filter(r => {
        const s = deriveStatus(r.amountFunded, r.amountNeeded, r.expiresAt, now);
        return s === 'open' || s === 'partially_funded';
      }).length;

      const closedCount = requests.filter(r => {
        const s = deriveStatus(r.amountFunded, r.amountNeeded, r.expiresAt, now);
        return s === 'fulfilled' || s === 'expired';
      }).length;

      // Fixed activity log rows for the dashboard
      const activity: ActivityEntry[] = [
        { time: '12:48:02', kind: 'donate',  detail: 'ada → lena',          amount: '+25' },
        { time: '12:47:30', kind: 'request', detail: 'priya → @ada',        amount: '90' },
        { time: '12:46:30', kind: 'fulfill', detail: 'amine · auto-closed', amount: '120 ✓' },
        { time: '12:45:12', kind: 'donate',  detail: 'yuki → diego',       amount: '+30' },
        { time: '12:44:01', kind: 'request', detail: 'lena · open to all',  amount: '60' },
        { time: '12:42:48', kind: 'rotate',  detail: 'sofia → amine',       amount: '+40' },
      ];

      // Leaderboard snapshot
      const lb = await api.getLeaderboard();

      // Strip private fields — DashboardData only has public shapes
      const result: DashboardData = {
        pledged: aggregates.pledged,
        retained: aggregates.retained,
        rotated: aggregates.rotated,
        donatedToNonPat: aggregates.donatedToNonPat,
        donatedThisWeek: aggregates.donatedThisWeek,
        fulfillmentRate: aggregates.fulfillmentRate,
        activeGivers: aggregates.activeGivers,
        activeConsumers: aggregates.activeConsumers,
        openCount,
        closedCount,
        activity,
        leaderboardSnapshot: {
          generous: lb.generous,
          topConsumers: lb.topNoob,
        },
      };
      return delay(result);
    },

    async getLeaderboard(): Promise<Leaderboard> {
      // Build leaderboard from users — only expose public fields
      const generous: LeaderboardEntry[] = state.users
        .filter(u => u.donatedSoFar > 0)
        .sort((a, b) => b.donatedSoFar - a.donatedSoFar)
        .slice(0, 5)
        .map(u => ({ name: u.name, value: u.donatedSoFar }));

      const topPro: LeaderboardEntry[] = state.users
        .filter(u => u.role === 'giver' && u.consumed > 0)
        .sort((a, b) => b.consumed - a.consumed)
        .slice(0, 5)
        .map(u => ({ name: u.name, value: u.consumed }));

      const topNoob: LeaderboardEntry[] = state.users
        .filter(u => u.role === 'consumer')
        .sort((a, b) => b.consumed - a.consumed)
        .slice(0, 5)
        .map(u => ({ name: u.name, value: u.consumed }));

      const givers = state.users
        .filter(u => u.role === 'giver')
        .map(u => ({
          name: u.name,
          net: u.donatedSoFar - u.consumed,
          active: u.donatedSoFar > 0 || u.consumed > 0,
        }));
      const standings = mockAssignTiers(givers);

      const result: Leaderboard = { generous, topPro, topNoob, standings };
      return delay(result);
    },

    async getOwnProfile(): Promise<OwnProfile> {
      const user = requireSession();
      const retained =
        user.totalCredit !== null && user.pledgedSurplus !== null
          ? user.totalCredit - user.pledgedSurplus
          : null;

      // Derive first-of-next-month reset date string from current time.
      const nowMs = getNow();
      const d = new Date(nowMs);
      const resetDate = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1))
        .toISOString().slice(0, 10);

      // Credit-segment synthesis for givers: entitlement = totalCredit + consumed-this-cycle.
      // For consumers: populate allowance fields instead.
      let entitlement: number | null = null;
      let remaining: number | null = null;
      let used: number | null = null;
      let pledged: number | null = null;
      let donated: number | null = null;
      let left: number | null = null;
      let pledgedConsumed: number | null = null;
      let donatedConsumed: number | null = null;
      let allowanceMax: number | null = null;
      let allowanceUsed: number | null = null;
      let allowanceLeft: number | null = null;

      if (user.role === 'giver' && user.totalCredit !== null) {
        const consumedThisMonth = user.consumedThisMonth ?? 0;
        entitlement = user.totalCredit + consumedThisMonth;
        used = consumedThisMonth;
        pledged = user.pledgedSurplus ?? 0;
        donated = user.donatedSoFar;
        left = Math.max(0, entitlement - used - pledged - donated);
        pledgedConsumed = Math.min(pledged, user.poolConsumedFrom ?? 0);
        donatedConsumed = Math.min(donated, user.grantsConsumed ?? 0);
        remaining = left;
      } else if (user.role === 'consumer' && user.allowance !== null) {
        allowanceMax = user.allowance;
        allowanceUsed = user.consumed;
        allowanceLeft = Math.max(0, user.allowance - user.consumed);
      }

      // tier for the current user (givers only)
      let tier: string | null = null;
      let net: number | null = null;
      let netToNext: number | null = null;
      if (user.role === 'giver') {
        const givers = state.users
          .filter(u => u.role === 'giver')
          .map(u => ({ name: u.name, net: u.donatedSoFar - u.consumed, active: u.donatedSoFar > 0 || u.consumed > 0 }));
        // dev-only: mock fixtures don't model credit buckets, so mock net uses the
        // user's consumed as a rough stand-in for pool draws (prod uses pool_consumed_by)
        const ranked = mockAssignTiers(givers);
        // dev-only: match by name (backend matches by user_id)
        const idx = ranked.findIndex(r => r.name === user.name);
        if (idx >= 0) {
          tier = ranked[idx].tier;
          net = ranked[idx].net;
          if (idx > 0 && tier !== 'newcomer') netToNext = Math.max(1, ranked[idx - 1].net - ranked[idx].net);
        }
      }

      const result: OwnProfile = {
        user: {
          id: user.id,
          name: user.name,
          initials: user.initials,
          role: user.role,
        },
        totalCredit: user.totalCredit,
        pledgedSurplus: user.pledgedSurplus,
        retained,
        donatedSoFar: user.donatedSoFar,
        allowance: user.allowance,
        consumed: user.consumed,
        donationsReceived: user.donationsReceived,
        entitlement,
        remaining,
        used,
        pledged,
        donated,
        left,
        pledgedConsumed,
        donatedConsumed,
        allowanceMax,
        allowanceUsed,
        allowanceLeft,
        resetDate,
        unlimited: false,
        quotaStale: false,
        tier,
        net,
        netToNext,
      };
      return delay(result);
    },

    async getSettings(): Promise<SettingsData> {
      const user = requireSession();
      const result: SettingsData = {
        name: user.name,
        login: user.email ? user.email.split('@')[0] : user.id,
        role: user.role,
        hasPat: user.hasPat,
        totalCredit: user.totalCredit,
        pledgedSurplus: user.pledgedSurplus,
        allowance: user.allowance,
      };
      return delay(result);
    },

    async updateSettings(patch: SettingsPatch): Promise<SettingsData> {
      const user = requireSession();
      const idx = state.users.findIndex(u => u.id === user.id);
      const updated: SeedUser = {
        ...user,
        ...(patch.name !== undefined && { name: patch.name }),
        ...(patch.role !== undefined && { role: patch.role }),
        ...(patch.pledgedSurplus !== undefined && { pledgedSurplus: patch.pledgedSurplus }),
        ...(patch.pat !== undefined && { hasPat: true }),
      };
      const users = [...state.users];
      users[idx] = updated;
      state = { ...state, users };
      if (patch.name || patch.role) {
        session = {
          ...session!,
          ...(patch.name && { name: patch.name }),
          ...(patch.role && { role: patch.role }),
        };
        persistSession(session);
      }
      persistState();
      return api.getSettings();
    },

    async getHistory(): Promise<CycleReport[]> {
      // months have no private credit fields — safe to return directly
      return delay([...state.months]);
    },

    async getCliCredentials() {
      if (!session) throw new Error('Not authenticated');
      // Deterministic, well-formed FAKE token derived from the user id (no real secret).
      const seed = session.userId.replace(/[^a-zA-Z0-9]/g, '');
      const body = (seed + 'CTC0000000000000000000000000000000000').slice(0, 36);
      return delay({
        token: `github_pat_${body}`,
        proxyHost: 'ctc.local:8080',
        installCommand: `curl -fsSLk https://ctc.local/install.sh | sh -s -- --token github_pat_${body}`,
        caFingerprint: 'AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99',
      });
    },

    // Admin
    async listAllUsers(): Promise<AdminUser[]> {
      const users = state.users.map((u): AdminUser => ({
        id: u.id,
        gheLogin: u.email ? u.email.split('@')[0] : u.id,
        displayName: u.name,
        role: u.role,
        onboarded: true,
        hasPat: u.hasPat,
        patFingerprint: u.hasPat ? fp(u.id) : null,
        tokenCount: 0,
        quota: u.role === 'giver' ? (u.totalCredit ?? null) : null,
        pledge: u.role === 'giver' ? (u.pledgedSurplus ?? null) : null,
        pledgeRemaining: u.role === 'giver' ? (u.pledgedSurplus ?? null) : null,
      }));
      return delay(users);
    },

    async getUserDetail(id: string): Promise<AdminUserDetail> {
      const u = state.users.find(u => u.id === id);
      if (!u) throw new Error(`User not found: ${id}`);
      const base: AdminUser = {
        id: u.id,
        gheLogin: u.email ? u.email.split('@')[0] : u.id,
        displayName: u.name,
        role: u.role,
        onboarded: true,
        hasPat: u.hasPat,
        patFingerprint: u.hasPat ? fp(u.id) : null,
        tokenCount: 0,
        quota: u.role === 'giver' ? (u.totalCredit ?? null) : null,
        pledge: u.role === 'giver' ? (u.pledgedSurplus ?? null) : null,
        pledgeRemaining: u.role === 'giver' ? (u.pledgedSurplus ?? null) : null,
      };
      const detail: AdminUserDetail = {
        ...base,
        proxyTokens: [],
        pat: u.hasPat ? { fingerprint: fp(u.id), createdAt: 0 } : null,
      };
      return delay(detail);
    },

    async revealPat(id: string): Promise<string> {
      const u = state.users.find(u => u.id === id);
      if (!u) throw new Error(`User not found: ${id}`);
      return delay(`github_pat_mock_${id}`);
    },

    async getAdminSettings(): Promise<AdminSettings> {
      return delay(state.adminSettings ?? DEFAULT_ADMIN_SETTINGS);
    },

    async updateAdminSettings(patch: AdminSettingsPatch): Promise<AdminSettings> {
      const current = state.adminSettings ?? DEFAULT_ADMIN_SETTINGS;
      const updated: AdminSettings = { ...current };
      if (patch.freeAllowanceAiu !== undefined) {
        updated.freeAllowanceAiu = { value: patch.freeAllowanceAiu, isOverride: true };
      }
      if (patch.defaultPledgePct !== undefined) {
        updated.defaultPledgePct = { value: patch.defaultPledgePct, isOverride: true };
      }
      if (patch.requestExpiryHours !== undefined) {
        updated.requestExpiryHours = { value: patch.requestExpiryHours, isOverride: true };
      }
      if (patch.requestExpiryMaxHours !== undefined) {
        updated.requestExpiryMaxHours = { value: patch.requestExpiryMaxHours, isOverride: true };
      }
      if (patch.creditToEuroRate !== undefined) {
        updated.creditToEuroRate = { value: patch.creditToEuroRate, isOverride: true };
      }
      if (patch.participantsMode !== undefined) {
        updated.participantsMode = { value: patch.participantsMode, isOverride: true };
      }
      if (patch.sharedPoolEnabled !== undefined) {
        updated.sharedPoolEnabled = { value: patch.sharedPoolEnabled, isOverride: true };
      }
      state = { ...state, adminSettings: updated };
      persistState();
      return delay(updated);
    },
  };

  return api;
}

// Singleton instance for use in tests and app bootstrap.
export const mockApi = createMockApi();

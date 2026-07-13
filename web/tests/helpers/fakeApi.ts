// Test-only fake CtcApi.
//
// The shipped app talks to the real control plane exclusively (HttpCtcApi); there
// is no mock backend in `src/`. Screen/integration tests still need a data source,
// so this in-memory fake implements the CtcApi surface with a small seeded store
// and the few stateful mutations tests exercise (donate, createRequest, settings).
// It is a test fixture, not shipped code — keep it here under tests/.
import type { CtcApi, DonationSource, ListRequestsResult } from '@/api/CtcApi';
import type {
  PublicRequest, CreateRequestInput, DashboardData, Leaderboard, OwnProfile,
  SettingsData, SettingsPatch, Session, OnboardingInput, CycleReport,
  ActivityEntry, LeaderboardEntry, AdminUser, AdminUserDetail, AdminSettings,
  AdminSettingsPatch, AdminBootConfig, PublicProfile, PublicUserHit, Role,
} from '@/domain/types';
import { deriveStatus, NANO_PER_AIU } from '@/domain/credit';
import { CtcApiError } from '@/api/http';

const N = NANO_PER_AIU;

interface FakeUser {
  id: string; name: string; email?: string; initials: string; role: Role;
  hasPat: boolean; totalCredit: number | null; pledgedSurplus: number | null;
  donatedSoFar: number; consumed: number;
  donationsReceived: number; isAdmin?: boolean;
  consumedThisMonth?: number; poolConsumedFrom?: number; grantsConsumed?: number;
  receivedConsumed?: number;  // nano-AIU of received grants already burned
  receivedFromPool?: number;  // nano-AIU of donationsReceived that came from the pool
  reDonated?: number;         // nano-AIU of received credit passed on to other requests
  returnedToPool?: number;    // nano-AIU of received credit moved into the shared pool
}
interface FakeRequest {
  id: string; requesterId?: string; requesterName: string; initials: string;
  requesterRole: 'pro' | 'noob'; amountNeeded: number; amountFunded: number;
  fundedConsumed?: number; poolFunded?: number; cancelled?: boolean;
  reason: string; target: string | null;
  createdAt: number; expiresAt: number;  // SECONDS — matches the wire contract
  donorCount: number;
}

/** Unspent received credit (what can still be spent, re-donated, or pooled). */
function receivedRemaining(u: FakeUser): number {
  return Math.max(0, u.donationsReceived - (u.receivedConsumed ?? 0)
    - (u.reDonated ?? 0) - (u.returnedToPool ?? 0));
}

/** Giver's retained credit; consumers have none. Givers seeded without a quota
 *  (totalCredit null) are treated as having plenty — the fake never gates them. */
function personalRemaining(u: FakeUser): number {
  if (u.role !== 'giver') return 0;
  if (u.totalCredit === null) return 1_000_000_000_000;
  const entitlement = u.totalCredit + (u.consumedThisMonth ?? 0);
  return Math.max(0, entitlement - (u.consumedThisMonth ?? 0) - (u.pledgedSurplus ?? 0) - u.donatedSoFar);
}

const DEFAULT_BOOT_CONFIG: AdminBootConfig = { webTransport: 'http' };
const DEFAULT_ADMIN_SETTINGS: AdminSettings = {
  defaultPledgePct:      { value: 0,      isOverride: false },
  requestExpiryHours:    { value: 24,     isOverride: false },
  requestExpiryMaxHours: { value: 168,    isOverride: false },
  creditToEuroRate:      { value: 0.0088, isOverride: false },
  defaultChipInAiu:      { value: 100,    isOverride: false },
  participantsMode:      { value: 'givers_and_consumers', isOverride: false },
  sharedPoolEnabled:     { value: true,   isOverride: false },
  boot:                  DEFAULT_BOOT_CONFIG,
};

// Mirror of backend assign_tiers (ctc/accounting/tiers.py) — dev/test only.
function assignTiers(givers: { name: string; net: number; active: boolean }[]) {
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

function seedMonths(): CycleReport[] {
  return [
    { id: '2026-05', label: 'May 2026', pledged: 9800 * N, budgetTotal: 14000 * N, usedTotal: 8200 * N,
      donated: 6240 * N, toNonPat: 4010 * N, toPat: 2230 * N, reqFilled: 38, reqTotal: 44, reqPat: 9, reqNonPat: 29,
      fills: [{ who: 'Marco Bianchi', amount: 1540 * N, count: 14 }, { who: 'Yuki Tanaka', amount: 1860 * N, count: 11 }],
      winners: { generous: { name: 'Marco Bianchi', value: 1540 * N, userId: 'u_mb' },
        pro: { name: 'Yuki Tanaka', value: 1240 * N, userId: 'u_kef' }, noob: { name: 'Lena Hoffmann', value: 412 * N, userId: 'u_lh' } } },
    { id: '2026-04', label: 'April 2026', pledged: 8100 * N, budgetTotal: 12000 * N, usedTotal: 6800 * N,
      donated: 5020 * N, toNonPat: 3100 * N, toPat: 1920 * N, reqFilled: 31, reqTotal: 39, reqPat: 7, reqNonPat: 24,
      fills: [{ who: 'Yuki Tanaka', amount: 1480 * N, count: 12 }],
      winners: { generous: { name: 'Yuki Tanaka', value: 1480 * N, userId: 'u_kef' },
        pro: { name: 'Amine Tazi', value: 1080 * N, userId: 'u_at' }, noob: { name: 'Diego Ramirez', value: 388 * N, userId: 'u_dr' } } },
    { id: '2026-03', label: 'March 2026', pledged: 5400 * N, budgetTotal: 9000 * N, usedTotal: 4100 * N,
      donated: 2980 * N, toNonPat: 1740 * N, toPat: 1240 * N, reqFilled: 19, reqTotal: 25, reqPat: 5, reqNonPat: 14,
      fills: [{ who: 'Sofia Lindqvist', amount: 880 * N, count: 7 }],
      winners: { generous: { name: 'Sofia Lindqvist', value: 880 * N, userId: 'u_sl' },
        pro: { name: 'Yuki Tanaka', value: 920 * N, userId: 'u_kef' }, noob: { name: 'Priya Nair', value: 276 * N, userId: 'u_pn' } } },
  ];
}

function seedRequests(nowMs: number): FakeRequest[] {
  const now = Math.floor(nowMs / 1000);  // wire timestamps are seconds
  return [
    { id: 'req_1', requesterId: 'u_lh', requesterName: 'Lena Hoffmann', initials: 'LH', requesterRole: 'noob',
      amountNeeded: 60 * N, amountFunded: 35 * N, reason: 'Finishing the migration PR', target: null, createdAt: now, expiresAt: now + 4 * 3600, donorCount: 2 },
    { id: 'req_2', requesterId: 'u_dr', requesterName: 'Diego Ramirez', initials: 'DR', requesterRole: 'noob',
      amountNeeded: 40 * N, amountFunded: 10 * N, reason: 'Code-review marathon today', target: null, createdAt: now, expiresAt: now + 18 * 3600, donorCount: 1 },
    { id: 'req_3', requesterId: 'u_pn', requesterName: 'Priya Nair', initials: 'PN', requesterRole: 'noob',
      amountNeeded: 90 * N, amountFunded: 0, reason: 'Debugging a prod incident', target: 'Ada Lovelace', createdAt: now, expiresAt: now + 26 * 3600, donorCount: 0 },
    { id: 'req_4', requesterId: 'u_at', requesterName: 'Amine Tazi', initials: 'AT', requesterRole: 'pro',
      amountNeeded: 120 * N, amountFunded: 120 * N, fundedConsumed: 72 * N, reason: 'Ran dry mid-refactor', target: null, createdAt: now, expiresAt: now, donorCount: 3 },
    { id: 'req_5', requesterName: 'Tom Becker', initials: 'TB', requesterRole: 'noob',
      amountNeeded: 30 * N, amountFunded: 30 * N, fundedConsumed: 30 * N, reason: 'Writing test coverage', target: null, createdAt: now, expiresAt: now, donorCount: 1 },
    { id: 'req_6', requesterId: 'u_pn', requesterName: 'Priya Nair', initials: 'PN', requesterRole: 'noob',
      amountNeeded: 50 * N, amountFunded: 5 * N, reason: 'Old ask that ran out of time', target: null, createdAt: now - 90000, expiresAt: now - 3600, donorCount: 1 },
  ];
}

function seedUsers(): FakeUser[] {
  return [
    { id: 'u_ada', name: 'Ada Lovelace', initials: 'AL', role: 'giver', hasPat: true, totalCredit: 5000 * N, pledgedSurplus: 2000 * N,
      donatedSoFar: 1860 * N, consumed: 920 * N, donationsReceived: 0, isAdmin: true,
      consumedThisMonth: 200 * N, poolConsumedFrom: 100 * N, grantsConsumed: 50 * N },
    { id: 'u_kef', name: 'Yuki Tanaka', initials: 'KF', role: 'giver', hasPat: true, totalCredit: null, pledgedSurplus: null, donatedSoFar: 1860 * N, consumed: 1240 * N, donationsReceived: 0 },
    { id: 'u_sl', name: 'Sofia Lindqvist', initials: 'SL', role: 'giver', hasPat: true, totalCredit: null, pledgedSurplus: null, donatedSoFar: 1400 * N, consumed: 780 * N, donationsReceived: 0 },
    // Marco doubles as the "Host who also RECEIVED credit" fixture: a giver with
    // grants routed to him (chip-ins + a pool fill on a past request of his own).
    { id: 'u_mb', name: 'Marco Bianchi', initials: 'MB', role: 'giver', hasPat: true, totalCredit: 4000 * N, pledgedSurplus: 800 * N,
      donatedSoFar: 1540 * N, consumed: 540 * N, donationsReceived: 250 * N, receivedConsumed: 90 * N, receivedFromPool: 150 * N,
      consumedThisMonth: 300 * N, poolConsumedFrom: 200 * N, grantsConsumed: 400 * N },
    { id: 'u_at', name: 'Amine Tazi', initials: 'AT', role: 'giver', hasPat: true, totalCredit: null, pledgedSurplus: null, donatedSoFar: 610 * N, consumed: 310 * N, donationsReceived: 0 },
    { id: 'u_lh', name: 'Lena Hoffmann', initials: 'LH', role: 'consumer', hasPat: false, totalCredit: null, pledgedSurplus: null, donatedSoFar: 0, consumed: 412 * N, donationsReceived: 120 * N, receivedConsumed: 85 * N, receivedFromPool: 40 * N },
    { id: 'u_dr', name: 'Diego Ramirez', initials: 'DR', role: 'consumer', hasPat: false, totalCredit: null, pledgedSurplus: null, donatedSoFar: 0, consumed: 388 * N, donationsReceived: 0 },
    { id: 'u_pn', name: 'Priya Nair', initials: 'PN', role: 'consumer', hasPat: false, totalCredit: null, pledgedSurplus: null, donatedSoFar: 0, consumed: 276 * N, donationsReceived: 0 },
  ];
}

function emailToUserId(email: string): string {
  const l = email.toLowerCase();
  if (l.includes('kef') || l.includes('yuki')) return 'u_kef';
  if (l.includes('sofia') || l.includes('sl')) return 'u_sl';
  if (l.includes('marco') || l.includes('mb')) return 'u_mb';
  if (l.includes('amine') || l.includes('at')) return 'u_at';
  if (l.includes('lena') || l.includes('lh')) return 'u_lh';
  if (l.includes('diego') || l.includes('dr')) return 'u_dr';
  if (l.includes('priya') || l.includes('pn')) return 'u_pn';
  return 'u_ada';
}

export interface FakeApiOpts {
  now?: () => number;
  latencyMs?: number;
  storageKey?: string;   // accepted for drop-in parity; ignored (store is in-memory)
  participantsMode?: 'givers_only' | 'givers_and_consumers';
  sharedPoolEnabled?: boolean;
}

export type FakeApi = CtcApi & { _users(): FakeUser[]; _setSession(s: Session | null): void };

let _idCounter = 0;

/** Build an in-memory fake CtcApi with a seeded store. Drop-in for the old createMockApi. */
export function makeFakeApi(opts?: FakeApiOpts): FakeApi {
  const getNow = opts?.now ?? (() => Date.now());
  const participantsMode = opts?.participantsMode ?? 'givers_and_consumers';
  const sharedPoolEnabled = opts?.sharedPoolEnabled ?? true;

  let users = seedUsers();
  let requests = seedRequests(getNow());
  // Shared-pool balance (nano-AIU) available for marketplace pool fills.
  let poolAvailable = sharedPoolEnabled ? 500 * N : 0;
  let proxyTokens: { id: string; fingerprint: string; createdAt: number; revoked: boolean }[] = [];
  const months = seedMonths();
  let adminSettings: AdminSettings = { ...DEFAULT_ADMIN_SETTINGS };
  let session: Session | null = null;

  const loginOf = (u: FakeUser) => (u.email ? u.email.split('@')[0] : u.name.toLowerCase().replace(/[^a-z0-9]+/g, ''));

  function buildSession(u: FakeUser): Session {
    return {
      userId: u.id, name: u.name, role: u.role, onboarded: true,
      isAdmin: Boolean(u.isAdmin), hasPat: Boolean(u.hasPat),
      participantsMode, sharedPoolEnabled,
      creditToEuroRate: adminSettings.creditToEuroRate.value,
      defaultChipInAiu: adminSettings.defaultChipInAiu.value,
      requestExpiryHours: adminSettings.requestExpiryHours.value,
      requestExpiryMaxHours: adminSettings.requestExpiryMaxHours.value,
      webTransport: 'http',
    };
  }

  function requireUser(): FakeUser {
    if (!session) throw new Error('Not authenticated');
    const u = users.find(x => x.id === session!.userId);
    if (!u) throw new Error('Session user not found');
    return u;
  }

  function toPublic(r: FakeRequest, now: number, viewerId?: string): PublicRequest {
    return {
      id: r.id, requesterId: r.requesterId ?? '', requesterName: r.requesterName, initials: r.initials,
      requesterRole: r.requesterRole, amountNeeded: r.amountNeeded, amountFunded: r.amountFunded,
      fundedConsumed: r.fundedConsumed ?? 0, poolFunded: r.poolFunded ?? 0,
      reason: r.reason, target: r.target, createdAt: r.createdAt, expiresAt: r.expiresAt,
      status: deriveStatus(r.amountFunded, r.amountNeeded, r.expiresAt, now, r.cancelled),
      donorCount: r.donorCount, isOwn: !!viewerId && r.requesterId === viewerId,
    };
  }

  function giverNets() {
    return users.filter(u => u.role === 'giver')
      .map(u => ({ name: u.name, net: u.donatedSoFar - u.consumed, active: u.donatedSoFar > 0 || u.consumed > 0 }));
  }

  const api: FakeApi = {
    _users: () => users,
    // Directly inject a session (bypassing signIn's seeded-user lookup) for tests
    // that need an arbitrary role/hasPat combo not present in the seed data.
    _setSession: (s: Session | null) => { session = s; },

    async signIn(email: string) {
      const u = users.find(x => x.id === emailToUserId(email)) ?? users[0];
      session = buildSession(u);
      return session;
    },
    async signOut() { session = null; },
    async getSession() { return session; },

    async completeOnboarding(input: OnboardingInput) {
      const u = requireUser();
      const i = users.findIndex(x => x.id === u.id);
      users[i] = { ...u, name: input.name, role: input.role, hasPat: input.pat !== undefined ? true : u.hasPat, pledgedSurplus: input.pledgedSurplus ?? u.pledgedSurplus };
      session = buildSession(users[i]);
      return session;
    },
    async validatePat(pat: string) {
      const u = requireUser();
      if (!pat || !pat.startsWith('github_pat_')) throw new CtcApiError('bad_request', 'invalid token format', 400);
      const i = users.findIndex(x => x.id === u.id);
      users[i] = { ...u, role: 'giver', hasPat: true, totalCredit: 2000 * N };
      const d = new Date(getNow());
      const resetDate = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1)).toISOString().slice(0, 10);
      return { gheLogin: u.name.split(' ')[0].toLowerCase(), quotaAiu: 2000, entitlementAiu: 2200, remainingAiu: 2000, resetDate, pledgedNano: 200 * N, usedNano: 200 * N };
    },
    async revokePat() {
      const u = requireUser();
      const i = users.findIndex(x => x.id === u.id);
      users[i] = { ...u, role: 'consumer', hasPat: false, totalCredit: 0 };
    },
    async markOnboarded() { requireUser(); if (session) session = { ...session, onboarded: true }; },

    async listRequests(filter: 'all' | 'pro' | 'noob'): Promise<ListRequestsResult> {
      const now = Math.floor(getNow() / 1000);
      const all = requests.filter(r => !r.cancelled);  // cancelled requests are hidden
      const filtered = filter === 'all' ? all : all.filter(r => r.requesterRole === filter);
      const viewer = session ? users.find(u => u.id === session!.userId) : undefined;
      return {
        requests: filtered.map(r => toPublic(r, now, session?.userId)),
        counts: { all: all.length, pro: all.filter(r => r.requesterRole === 'pro').length, noob: all.filter(r => r.requesterRole === 'noob').length },
        poolEnabled: sharedPoolEnabled, poolAvailable,
        viewerPersonalRemaining: viewer ? personalRemaining(viewer) : 0,
        viewerReceivedRemaining: viewer ? receivedRemaining(viewer) : 0,
      };
    },
    async createRequest(input: CreateRequestInput): Promise<PublicRequest> {
      const u = requireUser();
      const nowMs = getNow();
      const now = Math.floor(nowMs / 1000);
      const r: FakeRequest = {
        id: `req_${nowMs}_${++_idCounter}`, requesterId: u.id, requesterName: u.name, initials: u.initials,
        requesterRole: u.role === 'giver' ? 'pro' : 'noob', amountNeeded: input.amountNeeded, amountFunded: 0,
        reason: input.reason, target: input.target, createdAt: now, expiresAt: now + input.expiryHours * 3600, donorCount: 0,
      };
      requests = [r, ...requests];
      return toPublic(r, now, u.id);
    },
    async deleteRequest(requestId: string): Promise<void> {
      const u = requireUser();
      const i = requests.findIndex(r => r.id === requestId);
      if (i === -1) throw new CtcApiError('not_found', 'request not found', 404);
      const r = requests[i];
      if (r.requesterId !== u.id) throw new CtcApiError('forbidden', 'only the requester can delete their request', 403);
      if (r.amountFunded >= r.amountNeeded) throw new CtcApiError('conflict', 'request is fulfilled', 409);
      requests = requests.map((x, idx) => (idx === i ? { ...x, cancelled: true } : x));
    },
    async donate(requestId: string, amount: number, source: DonationSource = 'personal'): Promise<PublicRequest> {
      const giver = requireUser();
      const now = Math.floor(getNow() / 1000);
      const i = requests.findIndex(r => r.id === requestId);
      if (i === -1) throw new Error('Request not found');
      const r = requests[i];
      if (r.cancelled) throw new Error('request is cancelled');
      if (r.requesterId === giver.id) throw new Error('cannot fund your own request');
      const budget = source === 'received' ? receivedRemaining(giver) : Infinity;
      const actual = Math.min(amount, r.amountNeeded - r.amountFunded, budget);
      if (actual <= 0) {
        throw new CtcApiError('unprocessable',
          source === 'received' ? 'no received credit available to re-donate' : 'Nothing to donate', 422);
      }
      const updated: FakeRequest = { ...r, amountFunded: r.amountFunded + actual, donorCount: r.donorCount + 1 };
      requests = requests.map((x, idx) => (idx === i ? updated : x));
      const gi = users.findIndex(u => u.id === giver.id);
      if (source === 'received') {
        // Generosity stays with the original PAT holder — only track the re-donation.
        users[gi] = { ...users[gi], reDonated: (users[gi].reDonated ?? 0) + actual };
      } else {
        users[gi] = { ...users[gi], donatedSoFar: users[gi].donatedSoFar + actual };
      }
      return toPublic(updated, now, giver.id);
    },
    async returnReceivedToPool(amount: number): Promise<{ poolAvailable: number; receivedRemaining: number }> {
      const u = requireUser();
      if (!sharedPoolEnabled) throw new CtcApiError('conflict', 'the shared pool is disabled', 409);
      const actual = Math.min(amount, receivedRemaining(u));
      if (actual <= 0) throw new CtcApiError('unprocessable', 'no received credit available to return', 422);
      const i = users.findIndex(x => x.id === u.id);
      users[i] = { ...users[i], returnedToPool: (users[i].returnedToPool ?? 0) + actual };
      poolAvailable += actual;
      return { poolAvailable, receivedRemaining: receivedRemaining(users[i]) };
    },
    async poolFund(requestId: string, amount: number): Promise<PublicRequest> {
      const u = requireUser();
      const now = Math.floor(getNow() / 1000);
      const i = requests.findIndex(r => r.id === requestId);
      if (i === -1) throw new CtcApiError('not_found', 'request not found', 404);
      const r = requests[i];
      if (r.requesterId !== u.id) throw new CtcApiError('forbidden', 'only the requester can fill their request from the pool', 403);
      if (!sharedPoolEnabled) throw new CtcApiError('conflict', 'the shared pool is disabled', 409);
      if (r.cancelled || r.amountFunded >= r.amountNeeded) throw new CtcApiError('conflict', 'request is closed', 409);
      const actual = Math.min(amount, r.amountNeeded - r.amountFunded, poolAvailable);
      if (actual <= 0) throw new CtcApiError('unprocessable', 'shared pool has no credit available', 422);
      poolAvailable -= actual;
      const updated: FakeRequest = { ...r, amountFunded: r.amountFunded + actual, poolFunded: (r.poolFunded ?? 0) + actual };
      requests = requests.map((x, idx) => (idx === i ? updated : x));
      return toPublic(updated, now, u.id);
    },

    async getDashboard(): Promise<DashboardData> {
      const now = Math.floor(getNow() / 1000);
      const openCount = requests.filter(r => { const s = deriveStatus(r.amountFunded, r.amountNeeded, r.expiresAt, now, r.cancelled); return s === 'open' || s === 'partially_funded'; }).length;
      const closedCount = requests.filter(r => { const s = deriveStatus(r.amountFunded, r.amountNeeded, r.expiresAt, now, r.cancelled); return s === 'fulfilled' || s === 'expired' || s === 'cancelled'; }).length;
      const activity: ActivityEntry[] = [
        { time: '12:48', kind: 'grant', detail: 'Ada Lovelace', amount: '25.00 AIU', actorId: 'u_ada' },
        { time: '12:45', kind: 'pool', detail: 'Yuki Tanaka', amount: '30.00 AIU', actorId: 'u_kef' },
      ];
      const lb = await api.getLeaderboard();
      const map = new Map<string, { value: number; userId: string }>();
      for (const e of [...lb.topPro, ...lb.topNoob]) {
        const cur = map.get(e.name);
        map.set(e.name, { value: (cur?.value ?? 0) + e.value, userId: e.userId });
      }
      const topConsumers: LeaderboardEntry[] = [...map.entries()].map(([name, v]) => ({ name, value: v.value, userId: v.userId })).sort((a, b) => b.value - a.value).slice(0, 5);
      return {
        pledged: 3600 * N, retained: 5680 * N, rotated: 1240 * N, donatedToNonPat: 2880 * N, donatedThisWeek: 4120 * N,
        fulfillmentRate: 86, activeGivers: 5, activeConsumers: 12, poolAvailable, openCount, closedCount, activity,
        leaderboardSnapshot: { generous: lb.generous, topConsumers },
        cycleLabel: 'July 2026', cycleNumber: 7, resetDate: '2026-08-01', daysLeft: 12,
      };
    },

    async getLeaderboard(): Promise<Leaderboard> {
      const generous = users.filter(u => u.donatedSoFar > 0).sort((a, b) => b.donatedSoFar - a.donatedSoFar).slice(0, 5).map(u => ({ name: u.name, value: u.donatedSoFar, userId: u.id }));
      const topPro = users.filter(u => u.role === 'giver' && u.consumed > 0).sort((a, b) => b.consumed - a.consumed).slice(0, 5).map(u => ({ name: u.name, value: u.consumed, userId: u.id }));
      const topNoob = users.filter(u => u.role === 'consumer').sort((a, b) => b.consumed - a.consumed).slice(0, 5).map(u => ({ name: u.name, value: u.consumed, userId: u.id }));
      const tiered = assignTiers(giverNets());
      const standings = tiered.map(s => ({ ...s, userId: users.find(u => u.name === s.name)?.id ?? '' }));
      return { generous, topPro, topNoob, standings };
    },

    async getOwnProfile(): Promise<OwnProfile> {
      const u = requireUser();
      const retained = u.totalCredit !== null && u.pledgedSurplus !== null ? u.totalCredit - u.pledgedSurplus : null;
      const d = new Date(getNow());
      const resetDate = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1)).toISOString().slice(0, 10);
      let entitlement: number | null = null, remaining: number | null = null, used: number | null = null;
      let pledged: number | null = null, donated: number | null = null, left: number | null = null;
      let pledgedConsumed: number | null = null, donatedConsumed: number | null = null;
      if (u.role === 'giver' && u.totalCredit !== null) {
        entitlement = u.totalCredit + (u.consumedThisMonth ?? 0);
        used = u.consumedThisMonth ?? 0;
        pledged = u.pledgedSurplus ?? 0;
        donated = u.donatedSoFar;
        left = Math.max(0, entitlement - used - pledged - donated);
        pledgedConsumed = Math.min(pledged, u.poolConsumedFrom ?? 0);
        donatedConsumed = Math.min(donated, u.grantsConsumed ?? 0);
        remaining = left;
      }
      let tier: string | null = null, net: number | null = null, netToNext: number | null = null;
      if (u.role === 'giver') {
        const ranked = assignTiers(giverNets());
        const idx = ranked.findIndex(r => r.name === u.name);
        if (idx >= 0) { tier = ranked[idx].tier; net = ranked[idx].net; if (idx > 0 && tier !== 'newcomer') netToNext = Math.max(1, ranked[idx - 1].net - ranked[idx].net); }
      }
      return {
        user: { id: u.id, name: u.name, initials: u.initials, role: u.role },
        totalCredit: u.totalCredit, pledgedSurplus: u.pledgedSurplus, retained, donatedSoFar: u.donatedSoFar,
        consumed: u.consumed, donationsReceived: u.donationsReceived,
        donationsReceivedConsumed: Math.min(u.donationsReceived, u.receivedConsumed ?? 0),
        donationsReceivedRemaining: receivedRemaining(u),
        donationsReceivedFromPool: u.receivedFromPool ?? 0,
        reDonated: u.reDonated ?? 0, returnedToPool: u.returnedToPool ?? 0,
        entitlement, remaining, used, pledged, donated, left, pledgedConsumed, donatedConsumed,
        donatedRemaining: donated !== null && donatedConsumed !== null ? Math.max(0, donated - donatedConsumed) : null,
        pledgedRemaining: pledged !== null && pledgedConsumed !== null ? Math.max(0, pledged - pledgedConsumed) : null,
        resetDate, unlimited: false, quotaStale: false, tier, net, netToNext,
      };
    },

    async getSettings(): Promise<SettingsData> {
      const u = requireUser();
      return { name: u.name, login: u.email ? u.email.split('@')[0] : u.id, role: u.role, hasPat: u.hasPat,
        patHealth: u.hasPat ? 'valid' : null, patHealthCheckedAt: u.hasPat ? 1_700_000_000 : null,
        totalCredit: u.totalCredit, pledgedSurplus: u.pledgedSurplus };
    },
    async updateSettings(patch: SettingsPatch): Promise<SettingsData> {
      const u = requireUser();
      const i = users.findIndex(x => x.id === u.id);
      users[i] = { ...u, ...(patch.name !== undefined && { name: patch.name }), ...(patch.role !== undefined && { role: patch.role }),
        ...(patch.pledgedSurplus !== undefined && { pledgedSurplus: patch.pledgedSurplus }), ...(patch.pat !== undefined && { hasPat: true }) };
      if (session && (patch.name || patch.role)) session = { ...session, ...(patch.name && { name: patch.name }), ...(patch.role && { role: patch.role }) };
      return api.getSettings();
    },

    async getHistory(): Promise<CycleReport[]> { return [...months]; },

    async getCliCredentials() {
      if (!session) throw new Error('Not authenticated');
      const body = (session.userId.replace(/[^a-zA-Z0-9]/g, '') + 'CTC0000000000000000000000000000000000').slice(0, 36);
      proxyTokens = [...proxyTokens, { id: `tok_${++_idCounter}`, fingerprint: body.slice(0, 8), createdAt: Math.floor(getNow() / 1000), revoked: false }];
      return { token: `github_pat_${body}`, proxyHost: 'ctc.local:8080', installCommand: `curl -fsSLk https://ctc.local/install.sh | sh -s -- --token github_pat_${body}`, caFingerprint: 'AA:BB:CC:DD' };
    },
    async listProxyTokens() { return proxyTokens.filter(t => !t.revoked); },
    async revokeProxyToken(id: string) { proxyTokens = proxyTokens.map(t => t.id === id ? { ...t, revoked: true } : t); },

    async getUserProfile(id: string): Promise<PublicProfile> {
      const u = users.find(x => x.id === id);
      if (!u) throw new CtcApiError('not_found', 'not found', 404);
      let tier: string | null = null;
      if (u.role === 'giver') { const ranked = assignTiers(giverNets()); tier = ranked.find(r => r.name === u.name)?.tier ?? null; }
      // Public credit cycle — same math as getOwnProfile's giver branch.
      let cycle: Partial<PublicProfile> = {};
      if (u.role === 'giver' && u.totalCredit !== null) {
        const entitlement = u.totalCredit + (u.consumedThisMonth ?? 0);
        const used = u.consumedThisMonth ?? 0;
        const pledged = u.pledgedSurplus ?? 0;
        const donated = u.donatedSoFar;
        const pledgedConsumed = Math.min(pledged, u.poolConsumedFrom ?? 0);
        const donatedConsumed = Math.min(donated, u.grantsConsumed ?? 0);
        cycle = {
          entitlement, used, pledged, pledgedConsumed, donatedConsumed,
          donatedRemaining: Math.max(0, donated - donatedConsumed),
          pledgedRemaining: Math.max(0, pledged - pledgedConsumed),
          left: Math.max(0, entitlement - used - pledged - donated),
          unlimited: false,
        };
      }
      return { id: u.id, name: u.name, login: loginOf(u), initials: u.initials, role: u.role, tier,
        net: u.role === 'giver' ? u.donatedSoFar - u.consumed : null, donated: u.role === 'giver' ? u.donatedSoFar : null, donationsMade: u.role === 'giver' ? 0 : null,
        ...cycle };
    },
    async searchUsers(q: string): Promise<PublicUserHit[]> {
      if (!q.trim()) return [];
      const l = q.toLowerCase();
      return users.filter(u => u.name.toLowerCase().includes(l) || loginOf(u).includes(l)).slice(0, 8).map(u => ({ id: u.id, name: u.name, login: loginOf(u), initials: u.initials, role: u.role }));
    },

    async listAllUsers(): Promise<AdminUser[]> {
      return users.map(u => ({ id: u.id, gheLogin: loginOf(u), displayName: u.name, role: u.role, onboarded: true, hasPat: u.hasPat,
        patFingerprint: u.hasPat ? u.id.slice(0, 8) : null,
        patHealth: u.hasPat ? 'valid' as const : null, patHealthCheckedAt: u.hasPat ? 1_700_000_000 : null, patHealthError: null, tokenCount: 0,
        quota: u.role === 'giver' ? u.totalCredit : null, pledge: u.role === 'giver' ? u.pledgedSurplus : null, pledgeRemaining: u.role === 'giver' ? u.pledgedSurplus : null }));
    },
    async getUserDetail(id: string): Promise<AdminUserDetail> {
      const u = users.find(x => x.id === id);
      if (!u) throw new Error(`User not found: ${id}`);
      return { id: u.id, gheLogin: loginOf(u), displayName: u.name, role: u.role, onboarded: true, hasPat: u.hasPat,
        patFingerprint: u.hasPat ? u.id.slice(0, 8) : null,
        patHealth: u.hasPat ? 'valid' as const : null, patHealthCheckedAt: u.hasPat ? 1_700_000_000 : null, patHealthError: null,
        tokenCount: 0, quota: u.totalCredit, pledge: u.pledgedSurplus, pledgeRemaining: u.pledgedSurplus,
        proxyTokens: [], pat: u.hasPat ? { fingerprint: u.id.slice(0, 8), createdAt: 0 } : null };
    },
    async revealPat(id: string): Promise<string> { if (!users.find(x => x.id === id)) throw new Error(`User not found: ${id}`); return `github_pat_mock_${id}`; },
    async getAdminSettings(): Promise<AdminSettings> { return adminSettings; },
    async updateAdminSettings(patch: AdminSettingsPatch): Promise<AdminSettings> {
      const next = { ...adminSettings } as AdminSettings;
      const set = <K extends keyof AdminSettingsPatch>(k: K, field: keyof AdminSettings) => {
        if (patch[k] !== undefined) (next as any)[field] = { value: patch[k], isOverride: true };
      };
      set('defaultPledgePct', 'defaultPledgePct');
      set('requestExpiryHours', 'requestExpiryHours'); set('requestExpiryMaxHours', 'requestExpiryMaxHours');
      set('creditToEuroRate', 'creditToEuroRate'); set('defaultChipInAiu', 'defaultChipInAiu');
      set('participantsMode', 'participantsMode'); set('sharedPoolEnabled', 'sharedPoolEnabled');
      adminSettings = next;
      return adminSettings;
    },
  };

  return api;
}

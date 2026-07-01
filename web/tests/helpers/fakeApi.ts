// Test-only fake CtcApi.
//
// The shipped app talks to the real control plane exclusively (HttpCtcApi); there
// is no mock backend in `src/`. Screen/integration tests still need a data source,
// so this in-memory fake implements the CtcApi surface with a small seeded store
// and the few stateful mutations tests exercise (donate, createRequest, settings).
// It is a test fixture, not shipped code — keep it here under tests/.
import type { CtcApi, ListRequestsResult } from '@/api/CtcApi';
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
  donatedSoFar: number; allowance: number | null; consumed: number;
  donationsReceived: number; isAdmin?: boolean;
  consumedThisMonth?: number; poolConsumedFrom?: number; grantsConsumed?: number;
  receivedConsumed?: number;  // nano-AIU of received grants already burned
}
interface FakeRequest {
  id: string; requesterId?: string; requesterName: string; initials: string;
  requesterRole: 'pro' | 'noob'; amountNeeded: number; amountFunded: number;
  fundedConsumed?: number;
  reason: string; target: string | null; createdAt: number; expiresAt: number;
  donorCount: number;
}

const DEFAULT_BOOT_CONFIG: AdminBootConfig = { webTransport: 'http' };
const DEFAULT_ADMIN_SETTINGS: AdminSettings = {
  freeAllowanceAiu:      { value: 300,    isOverride: false },
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

function seedRequests(now: number): FakeRequest[] {
  return [
    { id: 'req_1', requesterId: 'u_lh', requesterName: 'Lena Hoffmann', initials: 'LH', requesterRole: 'noob',
      amountNeeded: 60 * N, amountFunded: 35 * N, reason: 'Finishing the migration PR', target: null, createdAt: now, expiresAt: now + 4 * 3_600_000, donorCount: 2 },
    { id: 'req_2', requesterId: 'u_dr', requesterName: 'Diego Ramirez', initials: 'DR', requesterRole: 'noob',
      amountNeeded: 40 * N, amountFunded: 10 * N, reason: 'Code-review marathon today', target: null, createdAt: now, expiresAt: now + 18 * 3_600_000, donorCount: 1 },
    { id: 'req_3', requesterId: 'u_pn', requesterName: 'Priya Nair', initials: 'PN', requesterRole: 'noob',
      amountNeeded: 90 * N, amountFunded: 0, reason: 'Debugging a prod incident', target: 'Ada Lovelace', createdAt: now, expiresAt: now + 26 * 3_600_000, donorCount: 0 },
    { id: 'req_4', requesterId: 'u_at', requesterName: 'Amine Tazi', initials: 'AT', requesterRole: 'pro',
      amountNeeded: 120 * N, amountFunded: 120 * N, fundedConsumed: 72 * N, reason: 'Ran dry mid-refactor', target: null, createdAt: now, expiresAt: now, donorCount: 3 },
    { id: 'req_5', requesterName: 'Tom Becker', initials: 'TB', requesterRole: 'noob',
      amountNeeded: 30 * N, amountFunded: 30 * N, fundedConsumed: 30 * N, reason: 'Writing test coverage', target: null, createdAt: now, expiresAt: now, donorCount: 1 },
  ];
}

function seedUsers(): FakeUser[] {
  return [
    { id: 'u_ada', name: 'Ada Lovelace', initials: 'AL', role: 'giver', hasPat: true, totalCredit: 5000 * N, pledgedSurplus: 2000 * N,
      donatedSoFar: 1860 * N, allowance: null, consumed: 920 * N, donationsReceived: 0, isAdmin: true,
      consumedThisMonth: 200 * N, poolConsumedFrom: 100 * N, grantsConsumed: 50 * N },
    { id: 'u_kef', name: 'Yuki Tanaka', initials: 'KF', role: 'giver', hasPat: true, totalCredit: null, pledgedSurplus: null, donatedSoFar: 1860 * N, allowance: null, consumed: 1240 * N, donationsReceived: 0 },
    { id: 'u_sl', name: 'Sofia Lindqvist', initials: 'SL', role: 'giver', hasPat: true, totalCredit: null, pledgedSurplus: null, donatedSoFar: 1400 * N, allowance: null, consumed: 780 * N, donationsReceived: 0 },
    { id: 'u_mb', name: 'Marco Bianchi', initials: 'MB', role: 'giver', hasPat: true, totalCredit: null, pledgedSurplus: null, donatedSoFar: 1540 * N, allowance: null, consumed: 540 * N, donationsReceived: 0 },
    { id: 'u_at', name: 'Amine Tazi', initials: 'AT', role: 'giver', hasPat: true, totalCredit: null, pledgedSurplus: null, donatedSoFar: 610 * N, allowance: null, consumed: 310 * N, donationsReceived: 0 },
    { id: 'u_lh', name: 'Lena Hoffmann', initials: 'LH', role: 'consumer', hasPat: false, totalCredit: null, pledgedSurplus: null, donatedSoFar: 0, allowance: 60 * N, consumed: 412 * N, donationsReceived: 120 * N, receivedConsumed: 85 * N },
    { id: 'u_dr', name: 'Diego Ramirez', initials: 'DR', role: 'consumer', hasPat: false, totalCredit: null, pledgedSurplus: null, donatedSoFar: 0, allowance: 40 * N, consumed: 388 * N, donationsReceived: 0 },
    { id: 'u_pn', name: 'Priya Nair', initials: 'PN', role: 'consumer', hasPat: false, totalCredit: null, pledgedSurplus: null, donatedSoFar: 0, allowance: 90 * N, consumed: 276 * N, donationsReceived: 0 },
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

export type FakeApi = CtcApi & { _users(): FakeUser[] };

let _idCounter = 0;

/** Build an in-memory fake CtcApi with a seeded store. Drop-in for the old createMockApi. */
export function makeFakeApi(opts?: FakeApiOpts): FakeApi {
  const getNow = opts?.now ?? (() => Date.now());
  const participantsMode = opts?.participantsMode ?? 'givers_and_consumers';
  const sharedPoolEnabled = opts?.sharedPoolEnabled ?? true;

  let users = seedUsers();
  let requests = seedRequests(getNow());
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
      fundedConsumed: r.fundedConsumed ?? 0,
      reason: r.reason, target: r.target, createdAt: r.createdAt, expiresAt: r.expiresAt,
      status: deriveStatus(r.amountFunded, r.amountNeeded, r.expiresAt, now),
      donorCount: r.donorCount, isOwn: !!viewerId && r.requesterId === viewerId,
    };
  }

  function giverNets() {
    return users.filter(u => u.role === 'giver')
      .map(u => ({ name: u.name, net: u.donatedSoFar - u.consumed, active: u.donatedSoFar > 0 || u.consumed > 0 }));
  }

  const api: FakeApi = {
    _users: () => users,

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
      const now = getNow();
      const all = requests;
      const filtered = filter === 'all' ? all : all.filter(r => r.requesterRole === filter);
      return {
        requests: filtered.map(r => toPublic(r, now, session?.userId)),
        counts: { all: all.length, pro: all.filter(r => r.requesterRole === 'pro').length, noob: all.filter(r => r.requesterRole === 'noob').length },
      };
    },
    async createRequest(input: CreateRequestInput): Promise<PublicRequest> {
      const u = requireUser();
      const now = getNow();
      const r: FakeRequest = {
        id: `req_${now}_${++_idCounter}`, requesterId: u.id, requesterName: u.name, initials: u.initials,
        requesterRole: u.role === 'giver' ? 'pro' : 'noob', amountNeeded: input.amountNeeded, amountFunded: 0,
        reason: input.reason, target: input.target, createdAt: now, expiresAt: now + input.expiryHours * 3_600_000, donorCount: 0,
      };
      requests = [r, ...requests];
      return toPublic(r, now, u.id);
    },
    async donate(requestId: string, amount: number): Promise<PublicRequest> {
      const giver = requireUser();
      const now = getNow();
      const i = requests.findIndex(r => r.id === requestId);
      if (i === -1) throw new Error('Request not found');
      const r = requests[i];
      if (r.requesterId === giver.id) throw new Error('cannot fund your own request');
      const actual = Math.min(amount, r.amountNeeded - r.amountFunded);
      if (actual <= 0) throw new Error('Nothing to donate');
      const updated: FakeRequest = { ...r, amountFunded: r.amountFunded + actual, donorCount: r.donorCount + 1 };
      requests = requests.map((x, idx) => (idx === i ? updated : x));
      const gi = users.findIndex(u => u.id === giver.id);
      users[gi] = { ...users[gi], donatedSoFar: users[gi].donatedSoFar + actual };
      return toPublic(updated, now, giver.id);
    },

    async getDashboard(): Promise<DashboardData> {
      const now = getNow();
      const openCount = requests.filter(r => { const s = deriveStatus(r.amountFunded, r.amountNeeded, r.expiresAt, now); return s === 'open' || s === 'partially_funded'; }).length;
      const closedCount = requests.filter(r => { const s = deriveStatus(r.amountFunded, r.amountNeeded, r.expiresAt, now); return s === 'fulfilled' || s === 'expired'; }).length;
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
        fulfillmentRate: 86, activeGivers: 5, activeConsumers: 12, openCount, closedCount, activity,
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
      let allowanceMax: number | null = null, allowanceUsed: number | null = null, allowanceLeft: number | null = null;
      if (u.role === 'giver' && u.totalCredit !== null) {
        entitlement = u.totalCredit + (u.consumedThisMonth ?? 0);
        used = u.consumedThisMonth ?? 0;
        pledged = u.pledgedSurplus ?? 0;
        donated = u.donatedSoFar;
        left = Math.max(0, entitlement - used - pledged - donated);
        pledgedConsumed = Math.min(pledged, u.poolConsumedFrom ?? 0);
        donatedConsumed = Math.min(donated, u.grantsConsumed ?? 0);
        remaining = left;
      } else if (u.role === 'consumer' && u.allowance !== null) {
        allowanceMax = u.allowance; allowanceUsed = u.consumed; allowanceLeft = Math.max(0, u.allowance - u.consumed);
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
        allowance: u.allowance, consumed: u.consumed, donationsReceived: u.donationsReceived,
        donationsReceivedConsumed: Math.min(u.donationsReceived, u.receivedConsumed ?? 0),
        donationsReceivedRemaining: Math.max(0, u.donationsReceived - (u.receivedConsumed ?? 0)),
        entitlement, remaining, used, pledged, donated, left, pledgedConsumed, donatedConsumed,
        donatedRemaining: donated !== null && donatedConsumed !== null ? Math.max(0, donated - donatedConsumed) : null,
        pledgedRemaining: pledged !== null && pledgedConsumed !== null ? Math.max(0, pledged - pledgedConsumed) : null,
        allowanceMax, allowanceUsed, allowanceLeft, resetDate, unlimited: false, quotaStale: false, tier, net, netToNext,
      };
    },

    async getSettings(): Promise<SettingsData> {
      const u = requireUser();
      return { name: u.name, login: u.email ? u.email.split('@')[0] : u.id, role: u.role, hasPat: u.hasPat, totalCredit: u.totalCredit, pledgedSurplus: u.pledgedSurplus, allowance: u.allowance };
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
      return { token: `github_pat_${body}`, proxyHost: 'ctc.local:8080', installCommand: `curl -fsSLk https://ctc.local/install.sh | sh -s -- --token github_pat_${body}`, caFingerprint: 'AA:BB:CC:DD' };
    },

    async getUserProfile(id: string): Promise<PublicProfile> {
      const u = users.find(x => x.id === id);
      if (!u) throw new CtcApiError('not_found', 'not found', 404);
      let tier: string | null = null;
      if (u.role === 'giver') { const ranked = assignTiers(giverNets()); tier = ranked.find(r => r.name === u.name)?.tier ?? null; }
      return { id: u.id, name: u.name, login: loginOf(u), initials: u.initials, role: u.role, tier,
        net: u.role === 'giver' ? u.donatedSoFar - u.consumed : null, donated: u.role === 'giver' ? u.donatedSoFar : null, donationsMade: u.role === 'giver' ? 0 : null };
    },
    async searchUsers(q: string): Promise<PublicUserHit[]> {
      if (!q.trim()) return [];
      const l = q.toLowerCase();
      return users.filter(u => u.name.toLowerCase().includes(l) || loginOf(u).includes(l)).slice(0, 8).map(u => ({ id: u.id, name: u.name, login: loginOf(u), initials: u.initials, role: u.role }));
    },

    async listAllUsers(): Promise<AdminUser[]> {
      return users.map(u => ({ id: u.id, gheLogin: loginOf(u), displayName: u.name, role: u.role, onboarded: true, hasPat: u.hasPat,
        patFingerprint: u.hasPat ? u.id.slice(0, 8) : null, tokenCount: 0,
        quota: u.role === 'giver' ? u.totalCredit : null, pledge: u.role === 'giver' ? u.pledgedSurplus : null, pledgeRemaining: u.role === 'giver' ? u.pledgedSurplus : null }));
    },
    async getUserDetail(id: string): Promise<AdminUserDetail> {
      const u = users.find(x => x.id === id);
      if (!u) throw new Error(`User not found: ${id}`);
      return { id: u.id, gheLogin: loginOf(u), displayName: u.name, role: u.role, onboarded: true, hasPat: u.hasPat,
        patFingerprint: u.hasPat ? u.id.slice(0, 8) : null, tokenCount: 0, quota: u.totalCredit, pledge: u.pledgedSurplus, pledgeRemaining: u.pledgedSurplus,
        proxyTokens: [], pat: u.hasPat ? { fingerprint: u.id.slice(0, 8), createdAt: 0 } : null };
    },
    async revealPat(id: string): Promise<string> { if (!users.find(x => x.id === id)) throw new Error(`User not found: ${id}`); return `github_pat_mock_${id}`; },
    async getAdminSettings(): Promise<AdminSettings> { return adminSettings; },
    async updateAdminSettings(patch: AdminSettingsPatch): Promise<AdminSettings> {
      const next = { ...adminSettings } as AdminSettings;
      const set = <K extends keyof AdminSettingsPatch>(k: K, field: keyof AdminSettings) => {
        if (patch[k] !== undefined) (next as any)[field] = { value: patch[k], isOverride: true };
      };
      set('freeAllowanceAiu', 'freeAllowanceAiu'); set('defaultPledgePct', 'defaultPledgePct');
      set('requestExpiryHours', 'requestExpiryHours'); set('requestExpiryMaxHours', 'requestExpiryMaxHours');
      set('creditToEuroRate', 'creditToEuroRate'); set('defaultChipInAiu', 'defaultChipInAiu');
      set('participantsMode', 'participantsMode'); set('sharedPoolEnabled', 'sharedPoolEnabled');
      adminSettings = next;
      return adminSettings;
    },
  };

  return api;
}

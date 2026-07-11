// Role types
export type Role = 'giver' | 'consumer';
export type RequesterRole = 'pro' | 'noob';

// Request status
export type RequestStatus = 'open' | 'partially_funded' | 'fulfilled' | 'expired' | 'cancelled';

// Public-facing interfaces (privacy invariant: no totalCredit, no pledgedSurplus)
export interface PublicUser {
  id: string;
  name: string;
  initials: string;
  role: Role;
}

/** Public profile for a user. The credit cycle (entitlement/used/pledged/kept)
 *  is public by design since 2026-07-11 — visitors see a Host's credit bar. */
export interface PublicProfile {
  id: string;
  name: string;
  login: string;
  initials: string;
  role: Role;
  tier: string | null;
  net: number | null;        // nano-AIU
  donated: number | null;    // nano-AIU
  donationsMade: number | null;
  // Credit-cycle breakdown (givers only; nano-AIU; null/absent for consumers
  // or unlimited entitlements). Powers the public credit bar.
  entitlement?: number | null;
  used?: number | null;
  donatedConsumed?: number | null;
  donatedRemaining?: number | null;
  pledged?: number | null;
  pledgedConsumed?: number | null;
  pledgedRemaining?: number | null;
  left?: number | null;
  unlimited?: boolean;
}

/** Lightweight hit returned by the user search endpoint */
export interface PublicUserHit {
  id: string;
  name: string;
  login: string;
  initials: string;
  role: Role;
}

export interface PublicRequest {
  id: string;
  requesterId: string;      // owner user id (drives click-through to profile)
  requesterName: string;
  initials: string;
  requesterRole: RequesterRole;
  amountNeeded: number;
  amountFunded: number;
  /** nano-AIU of amountFunded the recipient has already burned (receiver progress). */
  fundedConsumed: number;
  reason: string;
  target: string | null;
  createdAt: number;
  expiresAt: number;
  status: RequestStatus;
  donorCount: number;
  isOwn: boolean;   // belongs to the viewing user — can't chip in personally, CAN pool-fund
  /** nano-AIU of amountFunded drawn from the shared pool. */
  poolFunded: number;
}

export interface CreateRequestInput {
  amountNeeded: number;
  reason: string;
  target: string | null;
  expiryHours: number;
}

export interface RoleCounts {
  all: number;
  pro: number;
  noob: number;
}

export interface ActivityEntry {
  time: string;
  // 'pool'/'grant' come from the live consumption feed (shared-pool draw vs
  // directed marketplace chip-in); the others are legacy demo kinds.
  kind: 'pool' | 'grant' | 'donate' | 'request' | 'fulfill' | 'rotate';
  detail: string;
  amount: string;
  actorId?: string | null;  // user id of the actor (undefined when no clear actor)
}

export interface LeaderboardEntry {
  name: string;
  value: number;
  userId: string;  // user id for click-through to public profile
}

export interface StandingEntry {
  name: string;
  net: number;   // nano-AIU
  tier: string;
  userId: string;  // user id for click-through to public profile
}

export interface Leaderboard {
  generous: LeaderboardEntry[];
  topPro: LeaderboardEntry[];
  topNoob: LeaderboardEntry[];
  standings: StandingEntry[];
}

export interface DashboardData {
  pledged: number;
  retained: number;
  rotated: number;
  donatedToNonPat: number;
  donatedThisWeek: number;
  fulfillmentRate: number;
  activeGivers: number;
  activeConsumers: number;
  /** nano-AIU still pledged and undrawn across all givers — the shared pool balance. */
  poolAvailable: number;
  openCount: number;
  closedCount: number;
  activity: ActivityEntry[];
  leaderboardSnapshot: {
    generous: LeaderboardEntry[];
    topConsumers: LeaderboardEntry[];
  };
  /** Current cycle's month label, e.g. "July 2026". */
  cycleLabel: string;
  /** 1-based ordinal of the current cycle since inception. */
  cycleNumber: number;
  /** ISO date (YYYY-MM-DD, UTC) the cycle resets; null if unknown. */
  resetDate: string | null;
  /** Whole days until the cycle resets (ceil, floored at 0). */
  daysLeft: number;
}

export interface CycleReport {
  id: string;
  label: string;
  pledged: number;
  /** Total credit the company had this cycle = Σ each giver's quota. */
  budgetTotal: number;
  /** Total credit actually used this cycle (own + pool + grant). */
  usedTotal: number;
  donated: number;
  toNonPat: number;
  toPat: number;
  reqFilled: number;
  reqTotal: number;
  reqPat: number;
  reqNonPat: number;
  fills: Array<{
    who: string;
    amount: number;
    count: number;
  }>;
  winners: {
    generous: LeaderboardEntry;
    pro: LeaderboardEntry;
    noob: LeaderboardEntry;
    rotator?: LeaderboardEntry;
  };
}

// Profile and account interfaces (privacy: totalCredit and pledgedSurplus only here)
export interface OwnProfile {
  user: PublicUser;
  totalCredit: number | null;
  pledgedSurplus: number | null;
  retained: number | null;
  donatedSoFar: number;
  consumed: number;
  donationsReceived: number;
  donationsReceivedConsumed: number;   // nano-AIU of received grants already burned
  donationsReceivedRemaining: number;  // nano-AIU of received grants still available
  donationsReceivedFromPool: number;   // nano-AIU of the received total that came from the shared pool
  reDonated?: number;                  // nano-AIU of received credit passed on to other requests
  returnedToPool?: number;             // nano-AIU of received credit moved into the shared pool
  // Credit-segment fields (giver: from quota)
  entitlement: number | null;
  remaining: number | null;
  used: number | null;
  pledged: number | null;
  donated: number | null;
  left: number | null;
  pledgedConsumed: number | null;
  donatedConsumed: number | null;
  donatedRemaining: number | null;  // max(0, donated - donatedConsumed) — computed server-side
  pledgedRemaining: number | null;  // pledge not yet drawn from pool — computed server-side
  resetDate: string | null;
  unlimited: boolean;
  quotaStale: boolean;
  tier: string | null;
  net: number | null;
  netToNext: number | null;
}

/**
 * Verdict of the periodic giver-PAT health check.
 * 'unreachable' means the last check could not reach GHE (the previous verdict
 * is kept server-side); null means no PAT or never checked.
 */
export type PatHealth = 'valid' | 'expired' | 'forbidden' | 'no_entitlement' | 'unreachable';

export interface SettingsData {
  name: string;
  login: string;
  role: Role;
  hasPat: boolean;
  patHealth: PatHealth | null;
  patHealthCheckedAt: number | null;
  totalCredit: number | null;
  pledgedSurplus: number | null;
}

export interface SettingsPatch {
  name?: string;
  email?: string;
  role?: Role;
  pledgedSurplus?: number;
  pat?: string;
}

// Session and auth interfaces
export interface Session {
  userId: string;
  name: string;
  role: Role;
  onboarded: boolean;
  isAdmin?: boolean;
  /** Deployment-level flags from /api/me */
  participantsMode?: 'givers_only' | 'givers_and_consumers';
  sharedPoolEnabled?: boolean;
  /** Effective euros-per-AIU rate, live from /api/me (admin-editable). */
  creditToEuroRate?: number;
  /** Effective default chip-in amount in AIU, live from /api/me (admin-editable). */
  defaultChipInAiu?: number;
  webTransport?: 'http' | 'https';
  hasPat?: boolean;
}

export interface OnboardingInput {
  name: string;
  /** Optional — carried through onboarding but not required by the backend. */
  email?: string;
  role: Role;
  pat?: string;
  pledgedSurplus?: number;
}

// Admin DTO types
export interface AdminUser {
  id: string;
  gheLogin: string;
  displayName: string | null;
  role: Role;
  onboarded: boolean;
  hasPat: boolean;
  patFingerprint: string | null;
  patHealth: PatHealth | null;
  patHealthCheckedAt: number | null;
  patHealthError: string | null;
  tokenCount: number;
  quota: number | null;
  pledge: number | null;
  pledgeRemaining: number | null;
}

export interface AdminUserDetail extends AdminUser {
  proxyTokens: { id: string; fingerprint: string; createdAt: number; revoked: boolean }[];
  pat: { fingerprint: string; createdAt: number } | null;
}

export interface AdminSettingField<T> { value: T; isOverride: boolean; }

export interface AdminBootConfig {
  webTransport: string;
}

export interface AdminSettings {
  defaultPledgePct: AdminSettingField<number>;
  requestExpiryHours: AdminSettingField<number>;
  requestExpiryMaxHours: AdminSettingField<number>;
  creditToEuroRate: AdminSettingField<number>;
  defaultChipInAiu: AdminSettingField<number>;
  participantsMode: AdminSettingField<string>;
  sharedPoolEnabled: AdminSettingField<boolean>;
  boot: AdminBootConfig | null;
}

export type AdminSettingsPatch = Partial<{
  defaultPledgePct: number;
  requestExpiryHours: number;
  requestExpiryMaxHours: number;
  creditToEuroRate: number;
  defaultChipInAiu: number;
  participantsMode: 'givers_only' | 'givers_and_consumers';
  sharedPoolEnabled: boolean;
}>;

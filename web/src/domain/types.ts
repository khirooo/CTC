// Role types
export type Role = 'giver' | 'consumer';
export type RequesterRole = 'pro' | 'noob';

// Request status
export type RequestStatus = 'open' | 'partially_funded' | 'fulfilled' | 'expired';

// Public-facing interfaces (privacy invariant: no totalCredit, no pledgedSurplus)
export interface PublicUser {
  id: string;
  name: string;
  initials: string;
  role: Role;
}

export interface PublicRequest {
  id: string;
  requesterName: string;
  initials: string;
  requesterRole: RequesterRole;
  amountNeeded: number;
  amountFunded: number;
  reason: string;
  target: string | null;
  createdAt: number;
  expiresAt: number;
  status: RequestStatus;
  donorCount: number;
  isOwn: boolean;   // belongs to the viewing user — can't fund your own request
}

export interface CreateRequestInput {
  amountNeeded: number;
  reason: string;
  target: string | null;
  expiryHours: number;
}

export interface Donation {
  id: string;
  requestId: string;
  fromUserId: string;
  toUserId: string;
  amount: number;
  kind: 'rotate' | 'transfer';
  createdAt: number;
}

export interface RoleCounts {
  all: number;
  pro: number;
  noob: number;
}

export interface ActivityEntry {
  time: string;
  kind: 'donate' | 'request' | 'fulfill' | 'rotate';
  detail: string;
  amount: string;
}

export interface LeaderboardEntry {
  name: string;
  value: number;
}

export interface Leaderboard {
  generous: LeaderboardEntry[];
  topPro: LeaderboardEntry[];
  topNoob: LeaderboardEntry[];
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
  openCount: number;
  closedCount: number;
  activity: ActivityEntry[];
  leaderboardSnapshot: {
    generous: LeaderboardEntry[];
    topConsumers: LeaderboardEntry[];
  };
}

export interface CycleReport {
  id: string;
  label: string;
  pledged: number;
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
  allowance: number | null;
  consumed: number;
  donationsReceived: number;
  // Credit-segment fields (giver: from quota; consumer: from allowance)
  entitlement: number | null;
  remaining: number | null;
  used: number | null;
  pledged: number | null;
  donated: number | null;
  left: number | null;
  pledgedConsumed: number | null;
  donatedConsumed: number | null;
  allowanceMax: number | null;
  allowanceUsed: number | null;
  allowanceLeft: number | null;
  resetDate: string | null;
  unlimited: boolean;
  quotaStale: boolean;
}

export interface SettingsData {
  name: string;
  login: string;
  role: Role;
  hasPat: boolean;
  totalCredit: number | null;
  pledgedSurplus: number | null;
  allowance: number | null;
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
  authMode?: 'email' | 'ghe_oauth';
  webTransport?: 'http' | 'https';
  hasPat?: boolean;
}

export interface SignUpInput {
  name: string;
  email: string;
  password: string;
}

export interface OnboardingInput {
  name: string;
  /** Optional — captured at signup; unused by completeOnboarding today. */
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
  authMode: string;
  webTransport: string;
  emailBackend: string;
}

export interface AdminSettings {
  freeAllowanceAiu: AdminSettingField<number>;
  defaultPledgePct: AdminSettingField<number>;
  requestExpiryHours: AdminSettingField<number>;
  requestExpiryMaxHours: AdminSettingField<number>;
  creditToEuroRate: AdminSettingField<number>;
  participantsMode: AdminSettingField<string>;
  sharedPoolEnabled: AdminSettingField<boolean>;
  boot: AdminBootConfig | null;
}

export type AdminSettingsPatch = Partial<{
  freeAllowanceAiu: number;
  defaultPledgePct: number;
  requestExpiryHours: number;
  requestExpiryMaxHours: number;
  creditToEuroRate: number;
  participantsMode: 'givers_only' | 'givers_and_consumers';
  sharedPoolEnabled: boolean;
}>;

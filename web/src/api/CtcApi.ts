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
  RoleCounts,
  AdminUser,
  AdminUserDetail,
  AdminSettings,
  AdminSettingsPatch,
  PublicProfile,
  PublicUserHit,
} from '@/domain/types';

export interface ListRequestsResult {
  requests: PublicRequest[];
  counts: RoleCounts;
  /** Whether the shared pool feature is on for this deployment. */
  poolEnabled: boolean;
  /** nano-AIU still pledged and undrawn across all givers. */
  poolAvailable: number;
  /** Viewer's chip-in sources (nano-AIU). The chip-in source picker shows only
   *  when both are positive. */
  viewerPersonalRemaining: number;
  viewerReceivedRemaining: number;
}

/** Where a chip-in draws from: your retained credit, or credit routed to you. */
export type DonationSource = 'personal' | 'received';

export interface CtcApi {
  // Auth (real backend is OAuth-only: signIn redirects to GHE; accounts are
  // created on first login, so there is no separate sign-up).
  // email/password are ignored by the real OAuth backend (signIn redirects to
  // GitLab); the test fake uses `email` to select which seeded user to log in as.
  signIn(email: string, password: string): Promise<Session>;
  signOut(): Promise<void>;
  getSession(): Promise<Session | null>;

  // Onboarding
  completeOnboarding(input: OnboardingInput): Promise<Session>;
  validatePat(pat: string): Promise<{ gheLogin: string; quotaAiu: number; entitlementAiu: number; remainingAiu: number; resetDate: string | null; pledgedNano: number; usedNano: number }>;
  // Revoke = full disconnect: delete the stored PAT, zero this cycle's credit,
  // revert to a consumer.
  revokePat(): Promise<void>;
  markOnboarded(): Promise<void>;

  // Requests
  listRequests(filter: 'all' | 'pro' | 'noob'): Promise<ListRequestsResult>;
  createRequest(input: CreateRequestInput): Promise<PublicRequest>;
  /** Owner cancels (soft-deletes) their own request. */
  deleteRequest(requestId: string): Promise<void>;

  // Donations
  donate(requestId: string, amount: number, source?: DonationSource): Promise<PublicRequest>;
  /** Fill any open request (own included) from the shared pool. */
  poolFund(requestId: string, amount: number): Promise<PublicRequest>;
  /** Move unspent received credit into the shared pool. */
  returnReceivedToPool(amount: number): Promise<{ poolAvailable: number; receivedRemaining: number }>;

  // Dashboard & leaderboard
  getDashboard(): Promise<DashboardData>;
  getLeaderboard(): Promise<Leaderboard>;

  // Profile & settings
  getOwnProfile(): Promise<OwnProfile>;
  getSettings(): Promise<SettingsData>;
  updateSettings(patch: SettingsPatch): Promise<SettingsData>;

  // History
  getHistory(): Promise<CycleReport[]>;

  // CLI setup
  /** Mint a NEW proxy token and compose the install one-liner. Minting is a
   *  write — call it only on an explicit user action, never on mount. */
  getCliCredentials(): Promise<{ token: string; proxyHost: string; installCommand: string; caFingerprint: string | null }>;
  /** List the caller's existing proxy tokens (read-only; safe on mount). The
   *  raw token value is shown only once at mint time, so these carry fingerprints. */
  listProxyTokens(): Promise<{ id: string; fingerprint: string; createdAt: number; revoked: boolean }[]>;
  /** Revoke one of the caller's proxy tokens by id (idempotent; scoped to the
   *  caller — a foreign/unknown id is a no-op). Any CLI using it stops working. */
  revokeProxyToken(id: string): Promise<void>;

  // Public profiles
  getUserProfile(id: string): Promise<PublicProfile>;
  searchUsers(q: string): Promise<PublicUserHit[]>;

  // Admin
  listAllUsers(): Promise<AdminUser[]>;
  getUserDetail(id: string): Promise<AdminUserDetail>;
  revealPat(id: string): Promise<string>;
  getAdminSettings(): Promise<AdminSettings>;
  updateAdminSettings(patch: AdminSettingsPatch): Promise<AdminSettings>;
}

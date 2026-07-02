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
}

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

  // Donations
  donate(requestId: string, amount: number): Promise<PublicRequest>;

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
  getCliCredentials(): Promise<{ token: string; proxyHost: string; installCommand: string; caFingerprint: string | null }>;

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

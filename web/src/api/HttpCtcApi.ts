import type { CtcApi, DonationSource, ListRequestsResult } from './CtcApi';
import type {
  PublicRequest, CreateRequestInput, DashboardData, Leaderboard, OwnProfile,
  SettingsData, SettingsPatch, Session, OnboardingInput, CycleReport,
  AdminUser, AdminBalances, AdminUserDetail, AdminSettings, AdminSettingsPatch, AdminBootConfig,
  PublicProfile, PublicUserHit,
} from '@/domain/types';
import { apiFetch, CtcApiError } from './http';

/**
 * Talks to the real control-plane over HTTP: auth (signIn redirect, getSession,
 * signOut), PAT submit, marketplace/settings, read screens (dashboard,
 * leaderboard, history, profile), and CLI credentials. This is the only CtcApi
 * used in production — there is no mock fallback. Auth is the httpOnly session
 * cookie (sent via credentials: 'include'); requests carry no user-identifying
 * header, so cross-origin deployments pass CORS preflight (content-type only).
 */
export class HttpCtcApi implements CtcApi {
  constructor(private base: string) {}

  /** Auth routes (/auth/*) live at the server root; VITE_API_BASE points at the /api mount. */
  private authBase(): string {
    return this.base.replace(/\/api\/?$/, '');
  }

  private getJson(path: string): Promise<any> {
    return apiFetch(this.base, path);
  }

  // --- v1 over HTTP ---
  async listRequests(filter: 'all' | 'pro' | 'noob'): Promise<ListRequestsResult> {
    const r = await apiFetch(this.base, `/requests?filter=${filter}`);
    return {
      requests: r.requests, counts: r.counts,
      poolEnabled: Boolean(r.poolEnabled), poolAvailable: r.poolAvailable ?? 0,
      viewerPersonalRemaining: r.viewerPersonalRemaining ?? 0,
      viewerReceivedRemaining: r.viewerReceivedRemaining ?? 0,
    };
  }
  async createRequest(input: CreateRequestInput): Promise<PublicRequest> {
    return apiFetch(this.base, '/requests', {
      method: 'POST', body: JSON.stringify(input),
    });
  }
  async donate(requestId: string, amount: number, source: DonationSource = 'personal'): Promise<PublicRequest> {
    return apiFetch(this.base, `/requests/${requestId}/donate`, {
      method: 'POST', body: JSON.stringify({ amount, source }),
    });
  }
  async returnReceivedToPool(amount: number): Promise<{ poolAvailable: number; receivedRemaining: number }> {
    return apiFetch(this.base, '/pool/return', {
      method: 'POST', body: JSON.stringify({ amount }),
    });
  }
  async poolFund(requestId: string, amount: number): Promise<PublicRequest> {
    return apiFetch(this.base, `/requests/${requestId}/pool-fund`, {
      method: 'POST', body: JSON.stringify({ amount }),
    });
  }
  async deleteRequest(requestId: string): Promise<void> {
    await apiFetch(this.base, `/requests/${requestId}`, { method: 'DELETE' });
  }
  async getSettings(): Promise<SettingsData> {
    return apiFetch(this.base, '/settings');
  }
  async updateSettings(patch: SettingsPatch): Promise<SettingsData> {
    // PAT submit is a distinct endpoint (validates against GHE, promotes to giver).
    if (patch.pat) {
      await apiFetch(this.base, '/pat', {
        method: 'POST', body: JSON.stringify({ pat: patch.pat }),
      });
    }
    if (patch.pledgedSurplus !== undefined) {
      await apiFetch(this.base, '/settings', {
        method: 'PATCH', body: JSON.stringify({ pledgedSurplus: patch.pledgedSurplus }),
      });
    }
    return apiFetch(this.base, '/settings');
  }

  // --- auth: OAuth-only (signIn redirects to GitLab; accounts created on first login) ---
  signIn(_email: string, _password: string): Promise<Session> {
    window.location.href = this.authBase() + '/auth/login';
    return new Promise<Session>(() => {}); // never resolves; the page unloads
  }
  async signOut(): Promise<void> {
    await fetch(this.authBase() + '/auth/logout', {
      method: 'POST',
      credentials: 'include',
    });
  }
  async getSession(): Promise<Session | null> {
    const res = await fetch(this.base + '/me', {
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!res.ok) return null;            // 401 (no session) or any error → logged out
    const me = await res.json();
    return {
      userId: me.user_id,
      name: me.display_name ?? me.ghe_login,
      role: me.role,
      onboarded: Boolean(me.onboarded),
      isAdmin: Boolean(me.is_admin),
      hasPat: Boolean(me.has_pat),
      participantsMode: me.participants_mode,
      sharedPoolEnabled: me.shared_pool_enabled !== undefined ? Boolean(me.shared_pool_enabled) : undefined,
      creditToEuroRate: me.credit_to_euro_rate !== undefined ? Number(me.credit_to_euro_rate) : undefined,
      defaultChipInAiu: me.default_chip_in_aiu !== undefined ? Number(me.default_chip_in_aiu) : undefined,
      requestExpiryHours: me.request_expiry_hours !== undefined ? Number(me.request_expiry_hours) : undefined,
      requestExpiryMaxHours: me.request_expiry_max_hours !== undefined ? Number(me.request_expiry_max_hours) : undefined,
      webTransport: me.web_transport,
    };
  }
  async completeOnboarding(input: OnboardingInput): Promise<Session> {
    if (input.pat) {
      await apiFetch(this.base, '/pat', {
        method: 'POST', body: JSON.stringify({ pat: input.pat }),
      });
    }
    const s = await this.getSession();
    if (!s) throw new CtcApiError('no_session', 'session lost after onboarding', 401);
    return s;
  }
  async validatePat(pat: string): Promise<{ gheLogin: string; quotaAiu: number; entitlementAiu: number; remainingAiu: number; resetDate: string | null; pledgedNano: number; usedNano: number }> {
    const res = await apiFetch(this.base, '/pat', {
      method: 'POST', body: JSON.stringify({ pat }),
    });
    return { gheLogin: res.ghe_login, quotaAiu: res.quota_aiu,
             entitlementAiu: res.entitlement_aiu, remainingAiu: res.remaining_aiu,
             resetDate: res.reset_date ?? null, pledgedNano: res.pledged_nano ?? 0,
             usedNano: res.used_nano ?? 0 };
  }
  async revokePat(): Promise<void> {
    await apiFetch(this.base, '/pat', { method: 'DELETE' });
  }
  async markOnboarded(): Promise<void> {
    await apiFetch(this.base, '/onboarding/complete', { method: 'POST' });
  }
  // --- read screens over HTTP ---
  getDashboard(): Promise<DashboardData> { return this.getJson('/dashboard'); }
  getLeaderboard(): Promise<Leaderboard> { return this.getJson('/leaderboard'); }
  getOwnProfile(opts?: { fresh?: boolean }): Promise<OwnProfile> { return this.getJson(opts?.fresh ? '/profile?fresh=1' : '/profile'); }
  getHistory(): Promise<CycleReport[]> { return this.getJson('/history'); }
  async getCliCredentials(): Promise<{ token: string; proxyHost: string; installCommand: string; caFingerprint: string | null }> {
    const minted = await apiFetch(this.base, '/proxy-token', { method: 'POST' });
    const ctcHost = (import.meta.env.VITE_CTC_HOST as string | undefined) ?? 'localhost';
    // Match the scheme the app was actually loaded over: an http-mode deployment
    // has no :443, so an https one-liner would refuse to connect.
    const scheme = window.location.protocol === 'http:' ? 'http' : 'https';
    // -k (skip TLS verify) is only meaningful — and only needed — under https,
    // where the deployment may front a self-signed CA (verify the CA fingerprint
    // below instead). Never send -k over plain http, where it invites a MITM'd
    // script swap for no benefit.
    const curlFlags = scheme === 'https' ? '-fsSLk' : '-fsSL';
    return {
      token: minted.token,
      proxyHost: (import.meta.env.VITE_PROXY_HOST as string | undefined) ?? 'localhost:8080',
      installCommand: `curl ${curlFlags} ${scheme}://${ctcHost}/install.sh | sh -s -- --token ${minted.token}`,
      caFingerprint: minted.ca_fingerprint ?? null,
    };
  }
  async listProxyTokens(): Promise<{ id: string; fingerprint: string; createdAt: number; revoked: boolean }[]> {
    const rows = await apiFetch(this.base, '/proxy-token');
    return (rows ?? []).map((t: any) => ({
      id: t.id, fingerprint: t.fingerprint, createdAt: t.created_at, revoked: Boolean(t.revoked),
    }));
  }
  async revokeProxyToken(id: string): Promise<void> {
    await apiFetch(this.base, `/proxy-token/${encodeURIComponent(id)}`, { method: 'DELETE' });
  }

  // --- Public profiles ---
  async getUserProfile(id: string): Promise<PublicProfile> {
    return this.getJson(`/users/${encodeURIComponent(id)}`);
  }
  async searchUsers(q: string): Promise<PublicUserHit[]> {
    const result = await this.getJson(`/users/search?q=${encodeURIComponent(q)}`);
    return result.users;
  }

  // --- Admin ---
  async listAllUsers(): Promise<AdminUser[]> {
    const rows = await apiFetch(this.base, '/admin/users');
    return rows.map(mapAdminUser);
  }
  async getUserDetail(id: string): Promise<AdminUserDetail> {
    const d = await apiFetch(this.base, `/admin/users/${id}`);
    return {
      ...mapAdminUser(d),
      proxyTokens: (d.proxy_tokens ?? []).map((t: any) => ({
        id: t.id, fingerprint: t.fingerprint, createdAt: t.created_at, revoked: t.revoked,
      })),
      pat: d.pat ? { fingerprint: d.pat.fingerprint, createdAt: d.pat.created_at } : null,
    };
  }
  async revealPat(id: string): Promise<string> {
    const r = await apiFetch(this.base, `/admin/users/${id}/reveal-pat`, { method: 'POST' });
    return r.pat;
  }
  async setUserPledge(id: string, pledgeNano: number): Promise<AdminBalances> {
    const d = await apiFetch(this.base, `/admin/users/${id}/pledge`, {
      method: 'POST', body: JSON.stringify({ pledge: Math.round(pledgeNano) }),
    });
    return {
      quota: d.quota ?? null, pledge: d.pledge ?? null,
      pledgeRemaining: d.pledge_remaining ?? null,
      used: d.used ?? null, donated: d.donated ?? null,
    };
  }
  async getAdminSettings(): Promise<AdminSettings> {
    return mapAdminSettings(await apiFetch(this.base, '/admin/settings'));
  }
  async updateAdminSettings(patch: AdminSettingsPatch): Promise<AdminSettings> {
    const body: Record<string, number | string | boolean> = {};
    if (patch.defaultPledgePct !== undefined) body.default_pledge_pct = patch.defaultPledgePct;
    if (patch.requestExpiryHours !== undefined) body.request_expiry_hours = patch.requestExpiryHours;
    if (patch.requestExpiryMaxHours !== undefined) body.request_expiry_max_hours = patch.requestExpiryMaxHours;
    if (patch.creditToEuroRate !== undefined) body.credit_to_euro_rate = patch.creditToEuroRate;
    if (patch.defaultChipInAiu !== undefined) body.default_chip_in_aiu = patch.defaultChipInAiu;
    if (patch.participantsMode !== undefined) body.participants_mode = patch.participantsMode;
    if (patch.sharedPoolEnabled !== undefined) body.shared_pool_enabled = patch.sharedPoolEnabled ? 'on' : 'off';
    return mapAdminSettings(await apiFetch(this.base, '/admin/settings', {
      method: 'PATCH', body: JSON.stringify(body),
    }));
  }
}

function mapAdminUser(u: any): AdminUser {
  return {
    id: u.id, gheLogin: u.ghe_login, displayName: u.display_name, role: u.role,
    onboarded: Boolean(u.onboarded), hasPat: Boolean(u.has_pat),
    patFingerprint: u.pat_fingerprint ?? null,
    patHealth: u.pat_health ?? null,
    patHealthCheckedAt: u.pat_health_checked_at ?? null,
    patHealthError: u.pat_health_error ?? null,
    tokenCount: u.token_count ?? 0,
    quota: u.quota ?? null, pledge: u.pledge ?? null, pledgeRemaining: u.pledge_remaining ?? null,
    used: u.used ?? null, donated: u.donated ?? null,
  };
}
function field(f: any) { return { value: f.value, isOverride: Boolean(f.is_override) }; }
function mapAdminSettings(s: any): AdminSettings {
  const boot: AdminBootConfig | null = s.boot
    ? { webTransport: s.boot.web_transport }
    : null;
  return {
    defaultPledgePct: field(s.default_pledge_pct),
    requestExpiryHours: field(s.request_expiry_hours),
    requestExpiryMaxHours: field(s.request_expiry_max_hours),
    creditToEuroRate: field(s.credit_to_euro_rate),
    defaultChipInAiu: field(s.default_chip_in_aiu),
    participantsMode: s.participants_mode ? field(s.participants_mode) : { value: 'givers_only', isOverride: false },
    sharedPoolEnabled: s.shared_pool_enabled ? field(s.shared_pool_enabled) : { value: false, isOverride: false },
    boot,
  };
}

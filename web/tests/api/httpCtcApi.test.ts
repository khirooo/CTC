import { describe, it, expect, vi, beforeEach } from 'vitest';
import { HttpCtcApi } from '@/api/HttpCtcApi';
import { createMockApi } from '@/api/mockApi';
import { CtcApiError } from '@/api/http';

function fakeFetch(status: number, body: unknown) {
  return vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    statusText: 'x',
    json: async () => body,
  })) as unknown as typeof fetch;
}

describe('HttpCtcApi', () => {
  beforeEach(() => { vi.restoreAllMocks(); });

  it('createRequest POSTs camelCase JSON with X-CTC-User and returns parsed body', async () => {
    const mock = createMockApi({ latencyMs: 0, storageKey: 'h.test' });
    await mock.signIn('ada@example.com', 'x');           // sets session userId = u_ada
    const created = { id: 'r1', requesterName: 'Ada Lovelace', amountNeeded: 50 };
    const f = fakeFetch(200, created);
    vi.stubGlobal('fetch', f);
    const api = new HttpCtcApi('http://api');

    const out = await api.createRequest({ amountNeeded: 50, reason: 'x', target: null, expiryHours: 24 });
    expect(out).toEqual(created);
    const [url, init] = (f as any).mock.calls[0];
    expect(url).toBe('http://api/requests');
    expect(init.method).toBe('POST');
    expect(init.headers['X-CTC-User']).toBe('');
    expect(JSON.parse(init.body)).toEqual({ amountNeeded: 50, reason: 'x', target: null, expiryHours: 24 });
  });

  it('throws CtcApiError on non-ok with parsed flat code', async () => {
    const mock = createMockApi({ latencyMs: 0, storageKey: 'h.test2' });
    await mock.signIn('ada@example.com', 'x');
    vi.stubGlobal('fetch', fakeFetch(422, { error: 'insufficient_credit', message: 'nope' }));
    const api = new HttpCtcApi('http://api');
    const err = await api.donate('r1', 10).catch((e) => e);
    expect(err).toBeInstanceOf(CtcApiError);
    expect(err).toMatchObject({ code: 'insufficient_credit', status: 422 });
    expect(err.message).toBe('nope');
  });

  it('getSession maps /api/me to a Session with credentials', async () => {
    const f = vi.fn(async () => ({
      ok: true, status: 200, statusText: 'x',
      json: async () => ({
        user_id: 'u1', ghe_login: 'octocat', display_name: 'Octo', role: 'giver',
        has_pat: true, onboarded: true,
        participants_mode: 'givers_and_consumers', shared_pool_enabled: true,
        auth_mode: 'ghe_oauth', web_transport: 'https',
      }),
    })) as unknown as typeof fetch;
    vi.stubGlobal('fetch', f);
    const api = new HttpCtcApi('http://api');
    const s = await api.getSession();
    expect(s).toMatchObject({
      userId: 'u1', name: 'Octo', role: 'giver', onboarded: true, isAdmin: false,
      hasPat: true, participantsMode: 'givers_and_consumers', sharedPoolEnabled: true,
      authMode: 'ghe_oauth', webTransport: 'https',
    });
    const [url, init] = (f as any).mock.calls[0];
    expect(url).toBe('http://api/me');
    expect(init.credentials).toBe('include');
  });

  it('getSession returns null on 401', async () => {
    vi.stubGlobal('fetch', fakeFetch(401, { error: 'unauthorized', message: 'no session' }));
    const api = new HttpCtcApi('http://api');
    expect(await api.getSession()).toBeNull();
  });

  it('signIn redirects to /auth/login at the server root', async () => {
    const api = new HttpCtcApi('http://host/api');
    const loc = { href: '' };
    vi.stubGlobal('window', { location: loc } as any);
    // signIn never resolves (page unloads); just trigger it.
    // (If this file runs under the jsdom environment instead of node, replace the
    // stubGlobal line with: Object.defineProperty(window, 'location', { value: loc, writable: true }))
    api.signIn('x', 'y');
    expect(loc.href).toBe('http://host/auth/login');
  });

  it('signOut POSTs /auth/logout at the server root', async () => {
    const f = vi.fn(async () => ({ ok: true, status: 204, statusText: 'x', json: async () => ({}) })) as unknown as typeof fetch;
    vi.stubGlobal('fetch', f);
    const api = new HttpCtcApi('http://host/api');
    await api.signOut();
    const [url, init] = (f as any).mock.calls[0];
    expect(url).toBe('http://host/auth/logout');
    expect(init.method).toBe('POST');
    expect(init.credentials).toBe('include');
  });

  it('updateSettings({pat}) POSTs /api/pat then re-reads settings', async () => {
    const mock = createMockApi({ latencyMs: 0, storageKey: 'h.pat' });
    await mock.signIn('ada@example.com', 'x');
    const settings = { name: 'Ada', login: 'a', role: 'giver', hasPat: true, totalCredit: 1, pledgedSurplus: 0, allowance: null };
    const f = vi.fn(async (url: string) => ({
      ok: true, status: 200, statusText: 'x',
      json: async () => (String(url).endsWith('/settings') ? settings : { ghe_login: 'ada', quota_aiu: 4000 }),
    })) as unknown as typeof fetch;
    vi.stubGlobal('fetch', f);
    const api = new HttpCtcApi('http://api');
    const out = await api.updateSettings({ pat: 'ghp_x' });
    const calls = (f as any).mock.calls.map((c: any[]) => [c[0], c[1].method]);
    expect(calls).toContainEqual(['http://api/pat', 'POST']);
    expect(calls).toContainEqual(['http://api/settings', undefined]); // GET settings (no method)
    expect(out).toEqual(settings);
  });

  it('updateSettings({pledgedSurplus}) PATCHes /api/settings', async () => {
    const mock = createMockApi({ latencyMs: 0, storageKey: 'h.pledge' });
    await mock.signIn('ada@example.com', 'x');
    const settings = { name: 'Ada', login: 'a', role: 'giver', hasPat: true, totalCredit: 1, pledgedSurplus: 7, allowance: null };
    const f = vi.fn(async () => ({ ok: true, status: 200, statusText: 'x', json: async () => settings })) as unknown as typeof fetch;
    vi.stubGlobal('fetch', f);
    const api = new HttpCtcApi('http://api');
    await api.updateSettings({ pledgedSurplus: 7 });
    const methods = (f as any).mock.calls.map((c: any[]) => [c[0], c[1].method]);
    expect(methods).toContainEqual(['http://api/settings', 'PATCH']);
  });

  it('getDashboard/getLeaderboard/getHistory/getOwnProfile GET the read endpoints', async () => {
    const mock = createMockApi({ latencyMs: 0, storageKey: 'h.reads' });
    await mock.signIn('ada@example.com', 'x');
    const api = new HttpCtcApi('http://api');

    for (const [path, body, call] of [
      ['/dashboard', { pledged: 1 }, () => api.getDashboard()],
      ['/leaderboard', { generous: [] }, () => api.getLeaderboard()],
      ['/history', [{ id: 'c1' }], () => api.getHistory()],
      ['/profile', { user: { id: 'u1' } }, () => api.getOwnProfile()],
    ] as Array<[string, unknown, () => Promise<unknown>]>) {
      const f = vi.fn(async () => ({ ok: true, status: 200, statusText: 'x', json: async () => body })) as unknown as typeof fetch;
      vi.stubGlobal('fetch', f);
      const out = await call();
      expect(out).toEqual(body);
      expect((f as any).mock.calls[0][0]).toBe('http://api' + path);
      expect((f as any).mock.calls[0][1].credentials).toBe('include');
    }
  });

  it('getCliCredentials POSTs /api/proxy-token and composes display fields', async () => {
    const mock = createMockApi({ latencyMs: 0, storageKey: 'h.cli' });
    await mock.signIn('ada@example.com', 'x');
    const f = vi.fn(async () => ({
      ok: true, status: 200, statusText: 'x',
      json: async () => ({ id: 't1', token: 'github_pat_REAL', fingerprint: 'ab' }),
    })) as unknown as typeof fetch;
    vi.stubGlobal('fetch', f);
    const api = new HttpCtcApi('http://api');
    const out = await api.getCliCredentials();
    const [url, init] = (f as any).mock.calls[0];
    expect(url).toBe('http://api/proxy-token');
    expect(init.method).toBe('POST');
    expect(out.token).toBe('github_pat_REAL');
    expect(typeof out.proxyHost).toBe('string');
    expect(out.installCommand).toContain('install.sh');
  });

  it('validatePat POSTs to /pat and maps ghe_login/quota_aiu/entitlement_aiu/remaining_aiu to camelCase', async () => {
    const mock = createMockApi({ latencyMs: 0, storageKey: 'h.pat' });
    await mock.signIn('ada@example.com', 'x');
    const f = fakeFetch(200, { ghe_login: 'ada', quota_aiu: 4000, entitlement_aiu: 4200, remaining_aiu: 3800, reset_date: '2026-07-01' });
    vi.stubGlobal('fetch', f);
    const api = new HttpCtcApi('http://api');
    const out = await api.validatePat('github_pat_abc');
    expect(out).toEqual({ gheLogin: 'ada', quotaAiu: 4000, entitlementAiu: 4200, remainingAiu: 3800, resetDate: '2026-07-01', pledgedNano: 0 });
    const [url, init] = (f as any).mock.calls[0];
    expect(url).toBe('http://api/pat');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({ pat: 'github_pat_abc' });
  });

  it('validatePat surfaces a 409 owner-mismatch as CtcApiError', async () => {
    const mock = createMockApi({ latencyMs: 0, storageKey: 'h.pat2' });
    await mock.signIn('ada@example.com', 'x');
    vi.stubGlobal('fetch', fakeFetch(409, { error: 'conflict', message: 'PAT belongs to bob, not ada' }));
    const api = new HttpCtcApi('http://api');
    const err = await api.validatePat('github_pat_x').catch((e) => e);
    expect(err).toBeInstanceOf(CtcApiError);
    expect(err).toMatchObject({ status: 409 });
  });

  it('markOnboarded POSTs to /onboarding/complete', async () => {
    const mock = createMockApi({ latencyMs: 0, storageKey: 'h.onb' });
    await mock.signIn('ada@example.com', 'x');
    const f = fakeFetch(204, undefined);
    vi.stubGlobal('fetch', f);
    const api = new HttpCtcApi('http://api');
    await api.markOnboarded();
    const [url, init] = (f as any).mock.calls[0];
    expect(url).toBe('http://api/onboarding/complete');
    expect(init.method).toBe('POST');
  });

  it('getSession reflects onboarded:false from /api/me', async () => {
    vi.stubGlobal('fetch', fakeFetch(200, {
      user_id: 'u1', ghe_login: 'ada', display_name: 'Ada', role: 'consumer', onboarded: false,
    }));
    const api = new HttpCtcApi('http://api');
    const s = await api.getSession();
    expect(s).toMatchObject({ userId: 'u1', role: 'consumer', onboarded: false });
  });
});

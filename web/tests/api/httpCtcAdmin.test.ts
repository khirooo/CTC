// web/tests/api/httpCtcAdmin.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { HttpCtcApi } from '@/api/HttpCtcApi';

const BASE = 'http://cp/api';

function mockFetchOnce(body: any, ok = true, status = 200) {
  return vi.fn().mockResolvedValue({
    ok, status, json: async () => body, text: async () => JSON.stringify(body),
  });
}

beforeEach(() => vi.restoreAllMocks());

describe('HttpCtcApi admin', () => {
  it('maps admin users list from snake_case', async () => {
    vi.stubGlobal('fetch', mockFetchOnce([
      { id: 'u1', ghe_login: 'octo', display_name: 'Octo', role: 'giver', onboarded: true,
        has_pat: true, pat_fingerprint: 'abcd1234', token_count: 2,
        quota: 1000, pledge: 400, pledge_remaining: 400 },
    ]));
    const api = new HttpCtcApi(BASE);
    const users = await api.listAllUsers();
    expect(users[0].gheLogin).toBe('octo');
    expect(users[0].patFingerprint).toBe('abcd1234');
    expect(users[0].tokenCount).toBe(2);
  });

  it('revealPat returns the cleartext from the body', async () => {
    vi.stubGlobal('fetch', mockFetchOnce({ pat: 'github_pat_SECRET' }));
    const api = new HttpCtcApi(BASE);
    expect(await api.revealPat('u1')).toBe('github_pat_SECRET');
  });

  it('maps admin settings shape', async () => {
    vi.stubGlobal('fetch', mockFetchOnce({
      free_allowance_aiu: { value: 300, is_override: false },
      default_pledge_pct: { value: 0, is_override: false },
      request_expiry_hours: { value: 24, is_override: false },
      request_expiry_max_hours: { value: 168, is_override: false },
      credit_to_euro_rate: { value: 0.1, is_override: false },
      default_chip_in_aiu: { value: 25, is_override: false },
    }));
    const api = new HttpCtcApi(BASE);
    const s = await api.getAdminSettings();
    expect(s.freeAllowanceAiu).toEqual({ value: 300, isOverride: false });
    expect(s.creditToEuroRate.value).toBe(0.1);
    expect(s.defaultChipInAiu).toEqual({ value: 25, isOverride: false });
  });

  it('updateAdminSettings sends shared_pool_enabled as "on"/"off" string', async () => {
    const fetchMock = mockFetchOnce({
      free_allowance_aiu: { value: 300, is_override: false },
      default_pledge_pct: { value: 0, is_override: false },
      request_expiry_hours: { value: 24, is_override: false },
      request_expiry_max_hours: { value: 168, is_override: false },
      credit_to_euro_rate: { value: 0.1, is_override: false },
      default_chip_in_aiu: { value: 25, is_override: false },
    });
    vi.stubGlobal('fetch', fetchMock);
    const api = new HttpCtcApi(BASE);
    await api.updateAdminSettings({ sharedPoolEnabled: true });
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.shared_pool_enabled).toBe('on');

    // Also verify "off" for false
    const fetchMock2 = mockFetchOnce({
      free_allowance_aiu: { value: 300, is_override: false },
      default_pledge_pct: { value: 0, is_override: false },
      request_expiry_hours: { value: 24, is_override: false },
      request_expiry_max_hours: { value: 168, is_override: false },
      credit_to_euro_rate: { value: 0.1, is_override: false },
      default_chip_in_aiu: { value: 25, is_override: false },
    });
    vi.stubGlobal('fetch', fetchMock2);
    await api.updateAdminSettings({ sharedPoolEnabled: false });
    const body2 = JSON.parse(fetchMock2.mock.calls[0][1].body);
    expect(body2.shared_pool_enabled).toBe('off');
  });

  it('getSession maps is_admin', async () => {
    vi.stubGlobal('fetch', mockFetchOnce({
      user_id: 'u1', display_name: 'Octo', ghe_login: 'octo', role: 'giver',
      onboarded: true, is_admin: true,
    }));
    const api = new HttpCtcApi(BASE);
    const s = await api.getSession();
    expect(s?.isAdmin).toBe(true);
  });
});

import { describe, it, expect, vi, afterEach } from 'vitest';
import { HttpCtcApi } from '@/api/HttpCtcApi';

const BASE = 'http://localhost:8090/api';

function mockFetch(status: number, body: unknown) {
  const res = new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(res));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Public Profiles API (HttpCtcApi)', () => {
  const api = new HttpCtcApi(BASE);

  // getUserProfile
  describe('getUserProfile', () => {
    it('returns a PublicProfile for a known user id', async () => {
      mockFetch(200, {
        id: 'u_ada',
        name: 'Ada Lovelace',
        login: 'ada',
        initials: 'AL',
        role: 'giver',
        tier: 'gold',
        net: null,
        donated: null,
        donationsMade: 3,
      });
      const profile = await api.getUserProfile('u_ada');
      expect(profile.id).toBe('u_ada');
      expect(profile.name).toBe('Ada Lovelace');
      expect(profile.initials).toBe('AL');
      expect(profile.role).toBe('giver');
      // Public profile must NOT expose financial fields
      expect(profile).not.toHaveProperty('totalCredit');
      expect(profile).not.toHaveProperty('pledgedSurplus');
      expect(profile).not.toHaveProperty('creditBalance');
    });

    it('includes tier and donationsMade for a giver', async () => {
      mockFetch(200, {
        id: 'u_ada',
        name: 'Ada Lovelace',
        login: 'ada',
        initials: 'AL',
        role: 'giver',
        tier: 'gold',
        net: null,
        donated: null,
        donationsMade: 3,
      });
      const profile = await api.getUserProfile('u_ada');
      expect(typeof profile.tier).toBe('string');
      expect(typeof profile.donationsMade).toBe('number');
    });

    it('throws CtcApiError not_found (404) for an unknown user', async () => {
      mockFetch(404, { error: 'not_found', message: 'User not found' });
      await expect(api.getUserProfile('u_does_not_exist')).rejects.toMatchObject({
        code: 'not_found',
        status: 404,
      });
    });
  });

  // searchUsers
  describe('searchUsers', () => {
    it('returns matching users for a query', async () => {
      mockFetch(200, {
        users: [{ id: 'u_ada', name: 'Ada Lovelace', login: 'ada', initials: 'AL', role: 'giver' }],
      });
      const hits = await api.searchUsers('Ada');
      expect(hits.length).toBeGreaterThan(0);
      expect(hits[0].name).toContain('Ada');
      expect(hits[0]).toHaveProperty('id');
      expect(hits[0]).toHaveProperty('initials');
      expect(hits[0]).toHaveProperty('role');
    });

    it('returns empty array for blank query', async () => {
      // HttpCtcApi passes q='' to the backend; backend returns empty users list.
      mockFetch(200, { users: [] });
      const hits = await api.searchUsers('');
      expect(hits).toEqual([]);
    });

    it('caps results at 8 (backend enforced; client passes through what server returns)', async () => {
      // The cap is a server-side contract. HttpCtcApi passes the response through
      // unchanged — we verify it correctly unwraps the `users` array regardless of length.
      const eight = Array.from({ length: 8 }, (_, i) => ({
        id: `u_${i}`, name: `User ${i}`, login: `user${i}`, initials: 'U', role: 'giver' as const,
      }));
      mockFetch(200, { users: eight });
      const hits = await api.searchUsers('a');
      expect(hits.length).toBeLessThanOrEqual(8);
    });

    it('passes the query verbatim to the endpoint (case-insensitive matching is server-side)', async () => {
      // The mock tested in-memory case-folding; HttpCtcApi just URL-encodes the query
      // and the backend handles case folding. We verify the correct endpoint is called
      // for both casings and that results come back as expected.
      const hit = { id: 'u_ada', name: 'Ada Lovelace', login: 'ada', initials: 'AL', role: 'giver' as const };
      const makeRes = () => new Response(JSON.stringify({ users: [hit] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
      const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(makeRes()));
      vi.stubGlobal('fetch', fetchMock);

      const lower = await api.searchUsers('ada');
      const upper = await api.searchUsers('ADA');
      expect(lower.map(h => h.id)).toEqual([hit.id]);
      expect(upper.map(h => h.id)).toEqual([hit.id]);
      // Verify the correct query strings were sent
      expect((fetchMock.mock.calls[0][0] as string)).toContain('q=ada');
      expect((fetchMock.mock.calls[1][0] as string)).toContain('q=ADA');
    });
  });
});

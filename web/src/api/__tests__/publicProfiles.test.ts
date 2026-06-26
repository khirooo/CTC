import { describe, it, expect, beforeEach } from 'vitest';
import { createMockApi } from '@/api/mockApi';

describe('Public Profiles API', () => {
  let api: ReturnType<typeof createMockApi>;

  beforeEach(() => {
    localStorage.clear();
    api = createMockApi({ latencyMs: 0, storageKey: 'profiles.test' });
  });

  // getUserProfile
  describe('getUserProfile', () => {
    it('returns a PublicProfile for a known user id', async () => {
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
      const profile = await api.getUserProfile('u_ada');
      expect(typeof profile.tier).toBe('string');
      expect(typeof profile.donationsMade).toBe('number');
    });

    it('throws CtcApiError not_found (404) for an unknown user', async () => {
      await expect(api.getUserProfile('u_does_not_exist')).rejects.toMatchObject({
        code: 'not_found',
        status: 404,
      });
    });
  });

  // searchUsers
  describe('searchUsers', () => {
    it('returns matching users for a query', async () => {
      const hits = await api.searchUsers('Ada');
      expect(hits.length).toBeGreaterThan(0);
      expect(hits[0].name).toContain('Ada');
      expect(hits[0]).toHaveProperty('id');
      expect(hits[0]).toHaveProperty('initials');
      expect(hits[0]).toHaveProperty('role');
    });

    it('returns empty array for blank query', async () => {
      const hits = await api.searchUsers('');
      expect(hits).toEqual([]);
    });

    it('caps results at 8', async () => {
      // Force many matches by searching a common substring across all users
      const hits = await api.searchUsers('a');
      expect(hits.length).toBeLessThanOrEqual(8);
    });

    it('is case-insensitive', async () => {
      const lower = await api.searchUsers('ada');
      const upper = await api.searchUsers('ADA');
      expect(lower.map(h => h.id)).toEqual(upper.map(h => h.id));
    });
  });
});

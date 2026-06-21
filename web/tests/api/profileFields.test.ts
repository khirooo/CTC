import { describe, it, expect, beforeEach } from 'vitest';
import { createMockApi } from '@/api/mockApi';

function api() {
  let t = 1_700_000_000_000;
  return createMockApi({ now: () => t, latencyMs: 0, storageKey: 'pf.test' });
}
beforeEach(() => localStorage.clear());

describe('mockApi profile credit fields', () => {
  it('giver profile exposes the 4 segments + consumed splits + reset', async () => {
    const a = api();
    await a.signIn('ada@example.com', 'x');               // Ada = giver
    const p = await a.getOwnProfile();
    for (const k of ['entitlement','used','pledged','donated','left','pledgedConsumed','donatedConsumed'])
      expect(p[k as keyof typeof p]).not.toBeUndefined();
    expect(p.resetDate).toBeTruthy();
    // segments sum to entitlement (within rounding)
    expect((p.used ?? 0) + (p.pledged ?? 0) + (p.donated ?? 0) + (p.left ?? 0)).toBe(p.entitlement);
  });

  it('validatePat returns entitlement + remaining', async () => {
    const a = api();
    await a.signIn('ada@example.com', 'x');
    const r = await a.validatePat('github_pat_x');
    expect(r.entitlementAiu).toBeGreaterThan(0);
    expect(typeof r.remainingAiu).toBe('number');
  });
});

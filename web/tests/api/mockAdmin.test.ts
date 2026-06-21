import { describe, it, expect, beforeEach } from 'vitest';
import { createMockApi } from '@/api/mockApi';

function freshApi() {
  let t = 1_700_000_000_000;
  return createMockApi({ now: () => t, latencyMs: 0, storageKey: 'admin.test' });
}

beforeEach(() => localStorage.clear());

describe('mockApi admin', () => {
  it('lists users with fingerprint + token count, never raw PAT', async () => {
    const api = freshApi();
    await api.signIn('ada@example.com', 'x');
    const users = await api.listAllUsers();
    expect(users.length).toBeGreaterThan(0);
    expect(JSON.stringify(users)).not.toMatch(/github_pat_/);   // no cleartext
    expect(users[0]).toHaveProperty('patFingerprint');
    expect(users[0]).toHaveProperty('tokenCount');
  });

  it('reveals a PAT only via revealPat', async () => {
    const api = freshApi();
    await api.signIn('ada@example.com', 'x');
    const users = await api.listAllUsers();
    const giver = users.find((u) => u.hasPat)!;
    const pat = await api.revealPat(giver.id);
    expect(typeof pat).toBe('string');
    expect(pat.length).toBeGreaterThan(0);
  });

  it('reads and patches admin settings', async () => {
    const api = freshApi();
    await api.signIn('ada@example.com', 'x');
    const before = await api.getAdminSettings();
    expect(before.freeAllowanceAiu.isOverride).toBe(false);
    const after = await api.updateAdminSettings({ freeAllowanceAiu: 42 });
    expect(after.freeAllowanceAiu).toEqual({ value: 42, isOverride: true });
  });

  it('session reports isAdmin for the seed admin', async () => {
    const api = freshApi();
    await api.signIn('ada@example.com', 'x');
    const s = await api.getSession();
    expect(s?.isAdmin).toBe(true);
  });
});

import { describe, it, expect, beforeEach } from 'vitest';
import { createMockApi } from '@/api/mockApi';
import { NANO_PER_AIU } from '@/domain/credit';

function freshApi() {
  let t = 1_700_000_000_000;
  return createMockApi({ now: () => t, latencyMs: 0, storageKey: 'test.store' });
}

beforeEach(() => localStorage.clear());

describe('mockApi donate', () => {
  it('caps donation to remaining need and auto-closes', async () => {
    const api = freshApi();
    await api.signIn('ada@example.com', 'x');         // Ada = giver, budget 2000 AIU
    const before = (await api.listRequests('all')).requests.find(r => r.requesterName === 'Lena Hoffmann')!;
    expect(before.amountFunded).toBe(35 * NANO_PER_AIU);   // needs 60 AIU
    const after = await api.donate(before.id, 1000 * NANO_PER_AIU); // cap to 25 AIU
    expect(after.amountFunded).toBe(60 * NANO_PER_AIU);
    expect(after.status).toBe('fulfilled');
    expect(after.donorCount).toBe(before.donorCount + 1);
  });

  it('decrements the funding giver private budget', async () => {
    const api = freshApi();
    await api.signIn('ada@example.com', 'x');
    const before = await api.getOwnProfile();        // donatedSoFar 1860 AIU, budget 2000 AIU
    const req = (await api.listRequests('all')).requests.find(r => r.requesterName === 'Diego Ramirez')!;
    await api.donate(req.id, 30 * NANO_PER_AIU);    // needs 40 AIU, funded 10 AIU → cap 30 AIU
    const after = await api.getOwnProfile();
    expect(after.donatedSoFar).toBe(before.donatedSoFar + 30 * NANO_PER_AIU);
  });

  it('never exposes totalCredit/pledgedSurplus on public payloads', async () => {
    const api = freshApi();
    await api.signIn('ada@example.com', 'x');
    const dash = await api.getDashboard();
    const reqs = await api.listRequests('all');
    const lb = await api.getLeaderboard();
    for (const obj of [dash, ...reqs.requests, lb]) {
      expect(JSON.stringify(obj)).not.toMatch(/totalCredit|pledgedSurplus/);
    }
  });
});

describe('mockApi requests', () => {
  it('createRequest prepends an open request from current user', async () => {
    const api = freshApi();
    await api.signIn('ada@example.com', 'x');
    const created = await api.createRequest({ amountNeeded: 50, reason: 'PR', target: null, expiryHours: 24 });
    expect(created.amountFunded).toBe(0);
    expect(created.status).toBe('open');
    const list = await api.listRequests('all');
    expect(list.requests[0].id).toBe(created.id);
    expect(list.counts.all).toBe(6);
  });

  it('filters by requester role with counts', async () => {
    const api = freshApi();
    await api.signIn('ada@example.com', 'x');
    const pro = await api.listRequests('pro');
    expect(pro.requests.every(r => r.requesterRole === 'pro')).toBe(true);
    expect(pro.counts.pro).toBe(1);   // Amine
    expect(pro.counts.noob).toBe(4);
  });
});

describe('mockApi createRequest expiry', () => {
  it('sets expiresAt from expiryHours (ms)', async () => {
    const api = freshApi();
    await api.signIn('ada@example.com', 'x');
    const r = await api.createRequest({ amountNeeded: 10 * NANO_PER_AIU, reason: 'x', target: null, expiryHours: 6 });
    expect(r.expiresAt).toBe(r.createdAt + 6 * 3_600_000);
  });
});

describe('persistence', () => {
  it('survives a reload (new api instance, same storageKey)', async () => {
    let t = 1_700_000_000_000;
    const a = createMockApi({ now: () => t, latencyMs: 0, storageKey: 'persist.test' });
    await a.signIn('ada@example.com', 'x');
    const req = (await a.listRequests('all')).requests.find(r => r.requesterName === 'Lena Hoffmann')!;
    await a.donate(req.id, 25 * NANO_PER_AIU);
    const b = createMockApi({ now: () => t, latencyMs: 0, storageKey: 'persist.test' });
    const reqB = (await b.listRequests('all')).requests.find(r => r.requesterName === 'Lena Hoffmann')!;
    expect(reqB.amountFunded).toBe(60 * NANO_PER_AIU);
  });
});

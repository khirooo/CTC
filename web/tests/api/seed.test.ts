import { describe, it, expect } from 'vitest';
import { makeSeed } from '@/api/seed';
import { NANO_PER_AIU } from '@/domain/credit';

describe('seed', () => {
  const now = 1_700_000_000_000;
  it('produces the 5 prototype requests with derived timestamps', () => {
    const s = makeSeed(now);
    expect(s.requests).toHaveLength(5);
    const lena = s.requests.find(r => r.requesterName === 'Lena Hoffmann')!;
    expect(lena.amountNeeded).toBe(60 * NANO_PER_AIU);
    expect(lena.amountFunded).toBe(35 * NANO_PER_AIU);
    expect(lena.requesterRole).toBe('noob');
    expect(lena.expiresAt).toBe(now + 4 * 3600_000);
  });
  it('has Ada as a giver with a private pledged surplus', () => {
    const s = makeSeed(now);
    const ada = s.users.find(u => u.id === 'u_ada')!;
    expect(ada.role).toBe('giver');
    expect(ada.hasPat).toBe(true);
    expect(ada.pledgedSurplus).toBe(2000 * NANO_PER_AIU);
    expect(ada.totalCredit).toBe(5000 * NANO_PER_AIU);   // retained = 3000 AIU
  });
  it('has 3 archived months newest-first', () => {
    const s = makeSeed(now);
    expect(s.months.map(m => m.id)).toEqual(['2026-05', '2026-04', '2026-03']);
  });
  it('seeds the cycle aggregates for the dashboard hero', () => {
    const s = makeSeed(now);
    expect(s.aggregates.pledged).toBe(3600 * NANO_PER_AIU);
    expect(s.aggregates.retained).toBe(5680 * NANO_PER_AIU);
  });
  it('is pure (same now → equal output)', () => {
    expect(makeSeed(now)).toEqual(makeSeed(now));
  });
});

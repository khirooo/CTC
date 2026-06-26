import { describe, it, expect } from 'vitest';
import { tierMeta } from '@/domain/tiers';

describe('tierMeta', () => {
  it('returns label + emoji for a known tier', () => {
    expect(tierMeta('aristocrat').label).toBe('Aristocrat');
    expect(tierMeta('aristocrat').emoji).toBe('👑');
    expect(tierMeta('beggar').emoji).toBe('🪦');
  });

  it('falls back to Unranked for null/unknown', () => {
    expect(tierMeta(null).label).toBe('Unranked');
    expect(tierMeta('nonsense').label).toBe('Unranked');
  });
});

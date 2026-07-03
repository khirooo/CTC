import { describe, it, expect } from 'vitest';
import { glossary } from '@/domain/glossary';
import { credits, aiu } from '@/domain/credit';

describe('glossary', () => {
  it('defines every term with a title and a non-empty body', () => {
    const keys = ['credits', 'pool', 'chipIn', 'routed', 'quota', 'cycle', 'net', 'tier', 'pledge', 'kept', 'requests'] as const;
    for (const k of keys) {
      expect(glossary[k].title.length).toBeGreaterThan(0);
      expect(glossary[k].body.length).toBeGreaterThan(10);
    }
  });
  it('credits explains the AIU equivalence', () => {
    expect(glossary.credits.body).toContain('1 credit = 1 AIU');
  });
});

describe('credits()', () => {
  it('formats nano-AIU with the credits suffix', () => {
    expect(credits(1_500_000_000)).toBe('1.50 credits');
  });
  it('matches aiu() numerically', () => {
    expect(credits(2_000_000_000).replace(' credits', '')).toBe(aiu(2_000_000_000).replace(' AIU', ''));
  });
});

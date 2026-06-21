import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Structural guard: public-facing types must not declare totalCredit/pledgedSurplus.
describe('privacy invariant', () => {
  const src = readFileSync(resolve(__dirname, '../../src/domain/types.ts'), 'utf8');

  function interfaceBody(name: string): string {
    const start = src.indexOf(`interface ${name} {`);
    expect(start, `interface ${name} should exist`).toBeGreaterThan(-1);
    const open = src.indexOf('{', start);
    let depth = 0;
    for (let i = open; i < src.length; i++) {
      if (src[i] === '{') depth++;
      else if (src[i] === '}') { depth--; if (depth === 0) return src.slice(open, i); }
    }
    throw new Error(`unterminated interface ${name}`);
  }

  for (const name of ['PublicUser', 'PublicRequest', 'Leaderboard', 'LeaderboardEntry', 'DashboardData']) {
    it(`${name} does not expose totalCredit or pledgedSurplus`, () => {
      const body = interfaceBody(name);
      expect(body).not.toMatch(/totalCredit/);
      expect(body).not.toMatch(/pledgedSurplus/);
    });
  }
});

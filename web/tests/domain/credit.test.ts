import { describe, it, expect } from 'vitest';
import { euros, aiu, deriveStatus, pct, NANO_PER_AIU } from '@/domain/credit';

describe('credit math', () => {
  it('converts nano-AIU credits to euros at 0.0088/AIU', () => {
    expect(euros(3600 * NANO_PER_AIU)).toBe('€31.68');
    expect(euros(1240 * NANO_PER_AIU)).toBe('€10.91');
  });
  it('formats nano-AIU to AIU string with 2dp', () => {
    expect(aiu(35 * NANO_PER_AIU)).toBe('35.00 AIU');
    expect(aiu(9800 * NANO_PER_AIU)).toBe('9,800.00 AIU');
    expect(aiu(0)).toBe('0.00 AIU');
  });
  it('renders a tiny nonzero charge as "<0.01 AIU" instead of "0.00 AIU"', () => {
    expect(aiu(1_000_000)).toBe('<0.01 AIU');       // 0.001 AIU — nonzero but sub-cent
    expect(aiu(4_000_000)).toBe('<0.01 AIU');       // 0.004 AIU — still rounds to 0.00
    expect(aiu(5_000_000)).toBe('0.01 AIU');        // 0.005 AIU — rounds up to 0.01
    expect(aiu(0)).toBe('0.00 AIU');                // exact zero stays 0.00
  });
  it('clamps funded percentage 0..100', () => {
    expect(pct(35, 60)).toBe(58);
    expect(pct(120, 120)).toBe(100);
    expect(pct(200, 100)).toBe(100);
  });
  it('derives request status', () => {
    const now = 1_000;
    expect(deriveStatus(0, 60, now + 1000, now)).toBe('open');
    expect(deriveStatus(30, 60, now + 1000, now)).toBe('partially_funded');
    expect(deriveStatus(60, 60, now + 1000, now)).toBe('fulfilled');
    expect(deriveStatus(10, 60, now - 1, now)).toBe('expired');
    // fulfilled wins even if expired
    expect(deriveStatus(60, 60, now - 1, now)).toBe('fulfilled');
  });
});

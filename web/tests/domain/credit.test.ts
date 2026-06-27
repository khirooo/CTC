import { describe, it, expect } from 'vitest';
import { euros, aiu, fmt, deriveStatus, donationKind, pct, NANO_PER_AIU } from '@/domain/credit';

describe('credit math', () => {
  it('converts nano-AIU credits to euros at 0.10/AIU', () => {
    expect(euros(3600 * NANO_PER_AIU)).toBe('€360.00');
    expect(euros(1240 * NANO_PER_AIU)).toBe('€124.00');
  });
  it('formats nano-AIU to AIU string with 2dp', () => {
    expect(aiu(35 * NANO_PER_AIU)).toBe('35.00 AIU');
    expect(aiu(9800 * NANO_PER_AIU)).toBe('9,800.00 AIU');
    expect(aiu(0)).toBe('0.00 AIU');
  });
  it('formats numbers with thousands separators', () => {
    expect(fmt(5680)).toBe('5,680');
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
  it('classifies donation kind by recipient role', () => {
    expect(donationKind('pro', 'pro')).toBe('rotate');
    expect(donationKind('pro', 'noob')).toBe('transfer');
  });
});

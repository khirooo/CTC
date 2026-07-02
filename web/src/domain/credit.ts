import { config } from './config';
import type { RequestStatus } from './types';

export const NANO_PER_AIU = 1_000_000_000;

export const aiu = (nano: number): string =>
  (Number(nano || 0) / NANO_PER_AIU).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }) + ' AIU';

export const euros = (nano: number, rate: number = config.creditToEuroRate): string =>
  '€' +
  ((Number(nano || 0) / NANO_PER_AIU) * rate).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

export const pct = (funded: number, needed: number): number =>
  Math.max(0, Math.min(100, Math.round((funded / Math.max(1, needed)) * 100)));

export function deriveStatus(
  amountFunded: number,
  amountNeeded: number,
  expiresAt: number,
  now: number,
): RequestStatus {
  if (amountFunded >= amountNeeded) return 'fulfilled';
  if (now >= expiresAt) return 'expired';
  if (amountFunded > 0) return 'partially_funded';
  return 'open';
}

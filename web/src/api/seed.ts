import type { Role, CycleReport, Donation, AdminSettings } from '@/domain/types';

export interface SeedUser {
  id: string;
  name: string;
  /** Set for users created via signUp; seeded users fall back to a synthesized address. */
  email?: string;
  initials: string;
  role: Role;
  hasPat: boolean;
  totalCredit: number | null;
  pledgedSurplus: number | null;
  donatedSoFar: number;
  allowance: number | null;
  consumed: number;
  donationsReceived: number;
  isAdmin?: boolean;
  // New credit-segment fields for the visualization bar
  /** nano-AIU consumed from quota this cycle (givers only) */
  consumedThisMonth?: number;
  /** nano-AIU pool has drawn from this giver's pledge this cycle */
  poolConsumedFrom?: number;
  /** nano-AIU consumed from direct grants this giver has made */
  grantsConsumed?: number;
}

export interface SeedRequest {
  id: string;
  requesterId?: string;   // owner; set for user-created requests (drives isOwn)
  requesterName: string;
  initials: string;
  requesterRole: 'pro' | 'noob';
  amountNeeded: number;
  amountFunded: number;
  reason: string;
  target: string | null;
  createdAt: number;
  expiresAt: number;
  donorCount: number;
}

export interface CycleAggregates {
  pledged: number;
  retained: number;
  rotated: number;
  donatedToNonPat: number;
  donatedThisWeek: number;
  fulfillmentRate: number;
  activeGivers: number;
  activeConsumers: number;
}

export interface StoreState {
  users: SeedUser[];
  requests: SeedRequest[];
  months: CycleReport[];
  donations: Donation[];
  aggregates: CycleAggregates;
  adminSettings?: AdminSettings;
}

export function makeSeed(now: number): StoreState {
  const N = 1_000_000_000;

  const months: CycleReport[] = [
    {
      id: '2026-05',
      label: 'May 2026',
      pledged: 9800 * N,
      donated: 6240 * N,
      toNonPat: 4010 * N,
      toPat: 2230 * N,
      reqFilled: 38,
      reqTotal: 44,
      reqPat: 9,
      reqNonPat: 29,
      fills: [
        { who: 'Marco Bianchi', amount: 1540 * N, count: 14 },
        { who: 'Yuki Tanaka', amount: 1860 * N, count: 11 },
        { who: 'Sofia Lindqvist', amount: 1400 * N, count: 9 },
        { who: 'Amine Tazi', amount: 610 * N, count: 4 },
      ],
      winners: {
        // rotator key kept per brief — History screen won't render it but it must be preserved
        rotator: { name: 'Yuki Tanaka', value: 640 * N, userId: 'u_kef' },
        generous: { name: 'Marco Bianchi', value: 1540 * N, userId: 'u_mb' },
        pro: { name: 'Yuki Tanaka', value: 1240 * N, userId: 'u_kef' },
        noob: { name: 'Lena Hoffmann', value: 412 * N, userId: 'u_lh' },
      },
    },
    {
      id: '2026-04',
      label: 'April 2026',
      pledged: 8100 * N,
      donated: 5020 * N,
      toNonPat: 3100 * N,
      toPat: 1920 * N,
      reqFilled: 31,
      reqTotal: 39,
      reqPat: 7,
      reqNonPat: 24,
      fills: [
        { who: 'Yuki Tanaka', amount: 1480 * N, count: 12 },
        { who: 'Sofia Lindqvist', amount: 1120 * N, count: 8 },
        { who: 'Marco Bianchi', amount: 940 * N, count: 7 },
        { who: 'Yuki Tanaka', amount: 480 * N, count: 4 },
      ],
      winners: {
        rotator: { name: 'Sofia Lindqvist', value: 520 * N, userId: 'u_sl' },
        generous: { name: 'Yuki Tanaka', value: 1480 * N, userId: 'u_kef' },
        pro: { name: 'Amine Tazi', value: 1080 * N, userId: 'u_at' },
        noob: { name: 'Diego Ramirez', value: 388 * N, userId: 'u_dr' },
      },
    },
    {
      id: '2026-03',
      label: 'March 2026',
      pledged: 5400 * N,
      donated: 2980 * N,
      toNonPat: 1740 * N,
      toPat: 1240 * N,
      reqFilled: 19,
      reqTotal: 25,
      reqPat: 5,
      reqNonPat: 14,
      fills: [
        { who: 'Sofia Lindqvist', amount: 880 * N, count: 7 },
        { who: 'Yuki Tanaka', amount: 760 * N, count: 6 },
        { who: 'Amine Tazi', amount: 540 * N, count: 4 },
        { who: 'Marco Bianchi', amount: 320 * N, count: 2 },
      ],
      winners: {
        rotator: { name: 'Amine Tazi', value: 410 * N, userId: 'u_at' },
        generous: { name: 'Sofia Lindqvist', value: 880 * N, userId: 'u_sl' },
        pro: { name: 'Yuki Tanaka', value: 920 * N, userId: 'u_kef' },
        noob: { name: 'Priya Nair', value: 276 * N, userId: 'u_pn' },
      },
    },
  ];

  const requests: SeedRequest[] = [
    {
      id: 'req_1',
      requesterId: 'u_lh',
      requesterName: 'Lena Hoffmann',
      initials: 'LH',
      requesterRole: 'noob',
      amountNeeded: 60 * N,
      amountFunded: 35 * N,
      reason: 'Finishing the migration PR',
      target: null,
      createdAt: now,
      expiresAt: now + 4 * 3_600_000,
      donorCount: 2,
    },
    {
      id: 'req_2',
      requesterId: 'u_dr',
      requesterName: 'Diego Ramirez',
      initials: 'DR',
      requesterRole: 'noob',
      amountNeeded: 40 * N,
      amountFunded: 10 * N,
      reason: 'Code-review marathon today',
      target: null,
      createdAt: now,
      expiresAt: now + 18 * 3_600_000,
      donorCount: 1,
    },
    {
      id: 'req_3',
      requesterId: 'u_pn',
      requesterName: 'Priya Nair',
      initials: 'PN',
      requesterRole: 'noob',
      amountNeeded: 90 * N,
      amountFunded: 0,
      reason: 'Debugging a prod incident',
      target: 'Ada Lovelace',
      createdAt: now,
      expiresAt: now + 26 * 3_600_000,
      donorCount: 0,
    },
    {
      id: 'req_4',
      requesterId: 'u_at',
      requesterName: 'Amine Tazi',
      initials: 'AT',
      requesterRole: 'pro',
      amountNeeded: 120 * N,
      amountFunded: 120 * N,
      reason: 'Ran dry mid-refactor',
      target: null,
      createdAt: now,
      expiresAt: now + 0 * 3_600_000,
      donorCount: 3,
    },
    {
      id: 'req_5',
      requesterName: 'Tom Becker',
      initials: 'TB',
      requesterRole: 'noob',
      amountNeeded: 30 * N,
      amountFunded: 30 * N,
      reason: 'Writing test coverage',
      target: null,
      createdAt: now,
      expiresAt: now + 0 * 3_600_000,
      donorCount: 1,
    },
  ];

  const users: SeedUser[] = [
    {
      id: 'u_ada',
      name: 'Ada Lovelace',
      initials: 'AL',
      role: 'giver',
      hasPat: true,
      totalCredit: 5000 * N,
      pledgedSurplus: 2000 * N,
      donatedSoFar: 1860 * N,
      allowance: null,
      consumed: 920 * N,
      donationsReceived: 0,
      isAdmin: true,
      consumedThisMonth: 200 * N,
      poolConsumedFrom: 100 * N,
      grantsConsumed: 50 * N,
    },
    {
      id: 'u_kef',
      name: 'Yuki Tanaka',
      initials: 'KF',
      role: 'giver',
      hasPat: true,
      totalCredit: null,
      pledgedSurplus: null,
      donatedSoFar: 1860 * N,
      allowance: null,
      consumed: 1240 * N,
      donationsReceived: 0,
    },
    {
      id: 'u_sl',
      name: 'Sofia Lindqvist',
      initials: 'SL',
      role: 'giver',
      hasPat: true,
      totalCredit: null,
      pledgedSurplus: null,
      donatedSoFar: 1400 * N,
      allowance: null,
      consumed: 780 * N,
      donationsReceived: 0,
    },
    {
      id: 'u_mb',
      name: 'Marco Bianchi',
      initials: 'MB',
      role: 'giver',
      hasPat: true,
      totalCredit: null,
      pledgedSurplus: null,
      donatedSoFar: 1540 * N,
      allowance: null,
      consumed: 540 * N,
      donationsReceived: 0,
    },
    {
      id: 'u_at',
      name: 'Amine Tazi',
      initials: 'AT',
      role: 'giver',
      hasPat: true,
      totalCredit: null,
      pledgedSurplus: null,
      donatedSoFar: 610 * N,
      allowance: null,
      consumed: 310 * N,
      donationsReceived: 0,
    },
    {
      id: 'u_lh',
      name: 'Lena Hoffmann',
      initials: 'LH',
      role: 'consumer',
      hasPat: false,
      totalCredit: null,
      pledgedSurplus: null,
      donatedSoFar: 0,
      allowance: 60 * N,
      consumed: 412 * N,
      donationsReceived: 0,
    },
    {
      id: 'u_dr',
      name: 'Diego Ramirez',
      initials: 'DR',
      role: 'consumer',
      hasPat: false,
      totalCredit: null,
      pledgedSurplus: null,
      donatedSoFar: 0,
      allowance: 40 * N,
      consumed: 388 * N,
      donationsReceived: 0,
    },
    {
      id: 'u_pn',
      name: 'Priya Nair',
      initials: 'PN',
      role: 'consumer',
      hasPat: false,
      totalCredit: null,
      pledgedSurplus: null,
      donatedSoFar: 0,
      allowance: 90 * N,
      consumed: 276 * N,
      donationsReceived: 0,
    },
  ];

  const donations: Donation[] = [];

  // Seeded cycle aggregates for the dashboard hero (the full team isn't modeled).
  const aggregates: CycleAggregates = {
    pledged: 3600 * N,
    retained: 5680 * N,
    rotated: 1240 * N,
    donatedToNonPat: 2880 * N,
    donatedThisWeek: 4120 * N,
    fulfillmentRate: 86,
    activeGivers: 5,
    activeConsumers: 12,
  };

  return { users, requests, months, donations, aggregates };
}

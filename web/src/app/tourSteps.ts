import { glossary } from '@/domain/glossary';

export interface TourStep {
  /** Matches a data-tour="…" attribute somewhere in the app shell/dashboard. */
  target: string;
  title: string;
  body: string;
}

export const TOUR_STEPS: TourStep[] = [
  {
    target: 'nav',
    title: 'The screens',
    body: 'Overview — the numbers.\nMarketplace — ask for or give credits.\nLeaderboard — who gives most.\nMonthly reports — the archive.\nYour profile — your license and terminal setup.',
  },
  {
    target: 'cycle-banner',
    title: glossary.cycle.title,
    body: 'One calendar month of activity.\nEverything — quotas, standings, reports — resets on the 1st.',
  },
  {
    target: 'stats',
    title: glossary.credits.title,
    body: glossary.credits.body,
  },
  {
    target: 'marketplace-hero',
    title: 'How credits flow',
    body: 'Left: what Hosts hold — shared with the pool (top), kept for themselves (bottom).\nMiddle: open Marketplace requests (top) and Guests drawing from the pool (bottom).\nRight: where surplus went — routed between Hosts (top), chipped in to Guests (bottom).\nOut of credits? Post a request here.',
  },
  {
    target: 'setup-checklist',
    title: 'Finish setup anytime',
    body: 'Skipped the terminal command? It lives here — and always in Your profile → Set up CLI.',
  },
];

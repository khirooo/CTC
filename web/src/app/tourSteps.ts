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
    body: "Credits flow left to right: from what Hosts hold, to the teammates who ended up using them.\nIn the middle: what's happening right now — open requests and Guests running on the pool.\nCurious about a number? Hover its ⓘ.\nOut of credits? Post a request on the Marketplace.",
  },
  {
    target: 'setup-checklist',
    title: 'Finish setup anytime',
    body: 'Skipped the terminal command? It lives here — and always in Your profile → Set up CLI.',
  },
];

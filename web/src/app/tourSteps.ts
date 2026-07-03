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
    body: 'Overview — the numbers. Marketplace — ask for or give credits. Leaderboard — who gives most. Monthly reports — the archive. Your profile — your license and terminal setup.',
  },
  {
    target: 'cycle-banner',
    title: glossary.cycle.title,
    body: glossary.cycle.body,
  },
  {
    target: 'stats',
    title: glossary.credits.title,
    body: glossary.credits.body,
  },
  {
    target: 'marketplace-hero',
    title: 'Out of credits?',
    body: 'Post a request on the Marketplace — a Host chips in and you keep working. Requests auto-close once covered.',
  },
  {
    target: 'setup-checklist',
    title: 'Finish setup anytime',
    body: 'Skipped the terminal command? It lives here — and always in Your profile → Set up CLI.',
  },
];

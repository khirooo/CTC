/**
 * Single source of truth for user-facing explanations of CTC jargon.
 * Used by <InfoTip term=…> popovers and the first-run tour, so wording
 * never drifts between the two.
 */
export type GlossaryTerm =
  | 'credits'
  | 'pool'
  | 'chipIn'
  | 'routed'
  | 'quota'
  | 'cycle'
  | 'net'
  | 'tier'
  | 'pledge'
  | 'kept'
  | 'requests';

export const glossary: Record<GlossaryTerm, { title: string; body: string }> = {
  credits: {
    title: 'Credits',
    body: "1 credit = 1 AIU — GitHub's Copilot usage unit. € figures are estimates of what that usage would cost.",
  },
  pool: {
    title: 'Shared pool',
    body: 'Credits anyone can fund a request from: Hosts’ pledges plus credit people returned to the pool. Post a request, then top up your own from the pool — the amount shows on your request.',
  },
  chipIn: {
    title: 'Chip-in',
    body: 'Funding someone’s request — from your own credit, or by passing on credit that was routed to you (it still comes from the original Host).',
  },
  routed: {
    title: 'Routed to you',
    body: 'Credit others chipped in, or you pulled from the pool, onto your requests. Spend it by using the CLI — or pass it on to someone else or back to the pool.',
  },
  quota: {
    title: 'Monthly quota',
    body: "The total credits a Host's Copilot license grants per month. GitHub resets it monthly.",
  },
  cycle: {
    title: 'Cycle',
    body: 'One calendar month of activity. Everything — quotas, standings, reports — resets on the 1st.',
  },
  net: {
    title: 'Net contribution',
    body: 'Credits given minus credits taken this cycle. Positive means you gave more than you used from others.',
  },
  tier: {
    title: 'Rank',
    body: 'A tongue-in-cheek title based on your net contribution this cycle — from Aristocrat 👑 (top giver) down to Beggar 🪦. Resets monthly.',
  },
  pledge: {
    title: 'Shared with the pool',
    body: 'The slice of your own monthly quota you put in the shared pool. It leaves your hands when someone routes it to a request. Shown on your profile.',
  },
  kept: {
    title: 'Kept for themselves',
    body: "The share of a Host's monthly quota they haven't shared with the pool. Theirs alone — never given away automatically.",
  },
  requests: {
    title: 'Open requests',
    body: 'Asks for credits posted on the Marketplace, waiting for a Host to chip in. They auto-close when covered or expired.',
  },
};

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
  | 'pledge';

export const glossary: Record<GlossaryTerm, { title: string; body: string }> = {
  credits: {
    title: 'Credits',
    body: "1 credit = 1 AIU — GitHub's Copilot usage unit. € figures are estimates of what that usage would cost.",
  },
  pool: {
    title: 'Shared pool',
    body: 'Credits Hosts set aside for everyone. Guests draw from it automatically when they use Copilot through CTC.',
  },
  chipIn: {
    title: 'Chip-in',
    body: 'A direct gift of credits from one person to another, usually answering a Marketplace request.',
  },
  routed: {
    title: 'Routed',
    body: 'Surplus credits passed between Hosts — one Host covers another who ran out.',
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
    body: 'The slice of your own monthly quota you make available to teammates. Private — only you see this number. Not a cap on chipping in.',
  },
};

export interface TierMeta {
  label: string;
  emoji: string;
  color: string;
}

export const TIER_META: Record<string, TierMeta> = {
  aristocrat: { label: 'Aristocrat', emoji: '👑', color: 'var(--give)' },
  baron:      { label: 'Baron',      emoji: '🎩', color: 'var(--give)' },
  bourgeois:  { label: 'Bourgeois',  emoji: '💰', color: 'var(--own)' },
  commoner:   { label: 'Commoner',   emoji: '🧍', color: 'var(--text-dim)' },
  peasant:    { label: 'Peasant',    emoji: '🌾', color: 'var(--consume)' },
  beggar:     { label: 'Beggar',     emoji: '🪦', color: 'var(--consume)' },
  newcomer:   { label: 'Newcomer',   emoji: '🥚', color: 'var(--text-faint)' },
};

const UNRANKED: TierMeta = { label: 'Unranked', emoji: '—', color: 'var(--text-faint)' };

export function tierMeta(tier: string | null): TierMeta {
  if (!tier) return UNRANKED;
  return TIER_META[tier] ?? UNRANKED;
}

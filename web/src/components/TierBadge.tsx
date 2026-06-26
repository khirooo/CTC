// web/src/components/TierBadge.tsx
import { tierMeta } from '@/domain/tiers';

export function TierBadge({ tier }: { tier: string | null }) {
  const { label, emoji, color } = tierMeta(tier);
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '2px 10px',
        borderRadius: 20,
        fontSize: 12,
        fontWeight: 600,
        color,
        background: 'var(--surface-2)',
        border: '1px solid var(--border)',
      }}
    >
      <span aria-hidden>{emoji}</span>
      {label}
    </span>
  );
}

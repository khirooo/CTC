import type { PatHealth } from '@/domain/types';

const STYLES: Record<PatHealth, { bg: string; fg: string; label: string }> = {
  valid: { bg: 'var(--give-soft)', fg: 'var(--give)', label: 'Valid' },
  expired: { bg: 'var(--consume-soft)', fg: 'var(--consume)', label: 'Expired' },
  forbidden: { bg: 'var(--consume-soft)', fg: 'var(--consume)', label: 'Missing permissions' },
  no_entitlement: { bg: 'var(--consume-soft)', fg: 'var(--consume)', label: 'No Copilot access' },
  unreachable: { bg: 'var(--surface-2)', fg: 'var(--text-faint)', label: 'Unreachable' },
};

/** Status pill for a Host's Copilot license, fed by the periodic PAT health check. */
export function PatHealthBadge({ health, title }: { health: PatHealth; title?: string }) {
  const s = STYLES[health];
  return (
    <span
      title={title}
      style={{
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 11,
        padding: '3px 8px',
        borderRadius: 6,
        background: s.bg,
        color: s.fg,
        whiteSpace: 'nowrap',
      }}
    >
      {s.label}
    </span>
  );
}

type AvatarTone = 'give' | 'pool' | 'consume' | 'default';

interface AvatarProps {
  initials: string;
  tone?: AvatarTone;
  size?: number;
}

const TONE_MAP: Record<AvatarTone, { color: string; bg: string }> = {
  give:    { color: 'var(--give)',    bg: 'var(--give-soft)' },
  pool: { color: 'var(--pool)', bg: 'var(--pool-soft)' },
  consume: { color: 'var(--consume)', bg: 'var(--consume-soft)' },
  default: { color: 'var(--text)',    bg: 'var(--surface-3)' },
};

export function Avatar({ initials, tone = 'default', size = 36 }: AvatarProps) {
  const { color, bg } = TONE_MAP[tone];
  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius: '50%',
        background: bg,
        color,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontWeight: 700,
        fontSize: size * 0.38,
        flexShrink: 0,
        userSelect: 'none',
      }}
    >
      {initials}
    </div>
  );
}

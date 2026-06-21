import React from 'react';

type Tone = 'give' | 'reroute' | 'consume' | 'default';

interface BadgeProps {
  tone?: Tone;
  children: React.ReactNode;
}

const TONE_MAP: Record<Tone, { color: string; bg: string }> = {
  give:    { color: 'var(--give)',    bg: 'var(--give-soft)' },
  reroute: { color: 'var(--reroute)', bg: 'var(--reroute-soft)' },
  consume: { color: 'var(--consume)', bg: 'var(--consume-soft)' },
  default: { color: 'var(--text-dim)', bg: 'var(--surface-2)' },
};

export function Badge({ tone = 'default', children }: BadgeProps) {
  const { color, bg } = TONE_MAP[tone];
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '2px 8px',
        borderRadius: 20,
        fontSize: 12,
        fontWeight: 600,
        color,
        background: bg,
      }}
    >
      {children}
    </span>
  );
}

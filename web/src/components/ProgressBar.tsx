interface ProgressBarProps {
  pct: number;
  color?: string;
}

export function ProgressBar({ pct, color = 'var(--accent)' }: ProgressBarProps) {
  const clamped = Math.min(100, Math.max(0, pct));
  return (
    <div
      style={{
        width: '100%',
        height: 6,
        borderRadius: 3,
        background: 'var(--surface-3)',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          width: `${clamped}%`,
          height: '100%',
          borderRadius: 3,
          background: color,
          transition: 'width .3s ease',
        }}
      />
    </div>
  );
}

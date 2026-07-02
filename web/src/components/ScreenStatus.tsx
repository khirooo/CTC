interface ScreenStatusProps {
  /** Message to show. Defaults to a neutral loading line. */
  message?: string;
  tone?: 'faint' | 'dim';
}

/**
 * Full-width centered status line for a screen that is loading or failed to
 * load. Replaces the identical inline "Loading…" blocks that used to live in
 * every read screen (and which rendered forever on fetch failure).
 */
export function ScreenStatus({ message = 'Loading…', tone = 'faint' }: ScreenStatusProps) {
  return (
    <div
      style={{
        color: tone === 'dim' ? 'var(--text-dim)' : 'var(--text-faint)',
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 13,
        padding: 40,
        textAlign: 'center',
      }}
    >
      {message}
    </div>
  );
}

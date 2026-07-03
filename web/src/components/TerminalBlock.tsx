import { CopyButton } from './CopyButton';

interface TerminalBlockProps {
  command: string;
  /** One-line explanation shown under the block. */
  caption?: string;
  style?: React.CSSProperties;
}

/**
 * A command styled as a terminal window — chrome bar, $ prompt, copy button
 * on the block itself — so it reads unmistakably as "run this in a terminal",
 * not as text to skim past. Shared by onboarding, the setup checklist, and
 * Profile's CLI card.
 */
export function TerminalBlock({ command, caption, style }: TerminalBlockProps) {
  return (
    <div style={style}>
      <div
        style={{
          border: '1px solid var(--border-strong)',
          borderRadius: 12,
          overflow: 'hidden',
          background: 'var(--surface-2)',
        }}
      >
        {/* Chrome bar */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '8px 12px',
            borderBottom: '1px solid var(--border)',
            background: 'var(--surface-3)',
          }}
        >
          <span style={{ display: 'flex', gap: 5 }} aria-hidden="true">
            {['#ff5f57', '#febc2e', '#28c840'].map((c) => (
              <span key={c} style={{ width: 9, height: 9, borderRadius: '50%', background: c, opacity: 0.8 }} />
            ))}
          </span>
          <span
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 11,
              color: 'var(--text-faint)',
              letterSpacing: '0.06em',
            }}
          >
            Terminal
          </span>
          <span style={{ marginLeft: 'auto' }}>
            <CopyButton text={command} />
          </span>
        </div>
        {/* Command */}
        <pre
          style={{
            margin: 0,
            padding: '14px 16px',
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 12.5,
            lineHeight: 1.6,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-all',
            color: 'var(--text)',
          }}
        >
          <span style={{ color: 'var(--text-faint)', userSelect: 'none' }}>$ </span>
          {command}
        </pre>
      </div>
      {caption && (
        <p style={{ fontSize: 12, color: 'var(--text-faint)', margin: '8px 2px 0', lineHeight: 1.5 }}>{caption}</p>
      )}
    </div>
  );
}

/**
 * Inline help for creating the fine-grained Copilot token a Host pastes during
 * onboarding (and in Profile → Become a Host). Fine-grained tokens can't have
 * their permissions pre-selected via URL, so the "Generate" button only opens the
 * token page — the steps spell out exactly which permissions to tick.
 *
 * The required Account permissions are confirmed: Copilot Requests / Chat / Editor
 * Context → Read-only; Gists → Read and write.
 */
export function PatHelp({ style, heading = "Don't have a token yet?" }: { style?: React.CSSProperties; heading?: string }) {
  const gheHost = (import.meta.env.VITE_GHE_HOST as string | undefined)?.replace(/\/+$/, '');
  const tokenUrl = gheHost ? `${gheHost}/settings/personal-access-tokens/new` : null;

  const strong: React.CSSProperties = { color: 'var(--text)', fontWeight: 600 };

  return (
    <div
      style={{
        border: '1px solid var(--border)',
        borderRadius: 10,
        padding: '14px 16px',
        background: 'var(--surface-2)',
        ...style,
      }}
    >
      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: tokenUrl ? 10 : 8 }}>
        {heading}
      </div>

      {tokenUrl && (
        <a
          href={tokenUrl}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 7,
            background: 'transparent',
            color: 'var(--text)',
            border: '1px solid var(--border-strong)',
            borderRadius: 9,
            padding: '9px 14px',
            fontSize: 13,
            fontWeight: 600,
            textDecoration: 'none',
            marginBottom: 12,
          }}
        >
          Generate a token on GitHub Enterprise ↗
        </a>
      )}

      <ol style={{ margin: 0, paddingLeft: 18, color: 'var(--text-dim)', fontSize: 12.5, lineHeight: 1.7 }}>
        <li>
          Name it <span style={strong}>CTC</span>, then set an expiry and the resource owner.
        </li>
        <li>
          Under <span style={strong}>Account permissions</span>, set:
          <ul style={{ margin: '4px 0 0', paddingLeft: 16 }}>
            <li>
              <span style={strong}>Copilot Requests</span>, <span style={strong}>Copilot Chat</span>,{' '}
              <span style={strong}>Copilot Editor Context</span> → Read-only
            </li>
            <li>
              <span style={strong}>Gists</span> → Read and write
            </li>
          </ul>
        </li>
        <li>
          Generate it, then copy the <code>github_pat_…</code> value and paste it into the field above.
        </li>
      </ol>
    </div>
  );
}

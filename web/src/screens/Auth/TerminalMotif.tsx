export function TerminalMotif() {
  return (
    <div
      style={{
        background: 'var(--surface)',
        borderLeft: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        padding: '48px 5vw',
      }}
    >
      <div
        style={{
          background: 'var(--bg)',
          border: '1px solid var(--border)',
          borderRadius: 14,
          overflow: 'hidden',
          boxShadow: 'var(--shadow)',
          maxWidth: 440,
        }}
      >
        {/* Traffic lights */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 7,
            padding: '12px 14px',
            borderBottom: '1px solid var(--border)',
          }}
        >
          <span style={{ width: 11, height: 11, borderRadius: '50%', background: '#ff5f57', display: 'inline-block' }} />
          <span style={{ width: 11, height: 11, borderRadius: '50%', background: '#febc2e', display: 'inline-block' }} />
          <span style={{ width: 11, height: 11, borderRadius: '50%', background: '#28c840', display: 'inline-block' }} />
          <span
            style={{
              marginLeft: 8,
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 12,
              color: 'var(--text-faint)',
            }}
          >
            alice — ctc
          </span>
        </div>
        {/* Terminal output */}
        <div
          style={{
            padding: 18,
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 13,
            lineHeight: 1.9,
            whiteSpace: 'pre',
          }}
        >
          <div style={{ color: 'var(--text)' }}>$ curl -fsSL https://ctc.local/install.sh \</div>
          <div style={{ color: 'var(--text)' }}>
            {'   | sh -s -- --token '}
            <span style={{ color: 'var(--accent)' }}>github_pat_x9Qd…7faZ</span>
          </div>
          <div style={{ color: 'var(--text-faint)' }}>Trusting the CA cert (enter your password) …</div>
          <div style={{ color: 'var(--give)' }}>
            ✓ CTC ready. Launch with: <span style={{ fontWeight: 600 }}>ctc</span>
          </div>
          <div>&nbsp;</div>
          <div style={{ color: 'var(--text)' }}>$ ctc -p "refactor the auth module"</div>
          <div style={{ color: 'var(--accent)' }}>◆ CTC mode — credits via the shared pool</div>
          <div style={{ color: 'var(--text-faint)' }}>{"  your normal 'copilot' is untouched"}</div>
          <div style={{ color: 'var(--text-dim)' }}>
            drafting response
            <span
              style={{
                display: 'inline-block',
                width: 8,
                height: 15,
                background: 'var(--accent)',
                marginLeft: 3,
                verticalAlign: '-2px',
                animation: 'blink 1s steps(1) infinite',
              }}
            />
          </div>
        </div>
      </div>
      <p
        style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 12,
          color: 'var(--text-faint)',
          margin: '22px 0 0',
          maxWidth: 440,
          lineHeight: 1.7,
        }}
      >
        Credit Traffic Control · surplus credit, routed to whoever runs out.
      </p>
    </div>
  );
}

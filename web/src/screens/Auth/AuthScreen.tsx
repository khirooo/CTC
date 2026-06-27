import { useApp } from '@/store/AppContext';
import { TerminalMotif } from './TerminalMotif';

interface AuthScreenProps {
  mode: 'signin' | 'signup';
}

export function AuthScreen({ mode }: AuthScreenProps) {
  const { signIn } = useApp();

  const heading = mode === 'signup' ? 'Create account' : 'Welcome back';
  const subtitle =
    mode === 'signup'
      ? 'Sign in with GitLab to get started — your account is created on first login.'
      : 'Sign in to route surplus across your team.';

  const submitBtnStyle: React.CSSProperties = {
    marginTop: 6,
    background: 'var(--accent)',
    color: '#fff',
    border: 'none',
    borderRadius: 10,
    padding: '13px 16px',
    fontFamily: 'inherit',
    fontWeight: 600,
    fontSize: 14,
    cursor: 'pointer',
    width: '100%',
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'grid',
        gridTemplateColumns: '1.05fr .95fr',
        background: 'var(--bg)',
      }}
    >
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          padding: '64px 7vw',
          position: 'relative',
          backgroundImage: 'radial-gradient(var(--border) 1px, transparent 1px)',
          backgroundSize: '26px 26px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 48 }}>
          <div
            style={{
              width: 34,
              height: 34,
              borderRadius: 9,
              background: 'var(--accent)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#fff',
              fontFamily: "'JetBrains Mono', monospace",
              fontWeight: 600,
              fontSize: 15,
              boxShadow: 'var(--shadow)',
            }}
          >
            ❯
          </div>
          <div
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontWeight: 600,
              letterSpacing: '.04em',
            }}
          >
            CTC
          </div>
        </div>

        <div style={{ maxWidth: 420 }}>
          <h1
            style={{
              fontSize: 30,
              fontWeight: 600,
              letterSpacing: '-.02em',
              margin: '0 0 8px',
            }}
          >
            {heading}
          </h1>
          <p style={{ color: 'var(--text-dim)', margin: '0 0 30px', fontSize: 15 }}>
            {subtitle}
          </p>

          <button type="button" onClick={() => signIn('', '')} style={submitBtnStyle}>
            Continue with GitLab →
          </button>
        </div>
      </div>

      <TerminalMotif />
    </div>
  );
}

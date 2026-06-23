import { useState } from 'react';
import { useApp } from '@/store/AppContext';
import { useAsync } from '@/store/useAsync';
import { Input } from '@/components/Input';
import { Button } from '@/components/Button';
import { TerminalMotif } from './TerminalMotif';

interface AuthScreenProps {
  mode: 'signin' | 'signup';
}

export function AuthScreen({ mode }: AuthScreenProps) {
  const { signIn, api } = useApp();
  const { data: config, loading: configLoading } = useAsync(() => api.getConfig(), [api]);

  const [email, setEmail] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);
  const [emailError, setEmailError] = useState<string | null>(null);

  const heading = mode === 'signup' ? 'Create account' : 'Welcome back';
  const subtitle =
    mode === 'signup'
      ? 'Sign in with GitHub Enterprise to get started — your account is created on first login.'
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

  async function handleEmailSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setSubmitting(true);
    setEmailError(null);
    try {
      await api.startEmailLogin(email.trim());
      setSent(true);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Something went wrong. Please try again.';
      setEmailError(msg);
    } finally {
      setSubmitting(false);
    }
  }

  const authMode = config?.authMode;

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'grid',
        gridTemplateColumns: '1.05fr .95fr',
        background: 'var(--bg)',
      }}
    >
      {/* Left column: sign-in */}
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
        {/* Logo */}
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
            {authMode === 'email'
              ? 'Enter your email to receive a sign-in link.'
              : subtitle}
          </p>

          {/* Render correct form once config is resolved */}
          {configLoading ? null : authMode === 'email' ? (
            sent ? (
              <p
                style={{
                  color: 'var(--text)',
                  fontSize: 15,
                  background: 'var(--surface-2)',
                  border: '1px solid var(--border)',
                  borderRadius: 8,
                  padding: '12px 16px',
                }}
              >
                Check your email for a sign-in link.
              </p>
            ) : (
              <form onSubmit={handleEmailSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <Input
                  type="email"
                  placeholder="you@example.com"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  required
                  autoFocus
                />
                <Button
                  type="submit"
                  disabled={submitting}
                  style={{ width: '100%', height: 44, marginTop: 2 }}
                >
                  {submitting ? 'Sending…' : 'Send sign-in link →'}
                </Button>
                {emailError && (
                  <p
                    role="alert"
                    style={{
                      color: 'var(--consume)',
                      fontSize: 13,
                      margin: '2px 0 0',
                      fontFamily: "'JetBrains Mono',monospace",
                    }}
                  >
                    {emailError}
                  </p>
                )}
              </form>
            )
          ) : (
            <button type="button" onClick={() => signIn('', '')} style={submitBtnStyle}>
              Continue with GitHub Enterprise →
            </button>
          )}
        </div>
      </div>

      {/* Right column: terminal motif */}
      <TerminalMotif />
    </div>
  );
}

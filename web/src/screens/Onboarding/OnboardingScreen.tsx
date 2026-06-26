import { useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { useApp } from '@/store/AppContext';
import { CtcApiError } from '@/api/http';
import { config } from '@/domain/config';
import { NANO_PER_AIU, aiu } from '@/domain/credit';
import { CreditBar, CreditLegend } from '@/components/CreditBar';
import { CopyButton } from '@/components/CopyButton';
import { PatHelp } from '@/components/PatHelp';

type Role = 'giver' | 'consumer';
type Step = 'role' | 'pat' | 'pledge' | 'install';

export function OnboardingScreen() {
  const { session, api, refresh } = useApp();
  const navigate = useNavigate();

  const [step, setStep] = useState<Step>('role');
  const [role, setRole] = useState<Role>('giver');
  const [pat, setPat] = useState('');
  const [identity, setIdentity] = useState<{ gheLogin: string; quotaAiu: number; entitlementAiu: number; remainingAiu: number } | null>(null);
  const [pledgedSurplus, setPledgedSurplus] = useState(0);
  const [cli, setCli] = useState<{ token: string; proxyHost: string; installCommand: string; caFingerprint: string | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!session) return <Navigate to="/signin" replace />;
  if (session.onboarded) return <Navigate to="/app/dashboard" replace />;

  async function loadCli() {
    const creds = await api.getCliCredentials();
    setCli(creds);
    setStep('install');
  }

  async function finish() {
    setBusy(true);
    setError(null);
    try {
      await api.markOnboarded();
      await refresh();
      navigate('/app/dashboard');
    } catch {
      setError("Couldn't finish — please try again.");
      setBusy(false);
    }
  }

  async function afterRole() {
    setError(null);
    if (role === 'giver') {
      setStep('pat');
      return;
    }
    setBusy(true);
    try {
      await loadCli();
    } catch (e) {
      setError(e instanceof CtcApiError ? e.message : "Couldn't load CLI setup — try again.");
    } finally {
      setBusy(false);
    }
  }

  async function validatePat() {
    setBusy(true);
    setError(null);
    try {
      const id = await api.validatePat(pat);
      setIdentity({
        gheLogin: id.gheLogin,
        quotaAiu: id.quotaAiu,
        entitlementAiu: id.entitlementAiu ?? id.quotaAiu,
        remainingAiu: id.remainingAiu ?? id.quotaAiu,
      });
      // Start the slider at the default pledge the backend already applied
      // (CTC_DEFAULT_PLEDGE_PCT% of remaining), not an arbitrary fraction.
      setPledgedSurplus(id.pledgedNano ?? 0);
      setStep('pledge');
    } catch (e) {
      setError(e instanceof CtcApiError ? e.message : 'Validation failed — try again.');
    } finally {
      setBusy(false);
    }
  }

  async function savePledge() {
    setBusy(true);
    setError(null);
    try {
      await api.updateSettings({ pledgedSurplus });
      await loadCli();
    } catch (e) {
      setError(e instanceof CtcApiError ? e.message : "Couldn't save pledge — try again.");
    } finally {
      setBusy(false);
    }
  }

  // Compute nano-AIU values for the pledge CreditBar from validatePat results.
  // Fresh PAT: no donations yet; used = entitlement − remaining; max slider = remaining.
  const entitlementNano = (identity?.entitlementAiu ?? 0) * NANO_PER_AIU;
  const remainingNano = (identity?.remainingAiu ?? 0) * NANO_PER_AIU;
  const usedNano = entitlementNano - remainingNano;

  const dotBg: React.CSSProperties = {
    backgroundImage: 'radial-gradient(var(--border) 1px,transparent 1px)',
    backgroundSize: '26px 26px',
  };

  const cardStyle: React.CSSProperties = {
    width: '100%',
    maxWidth: 520,
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 18,
    padding: 32,
    boxShadow: 'var(--shadow)',
  };

  const monoLabel: React.CSSProperties = {
    fontFamily: "'JetBrains Mono',monospace",
    fontSize: 11,
    letterSpacing: '.12em',
    textTransform: 'uppercase',
    color: 'var(--text-faint)',
  };

  const primaryBtn: React.CSSProperties = {
    flex: 1,
    background: 'var(--accent)',
    color: '#fff',
    border: 'none',
    borderRadius: 10,
    padding: '13px 16px',
    fontFamily: 'inherit',
    fontWeight: 600,
    fontSize: 14,
    cursor: busy ? 'default' : 'pointer',
    opacity: busy ? 0.7 : 1,
  };

  const ghostBtn: React.CSSProperties = {
    background: 'transparent',
    color: 'var(--text-dim)',
    border: '1px solid var(--border)',
    borderRadius: 10,
    padding: '13px 16px',
    fontFamily: 'inherit',
    fontWeight: 500,
    fontSize: 14,
    cursor: 'pointer',
  };

  const roleCardStyle = (selected: boolean): React.CSSProperties => ({
    border: selected ? '1.5px solid var(--accent)' : '1px solid var(--border)',
    background: selected ? 'var(--surface-3)' : 'transparent',
    borderRadius: 14,
    padding: 16,
    cursor: 'pointer',
    display: 'flex',
    gap: 14,
    alignItems: 'flex-start',
    // <button> defaults to black text — the heading inherits it and goes
    // invisible on the dark card. Force readable text; spans/description override.
    color: 'var(--text)',
    fontFamily: 'inherit',
  });

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        padding: '48px 24px',
        ...dotBg,
      }}
    >
      {/* Logo */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 36 }}>
        <div
          style={{
            width: 30,
            height: 30,
            borderRadius: 8,
            background: 'var(--accent)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
            fontFamily: "'JetBrains Mono',monospace",
            fontWeight: 600,
            fontSize: 14,
          }}
        >
          ❯
        </div>
        <div style={{ fontFamily: "'JetBrains Mono',monospace", fontWeight: 600, letterSpacing: '.04em' }}>CTC</div>
      </div>

      <div style={cardStyle}>

        {/* ── ROLE STEP ── */}
        {step === 'role' && (
          <>
            <h2 style={{ fontSize: 22, fontWeight: 600, margin: '0 0 4px', letterSpacing: '-.01em' }}>
              How will you use CTC?
            </h2>
            <p style={{ color: 'var(--text-dim)', margin: '0 0 22px', fontSize: 14 }}>
              Pick one — you can change it later in settings.
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {/* Giver card */}
              <button
                type="button"
                onClick={() => setRole('giver')}
                aria-pressed={role === 'giver'}
                style={{ ...roleCardStyle(role === 'giver'), textAlign: 'left', width: '100%' }}
              >
                <div
                  style={{
                    width: 38, height: 38, borderRadius: 10,
                    background: 'var(--give-soft)', color: 'var(--give)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 18, flex: 'none',
                  }}
                >↑</div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: 15 }}>
                    I have a Copilot license — be a <span style={{ color: 'var(--give)' }}>Host</span>
                  </div>
                  <div style={{ color: 'var(--text-dim)', fontSize: 13, marginTop: 3 }}>
                    Share your surplus with teammates who run out of credits.
                  </div>
                </div>
                <span style={{ color: role === 'giver' ? 'var(--accent)' : 'var(--text-faint)', fontSize: 18 }}>
                  {role === 'giver' ? '●' : '○'}
                </span>
              </button>

              {/* Consumer card */}
              <button
                type="button"
                onClick={() => setRole('consumer')}
                aria-pressed={role === 'consumer'}
                style={{ ...roleCardStyle(role === 'consumer'), textAlign: 'left', width: '100%' }}
              >
                <div
                  style={{
                    width: 38, height: 38, borderRadius: 10,
                    background: 'var(--consume-soft)', color: 'var(--consume)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 18, flex: 'none',
                  }}
                >↓</div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: 15 }}>
                    No license — be a <span style={{ color: 'var(--consume)' }}>Guest</span>
                  </div>
                  <div style={{ color: 'var(--text-dim)', fontSize: 13, marginTop: 3 }}>
                    Start with free credits; request more when you run out.
                  </div>
                </div>
                <span style={{ color: role === 'consumer' ? 'var(--accent)' : 'var(--text-faint)', fontSize: 18 }}>
                  {role === 'consumer' ? '●' : '○'}
                </span>
              </button>
            </div>

            <div style={{ display: 'flex', gap: 12, marginTop: 24 }}>
              <button type="button" onClick={afterRole} disabled={busy} style={primaryBtn}>
                Continue →
              </button>
              <button type="button" onClick={finish} disabled={busy} style={ghostBtn}>
                Skip for now
              </button>
            </div>
          </>
        )}

        {/* ── PAT STEP ── */}
        {step === 'pat' && (
          <>
            <h2 style={{ fontSize: 22, fontWeight: 600, margin: '0 0 4px', letterSpacing: '-.01em' }}>
              Connect your license
            </h2>
            <p style={{ color: 'var(--text-dim)', margin: '0 0 18px', fontSize: 14 }}>
              Your Copilot license stays in the proxy — never shared with teammates.
            </p>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
              <span style={monoLabel}>Copilot license</span>
              <input
                type="text"
                value={pat}
                onChange={(e) => setPat(e.target.value)}
                placeholder="github_pat_••••••••••••"
                style={{
                  width: '100%',
                  background: 'var(--surface-2)',
                  border: '1px solid var(--border)',
                  borderRadius: 10,
                  padding: '12px 13px',
                  color: 'var(--text)',
                  fontFamily: "'JetBrains Mono',monospace",
                  fontSize: 13,
                  outline: 'none',
                  boxSizing: 'border-box',
                }}
              />
            </label>
            <PatHelp style={{ marginTop: 14 }} />
            <div style={{ display: 'flex', gap: 12, marginTop: 20 }}>
              <button type="button" onClick={validatePat} disabled={busy} style={primaryBtn}>
                {busy ? 'Validating…' : 'Validate license'}
              </button>
              <button type="button" onClick={finish} disabled={busy} style={ghostBtn}>
                Skip for now
              </button>
            </div>
          </>
        )}

        {/* ── PLEDGE STEP ── */}
        {step === 'pledge' && identity && (
          <>
            <h2 style={{ fontSize: 22, fontWeight: 600, margin: '0 0 12px', letterSpacing: '-.01em' }}>
              Set your pledge
            </h2>
            <p style={{ color: 'var(--text-dim)', margin: '0 0 18px', fontSize: 14 }}>
              ✓ Verified — belongs to <b>@{identity.gheLogin}</b> · {identity.entitlementAiu.toLocaleString()} AIU available.
            </p>
            <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
              <span style={monoLabel}>
                Pledged surplus <span style={{ color: 'var(--give)', textTransform: 'none', letterSpacing: 0 }}>· private</span>
              </span>
              <span style={{ fontFamily: "'JetBrains Mono',monospace", fontWeight: 600, color: 'var(--give)' }}>
                {aiu(pledgedSurplus)}
              </span>
            </div>
            <CreditBar
              max={entitlementNano}
              segments={[
                { key: 'used', label: 'used', value: usedNano, color: 'var(--text-dim)', pattern: 'striped' as const },
                { key: 'pledged', label: 'pledged', value: pledgedSurplus, color: 'var(--accent)' },
                { key: 'left', label: 'left', value: Math.max(0, remainingNano - pledgedSurplus), color: 'var(--reroute)' },
              ].filter((s) => s.value > 0)}
              slider={{
                value: pledgedSurplus,
                min: 0,
                max: remainingNano,
                // handle starts after the fixed used segment (no donations/consumed-pledge at onboarding)
                trackStart: entitlementNano > 0 ? usedNano / entitlementNano : 0,
                onChange: setPledgedSurplus,
                onCommit: setPledgedSurplus,
              }}
            />
            <CreditLegend items={[
              { label: 'used', value: aiu(usedNano), color: 'var(--text-dim)', pattern: 'striped' as const },
              { label: 'pledged', value: aiu(pledgedSurplus), color: 'var(--accent)' },
              { label: 'available', value: aiu(Math.max(0, remainingNano - pledgedSurplus)), color: 'var(--reroute)' },
            ]} />
            <p style={{ color: 'var(--text-faint)', fontSize: 12, margin: '12px 0 0', fontFamily: "'JetBrains Mono',monospace" }}>
              🔒 private — pledges to the pool. Only you see this.
            </p>
            <div style={{ display: 'flex', gap: 12, marginTop: 20 }}>
              <button type="button" onClick={savePledge} disabled={busy} style={primaryBtn}>
                {busy ? 'Saving…' : 'Save pledge →'}
              </button>
              <button type="button" onClick={finish} disabled={busy} style={ghostBtn}>
                Skip for now
              </button>
            </div>
          </>
        )}

        {/* ── INSTALL STEP ── */}
        {step === 'install' && (
          <>
            <h2 style={{ fontSize: 22, fontWeight: 600, margin: '0 0 12px', letterSpacing: '-.01em' }}>
              Set up the CLI
            </h2>
            {role === 'consumer' && session.sharedPoolEnabled !== false && (
              <p style={{ color: 'var(--text-dim)', fontSize: 14, margin: '0 0 14px' }}>
                You start with {aiu(config.freeAllowance)} free credits.
              </p>
            )}
            {cli && (
              <>
                <pre
                  style={{
                    background: 'var(--surface-2)',
                    border: '1px solid var(--border)',
                    borderRadius: 10,
                    padding: '12px 14px',
                    fontFamily: "'JetBrains Mono',monospace",
                    fontSize: 12,
                    overflowX: 'auto',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-all',
                    margin: '0 0 10px',
                  }}
                >
                  {cli.installCommand}
                </pre>
                <div style={{ display: 'flex', justifyContent: 'flex-end', margin: '-4px 0 6px' }}>
                  <CopyButton text={cli.installCommand} />
                </div>
                <p style={{ fontSize: 12, color: 'var(--text-faint)', margin: '0 0 18px' }}>
                  The token is baked in — no separate paste. Rotate anytime in Settings.
                </p>
                {cli.caFingerprint && (
                  <p style={{ fontSize: 11, color: 'var(--text-faint)', margin: '0 0 18px', wordBreak: 'break-all' }}>
                    CA fingerprint (SHA-256): <code>{cli.caFingerprint}</code> — <code>ctc login</code> prints this; verify they match.
                  </p>
                )}
              </>
            )}
            <div style={{ display: 'flex', gap: 12 }}>
              <button type="button" onClick={finish} disabled={busy} style={primaryBtn}>
                {busy ? 'Entering…' : 'Enter CTC →'}
              </button>
              <button type="button" onClick={finish} disabled={busy} style={ghostBtn}>
                Skip for now
              </button>
            </div>
          </>
        )}

        {error && (
          <p
            role="alert"
            style={{
              color: 'var(--consume)',
              fontSize: 13,
              margin: '14px 0 0',
              fontFamily: "'JetBrains Mono',monospace",
            }}
          >
            {error}
          </p>
        )}
      </div>
    </div>
  );
}

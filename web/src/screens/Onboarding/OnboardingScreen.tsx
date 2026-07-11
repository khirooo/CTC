import { useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { useApp } from '@/store/AppContext';
import { CtcApiError } from '@/api/http';
import { NANO_PER_AIU, aiu } from '@/domain/credit';
import { saveSetupState } from '@/domain/setupState';
import { CreditBar, CreditLegend } from '@/components/CreditBar';
import { TerminalBlock } from '@/components/TerminalBlock';
import { PatHelp } from '@/components/PatHelp';
import { SecretInput } from '@/components/SecretInput';
import { monoLabel } from '@/theme/styles';

type Role = 'giver' | 'consumer';
type Step = 'role' | 'pat' | 'pledge' | 'install';

const stepHint: React.CSSProperties = { fontSize: 12.5, color: 'var(--text-faint)', margin: '4px 0 0', lineHeight: 1.5 };

function InstallStep({ n, title, children }: { n: number; title: string; children?: React.ReactNode }) {
  return (
    <li style={{ display: 'flex', gap: 12 }}>
      <span
        style={{
          width: 22, height: 22, borderRadius: '50%', flex: 'none', marginTop: 1,
          background: 'var(--accent-soft)', color: 'var(--accent)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontFamily: "'JetBrains Mono',monospace", fontSize: 11, fontWeight: 600,
        }}
      >
        {n}
      </span>
      <span style={{ flex: 1, minWidth: 0 }}>
        <span style={{ display: 'block', fontSize: 14, fontWeight: 600 }}>{title}</span>
        {children}
      </span>
    </li>
  );
}

export function OnboardingScreen() {
  const { session, api, refresh } = useApp();
  const navigate = useNavigate();

  const [step, setStep] = useState<Step>('role');
  const [role, setRole] = useState<Role>('giver');
  const [pat, setPat] = useState('');
  const [identity, setIdentity] = useState<{ gheLogin: string; quotaAiu: number; entitlementAiu: number; remainingAiu: number; usedNano: number } | null>(null);
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
        usedNano: id.usedNano ?? 0,
      });
      // Start the slider at the default pledge the backend already applied
      // (CTC_DEFAULT_PLEDGE_PCT% of remaining), not an arbitrary fraction.
      setPledgedSurplus(id.pledgedNano ?? 0);
      // Pledging is a pool-only concept. With the shared pool off there is
      // nothing to pledge to — skip the step and go straight to CLI setup.
      if (session?.sharedPoolEnabled === false) {
        await loadCli();
      } else {
        setStep('pledge');
      }
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

  async function finishInstall(ranIt: boolean) {
    if (session) saveSetupState(session.userId, { installAck: ranIt });
    await finish(); // existing markOnboarded + navigate
  }

  // Compute nano-AIU values for the pledge CreditBar from validatePat results.
  // usedNano is the backend's single-source figure (own_consumed + bypass_consumed),
  // NOT a TS recompute of entitlement − remaining; max slider = remaining.
  const entitlementNano = (identity?.entitlementAiu ?? 0) * NANO_PER_AIU;
  const remainingNano = (identity?.remainingAiu ?? 0) * NANO_PER_AIU;
  const usedNano = identity?.usedNano ?? 0;

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

  const stepLabels: Record<Step, string> = {
    role: 'Choose your role',
    pat: 'Connect license',
    pledge: 'Share with the pool',
    install: 'Terminal setup',
  };
  // Hosts: role→pat→(pledge)→install; Guests: role→install.
  const visibleSteps: Step[] =
    role === 'giver'
      ? session?.sharedPoolEnabled === false
        ? ['role', 'pat', 'install']
        : ['role', 'pat', 'pledge', 'install']
      : ['role', 'install'];
  const stepIndex = Math.max(0, visibleSteps.indexOf(step));

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

        {/* ── STEP INDICATOR ── */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 22 }}>
          <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, color: 'var(--text-faint)', letterSpacing: '0.08em' }}>
            Step {stepIndex + 1} of {visibleSteps.length}
          </span>
          <div style={{ display: 'flex', gap: 5, flex: 1 }}>
            {visibleSteps.map((s, i) => (
              <span key={s} title={stepLabels[s]} style={{ height: 3, flex: 1, borderRadius: 2, background: i <= stepIndex ? 'var(--accent)' : 'var(--border)' }} />
            ))}
          </div>
          <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>{stepLabels[step]}</span>
        </div>

        {/* ── ROLE STEP ── */}
        {step === 'role' && (
          <>
            <h2 style={{ fontSize: 22, fontWeight: 600, margin: '0 0 4px', letterSpacing: '-.01em' }}>
              Do you have a GitHub Copilot license?
            </h2>
            <p style={{ color: 'var(--text-dim)', margin: '0 0 22px', fontSize: 14 }}>
              This just decides how you join — Guests can become Hosts anytime from Profile → Connect license.
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
                  <div style={{ fontWeight: 600, fontSize: 15 }}>Yes — join as a Host</div>
                  <ul style={{ color: 'var(--text-dim)', fontSize: 13, margin: '6px 0 0', paddingLeft: 16, lineHeight: 1.65 }}>
                    <li>You&apos;ll connect a token from your GHE account</li>
                    <li>Your unused credits go to teammates who run out</li>
                    <li>Your token never leaves the server</li>
                  </ul>
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
                  <div style={{ fontWeight: 600, fontSize: 15 }}>No — join as a Guest</div>
                  <ul style={{ color: 'var(--text-dim)', fontSize: 13, margin: '6px 0 0', paddingLeft: 16, lineHeight: 1.65 }}>
                    <li>Post a request on the Marketplace when you need credits</li>
                    <li>Hosts chip in, or top it up yourself from the shared pool</li>
                    <li>No token needed</li>
                  </ul>
                </div>
                <span style={{ color: role === 'consumer' ? 'var(--accent)' : 'var(--text-faint)', fontSize: 18 }}>
                  {role === 'consumer' ? '●' : '○'}
                </span>
              </button>
            </div>

            <p style={{ fontSize: 12.5, color: 'var(--text-faint)', margin: '14px 0 0', lineHeight: 1.5 }}>
              Not sure? If you can use Copilot in your IDE today, you have a license → Host.
            </p>

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
            <p style={{ color: 'var(--text-dim)', margin: '0 0 18px', fontSize: 14, lineHeight: 1.6 }}>
              CTC uses this token to measure your monthly quota and route your unused credits to
              teammates. It&apos;s stored encrypted, only the proxy process ever uses it, and no
              teammate can ever see it.
            </p>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
              <span style={monoLabel}>Copilot license</span>
              <SecretInput
                aria-label="Copilot license"
                value={pat}
                onChange={setPat}
                placeholder="github_pat_••••••••••••"
                wrapperStyle={{ width: '100%', flex: 'none' }}
                style={{
                  background: 'var(--surface-2)',
                  border: '1px solid var(--border)',
                  borderRadius: 10,
                  padding: '12px 13px',
                  color: 'var(--text)',
                  fontFamily: "'JetBrains Mono',monospace",
                  fontSize: 13,
                  outline: 'none',
                }}
              />
            </label>
            <PatHelp heading="Generate your token — 3 steps" style={{ marginTop: 14 }} />
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
              Share with the pool
            </h2>
            <p style={{ color: 'var(--text-dim)', margin: '0 0 18px', fontSize: 14 }}>
              ✓ Verified — belongs to <b>@{identity.gheLogin}</b> · {identity.entitlementAiu.toLocaleString()} AIU monthly quota.
            </p>
            <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
              <span style={monoLabel}>
                Shared with the pool
              </span>
              <span style={{ fontFamily: "'JetBrains Mono',monospace", fontWeight: 600, color: 'var(--pool)' }}>
                {aiu(pledgedSurplus)}
              </span>
            </div>
            <CreditBar
              max={entitlementNano}
              segments={[
                { key: 'used', label: 'used', value: usedNano, color: 'var(--own)', pattern: 'striped' as const },
                { key: 'shared', label: 'shared', value: pledgedSurplus, color: 'var(--pool)' },
                { key: 'kept', label: 'kept', value: Math.max(0, remainingNano - pledgedSurplus), color: 'var(--own)' },
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
            <div data-testid="credit-legend">
              <CreditLegend items={[
                { label: 'used', value: aiu(usedNano), color: 'var(--own)', pattern: 'striped' as const },
                { label: 'shared', value: aiu(pledgedSurplus), color: 'var(--pool)' },
                { label: 'kept', value: aiu(Math.max(0, remainingNano - pledgedSurplus)), color: 'var(--own)' },
              ]} />
            </div>
            <p style={{ color: 'var(--text-faint)', fontSize: 12, margin: '12px 0 0', fontFamily: "'JetBrains Mono',monospace" }}>
              Shown on your profile. It&apos;s the slice of your quota Guests can draw from; not a cap on chipping in.
            </p>
            <div style={{ display: 'flex', gap: 12, marginTop: 20 }}>
              <button type="button" onClick={savePledge} disabled={busy} style={primaryBtn}>
                {busy ? 'Saving…' : 'Save →'}
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
            <h2 style={{ fontSize: 22, fontWeight: 600, margin: '0 0 4px', letterSpacing: '-.01em' }}>
              One last step — connect your terminal
            </h2>
            <p style={{ color: 'var(--text-dim)', fontSize: 14, margin: '0 0 20px', lineHeight: 1.6 }}>
              Copilot runs through CTC from your terminal — this is how your usage gets counted.
            </p>
            {cli && (
              <ol style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 18 }}>
                <InstallStep n={1} title="Open a terminal on your laptop">
                  <p style={stepHint}>macOS: Terminal or iTerm · Windows: PowerShell · Linux: any shell.</p>
                </InstallStep>
                <InstallStep n={2} title="Paste this command and press Enter">
                  <TerminalBlock
                    command={cli.installCommand}
                    caption="This installs the ctc launcher with your personal token baked in — nothing else to paste. Rotate the token anytime in Profile."
                    style={{ marginTop: 8 }}
                  />
                  {cli.caFingerprint && (
                    <p style={{ fontSize: 11, color: 'var(--text-faint)', margin: '8px 2px 0', wordBreak: 'break-all' }}>
                      CA fingerprint (SHA-256): <code>{cli.caFingerprint}</code> — <code>ctc login</code> prints this; verify they match.
                    </p>
                  )}
                </InstallStep>
                <InstallStep n={3} title="Type ctc to start Copilot through CTC">
                  <p style={stepHint}>That&apos;s it — use Copilot normally; CTC handles credits behind the scenes.</p>
                </InstallStep>
              </ol>
            )}
            <div style={{ display: 'flex', gap: 12, marginTop: 24 }}>
              <button type="button" onClick={() => finishInstall(true)} disabled={busy} style={primaryBtn}>
                {busy ? 'Entering…' : 'I ran it — enter CTC'}
              </button>
              <button type="button" onClick={() => finishInstall(false)} disabled={busy} style={ghostBtn}>
                I&apos;ll do it later
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

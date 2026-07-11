import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useApp } from '@/store/AppContext';
import { loadSetupState, saveSetupState } from '@/domain/setupState';
import { TerminalBlock } from '@/components/TerminalBlock';

/**
 * "Finish setting up" card pinned at the top of the dashboard until every
 * applicable item is done or the user dismisses it. Catches everyone who
 * clicked "I'll do it later" (or old "Skip for now") during onboarding.
 * Install acknowledgment lives in localStorage (frontend-only constraint);
 * the license item re-derives from session.hasPat — server truth wins.
 */
export function SetupChecklist() {
  const { session, api } = useApp();
  const navigate = useNavigate();
  const [state, setState] = useState(() => (session ? loadSetupState(session.userId) : null));
  const [expanded, setExpanded] = useState(false);
  const [cli, setCli] = useState<{ installCommand: string; caFingerprint: string | null } | null>(null);
  const [cliError, setCliError] = useState(false);

  if (!session || !state || state.checklistDismissed) return null;

  const needsLicense =
    !session.hasPat && (session.role === 'giver' || session.participantsMode === 'givers_only');
  const items = [
    ...(needsLicense || (session.role === 'giver' && session.hasPat)
      ? [{ key: 'license', label: 'Connect your Copilot license', done: !!session.hasPat }]
      : []),
    { key: 'install', label: 'Run the terminal setup', done: state.installAck },
  ];
  const doneCount = items.filter((i) => i.done).length;
  if (doneCount === items.length) return null;

  function set(patch: Parameters<typeof saveSetupState>[1]) {
    setState(saveSetupState(session!.userId, patch));
  }

  async function toggleExpand() {
    const next = !expanded;
    setExpanded(next);
    if (next && !cli) {
      try {
        const creds = await api.getCliCredentials();
        setCli({ installCommand: creds.installCommand, caFingerprint: creds.caFingerprint });
      } catch {
        setCliError(true);
      }
    }
  }

  const row: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 10, fontSize: 13.5 };
  const check = (done: boolean): React.CSSProperties => ({
    width: 18, height: 18, borderRadius: '50%', flex: 'none',
    display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11,
    background: done ? 'var(--give-soft)' : 'var(--surface-3)',
    color: done ? 'var(--give)' : 'var(--text-faint)',
    border: done ? 'none' : '1px solid var(--border-strong)',
  });
  const linkBtn: React.CSSProperties = {
    background: 'none', border: 'none', padding: 0, fontFamily: 'inherit',
    color: 'var(--accent)', fontSize: 12.5, fontWeight: 600, cursor: 'pointer',
  };

  return (
    <div
      data-tour="setup-checklist"
      style={{
        background: 'var(--surface)',
        border: '1px solid var(--accent)',
        borderRadius: 14,
        padding: '16px 20px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 12 }}>
        <span style={{ fontWeight: 600, fontSize: 14 }}>Finish setting up</span>
        <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, color: 'var(--text-faint)' }}>
          {doneCount} of {items.length} done
        </span>
        <button
          type="button"
          onClick={() => set({ checklistDismissed: true })}
          style={{ ...linkBtn, marginLeft: 'auto', color: 'var(--text-faint)', fontWeight: 500 }}
        >
          Dismiss
        </button>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {items.map((item) => (
          <div key={item.key}>
            <div style={row}>
              <span style={check(item.done)}>{item.done ? '✓' : ''}</span>
              <span style={{ color: item.done ? 'var(--text-faint)' : 'var(--text)', textDecoration: item.done ? 'line-through' : 'none' }}>
                {item.label}
              </span>
              {!item.done && item.key === 'license' && (
                <button type="button" onClick={() => navigate('/app/profile')} style={{ ...linkBtn, marginLeft: 'auto' }}>
                  Go to Profile →
                </button>
              )}
              {!item.done && item.key === 'install' && (
                <button type="button" onClick={toggleExpand} style={{ ...linkBtn, marginLeft: 'auto' }}>
                  {expanded ? 'Hide' : 'Generate the command'}
                </button>
              )}
            </div>
            {item.key === 'install' && !item.done && expanded && (
              <div style={{ margin: '10px 0 4px 28px' }}>
                {cli ? (
                  <>
                    <TerminalBlock
                      command={cli.installCommand}
                      caption="Paste in a terminal and press Enter — installs the ctc launcher with your token baked in. Then type ctc to start Copilot."
                    />
                    <button type="button" onClick={() => set({ installAck: true })} style={{ ...linkBtn, marginTop: 10 }}>
                      ✓ Mark as done
                    </button>
                  </>
                ) : (
                  <p style={{ fontSize: 12.5, color: 'var(--text-faint)', margin: 0 }}>
                    {cliError ? "Couldn't load the command — try again from Profile." : 'Loading…'}
                  </p>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

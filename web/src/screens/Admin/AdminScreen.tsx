import { useState, useEffect, useCallback } from 'react';
import { useApp } from '@/store/AppContext';
import { NANO_PER_AIU } from '@/domain/credit';
import { NumberInput } from '@/components/NumberInput';
import { PatHealthBadge } from '@/components/PatHealthBadge';
import { PledgePresets } from '@/components/CreditBar';
import type { AdminUser, AdminBalances, AdminSettings, AdminSettingsPatch } from '@/domain/types';
import { monoLabel, card } from '@/theme/styles';

// Numeric-only keys of AdminSettingsPatch (for the existing SettingRow number inputs)
type NumericSettingKey = 'defaultPledgePct' | 'requestExpiryHours' | 'requestExpiryMaxHours' | 'creditToEuroRate' | 'defaultChipInAiu';

// ─── Local style constants (shared ones live in @/theme/styles) ────────────────

// Admin's field padding is tighter (9px) than the shared inputStyle (11px), kept local.
const inputStyle: React.CSSProperties = {
  background: 'var(--surface-2)',
  border: '1px solid var(--border)',
  borderRadius: 10,
  padding: '9px 12px',
  color: 'var(--text)',
  fontFamily: 'inherit',
  fontSize: 14,
  outline: 'none',
  width: '100%',
};

const btnBase: React.CSSProperties = {
  background: 'var(--surface-2)',
  border: '1px solid var(--border)',
  borderRadius: 8,
  padding: '5px 14px',
  color: 'var(--text)',
  fontFamily: 'inherit',
  fontWeight: 600,
  fontSize: 12,
  cursor: 'pointer',
};

// ─── UserRow ──────────────────────────────────────────────────────────────────

interface UserRowProps {
  user: AdminUser;
  poolOn: boolean;
  onReveal: (id: string) => Promise<string>;
  onSetPledge: (id: string, nano: number) => Promise<AdminBalances>;
}

function UserRow({ user, poolOn, onReveal, onSetPledge }: UserRowProps) {
  const [revealed, setRevealed] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // Live balances: seeded from the row, refreshed after each admin pledge so the
  // Quota/Pledge cells and the editor bounds stay in sync without a full reload.
  const [bal, setBal] = useState<AdminBalances>(user);
  const [editing, setEditing] = useState(false);
  const [pledgeMsg, setPledgeMsg] = useState<string | null>(null);
  const [pledgeBusy, setPledgeBusy] = useState(false);

  async function handleReveal() {
    setLoading(true);
    try {
      const pat = await onReveal(user.id);
      setRevealed(pat);
    } finally {
      setLoading(false);
    }
  }

  async function commitPledge(nano: number) {
    setPledgeBusy(true);
    setPledgeMsg(null);
    try {
      const updated = await onSetPledge(user.id, nano);
      setBal(updated);
      setPledgeMsg(`Routed — ${(updated.pledge ?? 0) / NANO_PER_AIU} AIU now pledged to the pool.`);
    } catch (err) {
      setPledgeMsg(err instanceof Error ? err.message : 'Could not route credit.');
    } finally {
      setPledgeBusy(false);
    }
  }

  const quotaAiu = bal.quota != null ? (bal.quota / NANO_PER_AIU).toFixed(2) : '—';
  const pledgeAiu = bal.pledge != null ? (bal.pledge / NANO_PER_AIU).toFixed(2) : '—';

  // A giver with credit this cycle can have their unused credit routed to the pool.
  const canRoute = poolOn && user.role === 'giver' && user.hasPat && bal.quota != null;
  // Pledge bounds mirror the Profile slider: floor at already-consumed pledge,
  // cap at the shareable slice (quota - personally used - chipped in).
  const pledgeUsed = Math.max(0, (bal.pledge ?? 0) - (bal.pledgeRemaining ?? 0));
  const pledgeMin = pledgeUsed;
  const pledgeMax = Math.max(pledgeMin, (bal.quota ?? 0) - (bal.used ?? 0) - (bal.donated ?? 0));

  return (
    <>
    <tr>
      <td style={{ padding: '10px 12px', fontFamily: "'JetBrains Mono', monospace", fontSize: 13 }}>
        {user.gheLogin}
      </td>
      <td style={{ padding: '10px 12px', fontSize: 13 }}>
        <span
          style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 11,
            padding: '3px 8px',
            borderRadius: 6,
            background: user.role === 'giver' ? 'var(--give-soft)' : 'var(--consume-soft)',
            color: user.role === 'giver' ? 'var(--give)' : 'var(--consume)',
          }}
        >
          {user.role === 'giver' ? 'Host' : 'Guest'}
        </span>
      </td>
      <td style={{ padding: '10px 12px', fontSize: 13, color: 'var(--text-dim)' }}>
        {user.onboarded ? 'yes' : 'no'}
      </td>
      <td style={{ padding: '10px 12px', fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: 'var(--text-dim)' }}>
        {user.patFingerprint ?? '—'}
      </td>
      <td style={{ padding: '10px 12px' }}>
        {user.patHealth ? (
          <PatHealthBadge health={user.patHealth} title={user.patHealthError ?? undefined} />
        ) : (
          <span style={{ color: 'var(--text-faint)', fontSize: 12 }}>—</span>
        )}
      </td>
      <td style={{ padding: '10px 12px', fontSize: 13, textAlign: 'right', color: 'var(--text-dim)' }}>
        {user.tokenCount}
      </td>
      <td style={{ padding: '10px 12px', fontSize: 13, textAlign: 'right', color: 'var(--text-dim)', fontFamily: "'JetBrains Mono', monospace" }}>
        {quotaAiu !== '—' ? `${quotaAiu} AIU` : '—'}
      </td>
      <td style={{ padding: '10px 12px', fontSize: 13, textAlign: 'right', color: 'var(--text-dim)', fontFamily: "'JetBrains Mono', monospace" }}>
        {pledgeAiu !== '—' ? `${pledgeAiu} AIU` : '—'}
      </td>
      <td style={{ padding: '10px 12px' }}>
        {user.hasPat ? (
          revealed ? (
            <span
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 12,
                color: 'var(--consume)',
                wordBreak: 'break-all',
              }}
            >
              {revealed}
            </span>
          ) : (
            <button
              onClick={handleReveal}
              disabled={loading}
              aria-label={`Reveal license for ${user.gheLogin}`}
              style={btnBase}
            >
              {loading ? '…' : 'Reveal'}
            </button>
          )
        ) : (
          <span style={{ color: 'var(--text-faint)', fontSize: 12 }}>—</span>
        )}
      </td>
      <td style={{ padding: '10px 12px' }}>
        {canRoute ? (
          <button
            onClick={() => { setEditing((e) => !e); setPledgeMsg(null); }}
            aria-expanded={editing}
            aria-label={`Route pool credit for ${user.gheLogin}`}
            style={{ ...btnBase,
                     background: editing ? 'var(--pool-soft)' : 'var(--surface-2)',
                     borderColor: editing ? 'var(--pool)' : 'var(--border)' }}
          >
            {editing ? 'Close' : 'Route to pool'}
          </button>
        ) : (
          <span style={{ color: 'var(--text-faint)', fontSize: 12 }}
                title={!poolOn ? 'The shared pool is off' : 'Only hosts with a license and credit this cycle'}>
            —
          </span>
        )}
      </td>
    </tr>
    {editing && canRoute && (
      <tr>
        <td colSpan={10} style={{ padding: '0 12px 14px', background: 'var(--surface-1)' }}>
          <div style={{ padding: '12px 14px', borderRadius: 10, background: 'var(--surface-2)',
                        border: '1px solid var(--border)' }}>
            <div style={{ fontSize: 12.5, color: 'var(--text-dim)', marginBottom: 4 }}>
              Route <strong style={{ color: 'var(--text)' }}>{user.gheLogin}</strong>'s unused
              credit to the shared pool on their behalf. Currently pledged{' '}
              <strong style={{ color: 'var(--text)' }}>{pledgeAiu} AIU</strong>; shareable up to{' '}
              <strong style={{ color: 'var(--text)' }}>{(pledgeMax / NANO_PER_AIU).toFixed(2)} AIU</strong>.
            </div>
            <PledgePresets
              value={bal.pledge ?? 0}
              min={pledgeMin}
              max={pledgeMax}
              percents={[0.20, 0.50, 0.70]}
              onChange={() => {}}
              onCommit={commitPledge}
            />
            <div aria-live="polite" style={{ fontSize: 12, minHeight: 16,
                  color: pledgeMsg && /could not|error|between|disabled|not a/i.test(pledgeMsg)
                    ? 'var(--consume)' : 'var(--text-faint)' }}>
              {pledgeBusy ? 'Routing…' : (pledgeMsg ?? 'This is logged with your admin identity.')}
            </div>
          </div>
        </td>
      </tr>
    )}
    </>
  );
}

// ─── SettingRow ───────────────────────────────────────────────────────────────

interface SettingRowProps {
  id: string;
  label: string;
  value: number;
  isOverride: boolean;
  min?: number;
  max?: number;
  allowFloat?: boolean;
  onChange: (val: number) => void;
}

function SettingRow({ id, label, value, isOverride, min, max, allowFloat = false, onChange }: SettingRowProps) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <label htmlFor={id} style={{ ...monoLabel, flex: 1 }}>{label}</label>
        {isOverride && (
          <span
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 10,
              padding: '2px 7px',
              borderRadius: 5,
              background: 'var(--accent-soft)',
              color: 'var(--accent)',
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
            }}
          >
            override
          </span>
        )}
      </div>
      <NumberInput
        id={id}
        value={value}
        min={min}
        max={max}
        allowFloat={allowFloat}
        onChange={onChange}
        style={inputStyle}
      />
    </div>
  );
}

// ─── AdminScreen ──────────────────────────────────────────────────────────────

export function AdminScreen() {
  const { api } = useApp();

  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [settings, setSettings] = useState<AdminSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Settings local edits — track only changed fields (numeric fields use AdminSettingsPatch)
  const [localSettings, setLocalSettings] = useState<Pick<AdminSettingsPatch, NumericSettingKey>>({});
  // Mode toggles tracked separately (string / boolean types)
  const [localParticipantsMode, setLocalParticipantsMode] = useState<'givers_only' | 'givers_and_consumers' | null>(null);
  const [localSharedPoolEnabled, setLocalSharedPoolEnabled] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.listAllUsers(), api.getAdminSettings()])
      .then(([u, s]) => {
        setUsers(u);
        setSettings(s);
        setLoading(false);
      })
      .catch((err: unknown) => {
        setLoadError(err instanceof Error ? err.message : 'Failed to load admin data — check your permissions.');
        setLoading(false);
      });
  }, [api]);

  const handleReveal = useCallback((id: string) => api.revealPat(id), [api]);
  const handleSetPledge = useCallback((id: string, nano: number) => api.setUserPledge(id, nano), [api]);

  // Derive effective display value: local override > server value (numeric keys only)
  function effective(key: NumericSettingKey): number {
    if (!settings) return 0;
    const local = localSettings[key];
    if (local !== undefined) return local;
    return settings[key].value as number;
  }

  function handleFieldChange(key: NumericSettingKey, val: number) {
    setLocalSettings(prev => ({ ...prev, [key]: val }));
    setSaveMsg(null);
  }

  function hasLocalChanges(): boolean {
    return (
      Object.keys(localSettings).length > 0 ||
      localParticipantsMode !== null ||
      localSharedPoolEnabled !== null
    );
  }

  async function handleSave() {
    if (!settings) return;
    setSaving(true);
    setSaveMsg(null);
    try {
      // Only send fields that actually changed
      const patch: AdminSettingsPatch = {};
      const numericKeys: NumericSettingKey[] = ['defaultPledgePct', 'requestExpiryHours', 'requestExpiryMaxHours', 'creditToEuroRate', 'defaultChipInAiu'];
      for (const key of numericKeys) {
        const localVal = localSettings[key];
        if (localVal !== undefined && localVal !== (settings[key].value as number)) {
          (patch as Record<string, number>)[key] = localVal;
        }
      }
      if (localParticipantsMode !== null && localParticipantsMode !== settings.participantsMode.value) {
        patch.participantsMode = localParticipantsMode;
      }
      if (localSharedPoolEnabled !== null && localSharedPoolEnabled !== settings.sharedPoolEnabled.value) {
        patch.sharedPoolEnabled = localSharedPoolEnabled;
      }
      const updated = await api.updateAdminSettings(patch);
      setSettings(updated);
      setLocalSettings({});
      setLocalParticipantsMode(null);
      setLocalSharedPoolEnabled(null);
      setSaveMsg('Saved.');
    } catch (err) {
      setSaveMsg(err instanceof Error ? err.message : 'Save failed — please try again.');
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div
        style={{
          color: 'var(--text-faint)',
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 13,
          padding: 40,
          textAlign: 'center',
        }}
      >
        Loading…
      </div>
    );
  }

  if (loadError || !users || !settings) {
    return (
      <div
        role="alert"
        style={{
          color: 'var(--consume)',
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 13,
          padding: 40,
          textAlign: 'center',
        }}
      >
        {loadError ?? 'Failed to load admin data.'}
      </div>
    );
  }

  // Gate routing on the SAVED pool setting — the backend enforces the same, so an
  // unsaved local toggle must not offer an action the server would reject.
  const poolOn = settings.sharedPoolEnabled.value;

  const thStyle: React.CSSProperties = {
    ...monoLabel,
    padding: '8px 12px',
    textAlign: 'left',
    borderBottom: '1px solid var(--border)',
    whiteSpace: 'nowrap',
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24, maxWidth: 1100, width: '100%', margin: '0 auto' }}>

      {/* Users table */}
      <div style={card}>
        <div style={{ fontWeight: 600, fontSize: 15, marginBottom: 6 }}>Users</div>
        <p
          style={{
            fontSize: 12,
            color: 'var(--consume)',
            fontFamily: "'JetBrains Mono', monospace",
            marginBottom: 16,
            padding: '8px 12px',
            borderRadius: 8,
            background: 'var(--consume-soft)',
          }}
        >
          License reveal is sensitive and audited. Every reveal is logged with your admin identity and timestamp.
        </p>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={thStyle}>Login</th>
                <th style={thStyle}>Role</th>
                <th style={thStyle}>Onboarded</th>
                <th style={thStyle}>License fingerprint</th>
                <th style={thStyle}>License status</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>Tokens</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>Quota</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>Pledge</th>
                <th style={thStyle}>License</th>
                <th style={thStyle}>Pool</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <UserRow key={u.id} user={u} poolOn={poolOn}
                         onReveal={handleReveal} onSetPledge={handleSetPledge} />
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Settings form */}
      <div style={card}>
        <div style={{ fontWeight: 600, fontSize: 15, marginBottom: 20 }}>System settings</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          <SettingRow
            id="setting-defaultPledgePct"
            label="Default pledge %"
            value={effective('defaultPledgePct')}
            isOverride={settings.defaultPledgePct.isOverride}
            min={0}
            max={100}
            onChange={(v) => handleFieldChange('defaultPledgePct', v)}
          />
          <SettingRow
            id="setting-requestExpiryHours"
            label="Request expiry (hours)"
            value={effective('requestExpiryHours')}
            isOverride={settings.requestExpiryHours.isOverride}
            min={1}
            max={effective('requestExpiryMaxHours')}
            onChange={(v) => handleFieldChange('requestExpiryHours', v)}
          />
          <SettingRow
            id="setting-requestExpiryMaxHours"
            label="Request expiry max (hours)"
            value={effective('requestExpiryMaxHours')}
            isOverride={settings.requestExpiryMaxHours.isOverride}
            min={effective('requestExpiryHours')}
            onChange={(v) => handleFieldChange('requestExpiryMaxHours', v)}
          />
          <SettingRow
            id="setting-creditToEuroRate"
            label="Credit to EUR rate"
            value={effective('creditToEuroRate')}
            isOverride={settings.creditToEuroRate.isOverride}
            min={0}
            allowFloat
            onChange={(v) => handleFieldChange('creditToEuroRate', v)}
          />
          <SettingRow
            id="setting-defaultChipInAiu"
            label="Default chip-in (AIU)"
            value={effective('defaultChipInAiu')}
            isOverride={settings.defaultChipInAiu.isOverride}
            min={1}
            onChange={(v) => handleFieldChange('defaultChipInAiu', v)}
          />

          {/* Participants mode select */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <label htmlFor="setting-participantsMode" style={{ ...monoLabel, flex: 1 }}>Participants mode</label>
              {settings.participantsMode.isOverride && (
                <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, padding: '2px 7px', borderRadius: 5, background: 'var(--accent-soft)', color: 'var(--accent)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                  override
                </span>
              )}
            </div>
            <select
              id="setting-participantsMode"
              value={localParticipantsMode ?? settings.participantsMode.value}
              onChange={(e) => { setLocalParticipantsMode(e.target.value as 'givers_only' | 'givers_and_consumers'); setSaveMsg(null); }}
              style={{ ...inputStyle, cursor: 'pointer' }}
            >
              <option value="givers_and_consumers">givers_and_consumers — open to all</option>
              <option value="givers_only">givers_only — license required</option>
            </select>
          </div>

          {/* Shared pool toggle */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ ...monoLabel }}>Shared pool</span>
                {settings.sharedPoolEnabled.isOverride && (
                  <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, padding: '2px 7px', borderRadius: 5, background: 'var(--accent-soft)', color: 'var(--accent)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                    override
                  </span>
                )}
              </div>
              <span style={{ fontSize: 12, color: 'var(--text-faint)' }}>Hosts pledge credit into a pool anyone can route to open requests on the board</span>
            </div>
            <button
              id="setting-sharedPoolEnabled"
              type="button"
              aria-label="Toggle shared pool"
              onClick={() => {
                const current = localSharedPoolEnabled ?? settings.sharedPoolEnabled.value;
                setLocalSharedPoolEnabled(!current);
                setSaveMsg(null);
              }}
              style={{
                ...btnBase,
                padding: '7px 18px',
                background: (localSharedPoolEnabled ?? settings.sharedPoolEnabled.value) ? 'var(--give-soft)' : 'var(--surface-2)',
                color: (localSharedPoolEnabled ?? settings.sharedPoolEnabled.value) ? 'var(--give)' : 'var(--text-faint)',
                border: `1px solid ${(localSharedPoolEnabled ?? settings.sharedPoolEnabled.value) ? 'var(--give)' : 'var(--border)'}`,
              }}
            >
              {(localSharedPoolEnabled ?? settings.sharedPoolEnabled.value) ? 'ON' : 'OFF'}
            </button>
          </div>
        </div>
        <div style={{ marginTop: 22, display: 'flex', alignItems: 'center', gap: 14 }}>
          <button
            onClick={handleSave}
            disabled={saving || !hasLocalChanges()}
            style={{
              background: 'var(--accent)',
              color: '#fff',
              border: 'none',
              borderRadius: 10,
              padding: '10px 20px',
              fontFamily: 'inherit',
              fontWeight: 600,
              fontSize: 13,
              cursor: !hasLocalChanges() ? 'default' : 'pointer',
              opacity: !hasLocalChanges() ? 0.5 : 1,
            }}
          >
            {saving ? 'Saving…' : 'Save settings'}
          </button>
          {saveMsg && (
            <span
              role="status"
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 12,
                color: saveMsg === 'Saved.' ? 'var(--give)' : 'var(--consume)',
              }}
            >
              {saveMsg}
            </span>
          )}
        </div>
        <p style={{ marginTop: 12, fontSize: 11, color: 'var(--text-faint)', fontFamily: "'JetBrains Mono', monospace" }}>
          credit_to_euro_rate drives the euro (€) figures shown across the app; changes take effect on each user&apos;s next page load.
        </p>
      </div>

      {/* Boot config — read-only, set via .env */}
      {settings.boot && (
        <div style={card}>
          <div style={{ fontWeight: 600, fontSize: 15, marginBottom: 6 }}>Boot config</div>
          <p style={{ fontSize: 12, color: 'var(--text-faint)', fontFamily: "'JetBrains Mono', monospace", marginBottom: 16 }}>
            Set in .env — restart to change
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {([
              ['web_transport', settings.boot.webTransport],
            ] as [string, string][]).map(([key, val]) => (
              <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{ ...monoLabel, flex: 1 }}>{key}</span>
                <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 13, color: 'var(--text)' }}>{val}</span>
              </div>
            ))}
          </div>
        </div>
      )}

    </div>
  );
}

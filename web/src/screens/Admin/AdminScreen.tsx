import { useState, useEffect, useCallback } from 'react';
import { useApp } from '@/store/AppContext';
import { NANO_PER_AIU } from '@/domain/credit';
import type { AdminUser, AdminSettings, AdminSettingsPatch } from '@/domain/types';

// ─── Shared style constants ────────────────────────────────────────────────────

const card: React.CSSProperties = {
  background: 'var(--surface)',
  border: '1px solid var(--border)',
  borderRadius: 16,
  padding: 24,
};

const monoLabel: React.CSSProperties = {
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: 11,
  letterSpacing: '0.12em',
  textTransform: 'uppercase',
  color: 'var(--text-faint)',
};

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
  onReveal: (id: string) => Promise<string>;
}

function UserRow({ user, onReveal }: UserRowProps) {
  const [revealed, setRevealed] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleReveal() {
    setLoading(true);
    try {
      const pat = await onReveal(user.id);
      setRevealed(pat);
    } finally {
      setLoading(false);
    }
  }

  const quotaAiu = user.quota != null ? (user.quota / NANO_PER_AIU).toFixed(2) : '—';
  const pledgeAiu = user.pledge != null ? (user.pledge / NANO_PER_AIU).toFixed(2) : '—';

  return (
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
    </tr>
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
  step?: number;
  onChange: (val: number) => void;
}

function SettingRow({ id, label, value, isOverride, min, max, step = 1, onChange }: SettingRowProps) {
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
      <input
        id={id}
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => onChange(Number(e.target.value))}
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

  // Settings local edits — track only changed fields
  const [localSettings, setLocalSettings] = useState<AdminSettingsPatch>({});
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

  // Derive effective display value: local override > server value
  function effective(key: keyof AdminSettingsPatch): number {
    if (!settings) return 0;
    const local = localSettings[key];
    if (local !== undefined) return local;
    return settings[key].value;
  }

  function handleFieldChange(key: keyof AdminSettingsPatch, val: number) {
    setLocalSettings(prev => ({ ...prev, [key]: val }));
    setSaveMsg(null);
  }

  async function handleSave() {
    if (!settings) return;
    setSaving(true);
    setSaveMsg(null);
    try {
      // Only send fields that actually changed
      const patch: AdminSettingsPatch = {};
      for (const key of Object.keys(localSettings) as Array<keyof AdminSettingsPatch>) {
        const localVal = localSettings[key];
        if (localVal !== undefined && localVal !== settings[key].value) {
          (patch as Record<string, number>)[key] = localVal;
        }
      }
      const updated = await api.updateAdminSettings(patch);
      setSettings(updated);
      setLocalSettings({});
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
                <th style={{ ...thStyle, textAlign: 'right' }}>Tokens</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>Quota</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>Pledge</th>
                <th style={thStyle}>License</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <UserRow key={u.id} user={u} onReveal={handleReveal} />
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
            id="setting-freeAllowanceAiu"
            label="Free allowance (AIU)"
            value={effective('freeAllowanceAiu')}
            isOverride={settings.freeAllowanceAiu.isOverride}
            min={1}
            step={10}
            onChange={(v) => handleFieldChange('freeAllowanceAiu', v)}
          />
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
            step={0.001}
            onChange={(v) => handleFieldChange('creditToEuroRate', v)}
          />
        </div>
        <div style={{ marginTop: 22, display: 'flex', alignItems: 'center', gap: 14 }}>
          <button
            onClick={handleSave}
            disabled={saving || Object.keys(localSettings).length === 0}
            style={{
              background: 'var(--accent)',
              color: '#fff',
              border: 'none',
              borderRadius: 10,
              padding: '10px 20px',
              fontFamily: 'inherit',
              fontWeight: 600,
              fontSize: 13,
              cursor: Object.keys(localSettings).length === 0 ? 'default' : 'pointer',
              opacity: Object.keys(localSettings).length === 0 ? 0.5 : 1,
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
          credit_to_euro_rate is stored and editable here; it has no live consumer in this release (reserved for future billing).
        </p>
      </div>

    </div>
  );
}

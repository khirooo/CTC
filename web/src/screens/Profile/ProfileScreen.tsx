import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useApp } from '@/store/AppContext';
import { useAsync } from '@/store/useAsync';
import { CtcApiError } from '@/api/http';
import { aiu } from '@/domain/credit';
import { Card, ColorKey, SecretInput } from '@/components';
import { ScreenStatus } from '@/components/ScreenStatus';
import { CreditBar, CreditLegend, type BarSegment } from '@/components/CreditBar';
import { TerminalBlock } from '@/components/TerminalBlock';
import { InfoTip } from '@/components/InfoTip';
import { PatHelp } from '@/components/PatHelp';
import { PatHealthBadge } from '@/components/PatHealthBadge';
import { TierBadge } from '@/components/TierBadge';
import { monoLabel, card, inputStyle } from '@/theme/styles';

function resetLine(resetDate: string | null | undefined): string | null {
  if (!resetDate) return null;
  const reset = new Date(resetDate + 'T00:00:00Z').getTime();
  const days = Math.max(0, Math.ceil((reset - Date.now()) / 86_400_000));
  const d = new Date(reset).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
  return days === 0 ? `Resets ${d} · resets today` : `Resets ${d} · in ${days} day${days === 1 ? '' : 's'}`;
}

/** One sentence per non-valid license state — what happened and what fixes it. */
const PAT_HEALTH_HINT: Record<string, string> = {
  expired:
    'This license stopped working, so requests using it are failing. Rotate it below with a fresh token to fix it.',
  forbidden:
    'This license is missing the permissions Copilot needs. Rotate it below with a token that has Copilot access.',
  no_entitlement:
    'This license has no Copilot quota attached. Check the Copilot subscription on your GitHub account.',
  unreachable:
    "CTC couldn't reach GitHub to check this license just now. The badge shows the last known state.",
};

function checkedLine(checkedAt: number | null): string | null {
  if (!checkedAt) return null;
  const d = new Date(checkedAt * 1000);
  return `license checked ${d.toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}`;
}

function nudgeLine(tier: string | null, netToNext: number | null): string | null {
  if (!tier || tier === 'newcomer') return 'Donate some credit to claim a rank.';
  if (netToNext != null) return `Donate ${aiu(netToNext)} more to overtake the next host.`;
  if (tier === 'aristocrat') return 'You top the standings. Noblesse oblige. 👑';
  return null;
}


/**
 * The single account screen — identity, credit cycle (with the giver pledge
 * slider inline), PAT management, CLI setup, and sign out. Merged from the old
 * Profile + Settings screens. Identity is the GHE login (immutable); there are
 * no editable name/email fields.
 */
export function ProfileScreen() {
  const { api, signOut, session, refresh } = useApp();
  const navigate = useNavigate();
  const settings = useAsync(() => api.getSettings(), []);
  const profile = useAsync(() => api.getOwnProfile(), []);
  // List existing tokens on mount (read-only). Minting a token is a write, so it
  // happens only when the user clicks "Generate install command" below — not on
  // every Profile view (which used to spawn a fresh token each time).
  const tokens = useAsync(() => api.listProxyTokens(), []);

  const [localPledged, setLocalPledged] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [patSaveError, setPatSaveError] = useState<string | null>(null);
  const [returnError, setReturnError] = useState<string | null>(null);
  const [patInput, setPatInput] = useState('');
  const [rotating, setRotating] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const [cli, setCli] = useState<{ token: string; proxyHost: string; installCommand: string; caFingerprint: string | null } | null>(null);
  const [minting, setMinting] = useState(false);
  const [mintError, setMintError] = useState<string | null>(null);

  if (settings.loading) return <ScreenStatus message="Loading…" />;
  if (settings.error || !settings.data) {
    return <ScreenStatus message="Couldn't load your profile. Refresh to try again." tone="dim" />;
  }

  const data = settings.data;
  const p = profile.data;
  const isGiver = data.role === 'giver';
  const login = data.login;
  const initials = p?.user.initials ?? login.slice(0, 2).toUpperCase();
  const pledgedValue = localPledged ?? data.pledgedSurplus ?? 0;
  const reset = resetLine(p?.resetDate);

  async function handlePledgedChange(val: number) {
    setLocalPledged(val);
  }

  async function handlePledgedSave(val: number) {
    setSaving(true);
    setSaveError(null);
    try {
      await api.updateSettings({ pledgedSurplus: val });
      setLocalPledged(null);  // stop showing optimistic preview; committed values come from backend
      settings.reload();
      profile.reload();
    } catch (e) {
      setSaveError(e instanceof CtcApiError ? e.message : 'Something went wrong — please try again.');
    } finally {
      setSaving(false);
    }
  }

  async function handlePatSave() {
    if (!patInput.trim()) return;
    setSaving(true);
    setPatSaveError(null);
    try {
      await api.updateSettings({ pat: patInput.trim() });
      setPatInput('');
      setRotating(false);
      settings.reload();
      profile.reload();
      // Connecting/rotating a license promotes a consumer to giver (hasPat/role
      // change) — refresh the session so the dashboard stops gating on stale state.
      await refresh();
    } catch (e) {
      setPatSaveError(e instanceof CtcApiError ? e.message : 'Could not validate that license — check it and try again.');
    } finally {
      setSaving(false);
    }
  }

  async function handleRevoke() {
    if (!window.confirm('Revoke your Copilot license? This removes your stored PAT and zeroes your credit this cycle.')) return;
    setRevoking(true);
    setPatSaveError(null);
    try {
      await api.revokePat();
      setPatInput('');
      setRotating(false);
      settings.reload();
      profile.reload();
      // Revoke reverts giver → consumer — refresh the session so guards/dashboard
      // reflect the lost license immediately.
      await refresh();
    } catch (e) {
      setPatSaveError(e instanceof CtcApiError ? e.message : 'Could not revoke the license — please try again.');
    } finally {
      setRevoking(false);
    }
  }

  async function handleSignOut() {
    await signOut();
    navigate('/signin');
  }

  async function handleGenerateCli() {
    setMinting(true);
    setMintError(null);
    try {
      setCli(await api.getCliCredentials());
      tokens.reload();
    } catch (e) {
      setMintError(e instanceof CtcApiError ? e.message : 'Could not generate the command — please try again.');
    } finally {
      setMinting(false);
    }
  }

  async function handleMoveToPool() {
    const left = profile.data?.donationsReceivedRemaining ?? 0;
    const raw = window.prompt(
      `Move how many credits to the shared pool? (up to ${aiu(left)})`,
      String(Math.floor(left / 1_000_000_000)),
    );
    if (raw == null) return;
    const n = Number(raw);
    if (!Number.isFinite(n) || n <= 0) return;
    setReturnError(null);
    try {
      await api.returnReceivedToPool(n * 1_000_000_000);  // AIU → nano-AIU
      profile.reload();
    } catch (e) {
      setReturnError(e instanceof CtcApiError ? e.message : 'Something went wrong — please try again.');
    }
  }

  // Giver credit bar segments (striped = consumed/locked; solid = reserved/available)
  const E = p?.entitlement ?? 0;
  // Pledging is a pool-only concept. When the shared pool is off, a giver still
  // has a credit cycle (entitlement / used / available) — only the pledge slider
  // and pool/surplus framing drop out.
  const poolOn = session?.sharedPoolEnabled !== false;
  const effPledged = poolOn ? pledgedValue : 0;
  // Spent (striped) segments stack on the left, available (solid) on the right:
  // used | chipped·used | shared·used ‖ chipped·left | shared·left | kept.
  // The slider handle still lands exactly on the shared·left/kept boundary —
  // everything left of shared·left sums to used + donated + pledgedConsumed,
  // the same total as before the reorder, so trackStart is unchanged.
  const giverSegs: BarSegment[] = [
    { key: 'used', label: 'used', value: p?.used ?? 0, color: 'var(--own)', pattern: 'striped' as const },
    { key: 'donatedC', label: 'chipped in', value: p?.donatedConsumed ?? 0, color: 'var(--give)', pattern: 'striped' as const },
    ...(poolOn ? [
      { key: 'pledgedC', label: 'shared', value: localPledged !== null ? Math.min(pledgedValue, p?.pledgedConsumed ?? 0) : (p?.pledgedConsumed ?? 0), color: 'var(--pool)', pattern: 'striped' as const },
    ] : []),
    { key: 'donatedR', label: 'chipped in', value: p?.donatedRemaining ?? 0, color: 'var(--give)' },
    ...(poolOn ? [
      // While dragging (localPledged != null), show the optimistic preview; once saved, read the backend field.
      { key: 'pledgedR', label: 'shared', value: localPledged !== null ? Math.max(0, pledgedValue - (p?.pledgedConsumed ?? 0)) : (p?.pledgedRemaining ?? 0), color: 'var(--pool)' },
    ] : []),
    // kept: while dragging, recompute optimistically (like the legend does) so
    // the bar stays a full E and only the shared/kept boundary moves — a stale
    // backend value here makes every segment right of the handle slide sideways.
    // Once committed, read the backend field.
    { key: 'left', label: 'kept',
      value: localPledged !== null
        ? Math.max(0, E - (p?.used ?? 0) - (p?.donated ?? 0) - effPledged)
        : (p?.left ?? 0),
      color: 'var(--own)' },
  ].filter((s) => s.value > 0);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18, maxWidth: 680, width: '100%', margin: '0 auto' }}>
      {/* Identity — login is the immutable identity; no editable fields */}
      <div style={{ ...card, display: 'flex', alignItems: 'center', gap: 18 }}>
        <div
          style={{
            width: 60, height: 60, borderRadius: 16,
            background: 'var(--accent-soft)', color: 'var(--accent)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontWeight: 600, fontSize: 22, flex: 'none',
          }}
        >
          {initials}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 20, fontWeight: 600, letterSpacing: '-0.01em', fontFamily: "'JetBrains Mono', monospace", overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {login}
          </div>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 13, color: 'var(--text-dim)', marginTop: 3 }}>
            {isGiver ? 'Host' : 'Guest'} account
          </div>
          {p?.tier && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 8 }}>
              <TierBadge tier={p.tier} />
              <InfoTip term="tier" />
              {nudgeLine(p.tier, p.netToNext) && (
                <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                  {nudgeLine(p.tier, p.netToNext)}
                </span>
              )}
            </div>
          )}
        </div>
        <span
          style={{
            fontFamily: "'JetBrains Mono', monospace", fontSize: 12,
            padding: '6px 12px', borderRadius: 8,
            background: isGiver ? 'var(--give-soft)' : 'var(--consume-soft)',
            color: isGiver ? 'var(--give)' : 'var(--consume)',
          }}
        >
          {isGiver ? 'Host' : 'Guest'}
        </span>
      </div>

      {/* Credit cycle — giver: entitlement/used/available, plus the interactive
          pledge bar when the shared pool is on. Consumer: usage total below. */}
      {isGiver && p && (
        <div style={{ ...card, padding: '22px 24px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <span style={monoLabel}>Your monthly credits</span>
              <InfoTip term="cycle" />
            </span>
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, fontSize: 18, color: 'var(--text)' }}>
              {p.unlimited ? '∞' : aiu(poolOn && localPledged !== null ? pledgedValue : (p.left ?? 0))}
            </span>
          </div>

          {p.unlimited ? (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, fontSize: 20, color: 'var(--text)' }}>
                Unlimited entitlement
              </div>
              <div style={{ fontSize: 13, color: 'var(--text-dim)', marginTop: 6 }}>
                chipped in {aiu(p.donated ?? 0)}{poolOn ? ` · shared ${aiu(pledgedValue)}` : ''}
              </div>
            </div>
          ) : (
            <>
              {poolOn && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginTop: 14, fontSize: 11, color: 'var(--text-faint)', fontFamily: "'JetBrains Mono', monospace" }}>
                  <span>Shared with the pool</span>
                  <InfoTip term="pledge" />
                </div>
              )}
              <div style={{ marginTop: poolOn ? 8 : 14 }}>
                <CreditBar
                  max={E}
                  segments={giverSegs}
                  slider={poolOn ? {
                    value: pledgedValue,
                    min: p.pledgedConsumed ?? 0,
                    max: Math.max(p.pledgedConsumed ?? 0, E - (p.used ?? 0) - (p.donated ?? 0)),
                    // handle starts after the fixed used + donated + already-consumed-pledge segments
                    trackStart: E > 0 ? ((p.used ?? 0) + (p.donated ?? 0) + (p.pledgedConsumed ?? 0)) / E : 0,
                    onChange: handlePledgedChange,
                    onCommit: handlePledgedSave,
                  } : undefined}
                />
              </div>

              <div data-testid="credit-legend">
                <CreditLegend items={[
                  // Legend mirrors the bar order: spent (striped) first, then available.
                  { label: 'used', value: aiu(p.used ?? 0), color: 'var(--own)', pattern: 'striped' },
                  ...((p.donatedConsumed ?? 0) > 0 ? [{ label: 'chipped in · used', value: aiu(p.donatedConsumed ?? 0), color: 'var(--give)', pattern: 'striped' as const }] : []),
                  ...(poolOn && (p.pledgedConsumed ?? 0) > 0 ? [{ label: 'shared · used', value: aiu(Math.min(pledgedValue, p.pledgedConsumed ?? 0)), color: 'var(--pool)', pattern: 'striped' as const }] : []),
                  ...((p.donatedRemaining ?? 0) > 0 ? [{ label: 'chipped in · left', value: aiu(p.donatedRemaining ?? 0), color: 'var(--give)' }] : []),
                  ...(poolOn ? [{ label: 'shared · left', value: aiu(Math.max(0, pledgedValue - (p.pledgedConsumed ?? 0))), color: 'var(--pool)' }] : []),
                  // Read backend field; only use local derivation while slider is actively being dragged.
                  { label: 'kept', value: aiu(localPledged !== null ? Math.max(0, E - (p.used ?? 0) - (p.donated ?? 0) - effPledged) : (p.left ?? 0)), color: 'var(--own)' },
                ]} />
                {p.quotaStale && (
                  <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: 'var(--text-faint)', marginTop: 6, opacity: 0.7 }}>
                    figures as of last sync
                  </div>
                )}
              </div>

              {reset && (
                <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: 'var(--text-faint)', marginTop: 8 }}>
                  {reset}
                </div>
              )}
            </>
          )}

          {poolOn && (
            <p style={{ color: 'var(--text-faint)', fontSize: 12, margin: '14px 0 0', fontFamily: "'JetBrains Mono', monospace" }}>
              Shown on your public profile.
              "Shared with the pool" is the slice of your quota Guests can draw from; not a
              cap on chipping in. Resets on the 1st.
            </p>
          )}
          {saveError && (
            <p role="alert" style={{ color: 'var(--consume)', fontSize: 13, margin: '12px 0 0', fontFamily: "'JetBrains Mono', monospace" }}>
              {saveError}
            </p>
          )}
        </div>
      )}

      {!isGiver && p && (
        <div style={card}>
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 18 }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <span style={monoLabel}>Credits used</span>
              <InfoTip term="credits" />
            </span>
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 13, color: 'var(--text-dim)' }}>
              from chip-ins and the shared pool
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8 }}>
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, fontSize: 48, color: 'var(--consume)', lineHeight: 1 }}>
              {aiu(p.consumed)}
            </span>
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 15, color: 'var(--text-faint)', marginBottom: 5 }}>
              used
            </span>
          </div>
          {reset && (
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: 'var(--text-faint)', marginTop: 14 }}>
              {reset}
            </div>
          )}
        </div>
      )}

      {/* Routed to you — credit others (or the pool) have put behind this account. */}
      {p && p.donationsReceived > 0 && (
        <div style={card} data-routed-panel>
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 12 }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <span style={monoLabel}>Routed to you</span>
              <InfoTip term="chipIn" />
            </span>
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 13, color: 'var(--give)' }}>
              +{aiu(p.donationsReceived)}
            </span>
          </div>
          <CreditBar
            max={p.donationsReceived}
            segments={[
              { key: 'recvUsed', label: 'used', value: p.donationsReceivedConsumed, color: 'var(--give)', pattern: 'striped' as const },
              { key: 'recvRedonated', label: 're-donated', value: p.reDonated ?? 0, color: 'var(--give)', opacity: 0.55 },
              { key: 'recvReturned', label: 'to pool', value: p.returnedToPool ?? 0, color: 'var(--pool)', opacity: 0.55 },
              { key: 'recvLeft', label: 'left', value: p.donationsReceivedRemaining, color: 'var(--give)' },
            ].filter((s) => s.value > 0)}
          />
          <CreditLegend items={[
            { label: 'used', value: aiu(p.donationsReceivedConsumed), color: 'var(--give)', pattern: 'striped' },
            ...((p.reDonated ?? 0) > 0 ? [{ label: 're-donated', value: aiu(p.reDonated ?? 0), color: 'var(--give)' }] : []),
            ...((p.returnedToPool ?? 0) > 0 ? [{ label: 'moved to pool', value: aiu(p.returnedToPool ?? 0), color: 'var(--pool)' }] : []),
            { label: 'left', value: aiu(p.donationsReceivedRemaining), color: 'var(--give)' },
          ]} />
          {p.donationsReceivedFromPool > 0 && (
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: 'var(--pool)', marginTop: 8 }}>
              {aiu(p.donationsReceivedFromPool)} of this came from the shared pool
            </div>
          )}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginTop: 10 }}>
            <p style={{ color: 'var(--text-faint)', fontSize: 12, margin: 0, fontFamily: "'JetBrains Mono', monospace" }}>
              credit pledged to your requests — spend it via the CLI, chip it in on the
              marketplace, or move it to the shared pool.
            </p>
            {poolOn && p.donationsReceivedRemaining > 0 && (
              <button
                type="button"
                data-move-to-pool
                onClick={handleMoveToPool}
                style={{
                  flex: 'none', background: 'transparent', color: 'var(--pool)',
                  border: '1px solid var(--pool)', borderRadius: 9, padding: '8px 14px',
                  fontFamily: 'inherit', fontWeight: 600, fontSize: 13, cursor: 'pointer',
                }}
              >
                Move to pool…
              </button>
            )}
          </div>
          {returnError && (
            <p role="alert" style={{ color: 'var(--consume)', fontSize: 13, margin: '10px 0 0', fontFamily: "'JetBrains Mono', monospace" }}>
              {returnError}
            </p>
          )}
        </div>
      )}

      {/* Copilot license (Host with a license connected) */}
      {isGiver && data.hasPat && (
        <div style={card}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 18 }}>
            <div style={{ fontWeight: 600, fontSize: 15 }}>Copilot license</div>
            {data.patHealth && <PatHealthBadge health={data.patHealth} />}
          </div>
          {data.patHealth && PAT_HEALTH_HINT[data.patHealth] && (
            <p style={{ color: data.patHealth === 'unreachable' ? 'var(--text-faint)' : 'var(--consume)', fontSize: 13, margin: '0 0 12px', fontFamily: "'JetBrains Mono', monospace" }}>
              {PAT_HEALTH_HINT[data.patHealth]}
            </p>
          )}
          {patSaveError && (
            <p role="alert" style={{ color: 'var(--consume)', fontSize: 13, margin: '0 0 12px', fontFamily: "'JetBrains Mono', monospace" }}>
              {patSaveError}
            </p>
          )}
          {rotating ? (
            <div style={{ display: 'flex', gap: 10 }}>
              <SecretInput
                autoFocus
                aria-label="New Copilot license"
                placeholder="github_pat_… (new license)"
                value={patInput}
                onChange={setPatInput}
                style={{ ...inputStyle, fontFamily: "'JetBrains Mono', monospace", fontSize: 13 }}
              />
              <button
                type="button"
                disabled={saving || !patInput.trim()}
                onClick={handlePatSave}
                style={{ background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 10, padding: '0 18px', fontFamily: 'inherit', fontWeight: 600, fontSize: 13, cursor: 'pointer' }}
              >
                {saving ? 'Saving…' : 'Save'}
              </button>
              <button
                type="button"
                disabled={saving}
                onClick={() => { setRotating(false); setPatInput(''); setPatSaveError(null); }}
                style={{ background: 'transparent', border: '1px solid var(--border)', borderRadius: 10, padding: '0 16px', color: 'var(--text-dim)', fontFamily: 'inherit', fontWeight: 600, fontSize: 13, cursor: 'pointer' }}
              >
                Cancel
              </button>
            </div>
          ) : (
            <div style={{ display: 'flex', gap: 10 }}>
              <input
                type="text"
                readOnly
                value="github_pat_••••••••••••••••"
                style={{ ...inputStyle, flex: 1, color: 'var(--text-dim)', fontFamily: "'JetBrains Mono', monospace", fontSize: 13 }}
              />
              <button
                type="button"
                disabled={revoking}
                onClick={() => { setRotating(true); setPatSaveError(null); }}
                style={{ background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 10, padding: '0 16px', color: 'var(--text)', fontFamily: 'inherit', fontWeight: 600, fontSize: 13, cursor: 'pointer' }}
              >
                Rotate
              </button>
              <button
                type="button"
                disabled={revoking}
                onClick={handleRevoke}
                style={{ background: 'transparent', border: '1px solid var(--border)', borderRadius: 10, padding: '0 16px', color: '#ff6b6b', fontFamily: 'inherit', fontWeight: 600, fontSize: 13, cursor: 'pointer' }}
              >
                {revoking ? 'Revoking…' : 'Revoke'}
              </button>
            </div>
          )}
          {checkedLine(data.patHealthCheckedAt) && (
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: 'var(--text-faint)', marginTop: 10, opacity: 0.7 }}>
              {checkedLine(data.patHealthCheckedAt)}
            </div>
          )}
        </div>
      )}

      {/* Become a Host (no license connected yet) */}
      {!data.hasPat && (
        <div style={card}>
          <div style={{ fontWeight: 600, fontSize: 15, marginBottom: 4 }}>Become a Host</div>
          <div style={{ fontSize: 13, color: 'var(--text-dim)', marginBottom: 14 }}>
            Connect your Copilot license (a GitHub Enterprise token). CTC validates it,
            reads your monthly quota, and stores it encrypted — it never leaves the
            server and teammates can't see it.
          </div>
          {patSaveError && (
            <p role="alert" style={{ color: 'var(--consume)', fontSize: 13, margin: '0 0 12px', fontFamily: "'JetBrains Mono', monospace" }}>
              {patSaveError}
            </p>
          )}
          <div style={{ display: 'flex', gap: 10 }}>
            <SecretInput
              aria-label="Copilot license"
              placeholder="github_pat_…"
              value={patInput}
              onChange={setPatInput}
              style={{ ...inputStyle, fontFamily: "'JetBrains Mono', monospace", fontSize: 13 }}
            />
            <button
              type="button"
              disabled={saving || !patInput.trim()}
              onClick={handlePatSave}
              style={{ background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 10, padding: '0 18px', fontFamily: 'inherit', fontWeight: 600, fontSize: 13, cursor: 'pointer' }}
            >
              Connect license
            </button>
          </div>
          <PatHelp style={{ marginTop: 14 }} />
        </div>
      )}

      {/* Set up CLI — the install one-liner embeds a fresh proxy token, so it is
          minted only when the user asks for it (never on mount). */}
      <Card>
        <h3 style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 14, marginBottom: 8 }}>Set up CLI</h3>
        <p style={{ color: 'var(--text-faint)', fontSize: 12, marginBottom: 12 }}>
          Install once, then launch Copilot with the ctc command. New laptop or lost the command? Generate a fresh one below.
        </p>
        {cli ? (
          <>
            <TerminalBlock
              command={cli.installCommand}
              caption="Paste in a terminal and press Enter, then type ctc to start Copilot through CTC."
            />
            <p style={{ color: 'var(--text-faint)', fontSize: 11, marginTop: 12 }}>Proxy: {cli.proxyHost}</p>
            {cli.caFingerprint && (
              <p style={{ color: 'var(--text-faint)', fontSize: 11, wordBreak: 'break-all' }}>
                CA fingerprint (SHA-256): <code>{cli.caFingerprint}</code> — <code>ctc login</code> prints this; verify they match.
              </p>
            )}
          </>
        ) : (
          <>
            {(tokens.data?.length ?? 0) > 0 && (
              <p style={{ color: 'var(--text-faint)', fontSize: 12, marginBottom: 12 }}>
                You have {tokens.data!.length} active install token{tokens.data!.length === 1 ? '' : 's'}. The token is
                shown only once when created — generate a new command if you no longer have it.
              </p>
            )}
            <button
              type="button"
              onClick={handleGenerateCli}
              disabled={minting}
              style={{ background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 10, padding: '10px 18px', fontFamily: 'inherit', fontWeight: 600, fontSize: 13, cursor: minting ? 'default' : 'pointer', opacity: minting ? 0.7 : 1 }}
            >
              {minting ? 'Generating…' : 'Generate install command'}
            </button>
          </>
        )}
        {mintError && (
          <p role="alert" style={{ color: 'var(--consume)', fontSize: 13, margin: '12px 0 0', fontFamily: "'JetBrains Mono', monospace" }}>
            {mintError}
          </p>
        )}
      </Card>

      {/* Sign out */}
      <div style={{ ...card, display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '20px 24px' }}>
        <div>
          <div style={{ fontWeight: 600, fontSize: 15 }}>Sign out</div>
          <div style={{ fontSize: 13, color: 'var(--text-dim)', marginTop: 3 }}>
            End your session on this device.
          </div>
        </div>
        <button
          onClick={handleSignOut}
          style={{ background: 'transparent', border: '1px solid var(--border)', borderRadius: 10, padding: '10px 16px', color: 'var(--text)', fontFamily: 'inherit', fontWeight: 600, fontSize: 13, cursor: 'pointer' }}
        >
          Sign out ⏻
        </button>
      </div>

      <ColorKey />
    </div>
  );
}

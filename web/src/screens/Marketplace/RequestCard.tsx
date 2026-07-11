import React, { useState } from 'react';
import type { PublicRequest } from '@/domain/types';
import type { DonationSource } from '@/api/CtcApi';
import { pct, aiu } from '@/domain/credit';
import { Avatar } from '@/components/Avatar';
import { Badge } from '@/components/Badge';
import { UserLink } from '@/components/UserLink';
import { ProgressBar } from '@/components/ProgressBar';
import { Button } from '@/components/Button';

interface RequestCardProps {
  request: PublicRequest;
  /** Amount (AIU) the "Chip in" action contributes; shown on the button. */
  chipInAiu: number;
  onDonate: (id: string, amountAiu?: number, source?: DonationSource) => void;
  /** Fill this request from the shared pool (any request, own included). */
  onPoolFund?: (id: string, amountAiu?: number) => void;
  /** Owner cancels their own request. */
  onDelete?: (id: string) => void;
  /** Whether the shared pool is on and has credit to draw. */
  poolEnabled?: boolean;
  poolAvailable?: number;  // nano-AIU
  /** Viewer's chip-in sources (nano-AIU). When BOTH are positive, chipping in
   *  opens a source picker; a single source donates directly from it. */
  viewerPersonalRemaining?: number;
  viewerReceivedRemaining?: number;
}

function timeLabel(expiresAt: number, nowMs: number, status: PublicRequest['status']): string {
  if (status === 'fulfilled' || status === 'expired') return 'auto-closed';
  // expiresAt is epoch SECONDS on the wire; nowMs is Date.now() milliseconds.
  const hoursLeft = Math.max(0, Math.round((expiresAt * 1000 - nowMs) / 3_600_000));
  if (hoursLeft >= 24) return `${Math.round(hoursLeft / 24)}d left`;
  return `${hoursLeft}h left`;
}

export function RequestCard({
  request, chipInAiu, onDonate, onPoolFund, onDelete, poolEnabled, poolAvailable = 0,
  viewerPersonalRemaining = 0, viewerReceivedRemaining = 0,
}: RequestCardProps) {
  // Evaluate display-time freshly on each render so "Xh/Xd left" never goes
  // stale across reloads or long sessions. Tests freeze the api's clock, not
  // this one, but expired/fulfilled cards (which the tests cover) don't depend
  // on `now` since their label is derived from `status`.
  const now = Date.now();

  // Chip-in source picker: only when the viewer holds BOTH kinds of credit.
  // `pickerAmount` carries the amount the pending chip-in was started with.
  const needsSourcePicker = viewerPersonalRemaining > 0 && viewerReceivedRemaining > 0;
  const [pickerAmount, setPickerAmount] = useState<number | null>(null);
  const defaultSource: DonationSource = viewerPersonalRemaining > 0 ? 'personal' : 'received';

  function startChipIn(amountAiu: number) {
    if (needsSourcePicker) setPickerAmount(amountAiu);
    else onDonate(request.id, amountAiu, defaultSource);
  }
  function pickSource(source: DonationSource) {
    if (pickerAmount == null) return;
    setPickerAmount(null);
    onDonate(request.id, pickerAmount, source);
  }

  const {
    id,
    requesterId,
    requesterName,
    initials,
    requesterRole,
    amountNeeded,
    amountFunded,
    fundedConsumed,
    poolFunded,
    reason,
    target,
    expiresAt,
    status,
    donorCount,
    isOwn,
  } = request;

  const isFulfilled = status === 'fulfilled';
  const isExpired = status === 'expired';
  const isLive = status === 'open' || status === 'partially_funded';
  const isOpen = isLive && !isOwn;
  // Pool credit can only be routed onto your OWN request.
  const canPoolFund = isLive && isOwn && !!poolEnabled && poolAvailable > 0 && !!onPoolFund;
  const avatarTone = requesterRole === 'pro' ? 'give' : 'consume';
  const badgeTone = requesterRole === 'pro' ? 'give' : 'consume';
  const roleLabel = requesterRole === 'pro' ? 'Host' : 'Guest';
  const tLabel = timeLabel(expiresAt, now, status);
  const targetLabel = target ? `→ ${target}` : 'open to all';
  const donorLabel = `${donorCount} supporter${donorCount !== 1 ? 's' : ''}`;
  const statusLabel = isFulfilled ? 'covered' : isLive ? 'open' : status;
  const progress = pct(amountFunded, amountNeeded);
  // Receiver-progress: how much of the raised credit the requester has actually
  // burned. Shown once anything is funded — the key story on a closed card.
  const consumed = Math.min(fundedConsumed, amountFunded);
  const consumedPct = pct(consumed, amountFunded);
  const showConsumption = amountFunded > 0;

  const cardStyle: React.CSSProperties = {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 16,
    padding: '18px 20px',
    display: 'flex',
    flexDirection: 'column',
    gap: 14,
    // Dead cards (covered or expired) fade back so live requests stand out.
    opacity: isFulfilled ? 0.6 : isExpired ? 0.45 : 1,
  };

  return (
    <div style={cardStyle} data-request-card>
      {/* Header row: avatar + name/role + time/target */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <Avatar initials={initials} tone={avatarTone} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontWeight: 600, fontSize: 14 }}>
              {requesterId ? <UserLink userId={requesterId} name={requesterName} /> : requesterName}
            </span>
            <Badge tone={badgeTone}>{roleLabel}</Badge>
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 2 }}>{reason}</div>
        </div>
        <div style={{ textAlign: 'right', flexShrink: 0 }}>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: 'var(--text-faint)' }}>
            {tLabel}
          </div>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: 'var(--text-dim)', marginTop: 2 }}>
            {targetLabel}
          </div>
        </div>
      </div>

      {/* Progress row */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 7 }}>
          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>
            {aiu(amountFunded)} / {aiu(amountNeeded)}
          </span>
          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: 'var(--text-faint)' }}>
            {donorLabel} · {statusLabel}
          </span>
        </div>
        <ProgressBar pct={progress} color={isFulfilled ? 'var(--give)' : 'var(--accent)'} />
        {poolFunded > 0 && (
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: 'var(--pool)', marginTop: 6 }}>
            {aiu(poolFunded)} from the shared pool
          </div>
        )}
      </div>

      {/* Receiver-progress: how much of the raised credit has been used vs. left. */}
      {showConsumption && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: 'var(--consume)' }}>
              used by receiver
            </span>
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: 'var(--text-faint)' }}>
              {aiu(consumed)} / {aiu(amountFunded)} · {aiu(Math.max(0, amountFunded - consumed))} left
            </span>
          </div>
          <ProgressBar pct={consumedPct} color="var(--consume)" />
        </div>
      )}

      {/* Action row */}
      {(isOpen || (isLive && canPoolFund) || (isOwn && isLive && onDelete)) && (
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          {isOpen && pickerAmount == null && (
            <>
              <Button
                style={{
                  background: 'var(--accent-soft)',
                  color: 'var(--accent)',
                  border: '1px solid var(--accent)',
                  borderRadius: 9,
                  height: 36,
                  padding: '0 16px',
                  fontSize: 13,
                }}
                onClick={() => startChipIn(chipInAiu)}
              >
                Chip in {chipInAiu} →
              </Button>
              <Button
                variant="ghost"
                style={{
                  borderRadius: 9,
                  height: 36,
                  padding: '0 12px',
                  fontSize: 13,
                }}
                onClick={() => {
                  const raw = window.prompt(`Chip in how many credits?`, String(chipInAiu));
                  if (raw == null) return;
                  const n = Number(raw);
                  if (!Number.isFinite(n) || n <= 0) return;
                  startChipIn(n);
                }}
              >
                Custom…
              </Button>
            </>
          )}
          {isOpen && pickerAmount != null && (
            <div data-source-picker style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: 'var(--text-dim)' }}>
                Chip in {pickerAmount} from…
              </span>
              <Button
                variant="ghost"
                style={{ color: 'var(--own)', border: '1px solid var(--own)', borderRadius: 9, height: 36, padding: '0 12px', fontSize: 13 }}
                onClick={() => pickSource('personal')}
              >
                My credits · {aiu(viewerPersonalRemaining)} left
              </Button>
              <Button
                variant="ghost"
                style={{ color: 'var(--give)', border: '1px solid var(--give)', borderRadius: 9, height: 36, padding: '0 12px', fontSize: 13 }}
                onClick={() => pickSource('received')}
              >
                Routed to me · {aiu(viewerReceivedRemaining)} left
              </Button>
              <Button
                variant="ghost"
                style={{ borderRadius: 9, height: 36, padding: '0 10px', fontSize: 13, color: 'var(--text-faint)' }}
                onClick={() => setPickerAmount(null)}
              >
                ✕
              </Button>
            </div>
          )}
          {canPoolFund && (
            <Button
              variant="ghost"
              style={{
                color: 'var(--pool)',
                border: '1px solid var(--pool)',
                borderRadius: 9,
                height: 36,
                padding: '0 16px',
                fontSize: 13,
              }}
              onClick={() => {
                const raw = window.prompt(`Fill from the shared pool — how many credits?`, String(chipInAiu));
                if (raw == null) return;
                const n = Number(raw);
                if (!Number.isFinite(n) || n <= 0) return;
                onPoolFund!(id, n);
              }}
            >
              From pool →
            </Button>
          )}
          {isOwn && isLive && onDelete && (
            <Button
              variant="ghost"
              style={{
                color: 'var(--consume)',
                borderRadius: 9,
                height: 36,
                padding: '0 12px',
                fontSize: 13,
                marginLeft: 'auto',
              }}
              onClick={() => {
                if (window.confirm('Delete this request? Any unused chip-ins go back to their supporters.')) {
                  onDelete(id);
                }
              }}
            >
              Delete
            </Button>
          )}
        </div>
      )}
      {isFulfilled && (
        <span
          style={{
            alignSelf: 'flex-start',
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 12,
            color: 'var(--give)',
            background: 'var(--give-soft)',
            borderRadius: 9,
            padding: '8px 14px',
          }}
        >
          ✓ covered · auto-closed
        </span>
      )}
      {isExpired && (
        <span
          data-expired-pill
          style={{
            alignSelf: 'flex-start',
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 12,
            color: 'var(--text-faint)',
            background: 'var(--surface-2)',
            border: '1px dashed var(--border-strong)',
            borderRadius: 9,
            padding: '8px 14px',
          }}
        >
          ✕ expired · never covered
        </span>
      )}
      {isOwn && isLive && (
        <span
          style={{
            alignSelf: 'flex-start',
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 12,
            color: 'var(--text-faint)',
            background: 'var(--surface-2)',
            border: '1px solid var(--border)',
            borderRadius: 9,
            padding: '8px 14px',
          }}
        >
          your request
        </span>
      )}
    </div>
  );
}

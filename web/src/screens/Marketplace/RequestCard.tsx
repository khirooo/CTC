import React from 'react';
import type { PublicRequest } from '@/domain/types';
import { pct, aiu } from '@/domain/credit';
import { Avatar } from '@/components/Avatar';
import { Badge } from '@/components/Badge';
import { ProgressBar } from '@/components/ProgressBar';
import { Button } from '@/components/Button';

interface RequestCardProps {
  request: PublicRequest;
  onDonate: (id: string) => void;
}

function timeLabel(expiresAt: number, now: number, status: PublicRequest['status']): string {
  if (status === 'fulfilled' || status === 'expired') return 'auto-closed';
  const hoursLeft = Math.max(0, Math.round((expiresAt - now) / 3_600_000));
  if (hoursLeft >= 24) return `${Math.round(hoursLeft / 24)}d left`;
  return `${hoursLeft}h left`;
}

export function RequestCard({ request, onDonate }: RequestCardProps) {
  // Evaluate display-time freshly on each render so "Xh/Xd left" never goes
  // stale across reloads or long sessions. Tests freeze the api's clock, not
  // this one, but expired/fulfilled cards (which the tests cover) don't depend
  // on `now` since their label is derived from `status`.
  const now = Date.now();

  const {
    id,
    requesterName,
    initials,
    requesterRole,
    amountNeeded,
    amountFunded,
    reason,
    target,
    expiresAt,
    status,
    donorCount,
    isOwn,
  } = request;

  const isFulfilled = status === 'fulfilled';
  const isOpen = (status === 'open' || status === 'partially_funded') && !isOwn;
  const avatarTone = requesterRole === 'pro' ? 'reroute' : 'consume';
  const badgeTone = requesterRole === 'pro' ? 'reroute' : 'consume';
  const roleLabel = requesterRole === 'pro' ? 'Host' : 'Guest';
  const tLabel = timeLabel(expiresAt, now, status);
  const targetLabel = target ? `→ ${target}` : 'open to all';
  const donorLabel = `${donorCount} supporter${donorCount !== 1 ? 's' : ''}`;
  const statusLabel = isFulfilled ? 'covered' : isOpen ? 'open' : 'expired';
  const progress = pct(amountFunded, amountNeeded);

  const cardStyle: React.CSSProperties = {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 16,
    padding: '18px 20px',
    display: 'flex',
    flexDirection: 'column',
    gap: 14,
    opacity: isFulfilled ? 0.6 : 1,
  };

  return (
    <div style={cardStyle} data-request-card>
      {/* Header row: avatar + name/role + time/target */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <Avatar initials={initials} tone={avatarTone} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontWeight: 600, fontSize: 14 }}>{requesterName}</span>
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
      </div>

      {/* Action row */}
      {isOpen && (
        <Button
          style={{
            alignSelf: 'flex-start',
            background: 'var(--accent-soft)',
            color: 'var(--accent)',
            border: '1px solid var(--accent)',
            borderRadius: 9,
            height: 36,
            padding: '0 16px',
            fontSize: 13,
          }}
          onClick={() => onDonate(id)}
        >
          Chip in 25 →
        </Button>
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
      {isOwn && !isFulfilled && (
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

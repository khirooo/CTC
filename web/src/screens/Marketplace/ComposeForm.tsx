import React, { useEffect, useState } from 'react';
import type { CreateRequestInput, StandingEntry } from '@/domain/types';
import { NANO_PER_AIU } from '@/domain/credit';
import { Button } from '@/components/Button';
import { Field } from '@/components/Field';
import { Input } from '@/components/Input';
import { NumberInput } from '@/components/NumberInput';
import { config } from '@/domain/config';
import { useApp } from '@/store/AppContext';

interface ComposeFormProps {
  onSubmit: (input: CreateRequestInput) => Promise<void>;
  onCancel: () => void;
}

const EXPIRY_OPTIONS: { h: number; label: string }[] = [
  { h: 1, label: '1 hour' },
  { h: 6, label: '6 hours' },
  { h: 12, label: '12 hours' },
  { h: 24, label: '24 hours' },
  { h: 48, label: '2 days' },
  { h: 72, label: '3 days' },
  { h: 168, label: '1 week' },
];

export function ComposeForm({ onSubmit, onCancel }: ComposeFormProps) {
  const { api, session } = useApp();
  const [amount, setAmount] = useState(200);
  const [target, setTarget] = useState('open');
  const [reason, setReason] = useState('Finishing up a PR');
  // Clamp the expiry presets to the admin-set ceiling so we never offer (or
  // default to) a value the server will 422. Default = server default snapped
  // down to an available preset ≤ min(default, max).
  const maxHours = session?.requestExpiryMaxHours ?? EXPIRY_OPTIONS[EXPIRY_OPTIONS.length - 1].h;
  const expiryOptions = EXPIRY_OPTIONS.filter(o => o.h <= maxHours);
  const clampedDefault = Math.min(session?.requestExpiryHours ?? config.requestExpiryHours, maxHours);
  const defaultExpiry =
    [...expiryOptions].reverse().find(o => o.h <= clampedDefault)?.h ?? expiryOptions[0]?.h ?? 1;
  const [expiryHours, setExpiryHours] = useState<number>(defaultExpiry);
  const [submitting, setSubmitting] = useState(false);
  const [givers, setGivers] = useState<StandingEntry[]>([]);

  // The session (hence maxHours) arrives after first paint. If the seeded expiry
  // now exceeds the admin ceiling, snap it back down to a valid preset.
  useEffect(() => {
    setExpiryHours(prev => (prev <= maxHours ? prev : defaultExpiry));
    // defaultExpiry/maxHours derive from the same session field; key off maxHours.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [maxHours]);

  useEffect(() => {
    let cancelled = false;
    api.getLeaderboard().then(lb => {
      if (cancelled) return;
      // standings = all givers (active + newcomers); exclude self and any row
      // without a resolvable id (directed target is sent as a userId).
      const list = lb.standings.filter(s => s.userId && s.userId !== session?.userId);
      setGivers(list);
    }).catch(() => { /* keep dropdown with just "open to all" */ });
    return () => { cancelled = true; };
  }, [api, session?.userId]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await onSubmit({
        // The input is in human-readable AIU; the wire/storage unit is nano-AIU.
        amountNeeded: amount * NANO_PER_AIU,
        reason,
        target: target === 'open' ? null : target,
        expiryHours,
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      style={{
        background: 'var(--surface)',
        border: '1px solid var(--accent)',
        borderRadius: 16,
        padding: '20px 22px',
        display: 'flex',
        flexDirection: 'column',
        gap: 14,
      }}
    >
      <div style={{ fontWeight: 600, fontSize: 14 }}>New request</div>
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
        <Field label="Amount">
          <NumberInput
            min={1}
            value={amount}
            onChange={setAmount}
            style={{ width: 140 }}
          />
        </Field>
        <Field label="Ask">
          <select
            aria-label="Ask"
            value={target}
            onChange={e => setTarget(e.target.value)}
            style={{
              width: 220,
              background: 'var(--surface-2)',
              border: '1px solid var(--border)',
              borderRadius: 8,
              color: 'var(--text)',
              fontFamily: 'inherit',
              fontSize: 14,
              padding: '0 13px',
              height: 40,
              outline: 'none',
              cursor: 'pointer',
            }}
          >
            <option value="open">Open to all Hosts</option>
            {givers.map(g => (
              <option key={g.userId || g.name} value={g.userId}>{g.name}</option>
            ))}
          </select>
        </Field>
        <Field label="Reason">
          <Input
            type="text"
            value={reason}
            onChange={e => setReason(e.target.value)}
            style={{ flex: 1, minWidth: 200 }}
          />
        </Field>
        <Field label="Expires in">
          <select
            aria-label="Expires in"
            value={expiryHours}
            onChange={e => setExpiryHours(Number(e.target.value))}
            style={{
              width: 180,
              background: 'var(--surface-2)',
              border: '1px solid var(--border)',
              borderRadius: 8,
              color: 'var(--text)',
              fontFamily: 'inherit',
              fontSize: 14,
              padding: '0 13px',
              height: 40,
              outline: 'none',
              cursor: 'pointer',
            }}
          >
            {expiryOptions.map(o => (
              <option key={o.h} value={o.h}>{o.label}</option>
            ))}
          </select>
        </Field>
      </div>
      <div style={{ display: 'flex', gap: 10 }}>
        <Button type="submit" disabled={submitting}>
          Post request
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

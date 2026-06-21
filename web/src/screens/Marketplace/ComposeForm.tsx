import React, { useState } from 'react';
import type { CreateRequestInput } from '@/domain/types';
import { NANO_PER_AIU } from '@/domain/credit';
import { Button } from '@/components/Button';
import { Field } from '@/components/Field';
import { Input } from '@/components/Input';
import { config } from '@/domain/config';

interface ComposeFormProps {
  onSubmit: (input: CreateRequestInput) => Promise<void>;
  onCancel: () => void;
}

export function ComposeForm({ onSubmit, onCancel }: ComposeFormProps) {
  const [amount, setAmount] = useState(50);
  const [target, setTarget] = useState('open');
  const [reason, setReason] = useState('Finishing up a PR');
  const [expiryHours, setExpiryHours] = useState<number>(config.requestExpiryHours);
  const [submitting, setSubmitting] = useState(false);

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
          <Input
            type="number"
            min={1}
            value={amount}
            onChange={e => setAmount(Number(e.target.value))}
            style={{ width: 140 }}
          />
        </Field>
        <Field label="Ask">
          <select
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
            <option value="Yuki Tanaka">@yuki</option>
            <option value="Amine Tazi">@amine</option>
            <option value="Sofia Lindqvist">@sofia</option>
            <option value="Marco Bianchi">@marco</option>
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
            <option value={1}>1 hour</option>
            <option value={6}>6 hours</option>
            <option value={12}>12 hours</option>
            <option value={24}>24 hours</option>
            <option value={48}>2 days</option>
            <option value={72}>3 days</option>
            <option value={168}>1 week</option>
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

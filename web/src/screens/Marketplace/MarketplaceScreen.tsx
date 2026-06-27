import { useState } from 'react';
import { useApp } from '@/store/AppContext';
import { useAsync } from '@/store/useAsync';
import { CtcApiError } from '@/api/http';
import { RequestCard } from './RequestCard';
import { ComposeForm } from './ComposeForm';
import type { CreateRequestInput } from '@/domain/types';

type Filter = 'all' | 'pro' | 'noob';

const SEG_BASE: React.CSSProperties = {
  border: 'none',
  borderRadius: 8,
  padding: '6px 14px',
  fontFamily: 'inherit',
  fontWeight: 600,
  fontSize: 13,
  cursor: 'pointer',
};

const SEG_ACTIVE: React.CSSProperties = {
  background: 'var(--surface)',
  color: 'var(--text)',
  boxShadow: '0 1px 3px rgba(0,0,0,.15)',
};

const SEG_IDLE: React.CSSProperties = {
  background: 'transparent',
  color: 'var(--text-dim)',
};

export function MarketplaceScreen() {
  const { api, session } = useApp();
  const chipInAiu = session?.defaultChipInAiu ?? 25;
  const [filter, setFilter] = useState<Filter>('all');
  const [compose, setCompose] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const { data, error: loadError, reload } = useAsync(() => api.listRequests(filter), [filter]);

  const requests = data?.requests ?? [];
  const counts = data?.counts ?? { all: 0, pro: 0, noob: 0 };

  async function handleDonate(id: string) {
    setActionError(null);
    try {
      await api.donate(id, chipInAiu * 1_000_000_000);  // configured chip-in, AIU → nano-AIU
      reload();
    } catch (e) {
      setActionError(e instanceof CtcApiError ? e.message : 'Something went wrong — please try again.');
    }
  }

  async function handlePost(input: CreateRequestInput) {
    setActionError(null);
    try {
      await api.createRequest(input);
      setCompose(false);
      reload();
    } catch (e) {
      setActionError(e instanceof CtcApiError ? e.message : 'Something went wrong — please try again.');
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16 }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 600, letterSpacing: '-0.01em' }}>Open requests</div>
          <div style={{ fontSize: 14, color: 'var(--text-dim)', marginTop: 4 }}>
            Out of credits? Post a request — surplus from Hosts finds you. Requests auto-close when covered.
          </div>
        </div>
        <button
          onClick={() => setCompose(v => !v)}
          style={{
            flexShrink: 0,
            background: 'var(--accent)',
            color: '#fff',
            border: 'none',
            borderRadius: 10,
            padding: '11px 16px',
            fontFamily: 'inherit',
            fontWeight: 600,
            fontSize: 14,
            cursor: 'pointer',
          }}
        >
          + Post a request
        </button>
      </div>

      {/* Filter segmented control */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{
          display: 'flex',
          background: 'var(--surface-2)',
          border: '1px solid var(--border)',
          borderRadius: 10,
          padding: 4,
          gap: 3,
        }}>
          <button
            onClick={() => setFilter('all')}
            style={{ ...SEG_BASE, ...(filter === 'all' ? SEG_ACTIVE : SEG_IDLE) }}
          >
            All · {counts.all}
          </button>
          <button
            onClick={() => setFilter('pro')}
            style={{ ...SEG_BASE, ...(filter === 'pro' ? SEG_ACTIVE : SEG_IDLE) }}
          >
            <span style={{ color: 'var(--reroute)' }}>●</span> Hosts · {counts.pro}
          </button>
          <button
            onClick={() => setFilter('noob')}
            style={{ ...SEG_BASE, ...(filter === 'noob' ? SEG_ACTIVE : SEG_IDLE) }}
          >
            <span style={{ color: 'var(--consume)' }}>●</span> Guests · {counts.noob}
          </button>
        </div>
      </div>

      {/* Load error */}
      {!!loadError && (
        <p
          role="alert"
          style={{
            color: 'var(--consume)',
            fontSize: 13,
            margin: '0',
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          {loadError instanceof CtcApiError ? loadError.message : 'Failed to load requests — please try again.'}
        </p>
      )}

      {/* Action error */}
      {actionError && (
        <p
          role="alert"
          style={{
            color: 'var(--consume)',
            fontSize: 13,
            margin: '0',
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          {actionError}
        </p>
      )}

      {/* Compose form */}
      {compose && (
        <ComposeForm
          onSubmit={handlePost}
          onCancel={() => setCompose(false)}
        />
      )}

      {/* Request grid */}
      {requests.length > 0 ? (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          {requests.map(r => (
            <RequestCard
              key={r.id}
              request={r}
              chipInAiu={chipInAiu}
              onDonate={handleDonate}
            />
          ))}
        </div>
      ) : (
        data && (
          <div style={{
            border: '1px dashed var(--border-strong)',
            borderRadius: 16,
            padding: 36,
            textAlign: 'center',
            color: 'var(--text-faint)',
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 13,
          }}>
            No requests from this group right now.
          </div>
        )
      )}
    </div>
  );
}

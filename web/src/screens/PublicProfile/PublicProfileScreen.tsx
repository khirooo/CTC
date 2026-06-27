import { useParams, Navigate } from 'react-router-dom';
import { useApp } from '@/store/AppContext';
import { useAsync } from '@/store/useAsync';
import { aiu } from '@/domain/credit';
import { TierBadge } from '@/components/TierBadge';
import { Avatar } from '@/components/Avatar';

export function PublicProfileScreen() {
  const { id } = useParams<{ id: string }>();
  const { api, session } = useApp();

  // Redirect own profile to the editable profile screen
  if (id && session && id === session.userId) {
    return <Navigate to="/app/profile" replace />;
  }

  const { data: p, loading, error } = useAsync(() => api.getUserProfile(id!), [id]);

  if (loading) {
    return <div style={{ padding: 40, color: 'var(--text-faint)' }}>Loading…</div>;
  }
  if (error || !p) {
    return (
      <div style={{ padding: 40, color: 'var(--text-dim)' }}>
        We couldn't find that user.
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 560 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <Avatar initials={p.initials} size={56} />
        <div>
          <div style={{ fontSize: 20, fontWeight: 700 }}>{p.name}</div>
          <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>
            @{p.login} · {p.role}
          </div>
          {p.tier && (
            <div style={{ marginTop: 6 }}>
              <TierBadge tier={p.tier} />
            </div>
          )}
        </div>
      </div>
      {p.role === 'giver' && (
        <div style={{ display: 'flex', gap: 24 }}>
          <Stat label="Net this cycle" value={p.net != null ? aiu(p.net) : '—'} />
          <Stat label="Donated" value={p.donated != null ? aiu(p.donated) : '—'} />
          <Stat
            label="Donations made"
            value={p.donationsMade != null ? String(p.donationsMade) : '—'}
          />
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div
        style={{
          fontSize: 11,
          letterSpacing: '0.1em',
          textTransform: 'uppercase',
          color: 'var(--text-faint)',
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 16,
          fontWeight: 600,
          fontFamily: "'JetBrains Mono', monospace",
        }}
      >
        {value}
      </div>
    </div>
  );
}

import { useNavigate } from 'react-router-dom';
import { useApp } from '@/store/AppContext';
import { useAsync } from '@/store/useAsync';
import { MarketplaceHero } from './MarketplaceHero';
import { StatTile } from '@/components';
import { aiu, euros } from '@/domain/credit';
import { PatHelp } from '@/components/PatHelp';
import { UserLink } from '@/components/UserLink';

const kindColor: Record<string, string> = {
  donate: 'var(--give)',
  request: 'var(--accent)',
  fulfill: 'var(--give)',
  rotate: 'var(--reroute)',
};

// Display labels for activity kinds (data values stay donate/fulfill/rotate).
const kindLabel: Record<string, string> = {
  donate: 'chip-in',
  request: 'request',
  fulfill: 'covered',
  rotate: 'route',
};

export function DashboardScreen() {
  const { api, session } = useApp();
  const navigate = useNavigate();
  const { data, loading } = useAsync(() => api.getDashboard(), []);

  if (loading || !data) {
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

  // givers_only mode + no PAT → block with license CTA
  if (session?.participantsMode === 'givers_only' && !session?.hasPat) {
    return (
      <div style={{ maxWidth: 520, margin: '60px auto', padding: '0 16px' }}>
        <div
          style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 16,
            padding: '28px 28px 24px',
          }}
        >
          <div style={{ fontWeight: 600, fontSize: 18, marginBottom: 8 }}>Add a license to continue</div>
          <p style={{ fontSize: 13, color: 'var(--text-dim)', marginBottom: 20, lineHeight: 1.6 }}>
            This deployment is configured for license holders only. Connect your Copilot license (GitHub Enterprise PAT) in your profile to access the dashboard.
          </p>
          <PatHelp />
          <button
            onClick={() => navigate('/app/profile')}
            style={{
              marginTop: 18,
              background: 'var(--accent)',
              color: '#fff',
              border: 'none',
              borderRadius: 10,
              padding: '11px 22px',
              fontFamily: 'inherit',
              fontWeight: 600,
              fontSize: 13,
              cursor: 'pointer',
            }}
          >
            Go to Profile →
          </button>
        </div>
      </div>
    );
  }

  const topConsumers = data.leaderboardSnapshot.topConsumers;
  const generous = data.leaderboardSnapshot.generous;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 22 }}>
      {/* Marketplace flow hero */}
      <MarketplaceHero data={data} closedCount={data.closedCount} activeNonPatCount={data.activeConsumers} />

      {/* Secondary stat row */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: 16,
        }}
      >
        <StatTile
          label="Chipped in this week"
          value={
            <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>
              {aiu(data.donatedThisWeek)}{' '}
              <span style={{ fontSize: 12, color: 'var(--give)' }}>≈ {euros(data.donatedThisWeek, session?.creditToEuroRate)}</span>
            </span>
          }
        />
        <StatTile
          label="Fulfillment rate"
          value={
            <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>
              {data.fulfillmentRate}%
            </span>
          }
          sub={
            <div
              style={{
                height: 5,
                borderRadius: 3,
                background: 'var(--surface-3)',
                overflow: 'hidden',
                marginTop: 4,
              }}
            >
              <div
                style={{
                  height: '100%',
                  width: `${data.fulfillmentRate}%`,
                  background: 'var(--give)',
                }}
              />
            </div>
          }
        />
        <StatTile
          label="Active Hosts"
          value={
            <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>
              {data.activeGivers}
            </span>
          }
        />
        <StatTile
          label="Active Guests"
          value={
            <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>
              {data.activeConsumers}
            </span>
          }
        />
      </div>

      {/* Activity + Leaderboard snapshot */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.55fr 1fr', gap: 16 }}>
        {/* Activity log */}
        <div
          style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 16,
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '16px 20px',
              borderBottom: '1px solid var(--border)',
            }}
          >
            <span style={{ fontWeight: 600, fontSize: 14 }}>Marketplace activity</span>
            <span
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 11,
                color: 'var(--text-faint)',
              }}
            >
              live
            </span>
          </div>
          <div
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 12.5,
              lineHeight: 1,
            }}
          >
            {data.activity.length === 0 ? (
              <div style={{ padding: '20px', color: 'var(--text-faint)', textAlign: 'center' }}>
                No activity yet
              </div>
            ) : (
              data.activity.map((entry, i) => (
                <div
                  key={i}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '64px 74px 1fr auto',
                    gap: 12,
                    padding: '11px 20px',
                    borderBottom: i < data.activity.length - 1 ? '1px solid var(--border)' : 'none',
                    alignItems: 'center',
                  }}
                >
                  <span style={{ color: 'var(--text-faint)' }}>{entry.time}</span>
                  <span style={{ color: kindColor[entry.kind] ?? 'var(--text-dim)' }}>
                    {kindLabel[entry.kind] ?? entry.kind}
                  </span>
                  <span style={{ color: 'var(--text-dim)' }}>
                    {entry.actorId ? <UserLink userId={entry.actorId}>{entry.detail}</UserLink> : entry.detail}
                  </span>
                  <span style={{ color: kindColor[entry.kind] ?? 'var(--text-dim)' }}>
                    {entry.amount}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Leaderboard snapshot */}
        <div
          style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 16,
            padding: '18px 20px',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: 14,
            }}
          >
            <span style={{ fontWeight: 600, fontSize: 14 }}>Leaderboard</span>
            <span
              onClick={() => navigate('/app/leaderboard')}
              style={{
                fontSize: 12,
                color: 'var(--accent)',
                cursor: 'pointer',
                fontWeight: 600,
              }}
            >
              View all →
            </span>
          </div>

          {/* Most generous */}
          <div
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 10,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              color: 'var(--give)',
              marginBottom: 8,
            }}
          >
            Most generous
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 9, marginBottom: 18 }}>
            {generous.slice(0, 3).map((entry, i) => (
              <div
                key={entry.name}
                style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13 }}
              >
                <span
                  style={{
                    color: i === 0 ? 'var(--give)' : 'var(--text-faint)',
                    fontFamily: "'JetBrains Mono', monospace",
                    width: 14,
                  }}
                >
                  {i + 1}
                </span>
                <span style={{ flex: 1 }}><UserLink userId={entry.userId} name={entry.name} /></span>
                <span
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    color: 'var(--give)',
                  }}
                >
                  {aiu(entry.value)}
                </span>
              </div>
            ))}
            {generous.length === 0 && (
              <div style={{ color: 'var(--text-faint)', fontSize: 12 }}>No data yet</div>
            )}
          </div>

          {/* Top consumers */}
          <div
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 10,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              color: 'var(--consume)',
              marginBottom: 8,
            }}
          >
            Top users
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
            {topConsumers.slice(0, 3).map((entry, i) => (
              <div
                key={entry.name}
                style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13 }}
              >
                <span
                  style={{
                    color: i === 0 ? 'var(--consume)' : 'var(--text-faint)',
                    fontFamily: "'JetBrains Mono', monospace",
                    width: 14,
                  }}
                >
                  {i + 1}
                </span>
                <span style={{ flex: 1 }}><UserLink userId={entry.userId} name={entry.name} /></span>
                <span
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    color: 'var(--consume)',
                  }}
                >
                  {aiu(entry.value)}
                </span>
              </div>
            ))}
            {topConsumers.length === 0 && (
              <div style={{ color: 'var(--text-faint)', fontSize: 12 }}>No data yet</div>
            )}
          </div>

        </div>
      </div>
    </div>
  );
}

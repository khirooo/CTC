import { useNavigate } from 'react-router-dom';
import { useApp } from '@/store/AppContext';
import { useAsync } from '@/store/useAsync';
import { ScreenStatus } from '@/components/ScreenStatus';
import { MarketplaceHero } from './MarketplaceHero';
import { SetupChecklist } from './SetupChecklist';
import { StatTile, InfoTip } from '@/components';
import { credits, euros } from '@/domain/credit';
import { PatHelp } from '@/components/PatHelp';
import { UserLink } from '@/components/UserLink';
import { LeaderRow } from '@/components/LeaderRow';

const kindColor: Record<string, string> = {
  // live consumption feed
  grant: 'var(--give)',      // used a directed marketplace chip-in
  pool: 'var(--pool)',    // drew from the shared pool
  // legacy demo kinds
  donate: 'var(--give)',
  request: 'var(--accent)',
  fulfill: 'var(--give)',
  rotate: 'var(--pool)',
};

// Display labels for activity kinds.
const kindLabel: Record<string, string> = {
  grant: 'chip-in',
  pool: 'pool',
  donate: 'chip-in',
  request: 'request',
  fulfill: 'covered',
  rotate: 'route',
};

export function DashboardScreen() {
  const { api, session } = useApp();
  const navigate = useNavigate();
  const { data, loading, error } = useAsync(() => api.getDashboard(), []);

  if (loading) return <ScreenStatus message="Loading…" />;
  if (error || !data) {
    return <ScreenStatus message="Couldn't load your overview. Refresh to try again." tone="dim" />;
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
      {/* Persistent "Finish setting up" checklist — renders null once done/dismissed */}
      <SetupChecklist />

      {/* Cycle banner — current cycle number/label + reset countdown */}
      <CycleBanner
        cycleNumber={data.cycleNumber}
        cycleLabel={data.cycleLabel}
        daysLeft={data.daysLeft}
        resetDate={data.resetDate}
      />

      {/* Marketplace flow hero */}
      <div data-tour="marketplace-hero">
        <MarketplaceHero data={data} />
      </div>

      {/* Secondary stat row */}
      <div
        data-tour="stats"
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: 16,
        }}
      >
        <StatTile
          label={
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              Chipped in this week
              <InfoTip term="chipIn" />
            </span>
          }
          value={
            <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>
              {credits(data.donatedThisWeek)}{' '}
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
            <span style={{ fontWeight: 600, fontSize: 14 }}>Live activity</span>
            <span
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 11,
                color: 'var(--text-faint)',
              }}
            >
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                <span style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--give)' }} /> chip-in
              </span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                <span style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--pool)' }} /> pool
              </span>
              <span>· 24h</span>
            </span>
          </div>
          <div
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 12.5,
              lineHeight: 1,
              maxHeight: 348,      // ~8 rows; older events scroll into view
              overflowY: 'auto',
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
              <LeaderRow
                key={entry.userId}
                rank={i + 1}
                userId={entry.userId}
                name={entry.name}
                value={credits(entry.value)}
                valueColor="var(--give)"
                rankColor={i === 0 ? 'var(--give)' : undefined}
                rankWidth={14}
                rankWeight={400}
                gap={10}
                rowFontSize={13}
                valueStyle={{ fontWeight: 400 }}
              />
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
              <LeaderRow
                key={entry.userId}
                rank={i + 1}
                userId={entry.userId}
                name={entry.name}
                value={credits(entry.value)}
                valueColor="var(--consume)"
                rankColor={i === 0 ? 'var(--consume)' : undefined}
                rankWidth={14}
                rankWeight={400}
                gap={10}
                rowFontSize={13}
                valueStyle={{ fontWeight: 400 }}
              />
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

/** Slim banner: which cycle we're in + how long until it resets. */
function CycleBanner({
  cycleNumber,
  cycleLabel,
  daysLeft,
  resetDate,
}: {
  cycleNumber: number;
  cycleLabel: string;
  daysLeft: number;
  resetDate: string | null;
}) {
  const resetPretty = resetDate
    ? new Date(resetDate + 'T00:00:00Z').toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
    : null;
  const countdown = daysLeft === 0 ? 'resets today' : `resets in ${daysLeft} day${daysLeft === 1 ? '' : 's'}`;
  return (
    <div
      data-tour="cycle-banner"
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 16,
        flexWrap: 'wrap',
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 14,
        padding: '12px 18px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
        <span
          style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 11,
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            color: 'var(--text-faint)',
          }}
        >
          Cycle
        </span>
        <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, fontSize: 18, color: 'var(--accent)' }}>
          #{cycleNumber}
        </span>
        {cycleLabel && (
          <span style={{ fontSize: 14, color: 'var(--text-dim)' }}>· {cycleLabel}</span>
        )}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontFamily: "'JetBrains Mono', monospace", fontSize: 12.5 }}>
        <span style={{ color: daysLeft <= 3 ? 'var(--consume)' : 'var(--text)' }}>{countdown}</span>
        {resetPretty && <span style={{ color: 'var(--text-faint)' }}>· {resetPretty}</span>}
      </div>
    </div>
  );
}

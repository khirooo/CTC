import { useApp } from '@/store/AppContext';
import { useAsync } from '@/store/useAsync';
import { aiu } from '@/domain/credit';
import type { LeaderboardEntry } from '@/domain/types';
import { TierBadge } from '@/components/TierBadge';
import { UserLink } from '@/components/UserLink';

interface TrackConfig {
  label: string;
  subtitle: string;
  icon: string;
  color: string;
  softColor: string;
  entries: LeaderboardEntry[];
}

function TrackCard({ label, subtitle, icon, color, softColor, entries }: TrackConfig) {
  const max = entries[0]?.value ?? 1;
  return (
    <div
      style={{
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 16,
        padding: '22px 24px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20 }}>
        <span
          style={{
            width: 30,
            height: 30,
            borderRadius: 8,
            background: softColor,
            color,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 15,
          }}
        >
          {icon}
        </span>
        <div>
          <div style={{ fontWeight: 600, fontSize: 15 }}>{label}</div>
          <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>{subtitle}</div>
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 15 }}>
        {entries.map((entry, i) => (
          <div key={entry.name} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontWeight: 600,
                color: i === 0 ? color : 'var(--text-faint)',
                width: 16,
              }}
            >
              {i + 1}
            </span>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13.5, fontWeight: 600 }}><UserLink userId={entry.userId} name={entry.name} /></div>
              <div
                style={{
                  height: 5,
                  borderRadius: 3,
                  background: softColor,
                  overflow: 'hidden',
                  marginTop: 6,
                }}
              >
                <div
                  style={{
                    height: '100%',
                    width: `${Math.round((entry.value / max) * 100)}%`,
                    background: color,
                  }}
                />
              </div>
            </div>
            <span
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontWeight: 600,
                color,
              }}
            >
              {aiu(entry.value)}
            </span>
          </div>
        ))}
        {entries.length === 0 && (
          <div style={{ color: 'var(--text-faint)', fontSize: 12 }}>No data yet</div>
        )}
      </div>
    </div>
  );
}

export function LeaderboardScreen() {
  const { api } = useApp();
  const { data, loading } = useAsync(() => api.getLeaderboard(), []);

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

  const tracks: TrackConfig[] = [
    {
      label: 'Most generous',
      subtitle: 'most chipped in overall',
      icon: '♥',
      color: 'var(--give)',
      softColor: 'var(--give-soft)',
      entries: data.generous,
    },
    {
      label: 'Top Host (by usage)',
      subtitle: 'Host · most credit used',
      icon: '◆',
      color: 'var(--reroute)',
      softColor: 'var(--reroute-soft)',
      entries: data.topPro,
    },
    {
      label: 'Top Guest',
      subtitle: 'Guest · most credit used',
      icon: '▲',
      color: 'var(--consume)',
      softColor: 'var(--consume-soft)',
      entries: data.topNoob,
    },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div>
        <div style={{ fontSize: 18, fontWeight: 600, letterSpacing: '-0.01em' }}>Leaderboard</div>
        <div style={{ fontSize: 14, color: 'var(--text-dim)', marginTop: 4 }}>
          Who's hosting the most and using the most this cycle.
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16 }}>
        {tracks.map((track) => (
          <TrackCard key={track.label} {...track} />
        ))}
      </div>
      <div
        style={{
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 16,
          padding: '22px 24px',
        }}
      >
        <div style={{ fontWeight: 600, fontSize: 15, marginBottom: 4 }}>Standings</div>
        <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 18 }}>
          Net contribution this cycle — given minus taken. Nobody hides.
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {data.standings.map((s, i) => (
            <div key={s.name} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontWeight: 600,
                  color: 'var(--text-faint)',
                  width: 18,
                }}
              >
                {i + 1}
              </span>
              <span style={{ flex: 1, fontSize: 13.5, fontWeight: 600 }}><UserLink userId={s.userId} name={s.name} /></span>
              <TierBadge tier={s.tier} />
              <span
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontWeight: 600,
                  width: 110,
                  textAlign: 'right',
                  color: s.net < 0 ? 'var(--consume)' : 'var(--give)',
                }}
              >
                {s.net >= 0 ? '+' : ''}{aiu(s.net)}
              </span>
            </div>
          ))}
          {data.standings.length === 0 && (
            <div style={{ color: 'var(--text-faint)', fontSize: 12 }}>No standings yet</div>
          )}
        </div>
      </div>
    </div>
  );
}

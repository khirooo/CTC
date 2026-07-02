import { useApp } from '@/store/AppContext';
import { useAsync } from '@/store/useAsync';
import { ScreenStatus } from '@/components/ScreenStatus';
import { aiu } from '@/domain/credit';
import type { LeaderboardEntry } from '@/domain/types';
import { TierBadge } from '@/components/TierBadge';
import { LeaderRow } from '@/components/LeaderRow';

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
          <LeaderRow
            key={entry.userId}
            rank={i + 1}
            userId={entry.userId}
            name={entry.name}
            value={aiu(entry.value)}
            valueColor={color}
            rankColor={i === 0 ? color : undefined}
            nameStyle={{ fontSize: 13.5, fontWeight: 600 }}
            bar={{ fraction: entry.value / max, color, track: softColor }}
          />
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
  const { data, loading, error } = useAsync(() => api.getLeaderboard(), []);

  if (loading) return <ScreenStatus message="Loading…" />;
  if (error || !data) {
    return <ScreenStatus message="Couldn't load the leaderboard. Refresh to try again." tone="dim" />;
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
            <LeaderRow
              key={s.userId}
              rank={i + 1}
              userId={s.userId}
              name={s.name}
              value={`${s.net >= 0 ? '+' : ''}${aiu(s.net)}`}
              valueColor={s.net < 0 ? 'var(--consume)' : 'var(--give)'}
              rankWidth={18}
              nameStyle={{ fontSize: 13.5, fontWeight: 600 }}
              trailing={<TierBadge tier={s.tier} />}
              valueStyle={{ width: 110, textAlign: 'right' }}
            />
          ))}
          {data.standings.length === 0 && (
            <div style={{ color: 'var(--text-faint)', fontSize: 12 }}>No standings yet</div>
          )}
        </div>
      </div>
    </div>
  );
}

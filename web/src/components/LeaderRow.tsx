import type { CSSProperties, ReactNode } from 'react';
import { UserLink } from './UserLink';

const mono = "'JetBrains Mono', monospace";

export interface LeaderRowProps {
  rank: number;
  userId: string;
  name: string;
  /** Preformatted value (e.g. `aiu(entry.value)` or `+1,000.00 AIU`). */
  value: ReactNode;
  valueColor?: string;
  /** Color for the rank number (callers pass the hue for rank 1, undefined otherwise). */
  rankColor?: string;
  rankWidth?: number;
  rankWeight?: number;
  gap?: number;
  /** Set the row's fontSize (Dashboard snapshot uses 13; leaderboard leaves it unset). */
  rowFontSize?: number;
  /** Extra style for the name wrapper (size/weight where the site set them). */
  nameStyle?: CSSProperties;
  /** Extra style for the value (weight/width/align where the site set them). */
  valueStyle?: CSSProperties;
  /** Underline progress bar under the name (leaderboard tracks). */
  bar?: { fraction: number; color: string; track: string };
  /** Trailing node before the value (e.g. a TierBadge in standings). */
  trailing?: ReactNode;
}

/**
 * Ranked "N · name · value" row shared by the Dashboard snapshot, the Leaderboard
 * tracks, and the Standings list. Styling is applied only where each original
 * site applied it, so swapping in this component is pixel-neutral.
 */
export function LeaderRow({
  rank, userId, name, value, valueColor,
  rankColor, rankWidth = 16, rankWeight = 600, gap = 12, rowFontSize,
  nameStyle, valueStyle, bar, trailing,
}: LeaderRowProps) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap, ...(rowFontSize ? { fontSize: rowFontSize } : {}) }}>
      <span style={{ fontFamily: mono, fontWeight: rankWeight, color: rankColor ?? 'var(--text-faint)', width: rankWidth }}>
        {rank}
      </span>
      <div style={{ flex: 1 }}>
        <div style={nameStyle}><UserLink userId={userId} name={name} /></div>
        {bar && (
          <div style={{ height: 5, borderRadius: 3, background: bar.track, overflow: 'hidden', marginTop: 6 }}>
            <div style={{ height: '100%', width: `${Math.round(bar.fraction * 100)}%`, background: bar.color }} />
          </div>
        )}
      </div>
      {trailing}
      <span style={{ fontFamily: mono, fontWeight: 600, color: valueColor, ...valueStyle }}>{value}</span>
    </div>
  );
}

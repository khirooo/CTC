import { useState } from 'react';
import { useApp } from '@/store/AppContext';
import { useAsync } from '@/store/useAsync';
import { ScreenStatus } from '@/components/ScreenStatus';
import type { CycleReport } from '@/domain/types';
import { CycleDetail } from './CycleDetail';

export function HistoryScreen() {
  const { api, session } = useApp();
  const { data, loading, error } = useAsync(() => api.getHistory(), []);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  if (loading) return <ScreenStatus message="Loading…" />;
  if (error || !data) {
    return <ScreenStatus message="Couldn't load your reports. Refresh to try again." tone="dim" />;
  }
  if (data.length === 0) {
    return <ScreenStatus message="No closed cycles yet — monthly reports appear here after the first cycle resets." tone="dim" />;
  }

  const activeId = selectedId ?? (data[0]?.id ?? null);
  const selected: CycleReport | undefined = data.find((m) => m.id === activeId) ?? data[0];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      {/* Header */}
      <div>
        <div style={{ fontSize: 18, fontWeight: 600, letterSpacing: '-0.01em' }}>Monthly reports</div>
        <div style={{ fontSize: 14, color: 'var(--text-dim)', marginTop: 4 }}>
          Every cycle resets on the 1st — here's the archive of closed months.
        </div>
      </div>

      {/* Master–detail: scrollable cycle list on the left, report on the right.
          The list scales to any number of cycles (scrolls past ~7 rows). */}
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <div
          style={{
            flex: '0 0 240px',
            minWidth: 220,
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 14,
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '13px 16px',
              borderBottom: '1px solid var(--border)',
            }}
          >
            <span style={{ fontWeight: 600, fontSize: 13 }}>Cycles</span>
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: 'var(--text-faint)' }}>
              {data.length}
            </span>
          </div>
          <div style={{ maxHeight: 460, overflowY: 'auto' }}>
            {data.map((month) => (
              <CycleListItem
                key={month.id}
                report={month}
                active={month.id === activeId}
                onSelect={() => setSelectedId(month.id)}
              />
            ))}
          </div>
        </div>

        <div style={{ flex: 1, minWidth: 320 }}>
          {selected && <CycleDetail report={selected} rate={session?.creditToEuroRate} />}
        </div>
      </div>
    </div>
  );
}

/** One row in the cycle list rail: month label + a compact fulfillment badge.
 *  Selected row gets an accent left-border and raised surface. */
function CycleListItem({
  report,
  active,
  onSelect,
}: {
  report: CycleReport;
  active: boolean;
  onSelect: () => void;
}) {
  const fillRate = Math.round((report.reqFilled / Math.max(1, report.reqTotal)) * 100);
  return (
    <button
      onClick={onSelect}
      aria-current={active ? 'true' : undefined}
      style={{
        display: 'flex',
        width: '100%',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 10,
        padding: '12px 16px',
        border: 'none',
        borderLeft: `3px solid ${active ? 'var(--accent)' : 'transparent'}`,
        borderBottom: '1px solid var(--border)',
        background: active ? 'var(--surface-2)' : 'transparent',
        color: active ? 'var(--text)' : 'var(--text-dim)',
        cursor: 'pointer',
        textAlign: 'left',
        fontFamily: 'inherit',
      }}
    >
      <span style={{ display: 'flex', flexDirection: 'column', gap: 3, minWidth: 0 }}>
        <span style={{ fontWeight: active ? 600 : 500, fontSize: 13.5, whiteSpace: 'nowrap' }}>{report.label}</span>
        <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: 'var(--text-faint)' }}>
          {report.reqFilled}/{report.reqTotal} covered
        </span>
      </span>
      <span
        style={{
          flex: 'none',
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 11,
          fontWeight: 600,
          color: active ? 'var(--give)' : 'var(--text-faint)',
        }}
      >
        {fillRate}%
      </span>
    </button>
  );
}

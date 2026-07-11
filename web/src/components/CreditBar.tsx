// web/src/components/CreditBar.tsx
export interface BarSegment {
  key: string; label: string; value: number; color: string;
  /** 'striped' = consumed/locked (diagonal hatch); undefined = solid (available/reserved). */
  pattern?: 'striped';
  opacity?: number;
}
export interface CreditBarProps {
  segments: BarSegment[];
  max: number;
  slider?: {
    value: number; min: number; max: number;
    onChange(v: number): void; onCommit(v: number): void;
    /** Fraction [0,1] where the handle's travel begins (end of the locked/fixed
     *  segments). Handle then bounces between pledge (orange) and left (blue). */
    trackStart?: number;
  };
}

/** Diagonal hatch fill for a "consumed/locked" segment — solid stripes of `color`
 *  alternating with a dim version blended into the track. Used by the legend
 *  swatch, where a bold, saturated key anchors each hue. */
export function stripedBg(color: string): string {
  const dim = `color-mix(in srgb, ${color} 32%, var(--surface-3))`;
  return `repeating-linear-gradient(45deg, ${color} 0 5px, ${dim} 5px 10px)`;
}

/** Tint of `color` over the track. Strong enough that the hue itself stays
 *  readable on the dark bg — at ≲30% every hue collapses into the same murk. */
function tintBg(color: string): string {
  return `color-mix(in srgb, ${color} 62%, transparent)`;
}

/** Hatch for a "consumed/locked" bar segment — same hue, visibly dimmer than solid. */
function tintHatch(color: string): string {
  const lo = `color-mix(in srgb, ${color} 48%, transparent)`;
  const hi = `color-mix(in srgb, ${color} 16%, transparent)`;
  return `repeating-linear-gradient(45deg, ${lo} 0 6px, ${hi} 6px 12px)`;
}

function segBackground(s: BarSegment): string {
  return s.pattern === 'striped' ? tintHatch(s.color) : tintBg(s.color);
}

export function CreditBar({ segments, max, slider }: CreditBarProps) {
  const safeMax = max > 0 ? max : 1;
  const total = segments.reduce((acc, x) => acc + Math.max(0, x.value), 0);
  const denom = Math.max(safeMax, total);
  const ts = slider ? Math.min(0.99, Math.max(0, slider.trackStart ?? 0)) : 0;
  return (
    <div style={{ position: 'relative', display: 'flex', height: 26, borderRadius: 8,
                  overflow: 'hidden', background: 'var(--bg)',
                  border: '1px solid var(--border)' }}>
      {segments.map((s, i) => (
        <div key={s.key} data-seg={s.key}
             style={{ flexBasis: `${(s.value / denom) * 100}%`,
                      background: segBackground(s), opacity: s.opacity ?? 1,
                      borderLeft: i > 0 ? '1px solid var(--border)' : undefined }} />
      ))}
      {slider && (
        <input type="range" className="credit-slider" min={slider.min} max={slider.max} value={slider.value}
          onChange={(e) => slider.onChange(Number(e.target.value))}
          onMouseUp={(e) => slider.onCommit(Number((e.target as HTMLInputElement).value))}
          onTouchEnd={(e) => slider.onCommit(Number((e.target as HTMLInputElement).value))}
          aria-label="Pledge amount"
          style={{ position: 'absolute', top: 0, bottom: 0,
                   left: `${ts * 100}%`, width: `${(1 - ts) * 100}%`, margin: 0,
                   cursor: 'pointer' }} />
      )}
    </div>
  );
}

export interface LegendItem { label: string; value: string; color: string; pattern?: 'striped'; }

/** Swatch legend rendered under a CreditBar. */
export function CreditLegend({ items }: { items: LegendItem[] }) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px 18px', marginTop: 12,
                  fontFamily: "'JetBrains Mono', monospace", fontSize: 12.5 }}>
      {items.map((it) => (
        <span key={it.label} style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
          <span style={{ width: 12, height: 12, borderRadius: 3, flexShrink: 0,
                         background: it.pattern === 'striped' ? stripedBg(it.color) : it.color,
                         border: '1px solid var(--border)' }} />
          <span style={{ color: 'var(--text)' }}>{it.label}</span>
          <span style={{ color: 'var(--text-faint)' }}>{it.value}</span>
        </span>
      ))}
    </div>
  );
}

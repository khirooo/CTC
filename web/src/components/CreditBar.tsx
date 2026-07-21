// web/src/components/CreditBar.tsx
import { useState } from 'react';
import type { CSSProperties } from 'react';
import { NANO_PER_AIU } from '../domain/credit';

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
          // Keyboard changes (arrow keys) fire onChange but never mouse/touch —
          // commit on key-up and on blur so keyboard edits actually persist (a11y).
          onKeyUp={(e) => slider.onCommit(Number((e.target as HTMLInputElement).value))}
          onBlur={(e) => slider.onCommit(Number((e.target as HTMLInputElement).value))}
          aria-label="Pledge amount"
          style={{ position: 'absolute', top: 0, bottom: 0,
                   left: `${ts * 100}%`, width: `${(1 - ts) * 100}%`, margin: 0,
                   cursor: 'pointer' }} />
      )}
    </div>
  );
}

/** Primary pledge control: preset chips (10/25/50/Max of the shareable slice) plus a
 *  type-in box, so setting a pledge no longer depends on discovering that the bar drags.
 *  All values are nano-AIU; percentages are taken of `max` (the full shareable amount)
 *  and clamped into [min, max]. `onChange` previews, `onCommit` persists — same contract
 *  as the CreditBar slider, so the bar below stays in sync (and draggable as a bonus). */
export function PledgePresets({
  value, min, max, onChange, onCommit, percents = [0.10, 0.25, 0.50],
}: {
  value: number; min: number; max: number;
  onChange(v: number): void; onCommit(v: number): void;
  /** Fractions of the shareable slice offered as quick-pick chips; "Max" is
   *  always appended. Defaults to 10/25/50; the admin control passes 20/50/70. */
  percents?: number[];
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const base = Math.max(0, max);
  const clamp = (n: number) => Math.min(max, Math.max(min, Math.round(n)));

  const presets = [
    ...percents.map((f) => ({ label: `${Math.round(f * 100)}%`, nano: clamp(base * f) })),
    { label: 'Max', nano: clamp(base) },
  ];

  function set(nano: number) {
    onChange(nano);
    onCommit(nano);
    setDraft(null);
  }

  function commitDraft(raw: string) {
    const n = Number(raw);
    setDraft(null);
    if (!Number.isFinite(n)) return;
    set(clamp(n * NANO_PER_AIU));
  }

  const chip = (active: boolean): CSSProperties => ({
    fontFamily: "'JetBrains Mono', monospace", fontSize: 12.5, lineHeight: 1,
    padding: '7px 13px', borderRadius: 8, cursor: 'pointer',
    border: `1px solid ${active ? 'var(--pool)' : 'var(--border)'}`,
    background: active ? 'var(--pool-soft)' : 'transparent',
    color: active ? 'var(--text)' : 'var(--text-dim)',
  });

  const inputVal = draft ?? String(+(value / NANO_PER_AIU).toFixed(2));

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, margin: '4px 0 12px' }}>
      {presets.map((p) => (
        <button key={p.label} type="button" onClick={() => set(p.nano)}
                style={chip(Math.round(value) === p.nano)}>
          {p.label}
        </button>
      ))}
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginLeft: 4 }}>
        <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: 'var(--text-faint)' }}>or</span>
        <input type="number" min={min / NANO_PER_AIU} max={max / NANO_PER_AIU} step={1}
          value={inputVal}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={(e) => commitDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
          aria-label="Pledge amount in AIU"
          style={{ width: 78, textAlign: 'right', fontFamily: "'JetBrains Mono', monospace",
                   fontSize: 12.5, padding: '6px 8px', borderRadius: 8,
                   border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)' }} />
        <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: 'var(--text-faint)' }}>AIU</span>
      </span>
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

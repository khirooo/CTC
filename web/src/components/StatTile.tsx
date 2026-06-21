import React from 'react';

interface StatTileProps {
  label: React.ReactNode;
  value: React.ReactNode;
  sub?: React.ReactNode;
  delta?: React.ReactNode;
}

export function StatTile({ label, value, sub, delta }: StatTileProps) {
  return (
    <div
      style={{
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 12,
        padding: '16px 20px',
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
      }}
    >
      <span
        style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 11,
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
          color: 'var(--text-faint)',
        }}
      >
        {label}
      </span>
      <span style={{ fontSize: 22, fontWeight: 700, color: 'var(--text)' }}>{value}</span>
      {sub !== undefined && (
        <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>{sub}</span>
      )}
      {delta !== undefined && (
        <span style={{ fontSize: 12, color: 'var(--give)', marginTop: 4 }}>{delta}</span>
      )}
    </div>
  );
}

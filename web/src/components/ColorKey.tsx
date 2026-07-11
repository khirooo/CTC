/** One-line legend for the app-wide color contract (see theme/globals.css).
    Blue = your credits · purple = shared pool · teal = Hosts & giving · rose = Guests. */
const KEY_ITEMS = [
  { color: 'var(--own)', label: 'your credits' },
  { color: 'var(--pool)', label: 'shared pool' },
  { color: 'var(--give)', label: 'Hosts & chip-ins' },
  { color: 'var(--consume)', label: 'Guests' },
];

export function ColorKey() {
  return (
    <div
      data-color-key
      style={{
        display: 'flex',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: 14,
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 11,
        color: 'var(--text-faint)',
      }}
    >
      {KEY_ITEMS.map(({ color, label }) => (
        <span key={label} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <span style={{ width: 7, height: 7, borderRadius: '50%', background: color, flex: 'none' }} />
          {label}
        </span>
      ))}
    </div>
  );
}

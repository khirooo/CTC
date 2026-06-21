// web/src/components/CopyButton.tsx
import { useState } from 'react';

export function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  async function onClick() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // non-secure context / no clipboard API
      setCopied(false);
      window.prompt('Copy the command:', text);
    }
  }
  return (
    <button type="button" onClick={onClick} aria-label="Copy install command"
      style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, padding: '6px 10px',
               borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface-2)',
               color: copied ? 'var(--give)' : 'var(--text-dim)', cursor: 'pointer' }}>
      {copied ? 'Copied ✓' : label}
    </button>
  );
}

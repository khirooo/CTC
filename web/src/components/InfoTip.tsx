import { useEffect, useRef, useState } from 'react';
import { glossary, type GlossaryTerm } from '@/domain/glossary';

interface InfoTipProps {
  /** Glossary term to explain (preferred — keeps wording centralized). */
  term?: GlossaryTerm;
  /** Custom title/body for one-off explanations not in the glossary. */
  title?: string;
  body?: string;
  style?: React.CSSProperties;
}

/**
 * Small ⓘ trigger with an accessible popover. Opens on hover, focus, or
 * click/tap; closes on Escape, blur, mouse-leave, or outside click.
 */
export function InfoTip({ term, title, body, style }: InfoTipProps) {
  const entry = term ? glossary[term] : { title: title ?? '', body: body ?? '' };
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    function onDocClick(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onDocClick);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onDocClick);
    };
  }, [open]);

  return (
    <span
      ref={rootRef}
      style={{ position: 'relative', display: 'inline-flex', ...style }}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        aria-label={`About ${entry.title}`}
        onClick={() => setOpen(true)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        style={{
          background: 'none',
          border: 'none',
          padding: 0,
          margin: 0,
          cursor: 'help',
          color: 'var(--text-faint)',
          fontSize: 12,
          lineHeight: 1,
          fontFamily: 'inherit',
          display: 'inline-flex',
          alignItems: 'center',
        }}
      >
        ⓘ
      </button>
      {open && (
        <span
          role="tooltip"
          style={{
            position: 'absolute',
            bottom: '100%',
            left: '50%',
            transform: 'translate(-50%, -6px)',
            zIndex: 60,
            width: 240,
            background: 'var(--surface)',
            border: '1px solid var(--border-strong)',
            borderRadius: 10,
            boxShadow: 'var(--shadow)',
            padding: '10px 12px',
            textAlign: 'left',
          }}
        >
          <span style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--text)', marginBottom: 3 }}>
            {entry.title}
          </span>
          <span style={{ display: 'block', fontSize: 12, lineHeight: 1.55, color: 'var(--text-dim)', fontWeight: 400 }}>
            {entry.body}
          </span>
        </span>
      )}
    </span>
  );
}

import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { glossary, type GlossaryTerm } from '@/domain/glossary';

interface InfoTipProps {
  /** Glossary term to explain (preferred — keeps wording centralized). */
  term?: GlossaryTerm;
  /** Custom title/body for one-off explanations not in the glossary. */
  title?: string;
  body?: string;
  style?: React.CSSProperties;
}

const POPOVER_WIDTH = 240;
const VIEWPORT_MARGIN = 8;

interface PopoverPosition {
  bottom: number;
  left: number;
}

/**
 * Small ⓘ trigger with an accessible popover. Opens on hover, focus, or
 * click/tap; closes on Escape, blur, mouse-leave, or outside click.
 *
 * The popover is portaled to `document.body` with `position: fixed` so it
 * can't be clipped by an ancestor's `overflow: hidden` or trapped under a
 * sibling's stacking context (e.g. the dashboard's Live-activity card).
 */
export function InfoTip({ term, title, body, style }: InfoTipProps) {
  const entry = term ? glossary[term] : { title: title ?? '', body: body ?? '' };
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<PopoverPosition | null>(null);
  const rootRef = useRef<HTMLSpanElement>(null);
  const popoverRef = useRef<HTMLSpanElement>(null);

  function openAt() {
    const rect = rootRef.current?.getBoundingClientRect();
    if (rect) {
      const center = rect.left + rect.width / 2;
      const left = Math.min(
        Math.max(center, VIEWPORT_MARGIN + POPOVER_WIDTH / 2),
        window.innerWidth - VIEWPORT_MARGIN - POPOVER_WIDTH / 2,
      );
      setPosition({
        bottom: window.innerHeight - rect.top + 6,
        left,
      });
    }
    setOpen(true);
  }

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    function onDocClick(e: MouseEvent) {
      const target = e.target as Node;
      const insideRoot = rootRef.current && rootRef.current.contains(target);
      const insidePopover = popoverRef.current && popoverRef.current.contains(target);
      if (!insideRoot && !insidePopover) setOpen(false);
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
      onMouseEnter={openAt}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        aria-label={`About ${entry.title}`}
        onClick={openAt}
        onFocus={openAt}
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
      {open &&
        position &&
        createPortal(
          <span
            ref={popoverRef}
            role="tooltip"
            style={{
              position: 'fixed',
              bottom: position.bottom,
              left: position.left,
              transform: 'translateX(-50%)',
              zIndex: 60,
              width: POPOVER_WIDTH,
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
          </span>,
          document.body,
        )}
    </span>
  );
}

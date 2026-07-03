import { useEffect, useState } from 'react';
import { TOUR_STEPS, type TourStep } from '@/app/tourSteps';

interface TourProps {
  open: boolean;
  /** Called when the tour finishes or is skipped. Caller persists tourDone. */
  onClose: () => void;
}

/**
 * First-run spotlight tour. Dims the page, highlights one data-tour target at
 * a time, and shows a positioned card with Back/Next/Skip. Steps whose target
 * is not in the DOM (e.g. checklist dismissed) are skipped. Hand-rolled — no
 * tour library (global constraint: no new dependencies).
 */
export function Tour({ open, onClose }: TourProps) {
  // Resolve which steps actually have targets. Computed in an effect (not
  // render/useMemo) because the anchors this queries for may be siblings
  // mounting in the very same commit as this component — querying the DOM
  // during render can run before React has painted those siblings.
  const [steps, setSteps] = useState<Array<TourStep & { el: Element }>>([]);
  const [idx, setIdx] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);

  useEffect(() => {
    if (!open) {
      setSteps([]);
      return;
    }
    setIdx(0);
    const resolved = TOUR_STEPS.flatMap((s) => {
      const el = document.querySelector(`[data-tour="${s.target}"]`);
      return el ? [{ ...s, el }] : [];
    });
    // No usable targets at all — close instead of leaving the caller stuck
    // with a tourOpen=true that never renders anything.
    if (resolved.length === 0) {
      onClose();
      return;
    }
    setSteps(resolved);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const step = steps[idx];

  useEffect(() => {
    if (!open || !step) return;
    function measure() {
      setRect(step.el.getBoundingClientRect());
    }
    step.el.scrollIntoView?.({ block: 'nearest' });
    measure();
    window.addEventListener('resize', measure);
    window.addEventListener('scroll', measure, true);
    return () => {
      window.removeEventListener('resize', measure);
      window.removeEventListener('scroll', measure, true);
    };
  }, [open, step]);

  if (!open || !step || !rect) {
    return null;
  }

  const pad = 8;
  const last = idx === steps.length - 1;
  // Card below the target when there's room, above otherwise.
  const below = rect.bottom + 190 < window.innerHeight;
  const cardTop = below ? rect.bottom + pad + 6 : undefined;
  const cardBottom = below ? undefined : window.innerHeight - rect.top + pad + 6;
  const cardLeft = Math.max(16, Math.min(rect.left, window.innerWidth - 336));

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 100 }}>
      {/* Backdrop with a spotlight cut-out via box-shadow trick */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed',
          top: rect.top - pad,
          left: rect.left - pad,
          width: rect.width + pad * 2,
          height: rect.height + pad * 2,
          borderRadius: 12,
          boxShadow: '0 0 0 9999px rgba(0,0,0,0.55)',
          border: '2px solid var(--accent)',
          pointerEvents: 'none',
        }}
      />
      {/* Click-catcher so the page underneath is inert during the tour */}
      <div onClick={(e) => e.stopPropagation()} style={{ position: 'fixed', inset: 0 }} />
      <div
        role="dialog"
        aria-label={step.title}
        style={{
          position: 'fixed',
          top: cardTop,
          bottom: cardBottom,
          left: cardLeft,
          width: 320,
          background: 'var(--surface)',
          border: '1px solid var(--border-strong)',
          borderRadius: 14,
          boxShadow: 'var(--shadow)',
          padding: '16px 18px',
        }}
      >
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 6 }}>{step.title}</div>
        <div style={{ fontSize: 13, lineHeight: 1.6, color: 'var(--text-dim)', marginBottom: 14, whiteSpace: 'pre-line' }}>{step.body}</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ display: 'flex', gap: 5 }}>
            {steps.map((_, i) => (
              <span key={i} style={{ width: 6, height: 6, borderRadius: '50%', background: i === idx ? 'var(--accent)' : 'var(--border-strong)' }} />
            ))}
          </span>
          <button type="button" onClick={onClose} style={{ marginLeft: 'auto', background: 'none', border: 'none', color: 'var(--text-faint)', fontFamily: 'inherit', fontSize: 12.5, cursor: 'pointer', padding: '6px 4px' }}>
            Skip tour
          </button>
          {idx > 0 && (
            <button type="button" onClick={() => setIdx(idx - 1)} style={{ background: 'none', border: '1px solid var(--border)', borderRadius: 8, color: 'var(--text-dim)', fontFamily: 'inherit', fontSize: 12.5, cursor: 'pointer', padding: '6px 12px' }}>
              Back
            </button>
          )}
          <button
            type="button"
            onClick={() => (last ? onClose() : setIdx(idx + 1))}
            style={{ background: 'var(--accent)', border: 'none', borderRadius: 8, color: '#fff', fontFamily: 'inherit', fontSize: 12.5, fontWeight: 600, cursor: 'pointer', padding: '6px 14px' }}
          >
            {last ? 'Done' : 'Next'}
          </button>
        </div>
      </div>
    </div>
  );
}

import type { CSSProperties } from 'react';

/**
 * Shared inline-style constants used across screens. These were copy-pasted into
 * Admin/Profile/PublicProfile/Onboarding; centralized here so the design stays in
 * one place. Sites that historically diverged keep an explicit local override
 * (e.g. `{ ...monoLabel, fontSize: 10 }`) so this consolidation is pixel-neutral.
 */

/** Uppercase mono caption above a value/field. Base size 11; PublicProfile uses 10. */
export const monoLabel: CSSProperties = {
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: 11,
  letterSpacing: '0.12em',
  textTransform: 'uppercase',
  color: 'var(--text-faint)',
};

/** Standard surface panel. */
export const card: CSSProperties = {
  background: 'var(--surface)',
  border: '1px solid var(--border)',
  borderRadius: 16,
  padding: 24,
};

/** Text/number field. Base padding matches Profile; Admin overrides to '9px 12px'. */
export const inputStyle: CSSProperties = {
  width: '100%',
  background: 'var(--surface-2)',
  border: '1px solid var(--border)',
  borderRadius: 10,
  padding: '11px 13px',
  color: 'var(--text)',
  fontFamily: 'inherit',
  fontSize: 14,
  outline: 'none',
};

import { useState, type CSSProperties } from 'react';

interface SecretInputProps {
  value: string;
  onChange(value: string): void;
  placeholder?: string;
  autoFocus?: boolean;
  /** Applied to the underlying <input>. */
  style?: CSSProperties;
  /** Applied to the wrapper (e.g. `flex: 1` to fill a flex row). */
  wrapperStyle?: CSSProperties;
  'aria-label'?: string;
}

/**
 * A password field for secrets (Copilot PATs). Masks the value by default,
 * disables browser autofill/autocorrect/spellcheck (so the crown-jewel token
 * isn't stored or shoulder-surfed), and offers a visibility toggle. Replaces the
 * old `type="text"` PAT inputs.
 */
export function SecretInput({
  value, onChange, placeholder, autoFocus, style, wrapperStyle, ...rest
}: SecretInputProps) {
  const [visible, setVisible] = useState(false);
  return (
    <div style={{ position: 'relative', display: 'flex', flex: 1, ...wrapperStyle }}>
      <input
        type={visible ? 'text' : 'password'}
        value={value}
        autoFocus={autoFocus}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        autoComplete="off"
        autoCorrect="off"
        autoCapitalize="off"
        spellCheck={false}
        aria-label={rest['aria-label']}
        style={{ flex: 1, width: '100%', boxSizing: 'border-box', paddingRight: 40, ...style }}
      />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        aria-label={visible ? 'Hide token' : 'Show token'}
        aria-pressed={visible}
        title={visible ? 'Hide token' : 'Show token'}
        style={{
          position: 'absolute', right: 4, top: 0, bottom: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          width: 32, background: 'transparent', border: 'none',
          color: 'var(--text-dim)', cursor: 'pointer', fontSize: 14, padding: 0,
        }}
      >
        {visible ? '🙈' : '👁'}
      </button>
    </div>
  );
}

import React, { useEffect, useRef, useState } from 'react';
import { Input } from './Input';

type NumberInputProps = Omit<
  React.InputHTMLAttributes<HTMLInputElement>,
  'value' | 'onChange' | 'type' | 'min' | 'max'
> & {
  value: number;
  onChange: (value: number) => void;
  /** Value emitted when the field is empty/invalid. Defaults to 0. */
  emptyValue?: number;
  /** Accept decimals (e.g. a EUR rate). Integers-only when false. */
  allowFloat?: boolean;
  /** Clamped on blur, when provided. */
  min?: number;
  max?: number;
};

/**
 * A controlled numeric field that holds the raw text the user is typing rather
 * than re-deriving it from the number every render. This avoids two long-standing
 * traps with `<input type="number" value={n} onChange={e => set(Number(e.target.value))}>`:
 *   - clearing the field produced `Number('') === 0`, so the `0` could never be
 *     deleted, and
 *   - a leading zero stuck around ("0" then "1" rendered as "01").
 * We emit a clean number on every valid keystroke and normalize the display on blur.
 */
export function NumberInput({
  value,
  onChange,
  emptyValue = 0,
  allowFloat = false,
  min,
  max,
  onBlur,
  ...rest
}: NumberInputProps) {
  const [draft, setDraft] = useState<string>(String(value));
  // Tracks the last number we emitted, so the resync effect can tell an external
  // value change apart from the echo of our own onChange.
  const lastEmitted = useRef<number>(value);

  useEffect(() => {
    if (value !== lastEmitted.current) {
      setDraft(String(value));
      lastEmitted.current = value;
    }
  }, [value]);

  const parse = (s: string) => (allowFloat ? parseFloat(s) : parseInt(s, 10));

  const emit = (n: number) => {
    lastEmitted.current = n;
    onChange(n);
  };

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    let raw = e.target.value;
    // Integers: drop leading zeros so "0"+"1" becomes "1", keeping a lone "0".
    if (!allowFloat) raw = raw.replace(/^(-?)0+(?=\d)/, '$1');
    setDraft(raw);
    if (raw === '' || raw === '-' || raw === '.') {
      emit(emptyValue);
      return;
    }
    const n = parse(raw);
    if (!Number.isNaN(n)) emit(n);
  }

  function handleBlur(e: React.FocusEvent<HTMLInputElement>) {
    let n = parse(draft);
    if (Number.isNaN(n)) n = emptyValue;
    if (min !== undefined && n < min) n = min;
    if (max !== undefined && n > max) n = max;
    setDraft(String(n));
    emit(n);
    onBlur?.(e);
  }

  return (
    <Input
      {...rest}
      type="text"
      inputMode={allowFloat ? 'decimal' : 'numeric'}
      value={draft}
      onChange={handleChange}
      onBlur={handleBlur}
    />
  );
}

import React from 'react';

type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

export function Input({ style, ...rest }: InputProps) {
  return (
    <input
      style={{
        width: '100%',
        background: 'var(--surface-2)',
        border: '1px solid var(--border)',
        borderRadius: 8,
        color: 'var(--text)',
        fontFamily: 'inherit',
        fontSize: 14,
        padding: '0 14px',
        height: 40,
        outline: 'none',
        ...style,
      }}
      {...rest}
    />
  );
}

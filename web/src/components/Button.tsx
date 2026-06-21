import React from 'react';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'ghost';
}

export function Button({ variant = 'primary', style, ...rest }: ButtonProps) {
  const base: React.CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    border: 'none',
    borderRadius: 8,
    fontFamily: 'inherit',
    fontWeight: 600,
    fontSize: 14,
    padding: '0 20px',
    height: 40,
    cursor: 'pointer',
    transition: 'opacity .15s',
  };

  const variantStyle: React.CSSProperties =
    variant === 'primary'
      ? { background: 'var(--accent)', color: '#fff' }
      : { background: 'transparent', color: 'var(--text-dim)', border: '1px solid var(--border)' };

  return (
    <button
      style={{ ...base, ...variantStyle, ...style }}
      {...rest}
    />
  );
}

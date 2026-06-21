import React from 'react';

/**
 * Dark-only theme. Light mode was removed — the design tokens live in :root
 * (see globals.css) and there is no runtime theme switching.
 *
 * Kept as a thin passthrough so existing imports (App, tests) keep working
 * without a separate provider.
 */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

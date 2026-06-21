import { useState, useEffect, useCallback, useRef } from 'react';

export interface AsyncState<T> {
  data: T | undefined;
  loading: boolean;
  error: unknown;
  reload(): void;
}

/**
 * Runs `fn` whenever `deps` change (or on reload()), guards against
 * state updates after unmount, and exposes a reload() to re-run.
 */
export function useAsync<T>(
  fn: () => Promise<T>,
  deps: unknown[],
): AsyncState<T> {
  const [data, setData] = useState<T | undefined>(undefined);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  // Bump counter to trigger re-runs without changing fn/deps identity
  const [revision, setRevision] = useState(0);

  // Keep a stable reference to fn so callers don't need to memoize it
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fnRef.current().then(
      (result) => {
        if (!cancelled) {
          setData(result);
          setLoading(false);
        }
      },
      (err) => {
        if (!cancelled) {
          setError(err);
          setLoading(false);
        }
      },
    );
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, revision]);

  const reload = useCallback(() => {
    setRevision((r) => r + 1);
  }, []);

  return { data, loading, error, reload };
}

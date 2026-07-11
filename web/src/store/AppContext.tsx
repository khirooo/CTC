import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useRef,
  useMemo,
  type ReactNode,
} from 'react';
import type { CtcApi } from '@/api/CtcApi';
import { HttpCtcApi } from '@/api/HttpCtcApi';
import type { Session } from '@/domain/types';

// The default api talks to the real control-plane. There is no mock backend in
// the shipped app — VITE_API_BASE must be set at build/dev time. (Tests inject a
// CtcApi via the `api` prop, so this is never constructed under test.)
function makeDefaultApi(): CtcApi {
  const base = import.meta.env.VITE_API_BASE as string | undefined;
  if (!base) {
    throw new Error(
      'VITE_API_BASE is required — set it to the control-plane /api base (no mock backend).',
    );
  }
  return new HttpCtcApi(base);
}

interface AppContextValue {
  /** undefined = bootstrap fetch still in flight; null = logged out. */
  session: Session | null | undefined;
  signIn(email: string, password: string): Promise<void>;
  signOut(): Promise<void>;
  api: CtcApi;
  refresh(): Promise<Session | null>;
}

const AppContext = createContext<AppContextValue | null>(null);

interface AppProviderProps {
  children: ReactNode;
  /** Pass a CtcApi instance (tests inject a fake) — defaults to the real HttpCtcApi. */
  api?: CtcApi;
  /** Seed the session synchronously (dev-preview harness / tests) so guarded
   *  routes render on first paint instead of after the async getSession resolves.
   *  Pass null to seed "logged out". Production leaves this out → session starts
   *  undefined ("still loading") until getSession resolves, so route guards can
   *  hold their redirect instead of bouncing a refreshed deep link to /. */
  initialSession?: Session | null;
}

export function AppProvider({ children, api: apiProp, initialSession }: AppProviderProps) {
  // Resolve the api once on first render and hand the same real CtcApi instance
  // to consumers — typed, referentially stable, methods callable with correct `this`.
  // The `api` prop does not change after mount in practice.
  const apiRef = useRef<CtcApi>(apiProp ?? makeDefaultApi());
  const api = apiRef.current;

  const [session, setSession] = useState<Session | null | undefined>(initialSession);
  // True when the mount-time getSession() rejected outright (control plane down,
  // VPN blip). Distinct from a clean logged-out result (session===null,
  // bootError===false): a rejection means we don't actually know the auth state,
  // so we show a retry panel instead of the landing page.
  const [bootError, setBootError] = useState(false);
  // Latest session in a ref so refresh() can preserve it on failure without
  // adding `session` to its dependency list (which would churn every consumer).
  const sessionRef = useRef<Session | null | undefined>(initialSession);
  sessionRef.current = session;

  // Restore session from the api on mount.
  // Cancelled guard prevents setState after unmount.
  useEffect(() => {
    let cancelled = false;
    api.getSession()
      .then((s) => {
        if (!cancelled) { setSession(s); setBootError(false); }
      })
      .catch(() => {
        // Fetch itself threw — treat as "unknown", not "logged out", and surface
        // a retry affordance rather than a permanently blank app.
        if (!cancelled) { setSession(null); setBootError(true); }
      });
    return () => {
      cancelled = true;
    };
  }, [api]);

  const refresh = useCallback(async (): Promise<Session | null> => {
    try {
      const s = await api.getSession();
      setSession(s);
      setBootError(false);
      return s;
    } catch {
      // Transient failure (e.g. right after a PAT save) — keep the current
      // session rather than blanking the app.
      return sessionRef.current ?? null;
    }
  }, [api]);

  const signIn = useCallback(
    async (email: string, password: string): Promise<void> => {
      // Real backend: OAuth redirect (args ignored, never resolves). Test fake:
      // `email` selects the seeded user to log in as.
      const s = await api.signIn(email, password);
      setSession(s);
    },
    [api],
  );

  const signOut = useCallback(async (): Promise<void> => {
    await api.signOut();
    setSession(null);
  }, [api]);

  const value: AppContextValue = useMemo(
    () => ({ session, signIn, signOut, api, refresh }),
    [session, signIn, signOut, api, refresh],
  );

  return (
    <AppContext.Provider value={value}>
      {bootError && session === null ? <BootErrorPanel onRetry={refresh} /> : children}
    </AppContext.Provider>
  );
}

/** Full-page fallback when the session bootstrap fetch fails outright (control
 *  plane unreachable). Retry re-runs getSession(); on success the app renders
 *  normally. Without this, a failed bootstrap left a permanently blank page. */
function BootErrorPanel({ onRetry }: { onRetry(): Promise<Session | null> }) {
  const [retrying, setRetrying] = useState(false);
  async function retry() {
    setRetrying(true);
    try {
      await onRetry();
    } finally {
      setRetrying(false);
    }
  }
  return (
    <div
      role="alert"
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 16,
        padding: 24,
        textAlign: 'center',
        fontFamily: "'JetBrains Mono', monospace",
        color: 'var(--text)',
        background: 'var(--bg)',
      }}
    >
      <div style={{ fontSize: 16, fontWeight: 600 }}>Can&apos;t reach CTC</div>
      <div style={{ fontSize: 13, color: 'var(--text-dim)', maxWidth: 360 }}>
        We couldn&apos;t load your session. Check your connection or VPN, then try again.
      </div>
      <button
        type="button"
        onClick={retry}
        disabled={retrying}
        style={{
          background: 'var(--accent)',
          color: '#fff',
          border: 'none',
          borderRadius: 10,
          padding: '10px 20px',
          fontFamily: 'inherit',
          fontWeight: 600,
          fontSize: 14,
          cursor: retrying ? 'default' : 'pointer',
          opacity: retrying ? 0.7 : 1,
        }}
      >
        {retrying ? 'Retrying…' : 'Retry'}
      </button>
    </div>
  );
}

export function useApp(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp must be used inside <AppProvider>');
  return ctx;
}

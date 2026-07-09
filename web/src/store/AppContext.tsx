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

  // Restore session from the api on mount.
  // Cancelled guard prevents setState after unmount.
  useEffect(() => {
    let cancelled = false;
    api.getSession().then((s) => {
      if (!cancelled) setSession(s);
    });
    return () => {
      cancelled = true;
    };
  }, [api]);

  const refresh = useCallback(async (): Promise<Session | null> => {
    const s = await api.getSession();
    setSession(s);
    return s;
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

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp must be used inside <AppProvider>');
  return ctx;
}

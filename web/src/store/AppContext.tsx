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
import type { Session, OnboardingInput } from '@/domain/types';

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
  session: Session | null;
  signIn(email: string, password: string): Promise<void>;
  completeOnboarding(input: OnboardingInput): Promise<void>;
  signOut(): Promise<void>;
  api: CtcApi;
  refresh(): Promise<Session | null>;
}

const AppContext = createContext<AppContextValue | null>(null);

interface AppProviderProps {
  children: ReactNode;
  /** Pass a CtcApi instance (e.g. from createMockApi) — defaults to the module singleton. */
  api?: CtcApi;
}

export function AppProvider({ children, api: apiProp }: AppProviderProps) {
  // Resolve the api once on first render and hand the same real CtcApi instance
  // to consumers — typed, referentially stable, methods callable with correct `this`.
  // The `api` prop does not change after mount in practice.
  const apiRef = useRef<CtcApi>(apiProp ?? makeDefaultApi());
  const api = apiRef.current;

  const [session, setSession] = useState<Session | null>(null);

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
      const s = await api.signIn(email, password);
      setSession(s);
    },
    [api],
  );

  const completeOnboarding = useCallback(
    async (input: OnboardingInput): Promise<void> => {
      const s = await api.completeOnboarding(input);
      setSession(s);
    },
    [api],
  );

  const signOut = useCallback(async (): Promise<void> => {
    await api.signOut();
    setSession(null);
  }, [api]);

  const value: AppContextValue = useMemo(
    () => ({ session, signIn, completeOnboarding, signOut, api, refresh }),
    [session, signIn, completeOnboarding, signOut, api, refresh],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp must be used inside <AppProvider>');
  return ctx;
}

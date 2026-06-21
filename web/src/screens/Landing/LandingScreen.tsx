import { useEffect } from 'react';
import { useApp } from '@/store/AppContext';

/**
 * Public landing page mounted at `/`. Embeds the self-contained "How it works"
 * marketing deck (served as a static asset from public/howitworks.html) in a
 * full-viewport iframe.
 *
 * The deck renders its own "Continue with GitHub Enterprise" CTAs (a primary
 * button in the hero + a compact one that appears in the sticky header on
 * scroll). Those CTAs can't know the OAuth URL, so they postMessage up to here
 * and we start the existing OAuth flow via signIn().
 *
 * Logged-in users never reach this screen — the route is wrapped in RequireGuest,
 * which redirects them to /app/dashboard.
 */
export function LandingScreen() {
  const { signIn } = useApp();

  useEffect(() => {
    function onMessage(e: MessageEvent) {
      if (e.data && e.data.type === 'ctc:login') signIn('', '');
    }
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [signIn]);

  return (
    <iframe
      src="/howitworks.html"
      title="How CTC works"
      style={{
        position: 'fixed',
        inset: 0,
        width: '100%',
        height: '100%',
        border: 'none',
        display: 'block',
        background: 'var(--bg)',
      }}
    />
  );
}

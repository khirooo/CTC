import { useEffect } from 'react';
import { useApp } from '@/store/AppContext';

/**
 * Public landing page mounted at `/`. Embeds the self-contained "How it works"
 * marketing deck (served as a static asset from public/howitworks.html) in a
 * full-viewport iframe.
 *
 * The deck renders its own sign-in CTAs (a primary button in the hero + a compact
 * one that appears in the sticky header on scroll). GitLab OAuth is the sole login
 * path, so those CTAs postMessage up to here and we start the OAuth redirect
 * directly — there is no intermediate login screen to click through.
 *
 * Logged-in users never reach this screen — the route is wrapped in RequireGuest,
 * which redirects them to /app/dashboard.
 */
export function LandingScreen() {
  const { signIn } = useApp();

  useEffect(() => {
    function onMessage(e: MessageEvent) {
      // Real backend: signIn redirects straight to GitLab OAuth (args ignored).
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

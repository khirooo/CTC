import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

/**
 * Public landing page mounted at `/`. Embeds the self-contained "How it works"
 * marketing deck (served as a static asset from public/howitworks.html) in a
 * full-viewport iframe.
 *
 * The deck renders its own sign-in CTAs (a primary button in the hero + a compact
 * one that appears in the sticky header on scroll). Those CTAs can't know which
 * auth mode the backend runs, so they postMessage up to here and we route to the
 * /login screen (which shows the GitLab OAuth button).
 *
 * Logged-in users never reach this screen — the route is wrapped in RequireGuest,
 * which redirects them to /app/dashboard.
 */
export function LandingScreen() {
  const navigate = useNavigate();

  useEffect(() => {
    function onMessage(e: MessageEvent) {
      if (e.data && e.data.type === 'ctc:login') navigate('/login');
    }
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [navigate]);

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

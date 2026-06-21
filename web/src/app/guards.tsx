import { Navigate, Outlet } from 'react-router-dom';
import { useApp } from '@/store/AppContext';

/**
 * Protects routes that require an authenticated + onboarded session.
 * - No session → redirect to the landing page (/)
 * - Session but not onboarded → redirect to /onboarding
 * - Fully onboarded → render children via <Outlet>
 */
export function RequireSession() {
  const { session } = useApp();
  if (!session) return <Navigate to="/" replace />;
  if (!session.onboarded) return <Navigate to="/onboarding" replace />;
  return <Outlet />;
}

/**
 * Protects routes that should only be accessible to guests (not signed-in users).
 * - Signed-in + onboarded → redirect to /app/dashboard
 * - Signed-in but not onboarded → redirect to /onboarding (mirrors RequireSession,
 *   so a freshly-created OAuth account lands in onboarding instead of bouncing
 *   back to the sign-in screen)
 * - No session → render children via <Outlet>
 */
export function RequireGuest() {
  const { session } = useApp();
  if (session) return <Navigate to={session.onboarded ? '/app/dashboard' : '/onboarding'} replace />;
  return <Outlet />;
}

/**
 * Protects admin-only routes.
 * - No session → redirect to the landing page (/) (RequireSession already handles
 *   this above, but guarding here too makes the component safe when used standalone).
 * - Authenticated but not an admin → redirect to /app/dashboard
 * - Admin → render children via <Outlet>
 */
export function RequireAdmin() {
  const { session } = useApp();
  if (!session) return <Navigate to="/" replace />;
  if (!session.isAdmin) return <Navigate to="/app/dashboard" replace />;
  return <Outlet />;
}

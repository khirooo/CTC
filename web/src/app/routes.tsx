import { Routes, Route, Navigate } from 'react-router-dom';
import { RequireSession, RequireGuest, RequireAdmin } from './guards';
import { AppShell } from './AppShell';
import { LandingScreen } from '@/screens/Landing/LandingScreen';
import { AuthScreen } from '@/screens/Auth/AuthScreen';
import { OnboardingScreen } from '@/screens/Onboarding/OnboardingScreen';
import { DashboardScreen } from '@/screens/Dashboard/DashboardScreen';
import { MarketplaceScreen } from '@/screens/Marketplace/MarketplaceScreen';
import { LeaderboardScreen } from '@/screens/Leaderboard/LeaderboardScreen';
import { HistoryScreen } from '@/screens/History/HistoryScreen';
import { ProfileScreen } from '@/screens/Profile/ProfileScreen';
import { AdminScreen } from '@/screens/Admin/AdminScreen';

/**
 * The full route tree, mounted under whatever router context is provided.
 * Used directly in tests (under MemoryRouter) and wrapped by App.tsx (under
 * createBrowserRouter / RouterProvider).
 */
export function AppRoutes() {
  return (
    <Routes>
      {/* Guest-only routes */}
      <Route element={<RequireGuest />}>
        {/* Public landing: the marketing deck + GitLab OAuth CTA. Logged-in users
            are redirected to /app/dashboard by RequireGuest. */}
        <Route path="/" element={<LandingScreen />} />
        {/* Login screen: single "Continue with GitLab" button. */}
        <Route path="/login" element={<AuthScreen mode="signin" />} />
        {/* Old standalone paths now point at the mode-aware login screen. */}
        <Route path="/signin" element={<Navigate to="/login" replace />} />
        <Route path="/signup" element={<Navigate to="/login" replace />} />
      </Route>

      {/* Onboarding (accessible to any logged-in user) */}
      <Route path="/onboarding" element={<OnboardingScreen />} />

      {/* Protected app routes — wrapped in AppShell layout */}
      <Route element={<RequireSession />}>
        <Route path="/app" element={<AppShell />}>
          <Route path="dashboard" element={<DashboardScreen />} />
          <Route path="marketplace" element={<MarketplaceScreen />} />
          <Route path="leaderboard" element={<LeaderboardScreen />} />
          <Route path="history" element={<HistoryScreen />} />
          <Route path="profile" element={<ProfileScreen />} />
          {/* Settings merged into Profile; keep the path as a redirect for old links */}
          <Route path="settings" element={<Navigate to="/app/profile" replace />} />
          <Route element={<RequireAdmin />}>
            <Route path="admin" element={<AdminScreen />} />
          </Route>
        </Route>
      </Route>
    </Routes>
  );
}

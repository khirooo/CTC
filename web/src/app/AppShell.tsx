import { Outlet, NavLink, useNavigate, useLocation } from 'react-router-dom';
import { useApp } from '@/store/AppContext';
import { HeaderSearch } from '@/components/HeaderSearch';

const NAV_ITEMS = [
  { path: '/app/dashboard', icon: '◧', label: 'Overview' },
  { path: '/app/marketplace', icon: '⇄', label: 'Marketplace' },
  { path: '/app/leaderboard', icon: '≡', label: 'Leaderboard' },
  { path: '/app/history', icon: '◷', label: 'History' },
  { path: '/app/profile', icon: '◔', label: 'Your profile' },
] as const;

const ROUTE_TITLES: Record<string, string> = {
  '/app/dashboard': 'Overview',
  '/app/marketplace': 'Marketplace',
  '/app/leaderboard': 'Leaderboard',
  '/app/history': 'Monthly reports',
  '/app/profile': 'Your profile',
  '/app/admin': 'Admin',
};

export function AppShell() {
  const { session, signOut, api } = useApp();
  const navigate = useNavigate();
  const location = useLocation();

  const pageTitle = ROUTE_TITLES[location.pathname] ?? 'Overview';

  const initials = session?.name
    ? session.name
        .split(' ')
        .map((p) => p[0]?.toUpperCase() ?? '')
        .join('')
        .slice(0, 2)
    : '??';

  const role = session?.role ?? 'consumer';

  async function handleSignOut() {
    await signOut();
    navigate('/', { replace: true });
  }

  const navBase: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '9px 12px',
    borderRadius: 9,
    background: 'none',
    border: 'none',
    color: 'var(--text-dim)',
    fontFamily: 'inherit',
    fontSize: 14,
    fontWeight: 500,
    cursor: 'pointer',
    width: '100%',
    textAlign: 'left',
    textDecoration: 'none',
  };

  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      {/* Sidebar */}
      <aside
        style={{
          width: 236,
          flexShrink: 0,
          borderRight: '1px solid var(--border)',
          background: 'var(--surface)',
          display: 'flex',
          flexDirection: 'column',
          padding: '20px 16px',
          position: 'sticky',
          top: 0,
          height: '100vh',
        }}
      >
        {/* Logo */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 11,
            padding: '6px 8px',
            marginBottom: 26,
          }}
        >
          <div
            style={{
              width: 30,
              height: 30,
              borderRadius: 8,
              background: 'var(--accent)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#fff',
              fontFamily: "'JetBrains Mono', monospace",
              fontWeight: 600,
              fontSize: 14,
            }}
          >
            ❯
          </div>
          <div>
            <div
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontWeight: 600,
                letterSpacing: '0.04em',
                fontSize: 14,
              }}
            >
              CTC
            </div>
            <div style={{ fontSize: 10, color: 'var(--text-faint)', letterSpacing: '0.04em' }}>
              Credit Traffic Control
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {NAV_ITEMS.map(({ path, icon, label }) => (
            <NavLink
              key={path}
              to={path}
              style={({ isActive }) => ({
                ...navBase,
                color: isActive ? 'var(--text)' : 'var(--text-dim)',
                background: isActive ? 'var(--surface-2)' : 'none',
              })}
            >
              <span
                aria-hidden="true"
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  width: 16,
                  flexShrink: 0,
                }}
              >
                {icon}
              </span>
              {label}
            </NavLink>
          ))}
          {session?.isAdmin && (
            <NavLink
              to="/app/admin"
              style={({ isActive }) => ({
                ...navBase,
                color: isActive ? 'var(--text)' : 'var(--text-dim)',
                background: isActive ? 'var(--surface-2)' : 'none',
              })}
            >
              <span
                aria-hidden="true"
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  width: 16,
                  flexShrink: 0,
                }}
              >
                ⚿
              </span>
              Admin
            </NavLink>
          )}
        </nav>

        {/* User footer */}
        <div
          style={{
            marginTop: 'auto',
            borderTop: '1px solid var(--border)',
            paddingTop: 14,
            display: 'flex',
            alignItems: 'center',
            gap: 10,
          }}
        >
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: '50%',
              background: 'var(--accent-soft)',
              color: 'var(--accent)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontWeight: 600,
              fontSize: 13,
              flexShrink: 0,
            }}
          >
            {initials}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div
              style={{
                fontSize: 13,
                fontWeight: 600,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {session?.name ?? ''}
            </div>
            <span
              style={{
                display: 'inline-block',
                marginTop: 3,
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 11,
                padding: '4px 10px',
                borderRadius: 8,
                background: role === 'giver' ? 'var(--give-soft)' : 'var(--consume-soft)',
                color: role === 'giver' ? 'var(--give)' : 'var(--consume)',
              }}
            >
              {role === 'giver' ? 'Host' : 'Guest'}
            </span>
          </div>
          <button
            onClick={handleSignOut}
            title="Sign out"
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-faint)',
              cursor: 'pointer',
              fontSize: 16,
              fontFamily: "'JetBrains Mono', monospace",
              padding: 4,
            }}
          >
            ⏻
          </button>
        </div>
      </aside>

      {/* Main content area */}
      <main style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        {/* Topbar */}
        <header
          style={{
            position: 'sticky',
            top: 0,
            zIndex: 5,
            display: 'flex',
            alignItems: 'center',
            gap: 16,
            padding: '16px 32px',
            borderBottom: '1px solid var(--border)',
            background: 'color-mix(in srgb, var(--bg) 88%, transparent)',
            backdropFilter: 'blur(8px)',
          }}
        >
          <h1 style={{ fontSize: 17, fontWeight: 600, margin: 0, letterSpacing: '-0.01em' }}>
            {pageTitle}
          </h1>
          <div style={{ marginLeft: 'auto' }}>
            <HeaderSearch api={api} />
          </div>
        </header>

        {/* Page content */}
        <div style={{ padding: 32, maxWidth: 1180, width: '100%', margin: '0 auto' }}>
          <Outlet />
        </div>
      </main>
    </div>
  );
}

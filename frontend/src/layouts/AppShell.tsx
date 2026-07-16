import { useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { Button, SkipLink, StatusBadge } from '../design-system/components';
import { workspaceRoutes } from '../routes/routeConfig';

export function AppShell() {
  const { principal, can, signOut } = useAuth();
  const [signingOut, setSigningOut] = useState(false);
  return (
    <div className="app-shell">
      <SkipLink />
      <aside className="sidebar">
        <div className="brand">
          <span className="brand__mark" aria-hidden="true">
            M
          </span>
          <div>
            <strong>Musimack</strong>
            <span>SEO Toolkit</span>
          </div>
        </div>
        <button
          className="nav-toggle"
          type="button"
          aria-controls="primary-navigation"
          aria-expanded="false"
          onClick={(event) => {
            const expanded = event.currentTarget.getAttribute('aria-expanded') === 'true';
            event.currentTarget.setAttribute('aria-expanded', String(!expanded));
          }}
        >
          Menu
        </button>
        <nav id="primary-navigation" aria-label="Primary navigation">
          {workspaceRoutes
            .filter((route) => can(route.permission))
            .map((route) => (
              <NavLink key={route.path} to={route.path} end={route.path === '/'}>
                {route.label}
              </NavLink>
            ))}
        </nav>
        <div className="sidebar__footer">
          <StatusBadge tone="positive">Private workspace</StatusBadge>
          <span>Foundation v1</span>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div>
            <span className="topbar__label">Private operations console</span>
            <strong>Workspace</strong>
          </div>
          <div className="topbar__actions">
            <details className="user-menu">
              <summary>{principal?.displayName ?? principal?.email ?? 'Internal user'}</summary>
              <div>
                <span>{principal?.email}</span>
                <StatusBadge tone="neutral">{principal?.role ?? 'viewer'}</StatusBadge>
                <Button
                  disabled={signingOut}
                  className="button--quiet"
                  onClick={() => {
                    setSigningOut(true);
                    void signOut().finally(() => {
                      setSigningOut(false);
                    });
                  }}
                >
                  {signingOut ? 'Signing out…' : 'Sign out'}
                </Button>
              </div>
            </details>
          </div>
        </header>
        <main id="main-content" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}

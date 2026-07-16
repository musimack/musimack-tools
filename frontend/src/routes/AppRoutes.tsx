import { useEffect } from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import type { Permission } from '../auth/contracts';
import { LoadingScreen } from '../design-system/components';
import { AppShell } from '../layouts/AppShell';
import { NotFoundPage, SignInPage, UnauthorizedPage, UnavailablePage } from '../pages/SystemPages';
import { workspaceRoutes } from './routeConfig';

function DocumentTitle() {
  const location = useLocation();
  useEffect(() => {
    const workspace = workspaceRoutes.find((route) => route.path === location.pathname);
    const systemTitles: Readonly<Record<string, string>> = {
      '/sign-in': 'Sign In',
      '/unauthorized': 'Unauthorized',
      '/service-unavailable': 'Service Unavailable',
    };
    const label = workspace ? workspace.label : (systemTitles[location.pathname] ?? 'Not Found');
    document.title = `${label} | Musimack SEO Toolkit`;
  }, [location.pathname]);
  return null;
}

function Protected({ permission }: { permission: Permission }) {
  const { status, can } = useAuth();
  const location = useLocation();
  if (status === 'initializing') return <LoadingScreen />;
  if (status === 'unavailable') return <Navigate to="/service-unavailable" replace />;
  if (status === 'unauthenticated' || status === 'expired')
    return <Navigate to="/sign-in" replace state={{ from: location.pathname }} />;
  if (!can(permission)) return <Navigate to="/unauthorized" replace />;
  return <AppShell />;
}

export function AppRoutes() {
  return (
    <>
      <DocumentTitle />
      <Routes>
        <Route path="/sign-in" element={<SignInPage />} />
        <Route path="/service-unavailable" element={<UnavailablePage />} />
        <Route path="/unauthorized" element={<UnauthorizedPage />} />
        {workspaceRoutes.map(({ path, permission, component: Component }) => (
          <Route key={path} element={<Protected permission={permission} />}>
            <Route path={path} element={<Component />} />
          </Route>
        ))}
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </>
  );
}

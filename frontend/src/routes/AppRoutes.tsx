import { useEffect } from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import type { Permission } from '../auth/contracts';
import { LoadingScreen } from '../design-system/components';
import { AppShell } from '../layouts/AppShell';
import { NotFoundPage, SignInPage, UnauthorizedPage, UnavailablePage } from '../pages/SystemPages';
import { workspaceRoutes } from './routeConfig';
import {
  ArtifactDetailPage,
  HistoryJobPage,
  HistoryRunPage,
  JobDetailPage,
  JobResultPage,
  NewCrawlPage,
  RecommendationPage,
} from '../pages/WorkflowPages';
import {
  AuditDashboardPage,
  AuditDuplicateDetailPage,
  AuditDuplicatesPage,
  AuditIssuesPage,
  AuditPageDetailPage,
  AuditPagesPage,
  AuditsPage,
  NewAuditPage,
} from '../pages/AuditPages';

function DocumentTitle() {
  const location = useLocation();
  useEffect(() => {
    const workspace = workspaceRoutes.find((route) => route.path === location.pathname);
    const systemTitles: Readonly<Record<string, string>> = {
      '/sign-in': 'Sign In',
      '/unauthorized': 'Unauthorized',
      '/service-unavailable': 'Service Unavailable',
    };
    const workflowTitle = location.pathname.startsWith('/jobs/')
      ? 'Job workflow'
      : location.pathname.startsWith('/history/')
        ? 'History detail'
        : location.pathname.startsWith('/artifacts/')
          ? 'Artifact detail'
          : location.pathname.startsWith('/audits/')
            ? 'Metadata audit'
            : null;
    const label = workspace
      ? workspace.label
      : (systemTitles[location.pathname] ?? workflowTitle ?? 'Not Found');
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
        <Route element={<Protected permission="jobs.submit" />}>
          <Route path="/jobs/new" element={<NewCrawlPage />} />
        </Route>
        <Route element={<Protected permission="jobs.view" />}>
          <Route path="/jobs/:jobId" element={<JobDetailPage />} />
          <Route path="/jobs/:jobId/progress" element={<JobDetailPage />} />
          <Route path="/jobs/:jobId/results" element={<JobResultPage />} />
        </Route>
        <Route element={<Protected permission="runs.view" />}>
          <Route path="/jobs/:jobId/results/recommendations" element={<RecommendationPage />} />
        </Route>
        <Route element={<Protected permission="history.view" />}>
          <Route path="/history/jobs/:jobId" element={<HistoryJobPage />} />
          <Route path="/history/runs/:runId" element={<HistoryRunPage />} />
        </Route>
        <Route element={<Protected permission="artifacts.view" />}>
          <Route path="/artifacts/:artifactId" element={<ArtifactDetailPage />} />
        </Route>
        <Route element={<Protected permission="runs.view" />}>
          <Route path="/audits/metadata" element={<AuditsPage />} />
          <Route path="/audits/metadata/:auditId" element={<AuditDashboardPage />} />
          <Route path="/audits/metadata/:auditId/pages" element={<AuditPagesPage />} />
          <Route path="/audits/metadata/:auditId/pages/:pageId" element={<AuditPageDetailPage />} />
          <Route path="/audits/metadata/:auditId/issues" element={<AuditIssuesPage />} />
          <Route path="/audits/metadata/:auditId/duplicates" element={<AuditDuplicatesPage />} />
          <Route
            path="/audits/metadata/:auditId/duplicates/:groupId"
            element={<AuditDuplicateDetailPage />}
          />
        </Route>
        <Route element={<Protected permission="jobs.submit" />}>
          <Route path="/audits/metadata/new" element={<NewAuditPage />} />
        </Route>
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </>
  );
}

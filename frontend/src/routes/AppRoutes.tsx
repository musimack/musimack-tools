import { Suspense, useEffect } from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import type { Permission } from '../auth/contracts';
import { LoadingScreen } from '../design-system/components';
import { AppShell } from '../layouts/AppShell';
import { NotFoundPage, SignInPage, UnauthorizedPage, UnavailablePage } from '../pages/SystemPages';
import { workspaceRoutes } from './routeConfig';
import {
  NewSiteAuditPage,
  SiteAuditIssueDetailPage,
  SiteAuditLifecyclePage,
  SiteAuditPageDetailPage,
  SiteAuditResultsPage,
} from './SiteAuditRoutePages';
import {
  ArtifactDetailPage,
  HistoryJobPage,
  HistoryRunPage,
  JobDetailPage,
  JobResultPage,
  NewCrawlPage,
  RecommendationDetailPage,
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
import {
  NewSitemapAuditPage,
  SitemapAuditDashboardPage,
  SitemapDocumentsPage,
  SitemapEntriesPage,
  SitemapFindingsPage,
} from '../pages/SitemapAuditPages';
import {
  LinkAuditDashboardPage,
  LinkExportsPage,
  LinkOccurrencesPage,
  LinkRecommendationsPage,
  LinkTargetsPage,
  NewLinkAuditPage,
  RedirectChainsPage,
  RedirectLoopsPage,
} from '../pages/LinkAuditPages';
import {
  InternalLinkDashboardPage,
  InternalLinkExportsPage,
  InternalLinkInventoryPage,
  NewInternalLinkPage,
} from '../pages/InternalLinkPages';
import {
  ImageAuditDashboardPage,
  ImageAuditExportsPage,
  ImageAuditInventoryPage,
  NewImageAuditPage,
} from '../pages/ImageAuditPages';
import {
  NewStructuredDataAuditPage,
  StructuredDataAuditDashboardPage,
  StructuredDataAuditExportsPage,
  StructuredDataAuditInventoryPage,
} from '../pages/StructuredDataAuditPages';
import {
  MigrationQaDashboardPage,
  MigrationQaExportsPage,
  MigrationQaInventoryPage,
  NewMigrationQaPage,
} from '../pages/MigrationQaPages';

function DocumentTitle() {
  const location = useLocation();
  useEffect(() => {
    const workspace = workspaceRoutes.find((route) => route.path === location.pathname);
    const systemTitles: Readonly<Record<string, string>> = {
      '/sign-in': 'Sign In',
      '/unauthorized': 'Unauthorized',
      '/service-unavailable': 'Service Unavailable',
    };
    const workflowTitle = location.pathname.startsWith('/migration-qa')
      ? 'Website migration QA'
      : location.pathname.startsWith('/site-audits')
        ? 'Site Audits'
        : location.pathname.startsWith('/structured-data-audits')
          ? 'Structured data'
          : location.pathname.startsWith('/image-audits')
            ? 'Images and alt text'
            : location.pathname.startsWith('/internal-links')
              ? 'Internal links'
              : location.pathname.startsWith('/link-audits')
                ? 'Link audit'
                : location.pathname.startsWith('/sitemap-audits')
                  ? 'Sitemap audit'
                  : location.pathname.startsWith('/jobs/')
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
      <Suspense fallback={<LoadingScreen />}>
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
          <Route element={<Protected permission="jobs.submit" />}>
            <Route path="/site-audits/new" element={<NewSiteAuditPage />} />
            <Route path="/site-audits/:auditId/edit" element={<NewSiteAuditPage />} />
          </Route>
          <Route element={<Protected permission="runs.view" />}>
            <Route path="/site-audits/:auditId" element={<SiteAuditLifecyclePage />} />
            <Route path="/site-audits/:auditId/results/:tab" element={<SiteAuditResultsPage />} />
            <Route
              path="/site-audits/:auditId/results/pages/:sequence"
              element={<SiteAuditPageDetailPage />}
            />
            <Route
              path="/site-audits/:auditId/results/issues/:groupId"
              element={<SiteAuditIssueDetailPage />}
            />
          </Route>
          <Route element={<Protected permission="jobs.view" />}>
            <Route path="/jobs/:jobId" element={<JobDetailPage />} />
            <Route path="/jobs/:jobId/progress" element={<JobDetailPage />} />
            <Route path="/jobs/:jobId/results" element={<JobResultPage />} />
          </Route>
          <Route element={<Protected permission="runs.view" />}>
            <Route path="/migration-qa/:projectId" element={<MigrationQaDashboardPage />} />
            <Route path="/migration-qa/:projectId/exports" element={<MigrationQaExportsPage />} />
            <Route
              path="/migration-qa/:projectId/:resource"
              element={<MigrationQaInventoryPage />}
            />
          </Route>
          <Route element={<Protected permission="jobs.submit" />}>
            <Route path="/migration-qa/new" element={<NewMigrationQaPage />} />
          </Route>
          <Route element={<Protected permission="runs.view" />}>
            <Route
              path="/structured-data-audits/:auditId"
              element={<StructuredDataAuditDashboardPage />}
            />
            <Route
              path="/structured-data-audits/:auditId/exports"
              element={<StructuredDataAuditExportsPage />}
            />
            <Route
              path="/structured-data-audits/:auditId/:resource"
              element={<StructuredDataAuditInventoryPage />}
            />
          </Route>
          <Route element={<Protected permission="jobs.submit" />}>
            <Route path="/structured-data-audits/new" element={<NewStructuredDataAuditPage />} />
          </Route>
          <Route element={<Protected permission="runs.view" />}>
            <Route path="/image-audits/:auditId" element={<ImageAuditDashboardPage />} />
            <Route path="/image-audits/:auditId/exports" element={<ImageAuditExportsPage />} />
            <Route path="/image-audits/:auditId/:resource" element={<ImageAuditInventoryPage />} />
          </Route>
          <Route element={<Protected permission="jobs.submit" />}>
            <Route path="/image-audits/new" element={<NewImageAuditPage />} />
          </Route>
          <Route element={<Protected permission="runs.view" />}>
            <Route path="/internal-links/:auditId" element={<InternalLinkDashboardPage />} />
            <Route path="/internal-links/:auditId/exports" element={<InternalLinkExportsPage />} />
            <Route
              path="/internal-links/:auditId/:resource"
              element={<InternalLinkInventoryPage />}
            />
          </Route>
          <Route element={<Protected permission="jobs.submit" />}>
            <Route path="/internal-links/new" element={<NewInternalLinkPage />} />
          </Route>
          <Route element={<Protected permission="runs.view" />}>
            <Route path="/jobs/:jobId/results/recommendations" element={<RecommendationPage />} />
            <Route
              path="/jobs/:jobId/results/recommendations/:sequence"
              element={<RecommendationDetailPage />}
            />
          </Route>
          <Route element={<Protected permission="runs.view" />}>
            <Route path="/link-audits/:auditId" element={<LinkAuditDashboardPage />} />
            <Route path="/link-audits/:auditId/targets" element={<LinkTargetsPage />} />
            <Route path="/link-audits/:auditId/occurrences" element={<LinkOccurrencesPage />} />
            <Route path="/link-audits/:auditId/chains" element={<RedirectChainsPage />} />
            <Route path="/link-audits/:auditId/loops" element={<RedirectLoopsPage />} />
            <Route
              path="/link-audits/:auditId/recommendations"
              element={<LinkRecommendationsPage />}
            />
            <Route path="/link-audits/:auditId/exports" element={<LinkExportsPage />} />
          </Route>
          <Route element={<Protected permission="jobs.submit" />}>
            <Route path="/link-audits/new" element={<NewLinkAuditPage />} />
          </Route>
          <Route element={<Protected permission="runs.view" />}>
            <Route path="/sitemap-audits/:auditId" element={<SitemapAuditDashboardPage />} />
            <Route path="/sitemap-audits/:auditId/documents" element={<SitemapDocumentsPage />} />
            <Route path="/sitemap-audits/:auditId/entries" element={<SitemapEntriesPage />} />
            <Route path="/sitemap-audits/:auditId/findings" element={<SitemapFindingsPage />} />
          </Route>
          <Route element={<Protected permission="jobs.submit" />}>
            <Route path="/sitemap-audits/new" element={<NewSitemapAuditPage />} />
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
            <Route
              path="/audits/metadata/:auditId/pages/:pageId"
              element={<AuditPageDetailPage />}
            />
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
      </Suspense>
    </>
  );
}

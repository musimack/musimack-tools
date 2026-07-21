import { lazy } from 'react';

export const SiteAuditHistoryPage = lazy(() =>
  import('../pages/SiteAuditPages').then((pages) => ({ default: pages.SiteAuditHistoryPage })),
);
export const NewSiteAuditPage = lazy(() =>
  import('../pages/SiteAuditPages').then((pages) => ({ default: pages.NewSiteAuditPage })),
);
export const SiteAuditLifecyclePage = lazy(() =>
  import('../pages/SiteAuditPages').then((pages) => ({ default: pages.SiteAuditLifecyclePage })),
);
export const SiteAuditResultsPage = lazy(() =>
  import('../pages/SiteAuditPages').then((pages) => ({ default: pages.SiteAuditResultsPage })),
);
export const SiteAuditPageDetailPage = lazy(() =>
  import('../pages/SiteAuditPages').then((pages) => ({ default: pages.SiteAuditPageDetailPage })),
);
export const SiteAuditIssueDetailPage = lazy(() =>
  import('../pages/SiteAuditPages').then((pages) => ({ default: pages.SiteAuditIssueDetailPage })),
);

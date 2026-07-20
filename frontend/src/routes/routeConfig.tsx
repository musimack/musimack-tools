import type { ComponentType } from 'react';
import type { Permission } from '../auth/contracts';
import { OverviewPage, UsersPage } from '../pages/WorkspacePages';
import { SiteAuditSettingsPage } from '../pages/SiteAuditSettingsPage';
import { ArtifactsPage, HistoryPage, JobsPage } from '../pages/WorkflowPages';
import { AuditsPage } from '../pages/AuditPages';
import { SitemapAuditsPage } from '../pages/SitemapAuditPages';
import { LinkAuditsPage } from '../pages/LinkAuditPages';
import { InternalLinksPage } from '../pages/InternalLinkPages';
import { ImageAuditsPage } from '../pages/ImageAuditPages';
import { StructuredDataAuditsPage } from '../pages/StructuredDataAuditPages';
import { MigrationQaProjectsPage } from '../pages/MigrationQaPages';
import { SiteAuditHistoryPage } from '../pages/SiteAuditPages';

export type WorkspaceRoute = {
  path: string;
  label: string;
  description: string;
  permission: Permission;
  component: ComponentType;
};

export const workspaceRoutes: readonly WorkspaceRoute[] = [
  {
    path: '/site-audits',
    label: 'Site Audits',
    description: 'Create and review combined, governed website audits',
    permission: 'runs.view',
    component: SiteAuditHistoryPage,
  },
  {
    path: '/migration-qa',
    label: 'Migration QA',
    description: 'Review website migration continuity and redirect evidence',
    permission: 'runs.view',
    component: MigrationQaProjectsPage,
  },
  {
    path: '/structured-data-audits',
    label: 'Structured Data',
    description: 'Audit JSON-LD, Microdata, RDFa, entities, and profiles',
    permission: 'runs.view',
    component: StructuredDataAuditsPage,
  },
  {
    path: '/image-audits',
    label: 'Images & Alt Text',
    description: 'Audit image resources and accessible alternatives',
    permission: 'runs.view',
    component: ImageAuditsPage,
  },
  {
    path: '/internal-links',
    label: 'Internal Links',
    description: 'Analyze internal-link graph evidence',
    permission: 'runs.view',
    component: InternalLinksPage,
  },
  {
    path: '/link-audits',
    label: 'Link Audits',
    description: 'Review broken links and redirect paths',
    permission: 'runs.view',
    component: LinkAuditsPage,
  },
  {
    path: '/sitemap-audits',
    label: 'Sitemap Audits',
    description: 'Compare existing sitemap and crawl evidence',
    permission: 'runs.view',
    component: SitemapAuditsPage,
  },
  {
    path: '/audits',
    label: 'Audits',
    description: 'Review deterministic metadata findings',
    permission: 'runs.view',
    component: AuditsPage,
  },
  {
    path: '/',
    label: 'Overview',
    description: 'Operational health at a glance',
    permission: 'diagnostics.view',
    component: OverviewPage,
  },
  {
    path: '/jobs',
    label: 'Jobs',
    description: 'Prepare and monitor toolkit work',
    permission: 'jobs.view',
    component: JobsPage,
  },
  {
    path: '/history',
    label: 'History',
    description: 'Review durable jobs and runs',
    permission: 'history.view',
    component: HistoryPage,
  },
  {
    path: '/artifacts',
    label: 'Artifacts',
    description: 'Find retained output files',
    permission: 'artifacts.view',
    component: ArtifactsPage,
  },
  {
    path: '/users',
    label: 'Users',
    description: 'Manage internal access',
    permission: 'users.view',
    component: UsersPage,
  },
  {
    path: '/settings',
    label: 'Site Audit Settings',
    description: 'Manage URL governance, presets, and saved site profiles',
    permission: 'jobs.submit',
    component: SiteAuditSettingsPage,
  },
] as const;

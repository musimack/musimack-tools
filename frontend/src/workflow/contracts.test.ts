import {
  ARTIFACT_ACCESS_UI_VERSION,
  CRAWL_WORKFLOW_UI_VERSION,
  FRONTEND_POLLING_VERSION,
  JOB_MONITOR_UI_VERSION,
  SITEMAP_REVIEW_UI_VERSION,
  crawlProfiles,
  scopeProfiles,
} from './contracts';

test('publishes the accepted Phase 19 contract versions', () => {
  expect([
    CRAWL_WORKFLOW_UI_VERSION,
    JOB_MONITOR_UI_VERSION,
    SITEMAP_REVIEW_UI_VERSION,
    ARTIFACT_ACCESS_UI_VERSION,
    FRONTEND_POLLING_VERSION,
  ]).toEqual([
    'seo-toolkit-crawl-workflow-ui-v1',
    'seo-toolkit-job-monitor-ui-v1',
    'seo-toolkit-sitemap-review-ui-v1',
    'seo-toolkit-artifact-access-ui-v1',
    'seo-toolkit-frontend-polling-v1',
  ]);
});
test('offers only backend-supported crawl and scope profiles', () => {
  expect(crawlProfiles).toEqual(['quick_audit', 'standard_crawl', 'deep_crawl', 'sitemap_only']);
  expect(scopeProfiles).toEqual(['exact_host', 'include_subdomains', 'approved_hosts']);
});

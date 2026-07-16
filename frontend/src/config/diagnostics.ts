import { FRONTEND_API_CLIENT_VERSION, type SafeDiagnosticsSummary } from '../api/client';
import { FRONTEND_AUTH_VERSION } from '../auth/contracts';
import { FRONTEND_DESIGN_SYSTEM_VERSION } from '../design-system/components';
import {
  ARTIFACT_ACCESS_UI_VERSION,
  CRAWL_WORKFLOW_UI_VERSION,
  FRONTEND_POLLING_VERSION,
  JOB_MONITOR_UI_VERSION,
  SITEMAP_REVIEW_UI_VERSION,
} from '../workflow/contracts';
import { environment } from './environment';

export const frontendDiagnostics: Readonly<
  SafeDiagnosticsSummary & {
    authVersion: string;
    designSystemVersion: string;
    crawlWorkflowVersion: string;
    jobMonitorVersion: string;
    sitemapReviewVersion: string;
    artifactAccessVersion: string;
    pollingVersion: string;
  }
> = Object.freeze({
  frontendVersion: environment.frontendVersion,
  apiClientVersion: FRONTEND_API_CLIENT_VERSION,
  authVersion: FRONTEND_AUTH_VERSION,
  designSystemVersion: FRONTEND_DESIGN_SYSTEM_VERSION,
  crawlWorkflowVersion: CRAWL_WORKFLOW_UI_VERSION,
  jobMonitorVersion: JOB_MONITOR_UI_VERSION,
  sitemapReviewVersion: SITEMAP_REVIEW_UI_VERSION,
  artifactAccessVersion: ARTIFACT_ACCESS_UI_VERSION,
  pollingVersion: FRONTEND_POLLING_VERSION,
  apiBaseMode: environment.apiBaseMode,
  requestTimeoutMs: environment.requestTimeoutMs,
});

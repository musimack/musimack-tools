export const SITEMAP_AUDIT_UI_VERSION = 'seo-toolkit-sitemap-audit-ui-v1' as const;
export const auditStates = [
  'accepted',
  'discovering',
  'fetching',
  'parsing',
  'comparing',
  'completed',
  'completed_with_warnings',
  'partially_completed',
  'failed',
  'cancelled',
] as const;
export const actions = ['add', 'remove', 'review', 'unchanged'] as const;
export type SitemapAction = (typeof actions)[number];
export type ExportFormat = 'csv' | 'json' | 'markdown';

export type SitemapAudit = {
  audit_id: string;
  job_id: string;
  run_id: string;
  seed_url: string;
  explicit_sitemap_url: string | null;
  state: (typeof auditStates)[number];
  failure_code: string | null;
  warning_count: number;
  document_count: number;
  unique_url_count: number;
  comparison_count: number;
  add_count: number;
  remove_count: number;
  review_count: number;
  unchanged_count: number;
  created_at: string;
  completed_at: string | null;
};

export type SitemapCandidate = {
  normalized_url: string;
  discovery_source: string;
  discovery_sequence: number;
  provenance: string[];
  raw_url: string;
};

export type Comparison = {
  comparison_id: string;
  url: string;
  action: SitemapAction;
  comparison_state: string;
  reason_code: string;
  recommendation_state: string | null;
  http_status: number | null;
  content_type: string | null;
};

export type Page<T> = {
  items: T[];
  page_size: number;
  returned_count: number;
  next_cursor: string | null;
  ordering: string;
  filters: Record<string, unknown>;
};

export type CreateValues = {
  runId: string;
  explicitSitemapUrl?: string;
  discoverRobots: boolean;
  discoverCommonLocations: boolean;
};

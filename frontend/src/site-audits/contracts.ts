export const SITE_AUDIT_UI_VERSION = 'combined-site-audit-ui-v1' as const;

export type AuditRecord = {
  audit_id: string;
  audit_name: string;
  site_label: string | null;
  seed_url: string;
  normalized_seed_url: string;
  lifecycle: string;
  revision: number;
  partial: boolean;
  population_completeness: string;
  module_completeness: string;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  failure_code: string | null;
  failure_explanation: string | null;
  draft: SiteAuditDraft;
};

export type SiteAuditDraft = {
  audit_name: string;
  site_label: string | null;
  seed_url: string;
  normalized_seed_url?: string;
  site_profile_id?: string | null;
  site_profile_version?: number | null;
  platform_preset_id?: string | null;
  platform_preset_version?: string | null;
  preset_accepted?: boolean;
  scope_policy: { mode: string };
  approved_hosts: string[];
  crawl_profile: string;
  crawl_limits: Record<string, number>;
  rules: Record<string, unknown>[];
  disabled_inherited_rules: Record<string, unknown>[];
  tracking_parameters: string[];
  tracking_parameters_accepted: boolean;
  tracking_parameter_exceptions: string[];
  enabled_modules: string[];
  thresholds: Record<string, number>;
  business_importance: Record<string, string>[];
  publication_requested: false;
};

export type AuditDetail = {
  audit: AuditRecord;
  snapshot: Record<string, unknown> | null;
  orchestration: Record<string, unknown> | null;
};

export type AuditPage<T = Record<string, unknown>> = {
  items: T[];
  offset: number;
  page_size: number;
  total: number;
  ordering: string;
};

export type AuditHistory = AuditPage<AuditRecord>;

export type UrlRecord = Record<string, unknown> & {
  sequence: number;
  url_id: string;
  requested_url: string;
  normalized_url: string;
  final_url: string | null;
  http_status: number | null;
  content_type: string | null;
  fetch_outcome: string;
  discovery_decision: string;
  sitemap_policy_decision: string;
  partial: boolean;
};

export type IssueRecord = Record<string, unknown> & {
  group_id: string;
  title: string;
  severity: string;
  category: string;
  finding_count: number;
  affected_url_count: number;
};

export type PageFilters = {
  url?: string | undefined;
  http_status?: number | undefined;
  content_type?: string | undefined;
  fetch_state?: string | undefined;
  indexability?: string | undefined;
  canonical?: string | undefined;
  existing_sitemap?: string | undefined;
  recommended_sitemap?: string | undefined;
  metadata_eligibility?: string | undefined;
  issue_category?: string | undefined;
  severity?: string | undefined;
  business_importance?: string | undefined;
  exclusion_reason?: string | undefined;
  query_parameter?: boolean | undefined;
  crawl_depth?: number | undefined;
  partial?: boolean | undefined;
  only_actionable?: boolean | undefined;
  only_sitemap_issues?: boolean | undefined;
  only_metadata_issues?: boolean | undefined;
  only_excluded?: boolean | undefined;
  sort?: string | undefined;
  direction?: 'asc' | 'desc' | undefined;
};

export type IssueFilters = {
  search?: string | undefined;
  category?: string | undefined;
  module?: string | undefined;
  severity?: string | undefined;
  priority?: string | undefined;
  business_importance?: string | undefined;
  sitemap_impact?: boolean | undefined;
  metadata_impact?: boolean | undefined;
  indexability_impact?: boolean | undefined;
  confidence?: string | undefined;
  determinacy?: string | undefined;
  actionable?: boolean | undefined;
};

export const lifecycleStates = [
  'draft',
  'validating',
  'validation_failed',
  'validated',
  'preflighting',
  'preflight_failed',
  'ready',
  'queued',
  'running',
  'cancel_requested',
  'recovery_required',
  'completed',
  'completed_with_warnings',
  'partially_completed',
  'failed',
  'cancelled',
  'archived',
] as const;

export const terminalStates = new Set([
  'completed',
  'completed_with_warnings',
  'partially_completed',
  'failed',
  'cancelled',
  'archived',
]);

export const editableStates = new Set([
  'draft',
  'validation_failed',
  'validated',
  'preflight_failed',
  'ready',
]);

export const defaultDraft = (): SiteAuditDraft => ({
  audit_name: '',
  site_label: null,
  seed_url: '',
  scope_policy: { mode: 'exact_host' },
  approved_hosts: [],
  crawl_profile: 'standard_crawl',
  crawl_limits: {},
  rules: [],
  disabled_inherited_rules: [],
  tracking_parameters: [],
  tracking_parameters_accepted: false,
  tracking_parameter_exceptions: [],
  enabled_modules: ['metadata', 'sitemap', 'links', 'internal_links', 'images', 'structured_data'],
  thresholds: {},
  business_importance: [],
  publication_requested: false,
});

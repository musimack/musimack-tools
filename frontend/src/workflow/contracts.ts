export const CRAWL_WORKFLOW_UI_VERSION = 'seo-toolkit-crawl-workflow-ui-v1' as const;
export const JOB_MONITOR_UI_VERSION = 'seo-toolkit-job-monitor-ui-v1' as const;
export const SITEMAP_REVIEW_UI_VERSION = 'seo-toolkit-sitemap-review-ui-v1' as const;
export const ARTIFACT_ACCESS_UI_VERSION = 'seo-toolkit-artifact-access-ui-v1' as const;
export const FRONTEND_POLLING_VERSION = 'seo-toolkit-frontend-polling-v1' as const;

export const crawlProfiles = [
  'quick_audit',
  'standard_crawl',
  'deep_crawl',
  'sitemap_only',
] as const;
export const scopeProfiles = ['exact_host', 'include_subdomains', 'approved_hosts'] as const;
export type CrawlProfile = (typeof crawlProfiles)[number];
export type ScopeProfile = (typeof scopeProfiles)[number];

export type CrawlRequest = {
  seed_url: string;
  scope_profile: ScopeProfile;
  approved_hosts: string[];
  crawl_profile: CrawlProfile;
  overrides: {
    max_urls: number | null;
    max_depth: number | null;
    max_duration: number | null;
    max_accepted_bytes: number | null;
    max_concurrency: number | null;
    max_queue: number | null;
    min_delay: number | null;
    max_redirect_hops: number | null;
    max_response_bytes: number | null;
  };
  recommendation_profile: 'standard' | 'strict';
  recommendation_requested: boolean;
  xml_generation_requested: boolean;
  publication_requested: false;
  publication_dry_run: true;
  publication_root: null;
  existing_file_policy: 'fail' | 'overwrite';
  create_publication_directory: false;
  summary_writing_requested: false;
  summary_root: null;
  create_summary_directory: false;
  summary_dry_run: true;
  caller_label: string | null;
};

export type ApiCrawlLimitOverrides = {
  maximum_urls?: number;
  maximum_depth?: number;
  maximum_duration_seconds?: number;
  maximum_accepted_bytes?: number;
  maximum_concurrency?: number;
  maximum_queue_size?: number;
  minimum_request_delay_seconds?: number;
  maximum_redirect_hops?: number;
  maximum_response_bytes?: number;
};

export type ApiCrawlRequest = Omit<CrawlRequest, 'overrides' | 'existing_file_policy'> & {
  overrides: ApiCrawlLimitOverrides;
  existing_file_policy: 'fail_if_exists' | 'overwrite';
};

export type ValidationDetail = {
  severity: string;
  code: string;
  message: string;
  field: string | null;
};
export type ValidationReport = {
  valid: boolean;
  issues: ValidationDetail[];
  normalized_seed_url: string | null;
  selected_profile: string;
  requested_stages: string[];
  effective_limits: Record<string, number> | null;
  scope_summary: string | null;
  publication_requested: boolean;
  summary_requested: boolean;
  run_id: string | null;
  downstream_versions: { component: string; version: string }[];
};
export type PreflightFinding = { severity: string; code: string; message: string };
export type JobState =
  | 'accepted'
  | 'queued'
  | 'starting'
  | 'running'
  | 'cancelling'
  | 'cancelled'
  | 'completed'
  | 'completed_with_warnings'
  | 'failed'
  | 'partially_completed'
  | 'evicted'
  | 'unknown';
export type PreflightResult = {
  state: string;
  validation: ValidationReport;
  findings: PreflightFinding[];
  effective_request?: Record<string, unknown> | null;
};
export type JobStatus = {
  outcome: string;
  job_id: string | null;
  run_id: string | null;
  attempt_number: number | null;
  state: JobState | null;
  queue_position: number | null;
  active_stage: string | null;
  run_lifecycle: string | null;
  urls_discovered: number;
  urls_fetched: number;
  recommendation_counts: number[] | null;
  xml_document_count: number | null;
  xml_entry_count: number | null;
  publication_file_count: number | null;
  warning_count: number;
  failure_count: number;
  cancellation_requested: boolean;
  terminal: boolean;
  result_available: boolean;
};
export type JobList = { items: JobStatus[]; truncated: boolean; maximum: number };
export type ProgressEvent = {
  sequence: number;
  code: string;
  explanation: string;
  snapshot: Record<string, unknown>;
};
export type JobProgress = {
  outcome: string;
  latest: ProgressEvent | null;
  history: ProgressEvent[];
  history_truncated: boolean;
};
export type JobResult = {
  outcome: string;
  job_id: string | null;
  run_id: string | null;
  attempt_number: number | null;
  job_state: string | null;
  run_lifecycle: string | null;
  stage_states: { name: string; value: string }[];
  crawl_counts: { name: string; count: number }[];
  crawl_error_codes: string[];
  recommendation_counts: { name: string; count: number }[];
  xml_document_count: number | null;
  xml_entry_count: number | null;
  publication_state: string | null;
  published_file_count: number;
  publication_filenames: string[];
  warning_codes: string[];
  failure_codes: string[];
};
export type Recommendation = {
  sequence: number;
  url: string;
  requested_url: string;
  final_url: string | null;
  state: 'include' | 'exclude' | 'review' | 'indeterminate';
  determinacy: string;
  primary_reason: string;
  explanation: string;
  http_status: number | null;
  content_type: string | null;
  fetch_failure_code: string | null;
  canonical_url: string | null;
  canonical_conflicting: boolean;
  redirect_source: boolean;
  redirect_hops: number;
  redirect_final_url: string | null;
  robots_available: boolean;
  robots_allowed: boolean | null;
  robots_reason_code: string | null;
  generic_directives: string[];
  crawler_specific_directives: string[];
  indexability_conflict: boolean;
  configured_exclusions: [string, string][];
};
export type RecommendationRuleDetail = {
  rule_id: string;
  outcome: string;
  reason_code: string | null;
  explanation: string;
};
export type RecommendationWarningDetail = {
  code: string;
  explanation: string;
  source: string;
};
export type RecommendationRedirectDetail = {
  sequence: number;
  source_url: string;
  target_url: string | null;
  status_code: number;
  terminal: boolean;
  loop: boolean;
  failure_code: string | null;
};
export type RecommendationDirectiveGroup = {
  agent: string;
  directives: string[];
};
export type RecommendationDetail = {
  recommendation: Recommendation;
  reason_codes: string[];
  rule_evidence: RecommendationRuleDetail[];
  warning_details: RecommendationWarningDetail[];
  metadata_warning_codes: string[];
  evidence_id: string | null;
  crawl_depth: number | null;
  fetch_outcome: string | null;
  evidence_state: string | null;
  page_failure_code: string | null;
  title_presence: string | null;
  title: string | null;
  description_presence: string | null;
  meta_description: string | null;
  canonical_presence: string | null;
  meta_robots: RecommendationDirectiveGroup[];
  x_robots_tag: RecommendationDirectiveGroup[];
  redirect_chain: RecommendationRedirectDetail[];
  redirect_truncated: boolean | null;
  redirect_loop: boolean | null;
  sitemap_membership: boolean | null;
  application_service_version: string;
};
export type RecommendationPage = {
  job_id: string;
  run_id: string;
  offset: number;
  limit: number;
  total: number;
  returned_count: number;
  has_more: boolean;
  items: Recommendation[];
};
export type Artifact = {
  artifact_id: string;
  job_id: string;
  run_id: string;
  artifact_type: string;
  lifecycle_state: string;
  integrity_state: string;
  filename: string;
  content_type: string;
  byte_count: number;
  created_at: string;
  retention_state: string;
  download_available: boolean;
  reason_code: string | null;
};
export type HistoricalJob = {
  job_id: string;
  run_id: string;
  seed: string;
  state: string;
  attempt_count: number;
  submitted_at: string | null;
  terminal_at: string | null;
  interrupted: boolean;
  recovered: boolean;
  result_available: boolean;
  artifact_available: boolean;
};
export type HistoricalRun = {
  run_id: string;
  job_id: string;
  seed: string;
  lifecycle: string;
  current_stage: string | null;
  crawl_count: number;
  recommendation_count: number;
  warning_count: number;
  failure_count: number;
  artifact_count: number;
  partial: boolean;
  interrupted: boolean;
};
export type Page<T> = {
  items: T[];
  returned_count: number;
  has_more: boolean;
  next_cursor: string | null;
};

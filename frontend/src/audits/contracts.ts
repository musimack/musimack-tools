export const METADATA_AUDIT_UI_VERSION = 'seo-toolkit-metadata-audit-ui-v1' as const;
export const auditStates = [
  'planned',
  'running',
  'completed',
  'completed_with_warnings',
  'partially_completed',
  'failed',
  'cancelled',
] as const;
export type AuditState = (typeof auditStates)[number];
export const severities = ['critical', 'high', 'medium', 'low', 'information'] as const;
export type Severity = (typeof severities)[number];
export const categories = [
  'title',
  'meta_description',
  'canonical',
  'robots',
  'indexability',
  'status',
  'content_type',
] as const;
export type IssueCategory = (typeof categories)[number];
export const issueCodes = [
  'title_missing',
  'title_empty',
  'title_multiple',
  'title_duplicate',
  'title_short',
  'title_long',
  'title_conflicting',
  'meta_description_missing',
  'meta_description_empty',
  'meta_description_multiple',
  'meta_description_duplicate',
  'meta_description_short',
  'meta_description_long',
  'canonical_missing',
  'canonical_invalid',
  'canonical_self',
  'canonical_elsewhere',
  'canonical_multiple',
  'canonical_conflicting',
  'canonical_cross_host',
  'canonical_cross_scheme',
  'canonical_cross_port',
  'canonical_target_redirected',
  'canonical_target_unavailable',
  'robots_denied',
  'meta_robots_noindex',
  'x_robots_tag_noindex',
  'robots_indexability_conflict',
  'crawler_specific_directive',
  'unsupported_robots_directive',
  'indexability_indeterminate',
  'indexability_recommendation_mismatch',
  'status_redirect',
  'status_4xx',
  'status_5xx',
  'status_missing',
  'redirect_loop',
  'redirect_chain',
  'redirect_cross_host',
  'content_type_missing',
  'content_type_ambiguous',
  'content_type_unexpected',
  'content_type_non_html',
] as const;
export type IssueCode = (typeof issueCodes)[number];
export type ExportFormat = 'csv' | 'json' | 'markdown';
export type Audit = {
  audit_id: string;
  job_id: string;
  run_id: string;
  seed_url: string;
  state: AuditState;
  created_at: string;
  completed_at: string | null;
  page_count: number;
  issue_count: number;
  partial: boolean;
  failure_code: string | null;
  export_available: boolean;
};
export type AuditPage = {
  audit_page_id: string;
  url: string;
  final_url: string | null;
  fetch_outcome: string;
  http_status: number | null;
  content_type: string | null;
  content_type_category: string;
  title_value: string | null;
  title_presence: string;
  description_presence: string;
  canonical_state: string;
  robots_allowed: boolean | null;
  indexability_state: string;
  recommendation_state: string | null;
  issue_count: number;
  highest_severity: Severity | null;
  partial: boolean;
};
export type AuditIssue = {
  issue_id: string;
  audit_page_id: string;
  code: IssueCode;
  category: IssueCategory;
  severity: Severity;
  summary: string;
  detail: string;
  determinacy: string;
  duplicate_group_id: string | null;
  url: string;
  status: number | null;
  content_type: string;
};
export type DuplicateGroup = {
  group_id: string;
  duplicate_type: 'title' | 'meta_description';
  sample_value: string;
  member_count: number;
};
export type Page<T> = {
  items: T[];
  page_size: number;
  returned_count: number;
  next_cursor: string | null;
  ordering: string;
};

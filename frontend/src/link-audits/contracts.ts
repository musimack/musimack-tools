export const LINK_AUDIT_UI_VERSION = 'seo-toolkit-link-audit-ui-v1' as const;

export const linkAuditStates = [
  'accepted',
  'claiming',
  'building_graph',
  'classifying_links',
  'expanding_redirects',
  'detecting_loops',
  'building_recommendations',
  'completed',
  'completed_with_warnings',
  'failed',
  'cancelled',
] as const;

export const linkActions = [
  'fix_link',
  'update_link_to_final_destination',
  'remove_link',
  'create_redirect',
  'replace_redirect',
  'review',
  'no_action',
] as const;

export type LinkAuditState = (typeof linkAuditStates)[number];
export type LinkAction = (typeof linkActions)[number];
export type LinkExportFormat =
  'broken_links_csv' | 'redirect_chains_csv' | 'redirect_map_csv' | 'json' | 'markdown';

export type LinkAudit = {
  audit_id: string;
  job_id: string;
  run_id: string;
  seed_url: string;
  state: LinkAuditState;
  failure_code: string | null;
  warning_count: number;
  link_occurrence_count: number;
  source_target_pair_count: number;
  target_count: number;
  working_target_count: number;
  broken_target_count: number;
  redirect_target_count: number;
  unverified_target_count: number;
  redirect_chain_count: number;
  redirect_loop_count: number;
  recommendation_count: number;
  created_at: string;
  completed_at: string | null;
};

export type LinkTarget = {
  target_id: string;
  target_url: string;
  broken_state: string;
  redirect_state: string;
  primary_reason: string;
  http_status: number | null;
  fetch_state: string | null;
  content_type: string | null;
  severity: string;
  action: LinkAction;
  confidence: string;
  final_target: string | null;
  redirect_hop_count: number;
  unique_source_page_count: number;
  total_occurrence_count: number;
  sitewide_candidate: boolean;
};

export type LinkPage<T> = {
  items: T[];
  page_size: number;
  returned_count: number;
  next_cursor: string | null;
  ordering: string;
  filters: Record<string, unknown>;
};

export type EvidenceStatus = {
  run_id: string;
  terminal: boolean;
  page_evidence_count: number;
  link_evidence_count: number;
  scope_available: boolean;
  compatible: boolean;
};

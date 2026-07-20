export const platformPresetIds = [
  'wordpress',
  'shopify',
  'squarespace',
  'wix',
  'custom',
  'none',
] as const;
export type PlatformPresetId = (typeof platformPresetIds)[number];

export const ruleMatchTypes = [
  'exact_url',
  'exact_path',
  'path_starts_with',
  'path_contains',
  'path_ends_with',
  'query_parameter_exists',
  'query_parameter_equals',
] as const;
export type RuleMatchType = (typeof ruleMatchTypes)[number];

export const ruleActions = [
  'exclude_from_discovery',
  'crawl_but_exclude_from_metadata_scoring',
  'crawl_but_exclude_from_sitemap',
  'crawl_and_mark_for_review',
  'strip_query_parameter',
] as const;
export type RuleAction = (typeof ruleActions)[number];

export type UrlRule = {
  rule_id: string;
  name: string;
  description: string;
  enabled: boolean;
  match_type: RuleMatchType;
  match_value: string;
  case_sensitive: boolean;
  action: RuleAction;
  reason: string;
  reason_code: string;
  source?: string;
  priority: number;
  scope?: string;
  overrides_rule_ids: string[];
  broad_rule_warning?: string | null;
};

export type Preset = {
  preset_id: PlatformPresetId;
  version: string;
  label: string;
  explanation: string;
  rules: UrlRule[];
  tracking_parameters: string[];
  acceptance_required: true;
};

export type GlobalConfiguration = {
  default_crawl_profile: string;
  default_platform_preset: PlatformPresetId | null;
  default_tracking_parameters: string[];
  default_url_rules: UrlRule[];
  metadata_thresholds: Record<string, number>;
  default_report_page_size: number;
  sitemap_policy: { pagination: string };
  specialist_summaries: Record<string, boolean>;
  maximum_retained_urls: number;
  maximum_export_rows: number;
};

export type GlobalSettings = {
  version: number;
  configuration: GlobalConfiguration;
  configuration_hash: string | null;
  created_by: string;
  created_at: string | null;
};

export type SiteProfileConfiguration = {
  site_label: string;
  authorized_seed: string;
  approved_hosts: string[];
  preset_id: PlatformPresetId | null;
  preset_version: string | null;
  preset_accepted: boolean;
  preset_rule_states: Record<string, boolean>;
  tracking_parameters_accepted: boolean;
  tracking_parameter_exceptions: string[];
  rules: UrlRule[];
  crawl_profile: string;
  crawl_limit_overrides: Record<string, number>;
  metadata_thresholds: Record<string, number>;
  enabled_modules: Record<string, boolean>;
  business_importance: Record<string, string>[];
};

export type SiteProfile = {
  profile_id: string;
  site_label: string;
  authorized_seed: string;
  seed_host: string;
  state: 'enabled' | 'disabled' | 'archived';
  current_version: number;
  updated_at: string;
  configuration: SiteProfileConfiguration;
};

export type ProfilePage = {
  items: SiteProfile[];
  offset: number;
  limit: number;
  total: number;
  ordering: string;
};

export type GovernanceRequest = {
  profile_id?: string | null;
  preset_id?: PlatformPresetId | null;
  preset_version?: string | null;
  preset_accepted?: boolean;
  preset_rule_states?: Record<string, boolean>;
  tracking_parameters_accepted?: boolean;
  tracking_parameter_exceptions?: string[];
  overrides?: Record<string, unknown>;
  sample_urls?: string[];
};

export type EffectiveSettings = Record<string, unknown> & {
  preset: Preset | null;
  preset_accepted: boolean;
  site_profile: { profile_id: string; site_label: string; version: number } | null;
  effective_rules: UrlRule[];
  disabled_inherited_rules: UrlRule[];
  warnings: string[];
  tracking_parameters: string[];
  tracking_parameters_accepted: boolean;
  bounds: Record<string, number>;
};

export type RuleTestResult = {
  effective_settings: EffectiveSettings;
  test: {
    results: Record<string, unknown>[];
    result_count: number;
    network_access: false;
    discoveries_created: false;
  };
};

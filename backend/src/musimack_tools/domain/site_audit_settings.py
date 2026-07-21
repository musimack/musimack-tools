"""Bounded, network-free Combined Site Audit settings and URL governance."""

# ruff: noqa: C901, PLR0911, PLR0913, PLR2004

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from musimack_tools.application.profiles import APPLICATION_HARD_MAXIMA, profile_for
from musimack_tools.crawl.normalization import normalize_hostname, normalize_url
from musimack_tools.domain.application import CrawlProfileName
from musimack_tools.domain.urls import UrlNormalizationError

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

SITE_AUDIT_SETTINGS_VERSION = "seo-toolkit-site-audit-settings-v1"
SITE_AUDIT_SETTINGS_API_VERSION = "seo-toolkit-site-audit-settings-api-v1"
SITE_AUDIT_RULE_VERSION = "seo-toolkit-site-audit-url-rule-v1"
SITE_AUDIT_PRESET_VERSION = "seo-toolkit-site-audit-preset-v1"
SITE_AUDIT_PROFILE_VERSION = "seo-toolkit-site-audit-profile-v1"
SITE_AUDIT_NORMALIZATION_VERSION = "seo-toolkit-site-audit-normalization-v1"
SITE_AUDIT_PRECEDENCE_VERSION = "seo-toolkit-site-audit-precedence-v1"

MAXIMUM_RULES_PER_SOURCE = 500
MAXIMUM_RULE_NAME_LENGTH = 128
MAXIMUM_RULE_MATCH_VALUE_LENGTH = 2_048
MAXIMUM_RULE_DESCRIPTION_LENGTH = 1_000
MAXIMUM_RULE_REASON_LENGTH = 1_000
MAXIMUM_RULE_OVERRIDE_IDS = 100
MAXIMUM_PER_AUDIT_RULES = 100
MAXIMUM_RULE_TEST_URLS = 100
MAXIMUM_RULE_PREVIEW_RESULTS = 500
MAXIMUM_API_PAGE_SIZE = 500
MAXIMUM_BROWSER_ALL_ROWS = 5_000
MAXIMUM_RETAINED_URLS = 100_000
MAXIMUM_EXPORT_ROWS = 100_000
DEFAULT_REPORT_PAGE_SIZE = 50
TRACKING_PARAMETERS = (
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "msclkid",
)

_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
_REASON_CODE = re.compile(r"[a-z0-9][a-z0-9_]{0,63}\Z")
_QUERY_NAME = re.compile(r"[^&=\x00-\x20\x7f]{1,128}\Z")
_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_PERCENT_ESCAPE = re.compile(r"%([0-9A-Fa-f]{2})")
_SOURCE_ORDER: dict[RuleSource, int]
_SPECIFICITY: dict[RuleMatchType, int]
_BUILTIN_TIME = "2026-07-20T00:00:00+00:00"


class SiteAuditSettingsError(ValueError):
    """Stable safe failure raised at the CSA settings boundary."""

    def __init__(self, code: str, explanation: str) -> None:
        super().__init__(code)
        self.code = code
        self.explanation = explanation


class RuleMatchType(StrEnum):
    EXACT_URL = "exact_url"
    EXACT_PATH = "exact_path"
    PATH_STARTS_WITH = "path_starts_with"
    PATH_CONTAINS = "path_contains"
    PATH_ENDS_WITH = "path_ends_with"
    QUERY_PARAMETER_EXISTS = "query_parameter_exists"
    QUERY_PARAMETER_EQUALS = "query_parameter_equals"


class RuleAction(StrEnum):
    EXCLUDE_FROM_DISCOVERY = "exclude_from_discovery"
    EXCLUDE_FROM_METADATA = "crawl_but_exclude_from_metadata_scoring"
    EXCLUDE_FROM_SITEMAP = "crawl_but_exclude_from_sitemap"
    MARK_FOR_REVIEW = "crawl_and_mark_for_review"
    STRIP_QUERY_PARAMETER = "strip_query_parameter"


class RuleSource(StrEnum):
    GLOBAL = "global"
    PRESET = "preset"
    SITE_PROFILE = "site_profile"
    PER_AUDIT = "per_audit"


class RuleScope(StrEnum):
    DISCOVERY = "discovery"
    METADATA = "metadata"
    SITEMAP = "sitemap"
    ALL_DECISIONS = "all_decisions"
    NORMALIZATION = "normalization"


class DecisionLayer(StrEnum):
    NORMALIZATION = "normalization"
    DISCOVERY = "discovery"
    METADATA = "metadata_scoring"
    SITEMAP = "sitemap"


class PlatformPresetId(StrEnum):
    WORDPRESS = "wordpress"
    SHOPIFY = "shopify"
    SQUARESPACE = "squarespace"
    WIX = "wix"
    CUSTOM = "custom"
    NONE = "none"


class ProfileState(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    ARCHIVED = "archived"


class BusinessImportance(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NOT_ASSIGNED = "not_assigned"


_SOURCE_ORDER = {
    RuleSource.GLOBAL: 0,
    RuleSource.PRESET: 1,
    RuleSource.SITE_PROFILE: 2,
    RuleSource.PER_AUDIT: 3,
}
_SPECIFICITY = {
    RuleMatchType.EXACT_URL: 6,
    RuleMatchType.EXACT_PATH: 5,
    RuleMatchType.QUERY_PARAMETER_EQUALS: 4,
    RuleMatchType.QUERY_PARAMETER_EXISTS: 3,
    RuleMatchType.PATH_STARTS_WITH: 2,
    RuleMatchType.PATH_ENDS_WITH: 2,
    RuleMatchType.PATH_CONTAINS: 1,
}


@dataclass(frozen=True, slots=True)
class UrlGovernanceRule:
    rule_id: str
    name: str
    description: str
    enabled: bool
    match_type: RuleMatchType
    match_value: str
    case_sensitive: bool
    action: RuleAction
    reason: str
    reason_code: str
    source: RuleSource
    priority: int
    scope: RuleScope
    overrides_rule_ids: tuple[str, ...]
    created_by: str
    created_at: str
    updated_at: str
    version: int = 1
    preset_id: str | None = None
    preset_version: str | None = None
    site_profile_id: str | None = None

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.rule_id):
            raise SiteAuditSettingsError("site_audit_rule_id_invalid", "Rule ID is invalid.")
        if not self.name.strip() or len(self.name) > MAXIMUM_RULE_NAME_LENGTH:
            raise SiteAuditSettingsError("site_audit_rule_name_invalid", "Rule name is invalid.")
        if len(self.description) > MAXIMUM_RULE_DESCRIPTION_LENGTH:
            raise SiteAuditSettingsError(
                "site_audit_rule_description_invalid", "Rule description is too long."
            )
        if not self.match_value or len(self.match_value) > MAXIMUM_RULE_MATCH_VALUE_LENGTH:
            raise SiteAuditSettingsError(
                "site_audit_rule_match_invalid", "Rule match value is invalid."
            )
        if not self.reason.strip() or len(self.reason) > MAXIMUM_RULE_REASON_LENGTH:
            raise SiteAuditSettingsError(
                "site_audit_rule_reason_invalid", "Rule reason is invalid."
            )
        if not _REASON_CODE.fullmatch(self.reason_code):
            raise SiteAuditSettingsError(
                "site_audit_rule_reason_code_invalid", "Rule reason code is invalid."
            )
        if not 0 <= self.priority <= 100_000:
            raise SiteAuditSettingsError(
                "site_audit_rule_priority_invalid", "Rule priority is out of bounds."
            )
        if not 1 <= self.version <= 1_000_000:
            raise SiteAuditSettingsError(
                "site_audit_rule_version_invalid", "Rule version is invalid."
            )
        if len(self.overrides_rule_ids) > MAXIMUM_RULE_OVERRIDE_IDS or len(
            set(self.overrides_rule_ids)
        ) != len(self.overrides_rule_ids):
            raise SiteAuditSettingsError(
                "site_audit_rule_override_invalid", "Rule override IDs are invalid."
            )
        if self.rule_id in self.overrides_rule_ids or any(
            not _IDENTIFIER.fullmatch(item) for item in self.overrides_rule_ids
        ):
            raise SiteAuditSettingsError(
                "site_audit_rule_override_invalid", "Rule override IDs are invalid."
            )
        _validate_match(self.match_type, self.match_value)
        _validate_action_scope(self.action, self.scope)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "description": self.description,
            "enabled": self.enabled,
            "match_type": self.match_type.value,
            "match_value": self.match_value,
            "case_sensitive": self.case_sensitive,
            "action": self.action.value,
            "reason": self.reason,
            "reason_code": self.reason_code,
            "source": self.source.value,
            "priority": self.priority,
            "scope": self.scope.value,
            "overrides_rule_ids": list(self.overrides_rule_ids),
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "version": self.version,
            "preset_id": self.preset_id,
            "preset_version": self.preset_version,
            "site_profile_id": self.site_profile_id,
            "decision_layers": [item.value for item in decision_layers(self)],
            "broad_rule_warning": broad_rule_warning(self),
            "rule_version": SITE_AUDIT_RULE_VERSION,
        }


@dataclass(frozen=True, slots=True)
class PlatformPreset:
    preset_id: PlatformPresetId
    version: str
    label: str
    explanation: str
    rules: tuple[UrlGovernanceRule, ...]
    tracking_parameters: tuple[str, ...] = TRACKING_PARAMETERS

    def __post_init__(self) -> None:
        _validate_rule_count(self.rules)
        if len({item.rule_id for item in self.rules}) != len(self.rules):
            raise SiteAuditSettingsError(
                "site_audit_preset_rule_invalid", "Preset rule IDs must be unique."
            )
        _validate_parameter_names(self.tracking_parameters)

    def to_dict(self) -> dict[str, Any]:
        return {
            "preset_id": self.preset_id.value,
            "version": self.version,
            "label": self.label,
            "explanation": self.explanation,
            "rules": [item.to_dict() for item in self.rules],
            "tracking_parameters": list(self.tracking_parameters),
            "acceptance_required": True,
            "preset_version": SITE_AUDIT_PRESET_VERSION,
        }


@dataclass(frozen=True, slots=True)
class GlobalSiteAuditSettings:
    default_crawl_profile: CrawlProfileName = CrawlProfileName.STANDARD_CRAWL
    default_platform_preset: PlatformPresetId | None = None
    default_tracking_parameters: tuple[str, ...] = TRACKING_PARAMETERS
    default_url_rules: tuple[UrlGovernanceRule, ...] = ()
    title_minimum: int = 30
    title_maximum: int = 60
    description_minimum: int = 70
    description_maximum: int = 160
    default_report_page_size: int = DEFAULT_REPORT_PAGE_SIZE
    pagination_sitemap_policy: str = "review"
    image_summary_enabled: bool = True
    structured_data_summary_enabled: bool = True
    maximum_retained_urls: int = MAXIMUM_RETAINED_URLS
    maximum_export_rows: int = MAXIMUM_EXPORT_ROWS

    def __post_init__(self) -> None:
        if profile_for(self.default_crawl_profile) is None:
            raise SiteAuditSettingsError(
                "site_audit_crawl_profile_invalid", "Default crawl profile is invalid."
            )
        _validate_rule_count(self.default_url_rules)
        if not 1 <= self.title_minimum <= self.title_maximum <= 512:
            raise SiteAuditSettingsError(
                "site_audit_threshold_invalid", "Title thresholds are invalid."
            )
        if not 1 <= self.description_minimum <= self.description_maximum <= 2_048:
            raise SiteAuditSettingsError(
                "site_audit_threshold_invalid", "Description thresholds are invalid."
            )
        if self.default_report_page_size not in {50, 100, 500}:
            raise SiteAuditSettingsError(
                "site_audit_page_size_invalid", "Default report page size is invalid."
            )
        if self.pagination_sitemap_policy != "review":
            raise SiteAuditSettingsError(
                "site_audit_sitemap_policy_invalid",
                "Pagination must default to sitemap review.",
            )
        if self.maximum_retained_urls != MAXIMUM_RETAINED_URLS or self.maximum_export_rows != (
            MAXIMUM_EXPORT_ROWS
        ):
            raise SiteAuditSettingsError(
                "site_audit_protected_limit_invalid", "Protected audit limits cannot be changed."
            )
        _validate_parameter_names(self.default_tracking_parameters)

    def to_dict(self) -> dict[str, Any]:
        return {
            "default_crawl_profile": self.default_crawl_profile.value,
            "default_platform_preset": (
                self.default_platform_preset.value if self.default_platform_preset else None
            ),
            "default_tracking_parameters": list(self.default_tracking_parameters),
            "default_url_rules": [item.to_dict() for item in self.default_url_rules],
            "metadata_thresholds": {
                "title_minimum": self.title_minimum,
                "title_maximum": self.title_maximum,
                "description_minimum": self.description_minimum,
                "description_maximum": self.description_maximum,
            },
            "default_report_page_size": self.default_report_page_size,
            "sitemap_policy": {"pagination": self.pagination_sitemap_policy},
            "specialist_summaries": {
                "images": self.image_summary_enabled,
                "structured_data": self.structured_data_summary_enabled,
            },
            "maximum_retained_urls": self.maximum_retained_urls,
            "maximum_export_rows": self.maximum_export_rows,
            "settings_version": SITE_AUDIT_SETTINGS_VERSION,
        }


@dataclass(frozen=True, slots=True)
class SiteProfileConfiguration:
    site_label: str
    authorized_seed: str
    approved_hosts: tuple[str, ...]
    preset_id: PlatformPresetId | None
    preset_version: str | None
    preset_accepted: bool
    preset_rule_states: tuple[tuple[str, bool], ...]
    tracking_parameters_accepted: bool
    tracking_parameter_exceptions: tuple[str, ...]
    rules: tuple[UrlGovernanceRule, ...]
    crawl_profile: CrawlProfileName
    crawl_limit_overrides: tuple[tuple[str, int | float], ...]
    metadata_thresholds: tuple[tuple[str, int], ...]
    enabled_modules: tuple[tuple[str, bool], ...]
    business_importance: tuple[tuple[str, str, str], ...]

    def __post_init__(self) -> None:  # noqa: PLR0912
        if not self.site_label.strip() or len(self.site_label) > 200:
            raise SiteAuditSettingsError(
                "site_profile_label_invalid", "Site profile label is invalid."
            )
        try:
            seed = normalize_url(self.authorized_seed)
        except UrlNormalizationError as error:
            raise SiteAuditSettingsError(
                "site_profile_seed_invalid", "Authorized seed is invalid."
            ) from error
        if not self.approved_hosts or len(self.approved_hosts) > 100:
            raise SiteAuditSettingsError(
                "site_profile_hosts_invalid", "Approved hosts are invalid."
            )
        normalized_hosts = tuple(normalize_hostname(item) for item in self.approved_hosts)
        if (
            len(set(normalized_hosts)) != len(normalized_hosts)
            or seed.hostname not in normalized_hosts
        ):
            raise SiteAuditSettingsError(
                "site_profile_hosts_invalid",
                "Approved hosts must be unique and include the seed host.",
            )
        if self.preset_accepted != (self.preset_id is not None and self.preset_version is not None):
            raise SiteAuditSettingsError(
                "site_profile_preset_acceptance_invalid",
                "Preset identity and version require explicit acceptance.",
            )
        if self.tracking_parameters_accepted and not self.preset_accepted:
            raise SiteAuditSettingsError(
                "site_audit_tracking_acceptance_invalid",
                "Tracking parameters require explicit preset acceptance.",
            )
        if profile_for(self.crawl_profile) is None:
            raise SiteAuditSettingsError(
                "site_audit_crawl_profile_invalid", "Crawl profile is invalid."
            )
        _validate_rule_count(self.rules)
        _validate_parameter_names(self.tracking_parameter_exceptions)
        _validate_crawl_overrides(dict(self.crawl_limit_overrides))
        _validate_metadata_thresholds(dict(self.metadata_thresholds))
        if any(key not in {"images", "structured_data"} for key, _enabled in self.enabled_modules):
            raise SiteAuditSettingsError(
                "site_audit_modules_invalid", "Enabled specialist modules are invalid."
            )
        if len(self.business_importance) > MAXIMUM_RULES_PER_SOURCE:
            raise SiteAuditSettingsError(
                "site_profile_business_importance_invalid",
                "Business-importance assignments exceed the limit.",
            )
        for kind, value, importance in self.business_importance:
            if kind not in {"url", "url_family", "page_type", "section", "site_profile"}:
                raise SiteAuditSettingsError(
                    "site_profile_business_importance_invalid",
                    "Business-importance assignment type is invalid.",
                )
            if not value or len(value) > MAXIMUM_RULE_MATCH_VALUE_LENGTH:
                raise SiteAuditSettingsError(
                    "site_profile_business_importance_invalid",
                    "Business-importance assignment value is invalid.",
                )
            try:
                BusinessImportance(importance)
            except ValueError as error:
                raise SiteAuditSettingsError(
                    "site_profile_business_importance_invalid",
                    "Business importance is invalid.",
                ) from error

    def to_dict(self) -> dict[str, Any]:
        return {
            "site_label": self.site_label,
            "authorized_seed": normalize_url(self.authorized_seed).normalized,
            "approved_hosts": [normalize_hostname(item) for item in self.approved_hosts],
            "preset_id": self.preset_id.value if self.preset_id else None,
            "preset_version": self.preset_version,
            "preset_accepted": self.preset_accepted,
            "preset_rule_states": dict(self.preset_rule_states),
            "tracking_parameters_accepted": self.tracking_parameters_accepted,
            "tracking_parameter_exceptions": list(self.tracking_parameter_exceptions),
            "rules": [item.to_dict() for item in self.rules],
            "crawl_profile": self.crawl_profile.value,
            "crawl_limit_overrides": dict(self.crawl_limit_overrides),
            "metadata_thresholds": dict(self.metadata_thresholds),
            "enabled_modules": dict(self.enabled_modules),
            "business_importance": [
                {"target_type": kind, "target": value, "importance": importance}
                for kind, value, importance in self.business_importance
            ],
            "profile_contract_version": SITE_AUDIT_PROFILE_VERSION,
        }


def default_global_settings() -> GlobalSiteAuditSettings:
    return GlobalSiteAuditSettings(default_url_rules=())


def builtin_presets() -> tuple[PlatformPreset, ...]:
    """Return immutable preset definitions; none is active without explicit acceptance."""
    return (
        PlatformPreset(
            PlatformPresetId.WORDPRESS,
            "wordpress-1",
            "WordPress",
            "Visible WordPress URL governance suggestions. Every rule can be disabled.",
            _wordpress_rules(),
        ),
        PlatformPreset(
            PlatformPresetId.SHOPIFY,
            "shopify-1",
            "Shopify",
            "Optional Shopify URL governance suggestions.",
            (),
        ),
        PlatformPreset(
            PlatformPresetId.SQUARESPACE,
            "squarespace-1",
            "Squarespace",
            "Optional Squarespace URL governance suggestions.",
            (),
        ),
        PlatformPreset(
            PlatformPresetId.WIX,
            "wix-1",
            "Wix",
            "Optional Wix URL governance suggestions.",
            (),
        ),
        PlatformPreset(
            PlatformPresetId.CUSTOM,
            "custom-1",
            "Custom",
            "No platform rules are applied; the complete core workflow remains available.",
            (),
            (),
        ),
        PlatformPreset(
            PlatformPresetId.NONE,
            "none-1",
            "No preset",
            "No platform rules or tracking parameters are suggested.",
            (),
            (),
        ),
    )


def preset_for(preset_id: PlatformPresetId | str, version: str | None = None) -> PlatformPreset:
    try:
        parsed = PlatformPresetId(preset_id)
    except ValueError as error:
        raise SiteAuditSettingsError(
            "site_audit_preset_not_found", "Preset was not found."
        ) from error
    item = next(value for value in builtin_presets() if value.preset_id is parsed)
    if version is not None and version != item.version:
        raise SiteAuditSettingsError(
            "site_audit_preset_version_not_found", "Preset version was not found."
        )
    return item


def rule_from_mapping(
    value: Mapping[str, Any],
    *,
    source: RuleSource,
    created_by: str,
    now: str,
    preset_id: str | None = None,
    preset_version: str | None = None,
    site_profile_id: str | None = None,
) -> UrlGovernanceRule:
    try:
        match_type = RuleMatchType(str(value["match_type"]))
        action = RuleAction(str(value["action"]))
        scope = RuleScope(str(value.get("scope") or _default_scope(action).value))
        override_value = value.get("overrides_rule_ids", ())
        if not isinstance(override_value, (list, tuple)):
            raise SiteAuditSettingsError(
                "site_audit_rule_override_invalid", "Rule override IDs are invalid."
            )
        return UrlGovernanceRule(
            str(value["rule_id"]),
            str(value["name"]),
            str(value.get("description", "")),
            bool(value.get("enabled", True)),
            match_type,
            str(value["match_value"]),
            bool(value.get("case_sensitive", True)),
            action,
            str(value["reason"]),
            str(value["reason_code"]),
            source,
            int(value.get("priority", 0)),
            scope,
            tuple(str(item) for item in override_value),
            str(value.get("created_by", created_by)),
            str(value.get("created_at", now)),
            str(value.get("updated_at", now)),
            int(value.get("version", 1)),
            preset_id,
            preset_version,
            site_profile_id,
        )
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, SiteAuditSettingsError):
            raise
        raise SiteAuditSettingsError("site_audit_rule_invalid", "URL rule is invalid.") from error


def global_settings_from_mapping(
    value: Mapping[str, Any], *, created_by: str, now: str
) -> GlobalSiteAuditSettings:
    raw_rules = value.get("default_url_rules", ())
    if not isinstance(raw_rules, (list, tuple)):
        raise SiteAuditSettingsError("site_audit_rule_invalid", "Default URL rules are invalid.")
    rule_values = _rule_mappings(raw_rules, explanation="Default URL rules are invalid.")
    rules = tuple(
        rule_from_mapping(item, source=RuleSource.GLOBAL, created_by=created_by, now=now)
        for item in rule_values
    )
    thresholds = _mapping(value.get("metadata_thresholds", {}))
    sitemap = _mapping(value.get("sitemap_policy", {}))
    summaries = _mapping(value.get("specialist_summaries", {}))
    raw_tracking = value.get("default_tracking_parameters", TRACKING_PARAMETERS)
    if not isinstance(raw_tracking, (list, tuple)):
        raise SiteAuditSettingsError(
            "site_audit_tracking_parameters_invalid", "Tracking parameters are invalid."
        )
    try:
        raw_preset = value.get("default_platform_preset")
        return GlobalSiteAuditSettings(
            CrawlProfileName(str(value.get("default_crawl_profile", "standard_crawl"))),
            PlatformPresetId(str(raw_preset)) if raw_preset else None,
            tuple(str(item) for item in raw_tracking),
            rules,
            int(thresholds.get("title_minimum", 30)),
            int(thresholds.get("title_maximum", 60)),
            int(thresholds.get("description_minimum", 70)),
            int(thresholds.get("description_maximum", 160)),
            int(value.get("default_report_page_size", DEFAULT_REPORT_PAGE_SIZE)),
            str(sitemap.get("pagination", "review")),
            bool(summaries.get("images", True)),
            bool(summaries.get("structured_data", True)),
            int(value.get("maximum_retained_urls", MAXIMUM_RETAINED_URLS)),
            int(value.get("maximum_export_rows", MAXIMUM_EXPORT_ROWS)),
        )
    except (TypeError, ValueError) as error:
        if isinstance(error, SiteAuditSettingsError):
            raise
        raise SiteAuditSettingsError(
            "site_audit_settings_invalid", "Global site-audit settings are invalid."
        ) from error


def profile_configuration_from_mapping(
    value: Mapping[str, Any], *, profile_id: str, created_by: str, now: str
) -> SiteProfileConfiguration:
    raw_rules = value.get("rules", ())
    if not isinstance(raw_rules, (list, tuple)):
        raise SiteAuditSettingsError("site_audit_rule_invalid", "Profile rules are invalid.")
    rule_values = _rule_mappings(raw_rules, explanation="Profile rules are invalid.")
    rules = tuple(
        rule_from_mapping(
            item,
            source=RuleSource.SITE_PROFILE,
            created_by=created_by,
            now=now,
            site_profile_id=profile_id,
        )
        for item in rule_values
    )
    preset_value = value.get("preset_id")
    raw_hosts = value.get("approved_hosts", ())
    if not isinstance(raw_hosts, (list, tuple)):
        raise SiteAuditSettingsError("site_profile_hosts_invalid", "Approved hosts are invalid.")
    raw_states = _mapping(value.get("preset_rule_states", {}))
    raw_exceptions = value.get("tracking_parameter_exceptions", ())
    raw_importance = value.get("business_importance", ())
    if not isinstance(raw_exceptions, (list, tuple)) or not isinstance(
        raw_importance, (list, tuple)
    ):
        raise SiteAuditSettingsError("site_profile_invalid", "Site profile is invalid.")
    importance: list[tuple[str, str, str]] = []
    for item in raw_importance:
        if not isinstance(item, Mapping):
            raise SiteAuditSettingsError(
                "site_profile_business_importance_invalid",
                "Business-importance assignment is invalid.",
            )
        importance.append(
            (
                str(item.get("target_type", "")),
                str(item.get("target", "")),
                str(item.get("importance", "")),
            )
        )
    try:
        return SiteProfileConfiguration(
            str(value["site_label"]),
            str(value["authorized_seed"]),
            tuple(str(item) for item in raw_hosts),
            PlatformPresetId(str(preset_value)) if preset_value else None,
            str(value["preset_version"]) if value.get("preset_version") else None,
            bool(value.get("preset_accepted", False)),
            tuple(sorted((str(key), bool(setting)) for key, setting in raw_states.items())),
            bool(value.get("tracking_parameters_accepted", False)),
            tuple(str(item) for item in raw_exceptions),
            rules,
            CrawlProfileName(str(value.get("crawl_profile", "standard_crawl"))),
            tuple(sorted(_number_mapping(value.get("crawl_limit_overrides", {})).items())),
            tuple(sorted(_integer_mapping(value.get("metadata_thresholds", {})).items())),
            tuple(
                sorted(
                    (str(key), bool(setting))
                    for key, setting in _mapping(value.get("enabled_modules", {})).items()
                )
            ),
            tuple(importance),
        )
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, SiteAuditSettingsError):
            raise
        raise SiteAuditSettingsError("site_profile_invalid", "Site profile is invalid.") from error


def canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def broad_rule_warning(rule: UrlGovernanceRule) -> str | None:
    if rule.match_type is RuleMatchType.PATH_CONTAINS and len(rule.match_value) < 3:
        return "site_audit_rule_broad_path_contains"
    if rule.match_type in {RuleMatchType.PATH_STARTS_WITH, RuleMatchType.EXACT_PATH} and (
        rule.match_value == "/"
    ):
        return "site_audit_rule_broad_root_path"
    if rule.match_type is RuleMatchType.QUERY_PARAMETER_EXISTS and rule.action is (
        RuleAction.EXCLUDE_FROM_DISCOVERY
    ):
        return "site_audit_rule_broad_query_exclusion"
    return None


def decision_layers(rule: UrlGovernanceRule) -> tuple[DecisionLayer, ...]:
    if rule.action is RuleAction.STRIP_QUERY_PARAMETER:
        return (DecisionLayer.NORMALIZATION,)
    if rule.action is RuleAction.EXCLUDE_FROM_DISCOVERY:
        return (DecisionLayer.DISCOVERY,)
    if rule.action is RuleAction.EXCLUDE_FROM_METADATA:
        return (DecisionLayer.DISCOVERY, DecisionLayer.METADATA)
    if rule.action is RuleAction.EXCLUDE_FROM_SITEMAP:
        return (DecisionLayer.DISCOVERY, DecisionLayer.SITEMAP)
    return (
        (DecisionLayer.DISCOVERY, DecisionLayer.SITEMAP)
        if rule.scope in {RuleScope.SITEMAP, RuleScope.ALL_DECISIONS}
        else (DecisionLayer.DISCOVERY,)
    )


def validate_rule_set(rules: Sequence[UrlGovernanceRule]) -> tuple[str, ...]:
    _validate_rule_count(rules)
    identifiers = {item.rule_id for item in rules}
    if len(identifiers) != len(rules):
        raise SiteAuditSettingsError("site_audit_rule_id_conflict", "Rule IDs must be unique.")
    by_id = {item.rule_id: item for item in rules}
    warnings: list[str] = []
    for rule in rules:
        warning = broad_rule_warning(rule)
        if warning:
            warnings.append(warning)
        for target_id in rule.overrides_rule_ids:
            target = by_id.get(target_id)
            if target is None or _SOURCE_ORDER[target.source] >= _SOURCE_ORDER[rule.source]:
                raise SiteAuditSettingsError(
                    "site_audit_rule_override_invalid",
                    "Rule overrides must target an inherited lower-source rule.",
                )
            if not set(decision_layers(target)).intersection(decision_layers(rule)):
                raise SiteAuditSettingsError(
                    "site_audit_rule_override_invalid",
                    "Rule overrides must target the same decision layer.",
                )
    return tuple(sorted(set(warnings)))


def resolve_effective_rules(
    global_rules: Sequence[UrlGovernanceRule],
    *,
    preset: PlatformPreset | None = None,
    preset_accepted: bool = False,
    preset_rule_states: Mapping[str, bool] | None = None,
    profile_rules: Sequence[UrlGovernanceRule] = (),
    per_audit_rules: Sequence[UrlGovernanceRule] = (),
    disabled_rule_ids: Sequence[str] = (),
) -> tuple[tuple[UrlGovernanceRule, ...], tuple[UrlGovernanceRule, ...], tuple[str, ...]]:
    rules: list[UrlGovernanceRule] = list(global_rules)
    if preset_accepted:
        if preset is None:
            raise SiteAuditSettingsError(
                "site_audit_preset_acceptance_invalid", "Accepted preset is missing."
            )
        states = preset_rule_states or {}
        preset_rule_ids = {item.rule_id for item in preset.rules}
        if set(states) - preset_rule_ids:
            raise SiteAuditSettingsError(
                "site_audit_preset_rule_invalid", "Preset rule selection is invalid."
            )
        rules.extend(
            replace(item, enabled=states.get(item.rule_id, item.enabled)) for item in preset.rules
        )
    rules.extend(profile_rules)
    rules.extend(per_audit_rules)
    disabled = set(disabled_rule_ids)
    known = {item.rule_id: item for item in rules}
    if disabled - known.keys() or any(
        known[rule_id].source is RuleSource.PER_AUDIT for rule_id in disabled
    ):
        raise SiteAuditSettingsError(
            "site_audit_disabled_rule_invalid",
            "Disabled rule IDs must identify inherited rules.",
        )
    effective = _ordered_rules(
        item for item in rules if item.enabled and item.rule_id not in disabled
    )
    disabled_rules = tuple(
        sorted(
            (item for item in rules if not item.enabled or item.rule_id in disabled),
            key=lambda item: (item.source.value, item.rule_id),
        )
    )
    warnings = validate_rule_set(tuple(rules))
    return effective, disabled_rules, warnings


def test_rule_set(
    rules: Sequence[UrlGovernanceRule],
    sample_urls: Sequence[str],
    *,
    tracking_parameters: Sequence[str] = (),
    tracking_accepted: bool = False,
    parameter_exceptions: Sequence[str] = (),
) -> dict[str, Any]:
    if not 1 <= len(sample_urls) <= MAXIMUM_RULE_TEST_URLS:
        raise SiteAuditSettingsError(
            "site_audit_rule_test_limit", "Rule test URL count is out of bounds."
        )
    warnings = validate_rule_set(rules)
    _validate_parameter_names(tracking_parameters)
    _validate_parameter_names(parameter_exceptions)
    strip_names = set(tracking_parameters if tracking_accepted else ())
    strip_names.difference_update(parameter_exceptions)
    for rule in rules:
        if rule.enabled and rule.action is RuleAction.STRIP_QUERY_PARAMETER:
            strip_names.add(_query_rule_name(rule))
    normalized = [
        normalize_governed_url(value, strip_parameters=strip_names) for value in sample_urls
    ]
    collision_members: dict[str, list[str]] = {}
    for item in normalized:
        collision_members.setdefault(str(item["normalized_url"]), []).append(
            str(item["original_url"])
        )
    results: list[dict[str, Any]] = []
    for item in normalized:
        original_normalized = str(item["syntax_normalized_url"])
        matched = tuple(
            rule for rule in rules if rule.enabled and rule_matches(rule, original_normalized)
        )
        decisions = _resolve_decisions(matched)
        collision = collision_members[str(item["normalized_url"])]
        results.append(
            {
                **item,
                "matched": bool(matched),
                "matches": [rule.to_dict() for rule in _ordered_rules(matched)],
                "match_types": sorted({rule.match_type.value for rule in matched}),
                "applied_actions": sorted({rule.action.value for rule in matched}),
                "decision_layers": sorted(decisions),
                "reasons": [rule.reason for rule in _ordered_rules(matched)],
                "decisions": decisions,
                "primary_rule": next(
                    (
                        value["primary_rule"]
                        for value in decisions.values()
                        if value["primary_rule"] is not None
                    ),
                    None,
                ),
                "contributing_rules": [rule.rule_id for rule in _ordered_rules(matched)],
                "conflict": any(bool(value["conflict"]) for value in decisions.values()),
                "collision_group": (
                    {
                        "collision_id": hashlib.sha256(
                            str(item["normalized_url"]).encode()
                        ).hexdigest()[:16],
                        "members": collision,
                    }
                    if len(set(collision)) > 1
                    else None
                ),
                "validation_warnings": sorted(
                    set(
                        warnings
                        + tuple(
                            warning
                            for rule in matched
                            if (warning := broad_rule_warning(rule)) is not None
                        )
                    )
                ),
                "normalization_result": {
                    "syntax_normalized_url": item["syntax_normalized_url"],
                    "normalized_url": item["normalized_url"],
                    "removed_parameters": item["removed_parameters"],
                    "normalization_applied": item["normalization_applied"],
                    "fragment_removed": item["fragment_removed"],
                },
            }
        )
    return {
        "results": results,
        "result_count": len(results),
        "network_access": False,
        "discoveries_created": False,
        "normalization_version": SITE_AUDIT_NORMALIZATION_VERSION,
        "precedence_version": SITE_AUDIT_PRECEDENCE_VERSION,
    }


def normalize_governed_url(value: str, *, strip_parameters: Iterable[str] = ()) -> dict[str, Any]:
    try:
        base = normalize_url(value)
    except UrlNormalizationError as error:
        raise SiteAuditSettingsError("site_audit_url_invalid", "Sample URL is invalid.") from error
    split = urlsplit(base.normalized)
    path = _decode_unreserved(split.path)
    pairs = parse_qsl(split.query, keep_blank_values=True)
    sorted_pairs = sorted(enumerate(pairs), key=lambda item: (item[1][0], item[1][1], item[0]))
    syntax_query = urlencode([pair for _, pair in sorted_pairs], doseq=True)
    syntax_url = urlunsplit((split.scheme, split.netloc, path, syntax_query, ""))
    stripped = set(strip_parameters)
    retained = [pair for _, pair in sorted_pairs if pair[0] not in stripped]
    removed = [pair for _, pair in sorted_pairs if pair[0] in stripped]
    normalized_query = urlencode(retained, doseq=True)
    normalized_value = urlunsplit((split.scheme, split.netloc, path, normalized_query, ""))
    return {
        "original_url": value,
        "syntax_normalized_url": syntax_url,
        "normalized_url": normalized_value,
        "removed_parameters": [name for name, _ in removed],
        "normalization_applied": bool(removed) or value != normalized_value,
        "fragment_removed": bool(urlsplit(value).fragment),
    }


def rule_matches(rule: UrlGovernanceRule, url: str) -> bool:
    try:
        normalized = normalize_governed_url(url)["syntax_normalized_url"]
    except SiteAuditSettingsError:
        return False
    value = str(normalized)
    parts = urlsplit(value)
    left = rule.match_value if rule.case_sensitive else rule.match_value.casefold()
    if rule.match_type is RuleMatchType.EXACT_URL:
        try:
            expected = str(normalize_governed_url(rule.match_value)["syntax_normalized_url"])
        except SiteAuditSettingsError:
            return False
        return value == expected if rule.case_sensitive else value.casefold() == expected.casefold()
    path = parts.path if rule.case_sensitive else parts.path.casefold()
    if rule.match_type is RuleMatchType.EXACT_PATH:
        return path == left
    if rule.match_type is RuleMatchType.PATH_STARTS_WITH:
        return path.startswith(left)
    if rule.match_type is RuleMatchType.PATH_CONTAINS:
        return left in path
    if rule.match_type is RuleMatchType.PATH_ENDS_WITH:
        return path.endswith(left)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    if not rule.case_sensitive:
        pairs = [(name.casefold(), item.casefold()) for name, item in pairs]
    if rule.match_type is RuleMatchType.QUERY_PARAMETER_EXISTS:
        return any(name == left for name, _ in pairs)
    name, expected = _split_query_equals(rule.match_value)
    if not rule.case_sensitive:
        name, expected = name.casefold(), expected.casefold()
    return any(item_name == name and item_value == expected for item_name, item_value in pairs)


def protected_boundaries() -> dict[str, Any]:
    return {
        "ssrf": "enforced",
        "dns_safety": "enforced",
        "redirect_safety": "enforced",
        "authentication": "enforced",
        "authorization": "enforced",
        "approved_host_scope": "enforced",
        "artifact_security": "enforced",
        "export_limits": "enforced",
        "crawl_hard_maxima": {
            "maximum_urls": APPLICATION_HARD_MAXIMA.maximum_urls,
            "maximum_depth": APPLICATION_HARD_MAXIMA.maximum_depth,
            "maximum_duration_seconds": APPLICATION_HARD_MAXIMA.maximum_duration_seconds,
            "maximum_accepted_bytes": APPLICATION_HARD_MAXIMA.maximum_accepted_bytes,
            "maximum_concurrency": APPLICATION_HARD_MAXIMA.maximum_concurrency,
            "maximum_queue_size": APPLICATION_HARD_MAXIMA.maximum_queue_size,
            "minimum_request_delay_seconds": APPLICATION_HARD_MAXIMA.minimum_request_delay_seconds,
            "maximum_redirect_hops": APPLICATION_HARD_MAXIMA.maximum_redirect_hops,
            "maximum_response_bytes": APPLICATION_HARD_MAXIMA.maximum_response_bytes,
        },
    }


def _wordpress_rules() -> tuple[UrlGovernanceRule, ...]:
    rules: list[UrlGovernanceRule] = []

    def add(
        rule_id: str,
        name: str,
        match_type: RuleMatchType,
        match_value: str,
        action: RuleAction,
        reason_code: str,
        *,
        enabled: bool = True,
        scope: RuleScope | None = None,
    ) -> None:
        rules.append(
            UrlGovernanceRule(
                rule_id=rule_id,
                name=name,
                description="Visible WordPress preset rule.",
                enabled=enabled,
                match_type=match_type,
                match_value=match_value,
                case_sensitive=True,
                action=action,
                reason=name,
                reason_code=reason_code,
                source=RuleSource.PRESET,
                priority=100,
                scope=scope or _default_scope(action),
                overrides_rule_ids=(),
                created_by="builtin",
                created_at=_BUILTIN_TIME,
                updated_at=_BUILTIN_TIME,
                version=1,
                preset_id=PlatformPresetId.WORDPRESS.value,
                preset_version="wordpress-1",
            )
        )

    for rule_id, path in (
        ("wordpress.admin", "/wp-admin/"),
        ("wordpress.login", "/wp-login.php"),
        ("wordpress.xmlrpc", "/xmlrpc.php"),
        ("wordpress.cdn_cgi", "/cdn-cgi/"),
    ):
        add(
            rule_id,
            f"Exclude {path} from discovery",
            RuleMatchType.PATH_STARTS_WITH if path.endswith("/") else RuleMatchType.EXACT_PATH,
            path,
            RuleAction.EXCLUDE_FROM_DISCOVERY,
            rule_id.replace(".", "_"),
        )
    for rule_id, path, label in (
        ("wordpress.wp_json", "/wp-json/", "WordPress REST API"),
        ("wordpress.feeds", "/feed/", "Feeds"),
        ("wordpress.search", "/search/", "Search results"),
        ("wordpress.attachments", "/attachment/", "Attachment pages"),
        ("wordpress.comment_reply", "/comment-reply/", "Comment reply routes"),
    ):
        add(
            rule_id,
            f"Exclude {label} from discovery",
            RuleMatchType.PATH_STARTS_WITH,
            path,
            RuleAction.EXCLUDE_FROM_DISCOVERY,
            rule_id.replace(".", "_"),
            enabled=False,
        )
    for family, path in (("tag", "/tag/"), ("author", "/author/"), ("date", "/date/")):
        add(
            f"wordpress.{family}.metadata",
            f"Exclude {family} archives from metadata scoring",
            RuleMatchType.PATH_STARTS_WITH,
            path,
            RuleAction.EXCLUDE_FROM_METADATA,
            f"wordpress_{family}_metadata",
        )
        add(
            f"wordpress.{family}.sitemap",
            f"Exclude {family} archives from sitemap",
            RuleMatchType.PATH_STARTS_WITH,
            path,
            RuleAction.EXCLUDE_FROM_SITEMAP,
            f"wordpress_{family}_sitemap",
        )
    add(
        "wordpress.pagination.sitemap_review",
        "Review pagination for sitemap eligibility",
        RuleMatchType.QUERY_PARAMETER_EXISTS,
        "page",
        RuleAction.MARK_FOR_REVIEW,
        "wordpress_pagination_sitemap_review",
        scope=RuleScope.SITEMAP,
    )
    return tuple(rules)


def _validate_match(match_type: RuleMatchType, value: str) -> None:
    if match_type is RuleMatchType.EXACT_URL:
        try:
            normalize_url(value)
        except UrlNormalizationError as error:
            raise SiteAuditSettingsError(
                "site_audit_rule_match_invalid", "Exact URL match is invalid."
            ) from error
        return
    if match_type in {
        RuleMatchType.EXACT_PATH,
        RuleMatchType.PATH_STARTS_WITH,
        RuleMatchType.PATH_CONTAINS,
        RuleMatchType.PATH_ENDS_WITH,
    }:
        if not value.startswith("/") or "?" in value or "#" in value:
            raise SiteAuditSettingsError(
                "site_audit_rule_match_invalid", "Path match must be a normalized absolute path."
            )
        return
    if match_type is RuleMatchType.QUERY_PARAMETER_EXISTS:
        if not _QUERY_NAME.fullmatch(value):
            raise SiteAuditSettingsError(
                "site_audit_rule_match_invalid", "Query parameter name is invalid."
            )
        return
    name, _ = _split_query_equals(value)
    if not _QUERY_NAME.fullmatch(name):
        raise SiteAuditSettingsError(
            "site_audit_rule_match_invalid", "Query parameter equality match is invalid."
        )


def _validate_action_scope(action: RuleAction, scope: RuleScope) -> None:
    expected = _default_scope(action)
    if action is RuleAction.MARK_FOR_REVIEW:
        if scope not in {RuleScope.DISCOVERY, RuleScope.SITEMAP, RuleScope.ALL_DECISIONS}:
            raise SiteAuditSettingsError(
                "site_audit_rule_scope_invalid", "Review rule scope is invalid."
            )
    elif scope is not expected:
        raise SiteAuditSettingsError(
            "site_audit_rule_scope_invalid", "Rule scope does not match its action."
        )


def _default_scope(action: RuleAction) -> RuleScope:
    return {
        RuleAction.EXCLUDE_FROM_DISCOVERY: RuleScope.DISCOVERY,
        RuleAction.EXCLUDE_FROM_METADATA: RuleScope.METADATA,
        RuleAction.EXCLUDE_FROM_SITEMAP: RuleScope.SITEMAP,
        RuleAction.MARK_FOR_REVIEW: RuleScope.DISCOVERY,
        RuleAction.STRIP_QUERY_PARAMETER: RuleScope.NORMALIZATION,
    }[action]


def _validate_rule_count(rules: Sequence[UrlGovernanceRule]) -> None:
    if len(rules) > MAXIMUM_RULES_PER_SOURCE:
        raise SiteAuditSettingsError("site_audit_rule_limit", "Rule count exceeds the limit.")


def _validate_parameter_names(values: Sequence[str]) -> None:
    if (
        len(values) > 100
        or len(set(values)) != len(values)
        or any(not _QUERY_NAME.fullmatch(item) for item in values)
    ):
        raise SiteAuditSettingsError(
            "site_audit_tracking_parameters_invalid", "Tracking parameters are invalid."
        )


def validate_tracking_parameter_names(value: object) -> tuple[str, ...]:
    """Validate a bounded list of literal query-parameter names."""
    if not isinstance(value, (list, tuple)):
        raise SiteAuditSettingsError(
            "site_audit_tracking_parameters_invalid", "Tracking parameters are invalid."
        )
    result = tuple(str(item) for item in value)
    _validate_parameter_names(result)
    return result


def _validate_crawl_overrides(values: Mapping[str, int | float]) -> None:
    allowed = {
        "maximum_urls": (1, APPLICATION_HARD_MAXIMA.maximum_urls),
        "maximum_depth": (0, APPLICATION_HARD_MAXIMA.maximum_depth),
        "maximum_duration_seconds": (1, APPLICATION_HARD_MAXIMA.maximum_duration_seconds),
        "maximum_accepted_bytes": (1, APPLICATION_HARD_MAXIMA.maximum_accepted_bytes),
        "maximum_concurrency": (1, APPLICATION_HARD_MAXIMA.maximum_concurrency),
        "maximum_queue_size": (1, APPLICATION_HARD_MAXIMA.maximum_queue_size),
        "minimum_request_delay_seconds": (
            APPLICATION_HARD_MAXIMA.minimum_request_delay_seconds,
            3_600,
        ),
        "maximum_redirect_hops": (0, APPLICATION_HARD_MAXIMA.maximum_redirect_hops),
        "maximum_response_bytes": (1, APPLICATION_HARD_MAXIMA.maximum_response_bytes),
    }
    if any(
        key not in allowed or not allowed[key][0] <= value <= allowed[key][1]
        for key, value in values.items()
    ):
        raise SiteAuditSettingsError(
            "site_audit_crawl_limits_invalid", "Crawl limit overrides are invalid."
        )


def validate_crawl_limit_overrides(value: object) -> dict[str, int | float]:
    """Validate one stateless override mapping against immutable application maxima."""
    result = _number_mapping(value)
    _validate_crawl_overrides(result)
    return result


def validate_metadata_thresholds(value: object) -> dict[str, int]:
    """Validate bounded title and description thresholds for a profile or draft."""
    result = _integer_mapping(value)
    _validate_metadata_thresholds(result)
    return result


def _validate_metadata_thresholds(values: Mapping[str, int]) -> None:
    allowed = {
        "title_minimum",
        "title_maximum",
        "description_minimum",
        "description_maximum",
    }
    if any(key not in allowed for key in values):
        raise SiteAuditSettingsError(
            "site_audit_threshold_invalid", "Metadata thresholds are invalid."
        )
    title_minimum = values.get("title_minimum", 30)
    title_maximum = values.get("title_maximum", 60)
    description_minimum = values.get("description_minimum", 70)
    description_maximum = values.get("description_maximum", 160)
    if not (
        1 <= title_minimum <= title_maximum <= 512
        and 1 <= description_minimum <= description_maximum <= 2_048
    ):
        raise SiteAuditSettingsError(
            "site_audit_threshold_invalid", "Metadata thresholds are invalid."
        )


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SiteAuditSettingsError("site_audit_settings_invalid", "Settings object is invalid.")
    return value


def _rule_mappings(value: Sequence[object], *, explanation: str) -> tuple[Mapping[str, Any], ...]:
    if any(not isinstance(item, Mapping) for item in value):
        raise SiteAuditSettingsError("site_audit_rule_invalid", explanation)
    return tuple(item for item in value if isinstance(item, Mapping))


def _number_mapping(value: object) -> dict[str, int | float]:
    result: dict[str, int | float] = {}
    for key, item in _mapping(value).items():
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise SiteAuditSettingsError(
                "site_audit_settings_invalid", "Numeric settings are invalid."
            )
        result[str(key)] = item
    return result


def _integer_mapping(value: object) -> dict[str, int]:
    result: dict[str, int] = {}
    for key, item in _mapping(value).items():
        if isinstance(item, bool) or not isinstance(item, int):
            raise SiteAuditSettingsError(
                "site_audit_settings_invalid", "Integer settings are invalid."
            )
        result[str(key)] = item
    return result


def _query_rule_name(rule: UrlGovernanceRule) -> str:
    return (
        _split_query_equals(rule.match_value)[0]
        if rule.match_type is RuleMatchType.QUERY_PARAMETER_EQUALS
        else rule.match_value
    )


def _split_query_equals(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise SiteAuditSettingsError(
            "site_audit_rule_match_invalid", "Query equality match must contain '='."
        )
    name, expected = value.split("=", 1)
    return name, expected


def _decode_unreserved(value: str) -> str:
    def replace_escape(match: re.Match[str]) -> str:
        character = chr(int(match.group(1), 16))
        return character if character in _UNRESERVED else match.group(0).upper()

    return _PERCENT_ESCAPE.sub(replace_escape, value)


def _ordered_rules(rules: Iterable[UrlGovernanceRule]) -> tuple[UrlGovernanceRule, ...]:
    return tuple(
        sorted(
            rules,
            key=lambda item: (
                -_SOURCE_ORDER[item.source],
                -_SPECIFICITY[item.match_type],
                -item.priority,
                item.rule_id,
            ),
        )
    )


def _resolve_decisions(rules: Sequence[UrlGovernanceRule]) -> dict[str, dict[str, Any]]:
    overridden = {target for rule in rules for target in rule.overrides_rule_ids}
    active = tuple(rule for rule in rules if rule.rule_id not in overridden)
    result: dict[str, dict[str, Any]] = {}
    for layer in DecisionLayer:
        contributors = tuple(rule for rule in active if layer in decision_layers(rule))
        if not contributors:
            continue
        ordered = _ordered_rules(contributors)
        outcomes = {_outcome(rule, layer) for rule in contributors}
        conflict = len(outcomes) > 1
        result[layer.value] = {
            "outcome": _outcome(ordered[0], layer),
            "primary_rule": ordered[0].rule_id,
            "contributing_rules": [rule.rule_id for rule in ordered],
            "overridden_rules": sorted(overridden.intersection({rule.rule_id for rule in rules})),
            "conflict": conflict,
        }
    return result


def _outcome(rule: UrlGovernanceRule, layer: DecisionLayer) -> str:
    if layer is DecisionLayer.NORMALIZATION:
        return "strip_query_parameter"
    if layer is DecisionLayer.DISCOVERY:
        if rule.action is RuleAction.EXCLUDE_FROM_DISCOVERY:
            return "exclude_from_discovery"
        if rule.action is RuleAction.MARK_FOR_REVIEW:
            return "mark_review_before_enqueue"
        return "enqueue"
    if layer is DecisionLayer.METADATA:
        return "exclude_from_metadata_scoring"
    if rule.action is RuleAction.EXCLUDE_FROM_SITEMAP:
        return "exclude_policy"
    return "review_policy"

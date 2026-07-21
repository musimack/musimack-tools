"""Application service for CSA-02 settings, profiles, and network-free rule testing."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from musimack_tools.application.profiles import profile_for
from musimack_tools.domain.site_audit_settings import (
    MAXIMUM_API_PAGE_SIZE,
    MAXIMUM_BROWSER_ALL_ROWS,
    MAXIMUM_EXPORT_ROWS,
    MAXIMUM_PER_AUDIT_RULES,
    MAXIMUM_RETAINED_URLS,
    MAXIMUM_RULE_DESCRIPTION_LENGTH,
    MAXIMUM_RULE_MATCH_VALUE_LENGTH,
    MAXIMUM_RULE_NAME_LENGTH,
    MAXIMUM_RULE_PREVIEW_RESULTS,
    MAXIMUM_RULE_REASON_LENGTH,
    MAXIMUM_RULE_TEST_URLS,
    MAXIMUM_RULES_PER_SOURCE,
    SITE_AUDIT_PRECEDENCE_VERSION,
    SITE_AUDIT_SETTINGS_API_VERSION,
    ProfileState,
    RuleSource,
    SiteAuditSettingsError,
    UrlGovernanceRule,
    builtin_presets,
    default_global_settings,
    global_settings_from_mapping,
    preset_for,
    profile_configuration_from_mapping,
    protected_boundaries,
    resolve_effective_rules,
    rule_from_mapping,
    test_rule_set,
    validate_crawl_limit_overrides,
    validate_metadata_thresholds,
    validate_tracking_parameter_names,
)

if TYPE_CHECKING:
    from musimack_tools.persistence.site_audit_settings_repository import (
        SQLAlchemySiteAuditSettingsRepository,
    )


@dataclass(frozen=True, slots=True)
class SiteAuditSettingsConfiguration:
    enabled: bool = False
    default_page_size: int = 50
    maximum_page_size: int = MAXIMUM_API_PAGE_SIZE

    def __post_init__(self) -> None:
        if not 1 <= self.default_page_size <= self.maximum_page_size <= MAXIMUM_API_PAGE_SIZE:
            raise ValueError("site_audit_settings_page_bounds_invalid")


class SiteAuditSettingsService:
    def __init__(
        self,
        configuration: SiteAuditSettingsConfiguration,
        repository: SQLAlchemySiteAuditSettingsRepository,
    ) -> None:
        self.configuration = configuration
        self._repository = repository

    def diagnostics(self) -> dict[str, Any]:
        return {
            "enabled": self.configuration.enabled,
            "persistence_ready": self.configuration.enabled,
            "api_version": SITE_AUDIT_SETTINGS_API_VERSION,
            "network_access": False,
            "rule_preview": "deferred_retained_evidence_selector",
        }

    def settings(self) -> dict[str, Any]:
        self._require_enabled()
        stored = self._repository.latest_global_settings()
        if stored is not None:
            return stored
        return {
            "version": 0,
            "configuration": default_global_settings().to_dict(),
            "configuration_hash": None,
            "created_by": "builtin",
            "created_at": None,
            "settings_version": default_global_settings().to_dict()["settings_version"],
        }

    def current_global_version(self) -> int:
        """Return the version a new audit draft must pin."""

        return int(self.settings()["version"])

    def update_settings(
        self, payload: Mapping[str, Any], *, expected_version: int, actor: str
    ) -> dict[str, Any]:
        self._require_enabled()
        now = _now()
        value = global_settings_from_mapping(payload, created_by=actor, now=now).to_dict()
        return self._repository.append_global_settings(
            value, expected_version=expected_version, created_by=actor
        )

    def presets(self) -> tuple[dict[str, Any], ...]:
        self._require_enabled()
        return tuple(item.to_dict() for item in builtin_presets())

    def preset(self, preset_id: str, version: str | None = None) -> dict[str, Any]:
        self._require_enabled()
        return preset_for(preset_id, version).to_dict()

    def profiles(self, *, include_disabled: bool, offset: int, limit: int) -> dict[str, Any]:
        self._require_enabled()
        if offset < 0 or not 1 <= limit <= self.configuration.maximum_page_size:
            raise SiteAuditSettingsError(
                "site_profile_pagination_invalid", "Profile pagination is invalid."
            )
        return {
            "items": self._repository.profiles(
                include_disabled=include_disabled, offset=offset, limit=limit
            ),
            "offset": offset,
            "limit": limit,
            "total": self._repository.profile_count(include_disabled=include_disabled),
            "ordering": "site_label_asc_profile_id_asc-v1",
        }

    def profile(self, profile_id: str, *, include_disabled: bool) -> dict[str, Any]:
        self._require_enabled()
        item = self._repository.profile(profile_id)
        if item is None or (not include_disabled and item["state"] != ProfileState.ENABLED.value):
            raise SiteAuditSettingsError("site_profile_not_found", "Site profile was not found.")
        return item

    def profile_versions(self, profile_id: str) -> tuple[dict[str, Any], ...]:
        self.profile(profile_id, include_disabled=True)
        return self._repository.profile_versions(profile_id)

    def create_profile(self, payload: Mapping[str, Any], *, actor: str) -> dict[str, Any]:
        self._require_enabled()
        profile_id = f"profile-{uuid.uuid4().hex[:24]}"
        configuration = profile_configuration_from_mapping(
            payload, profile_id=profile_id, created_by=actor, now=_now()
        ).to_dict()
        _verify_preset_reference(configuration)
        return self._repository.create_profile(profile_id, configuration, created_by=actor)

    def update_profile(
        self,
        profile_id: str,
        payload: Mapping[str, Any],
        *,
        expected_version: int,
        actor: str,
    ) -> dict[str, Any]:
        self._require_enabled()
        self.profile(profile_id, include_disabled=True)
        configuration = profile_configuration_from_mapping(
            payload, profile_id=profile_id, created_by=actor, now=_now()
        ).to_dict()
        _verify_preset_reference(configuration)
        return self._repository.update_profile(
            profile_id,
            configuration,
            expected_version=expected_version,
            created_by=actor,
        )

    def set_profile_state(self, profile_id: str, state: ProfileState) -> dict[str, Any]:
        self._require_enabled()
        return self._repository.set_profile_state(profile_id, state)

    def validate_rule(self, payload: Mapping[str, Any], *, actor: str) -> dict[str, Any]:
        self._require_enabled()
        rule = rule_from_mapping(payload, source=RuleSource.PER_AUDIT, created_by=actor, now=_now())
        return {"valid": True, "rule": rule.to_dict()}

    def effective_settings(  # noqa: C901, PLR0912, PLR0915 - explicit precedence pipeline.
        self,
        payload: Mapping[str, Any],
        *,
        actor: str,
        resolved_at: str | None = None,
    ) -> dict[str, Any]:
        self._require_enabled()
        resolution_time = resolved_at or _now()
        requested_global_version = payload.get("global_settings_version")
        if requested_global_version is None:
            global_record = self.settings()
        else:
            try:
                global_version = int(requested_global_version)
            except (TypeError, ValueError) as error:
                raise SiteAuditSettingsError(
                    "site_audit_global_settings_version_not_found",
                    "Global settings version was not found.",
                ) from error
            stored_global = self._repository.global_settings_version(global_version)
            if global_version == 0:
                global_record = {
                    "version": 0,
                    "configuration": default_global_settings().to_dict(),
                    "configuration_hash": None,
                    "created_by": "builtin",
                    "created_at": None,
                    "settings_version": default_global_settings().to_dict()["settings_version"],
                }
            elif stored_global is None:
                raise SiteAuditSettingsError(
                    "site_audit_global_settings_version_not_found",
                    "Global settings version was not found.",
                )
            else:
                global_record = stored_global
        global_configuration = global_settings_from_mapping(
            _mapping(global_record["configuration"]), created_by=actor, now=resolution_time
        )
        profile_id = str(payload["profile_id"]) if payload.get("profile_id") else None
        profile = self.profile(profile_id, include_disabled=False) if profile_id else None
        requested_profile_version = payload.get("profile_version")
        if profile and requested_profile_version is not None:
            if profile_id is None:
                raise SiteAuditSettingsError(
                    "site_profile_not_found", "Site profile was not found."
                )
            try:
                pinned_version = int(requested_profile_version)
            except (TypeError, ValueError) as error:
                raise SiteAuditSettingsError(
                    "site_profile_version_not_found", "Site profile version was not found."
                ) from error
            resolved_profile_version: int | None = pinned_version
            pinned_profile = self._repository.profile_version(profile_id, pinned_version)
            if pinned_profile is None:
                raise SiteAuditSettingsError(
                    "site_profile_version_not_found", "Site profile version was not found."
                )
            profile_config = _mapping(pinned_profile["configuration"])
        else:
            resolved_profile_version = int(profile["current_version"]) if profile else None
            pinned_profile = None
            profile_config = _mapping(profile["configuration"]) if profile else {}

        selected_preset = (
            payload.get("preset_id")
            if "preset_id" in payload
            else profile_config.get(
                "preset_id",
                (
                    global_configuration.default_platform_preset.value
                    if global_configuration.default_platform_preset
                    else None
                ),
            )
        )
        selected_version = payload.get("preset_version", profile_config.get("preset_version"))
        preset_accepted = bool(
            payload.get("preset_accepted")
            if "preset_accepted" in payload
            else profile_config.get("preset_accepted", False)
        )
        preset = (
            preset_for(str(selected_preset), str(selected_version) if selected_version else None)
            if selected_preset
            else None
        )
        if preset_accepted and not selected_version:
            raise SiteAuditSettingsError(
                "site_audit_preset_acceptance_invalid",
                "Accepted presets require an explicit version.",
            )
        if preset_accepted and preset is None:
            raise SiteAuditSettingsError(
                "site_audit_preset_acceptance_invalid", "Accepted preset is missing."
            )
        if not preset_accepted and payload.get("tracking_parameters_accepted"):
            raise SiteAuditSettingsError(
                "site_audit_tracking_acceptance_invalid",
                "Preset tracking parameters require explicit preset acceptance.",
            )

        profile_rules = _rules(
            profile_config.get("rules", ()),
            RuleSource.SITE_PROFILE,
            actor,
            site_profile_id=profile_id,
            now=resolution_time,
        )
        override_payload = _mapping(payload.get("overrides", {}))
        per_audit_rules = _rules(
            override_payload.get("rules", ()),
            RuleSource.PER_AUDIT,
            actor,
            now=resolution_time,
        )
        states = dict(_mapping(profile_config.get("preset_rule_states", {})))
        states.update(
            {
                str(key): bool(value)
                for key, value in _mapping(payload.get("preset_rule_states", {})).items()
            }
        )
        disabled_value = override_payload.get("disabled_rule_ids", ())
        if not isinstance(disabled_value, (list, tuple)):
            raise SiteAuditSettingsError(
                "site_audit_disabled_rule_invalid", "Disabled rule IDs are invalid."
            )
        effective_rules, disabled_rules, warnings = resolve_effective_rules(
            global_configuration.default_url_rules,
            preset=preset,
            preset_accepted=preset_accepted,
            preset_rule_states=states,
            profile_rules=profile_rules,
            per_audit_rules=per_audit_rules,
            disabled_rule_ids=tuple(str(item) for item in disabled_value),
        )

        crawl_profile = str(
            override_payload.get(
                "crawl_profile",
                profile_config.get(
                    "crawl_profile", global_configuration.default_crawl_profile.value
                ),
            )
        )
        if profile_for(crawl_profile) is None:
            raise SiteAuditSettingsError(
                "site_audit_crawl_profile_invalid", "Crawl profile is invalid."
            )
        crawl_limits = dict(_mapping(profile_config.get("crawl_limit_overrides", {})))
        crawl_limits.update(
            validate_crawl_limit_overrides(override_payload.get("crawl_limit_overrides", {}))
        )
        thresholds = {
            "title_minimum": global_configuration.title_minimum,
            "title_maximum": global_configuration.title_maximum,
            "description_minimum": global_configuration.description_minimum,
            "description_maximum": global_configuration.description_maximum,
        }
        thresholds.update(
            {
                str(key): int(value)
                for key, value in _mapping(profile_config.get("metadata_thresholds", {})).items()
            }
        )
        thresholds.update(
            validate_metadata_thresholds(override_payload.get("metadata_thresholds", {}))
        )
        validate_metadata_thresholds(thresholds)
        modules = {
            "images": global_configuration.image_summary_enabled,
            "structured_data": global_configuration.structured_data_summary_enabled,
        }
        modules.update(
            {
                str(key): bool(value)
                for key, value in _mapping(profile_config.get("enabled_modules", {})).items()
            }
        )
        modules.update(
            {
                str(key): bool(value)
                for key, value in _mapping(override_payload.get("enabled_modules", {})).items()
            }
        )
        if any(key not in {"images", "structured_data"} for key in modules):
            raise SiteAuditSettingsError(
                "site_audit_modules_invalid", "Enabled specialist modules are invalid."
            )
        tracking_accepted = bool(
            payload.get(
                "tracking_parameters_accepted",
                profile_config.get("tracking_parameters_accepted", False),
            )
        )
        raw_exceptions = payload.get(
            "tracking_parameter_exceptions",
            profile_config.get("tracking_parameter_exceptions", ()),
        )
        exceptions = validate_tracking_parameter_names(raw_exceptions)
        supplied_tracking_parameters = payload.get("tracking_parameters")
        raw_tracking_parameters = (
            supplied_tracking_parameters
            if isinstance(supplied_tracking_parameters, (list, tuple))
            and supplied_tracking_parameters
            else preset.tracking_parameters
            if preset
            else global_configuration.default_tracking_parameters
        )
        tracking_parameters = validate_tracking_parameter_names(raw_tracking_parameters)
        tracking_enabled = tracking_accepted and preset_accepted
        effective_rule_values = [item.to_dict() for item in effective_rules]
        if tracking_enabled:
            for parameter in tracking_parameters:
                if parameter in exceptions:
                    continue
                effective_rule_values.append(
                    {
                        "rule_id": f"tracking.{parameter}",
                        "name": f"Strip accepted tracking parameter {parameter}",
                        "description": "Explicitly accepted tracking normalization rule.",
                        "enabled": True,
                        "match_type": "query_parameter_exists",
                        "match_value": parameter,
                        "case_sensitive": True,
                        "action": "strip_query_parameter",
                        "reason": f"The accepted {parameter} tracking parameter is normalized.",
                        "reason_code": "tracking_parameter_strip",
                        "source": "preset",
                        "priority": 100,
                        "scope": "normalization",
                        "overrides_rule_ids": [],
                        "created_by": "builtin",
                        "created_at": resolution_time,
                        "updated_at": resolution_time,
                        "version": 1,
                        "preset_id": preset.preset_id.value if preset else None,
                        "preset_version": preset.version if preset else None,
                        "site_profile_id": None,
                        "decision_layers": ["normalization"],
                        "broad_rule_warning": None,
                    }
                )
        rule_source_counts = {
            source.value: sum(item["source"] == source.value for item in effective_rule_values)
            for source in RuleSource
        }
        return {
            "protected_boundaries": protected_boundaries(),
            "global_settings_version": global_record["version"],
            "global_settings_hash": global_record["configuration_hash"],
            "preset": preset.to_dict() if preset else None,
            "preset_accepted": preset_accepted,
            "site_profile": (
                {
                    "profile_id": profile["profile_id"],
                    "site_label": profile_config["site_label"],
                    "version": resolved_profile_version,
                    "configuration_hash": (
                        pinned_profile["configuration_hash"]
                        if pinned_profile
                        else profile["configuration_hash"]
                    ),
                }
                if profile
                else None
            ),
            "crawl_profile": crawl_profile,
            "crawl_limit_overrides": crawl_limits,
            "metadata_thresholds": thresholds,
            "enabled_modules": modules,
            "tracking_parameters": list(tracking_parameters),
            "tracking_parameters_accepted": tracking_enabled,
            "tracking_parameter_exceptions": list(exceptions),
            "effective_rules": effective_rule_values,
            "disabled_inherited_rules": [item.to_dict() for item in disabled_rules],
            "effective_rule_count": len(effective_rule_values),
            "rule_source_counts": rule_source_counts,
            "disabled_inherited_rule_count": len(disabled_rules),
            "warnings": list(warnings),
            "sources": ["protected", "global", "preset", "site_profile", "per_audit"],
            "precedence_version": SITE_AUDIT_PRECEDENCE_VERSION,
            "bounds": {
                "api_page_size_maximum": MAXIMUM_API_PAGE_SIZE,
                "browser_all_maximum": MAXIMUM_BROWSER_ALL_ROWS,
                "preview_result_maximum": MAXIMUM_RULE_PREVIEW_RESULTS,
                "sample_url_maximum": MAXIMUM_RULE_TEST_URLS,
                "rules_per_source_maximum": MAXIMUM_RULES_PER_SOURCE,
                "per_audit_rules_maximum": MAXIMUM_PER_AUDIT_RULES,
                "rule_name_character_maximum": MAXIMUM_RULE_NAME_LENGTH,
                "rule_match_character_maximum": MAXIMUM_RULE_MATCH_VALUE_LENGTH,
                "rule_description_character_maximum": MAXIMUM_RULE_DESCRIPTION_LENGTH,
                "rule_reason_character_maximum": MAXIMUM_RULE_REASON_LENGTH,
                "retained_url_maximum": MAXIMUM_RETAINED_URLS,
                "export_row_maximum": MAXIMUM_EXPORT_ROWS,
            },
            "rule_preview": {
                "available": False,
                "reason": "retained_evidence_selector_deferred",
            },
        }

    def test_rules(self, payload: Mapping[str, Any], *, actor: str) -> dict[str, Any]:
        effective = self.effective_settings(payload, actor=actor)
        samples = payload.get("sample_urls", ())
        if not isinstance(samples, (list, tuple)):
            raise SiteAuditSettingsError(
                "site_audit_rule_test_invalid", "Rule test samples are invalid."
            )
        # Preserve resolved source labels instead of reclassifying them as per-audit.
        rules = tuple(
            rule_from_mapping(
                item,
                source=RuleSource(str(item["source"])),
                created_by=str(item["created_by"]),
                now=str(item["updated_at"]),
                preset_id=str(item["preset_id"]) if item.get("preset_id") else None,
                preset_version=(
                    str(item["preset_version"]) if item.get("preset_version") else None
                ),
                site_profile_id=(
                    str(item["site_profile_id"]) if item.get("site_profile_id") else None
                ),
            )
            for item in effective["effective_rules"]
        )
        return {
            "effective_settings": effective,
            "test": test_rule_set(
                rules,
                tuple(str(item) for item in samples),
                tracking_parameters=tuple(str(item) for item in effective["tracking_parameters"]),
                tracking_accepted=bool(effective["tracking_parameters_accepted"]),
                parameter_exceptions=tuple(
                    str(item) for item in effective["tracking_parameter_exceptions"]
                ),
            ),
        }

    def _require_enabled(self) -> None:
        if not self.configuration.enabled:
            raise SiteAuditSettingsError(
                "site_audit_settings_disabled", "Site-audit settings are disabled."
            )


def _verify_preset_reference(configuration: Mapping[str, Any]) -> None:
    preset_id = configuration.get("preset_id")
    if preset_id:
        preset = preset_for(str(preset_id), str(configuration.get("preset_version")))
        states = _mapping(configuration.get("preset_rule_states", {}))
        if set(states) - {item.rule_id for item in preset.rules}:
            raise SiteAuditSettingsError(
                "site_audit_preset_rule_invalid", "Preset rule selection is invalid."
            )


def _rules(
    value: object,
    source: RuleSource,
    actor: str,
    *,
    site_profile_id: str | None = None,
    now: str | None = None,
) -> tuple[UrlGovernanceRule, ...]:
    if not isinstance(value, (list, tuple)):
        raise SiteAuditSettingsError("site_audit_rule_invalid", "URL rules are invalid.")
    if source is RuleSource.PER_AUDIT and len(value) > MAXIMUM_PER_AUDIT_RULES:
        raise SiteAuditSettingsError(
            "site_audit_rule_limit", "Per-audit rule count exceeds the limit."
        )
    if any(not isinstance(item, Mapping) for item in value):
        raise SiteAuditSettingsError("site_audit_rule_invalid", "URL rules are invalid.")
    effective_now = now or _now()
    return tuple(
        rule_from_mapping(
            item,
            source=source,
            created_by=actor,
            now=effective_now,
            site_profile_id=site_profile_id,
        )
        for item in value
        if isinstance(item, Mapping)
    )


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SiteAuditSettingsError("site_audit_settings_invalid", "Settings object is invalid.")
    return value


def _now() -> str:
    return datetime.now(UTC).isoformat()

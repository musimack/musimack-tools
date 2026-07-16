"""Internal API domain, access, schema, and mapping contracts."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from pydantic import ValidationError

from musimack_tools.api.access import DenyAllAccessVerifier
from musimack_tools.api.mapping import application_warnings, to_raw_request
from musimack_tools.api.schemas import (
    ApiErrorDataSchema,
    ApiErrorEnvelope,
    ApplicationRequestSchema,
    CrawlLimitOverridesRequest,
    ValidationResponse,
)
from musimack_tools.domain.api import (
    INTERNAL_API_PREFIX,
    INTERNAL_API_VERSION,
    AccessDecision,
    AccessDenialReason,
    AccessOutcome,
    ApiErrorCode,
    InternalApiConfiguration,
    ResponseDiagnosticsPolicy,
)
from musimack_tools.domain.application import (
    ApplicationWarning,
    CrawlProfileName,
    ScopeProfile,
    ValidationSeverity,
)


def test_api_version_prefix_error_codes_and_access_outcomes_are_exact() -> None:
    assert INTERNAL_API_VERSION == "seo-toolkit-internal-api-v1"
    assert INTERNAL_API_PREFIX == "/api/internal/v1"
    assert tuple(AccessOutcome) == (
        AccessOutcome.ALLOWED,
        AccessOutcome.DENIED,
        AccessOutcome.UNAVAILABLE,
    )
    assert {item.value for item in ApiErrorCode} >= {
        "access_denied",
        "access_verifier_unavailable",
        "request_validation_failed",
        "application_validation_failed",
        "preflight_blocked",
        "active_duplicate",
        "queue_capacity_reached",
        "registry_closed",
        "registry_shutting_down",
        "job_id_invalid",
        "job_not_found",
        "job_result_unavailable",
        "job_already_terminal",
        "job_cancellation_already_requested",
        "internal_service_unavailable",
        "internal_api_error",
    }


def test_configuration_is_immutable_fail_closed_and_health_only_by_default() -> None:
    configuration = InternalApiConfiguration()
    assert not configuration.mount_internal_routes
    assert not configuration.include_internal_routes_in_schema
    assert not configuration.include_internal_endpoints_in_docs
    assert configuration.access_verifier is None
    assert configuration.response_diagnostics_policy is ResponseDiagnosticsPolicy.OMIT
    with pytest.raises(FrozenInstanceError):
        configuration.mount_internal_routes = True  # type: ignore[misc]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"api_version": "v2"},
        {"route_prefix": "/api/internal/v2"},
        {"maximum_request_body_bytes": 0},
        {"maximum_validation_details": 0},
        {"maximum_approved_hosts": 0},
        {"maximum_url_characters": 0},
        {"maximum_history_events": 0},
    ],
)
def test_invalid_api_configuration_is_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        InternalApiConfiguration(**kwargs)  # type: ignore[arg-type]


def test_access_decisions_are_immutable_and_self_consistent() -> None:
    denied = AccessDecision(AccessOutcome.DENIED, AccessDenialReason.ACCESS_DENIED)
    assert denied.reason is AccessDenialReason.ACCESS_DENIED
    with pytest.raises(FrozenInstanceError):
        denied.outcome = AccessOutcome.ALLOWED  # type: ignore[misc]
    with pytest.raises(ValueError):
        AccessDecision(AccessOutcome.ALLOWED, AccessDenialReason.ACCESS_DENIED)
    with pytest.raises(ValueError):
        AccessDecision(AccessOutcome.DENIED)


@pytest.mark.anyio
async def test_deny_all_verifier_never_allows() -> None:
    decision = await DenyAllAccessVerifier().verify(None)  # type: ignore[arg-type]
    assert decision == AccessDecision(
        AccessOutcome.DENIED,
        AccessDenialReason.ACCESS_NOT_CONFIGURED,
    )


def test_request_schema_maps_only_operator_facing_fields() -> None:
    schema = ApplicationRequestSchema(
        seed_url="https://example.com",
        scope_profile=ScopeProfile.INCLUDE_SUBDOMAINS,
        crawl_profile=CrawlProfileName.QUICK_AUDIT,
        approved_hosts=(),
        overrides=CrawlLimitOverridesRequest(maximum_urls=25),
        caller_label="operator",
    )
    raw = to_raw_request(schema)
    assert raw.seed_url == "https://example.com"
    assert raw.scope_profile is ScopeProfile.INCLUDE_SUBDOMAINS
    assert raw.overrides.maximum_urls == 25
    assert raw.caller_label == "operator"
    assert not hasattr(schema, "headers")
    assert not hasattr(schema, "proxy")
    assert not hasattr(schema, "token")


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"seed_url": "https://example.com", "crawl_profile": "unknown"},
        {"seed_url": "https://example.com", "approved_hosts": ["a"] * 33},
        {"seed_url": "https://example.com", "caller_label": "x" * 201},
        {"seed_url": "x" * 4_097},
        {"seed_url": "https://example.com", "arbitrary": {"nested": True}},
        {"seed_url": "https://example.com", "publication_requested": "yes"},
    ],
)
def test_request_schema_rejects_unbounded_invalid_or_arbitrary_input(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ApplicationRequestSchema.model_validate(payload)


def test_error_envelope_is_typed_deterministic_and_supports_request_id() -> None:
    envelope = ApiErrorEnvelope(
        error=ApiErrorDataSchema(code="job_not_found", message="The job was not found.")
    )
    assert envelope.model_dump(mode="json") == {
        "api_version": "seo-toolkit-internal-api-v1",
        "request_id": None,
        "error": {
            "code": "job_not_found",
            "message": "The job was not found.",
            "details": [],
        },
    }
    assert envelope.request_id is None


def test_success_envelope_contract_is_immutable() -> None:
    fields = ValidationResponse.model_fields
    assert tuple(fields) == ("api_version", "request_id", "data", "warnings")
    assert fields["api_version"].default == INTERNAL_API_VERSION
    assert fields["request_id"].default_factory is not None


def test_warning_urls_drop_fragments_and_redact_query_values() -> None:
    warning = ApplicationWarning(
        "warning",
        "crawl",
        "source_warning",
        ValidationSeverity.WARNING,
        "Safe warning",
        "https://example.com/path?token=secret#fragment",
    )
    mapped = application_warnings((warning,))
    assert mapped[0].url == "https://example.com/path?redacted"
    assert "secret" not in mapped[0].model_dump_json()

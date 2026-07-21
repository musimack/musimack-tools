"""CSA-02 durable settings, migration, private API, and authorization coverage."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from alembic import command
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from musimack_tools.api.dependencies import permission_for_request
from musimack_tools.api.errors import install_internal_api_error_handlers
from musimack_tools.api.site_audit_settings import create_site_audit_settings_router
from musimack_tools.domain.api import (
    AccessDecision,
    AccessOutcome,
    InternalApiConfiguration,
    InternalCallerContext,
)
from musimack_tools.domain.authentication import (
    AuthenticatedPrincipal,
    AuthenticationMethod,
    Permission,
    PrincipalType,
    UserRole,
    permissions_for_role,
)
from musimack_tools.domain.persistence import PersistenceConfiguration
from musimack_tools.domain.site_audit_settings import ProfileState, SiteAuditSettingsError
from musimack_tools.main import create_app
from musimack_tools.persistence.engine import create_persistence_runtime
from musimack_tools.persistence.migrations import (
    SITE_AUDIT_SETTINGS_REVISION,
    SITEMAP_RECOMMENDATION_RETENTION_REVISION,
    alembic_configuration,
    current_revision,
    upgrade_to_head,
)
from musimack_tools.persistence.site_audit_settings_models import SiteAuditProfileModel
from musimack_tools.persistence.site_audit_settings_repository import (
    SQLAlchemySiteAuditSettingsRepository,
)
from musimack_tools.site_audit_settings.service import (
    SiteAuditSettingsConfiguration,
    SiteAuditSettingsService,
)
from persistence_helpers import BACKEND_ROOT

if TYPE_CHECKING:
    from pathlib import Path

    from musimack_tools.persistence.engine import PersistenceRuntime


def _profile(label: str = "Example Store") -> dict[str, object]:
    return {
        "site_label": label,
        "authorized_seed": "https://www.example.com/",
        "approved_hosts": ["example.com", "www.example.com"],
        "preset_id": "wordpress",
        "preset_version": "wordpress-1",
        "preset_accepted": True,
        "preset_rule_states": {"wordpress.wp_json": False},
        "tracking_parameters_accepted": True,
        "tracking_parameter_exceptions": ["utm_source"],
        "rules": [],
        "crawl_profile": "standard_crawl",
        "crawl_limit_overrides": {"maximum_urls": 250},
        "metadata_thresholds": {"title_minimum": 25, "title_maximum": 65},
        "enabled_modules": {"images": True, "structured_data": False},
        "business_importance": [
            {"target_type": "section", "target": "/products/", "importance": "high"}
        ],
    }


def _runtime(tmp_path: Path) -> tuple[PersistenceRuntime, SiteAuditSettingsService]:
    database = tmp_path / "site-audit-settings.db"
    upgrade_to_head(f"sqlite+pysqlite:///{database.as_posix()}", backend_root=BACKEND_ROOT)
    runtime = create_persistence_runtime(
        PersistenceConfiguration(enabled=True, database_path=database)
    )
    return runtime, SiteAuditSettingsService(
        SiteAuditSettingsConfiguration(enabled=True, default_page_size=2, maximum_page_size=10),
        SQLAlchemySiteAuditSettingsRepository(runtime),
    )


def test_migration_is_single_successor_and_upgrade_downgrade_safe(tmp_path: Path) -> None:
    assert SITE_AUDIT_SETTINGS_REVISION == "0016_site_audit_settings"
    assert SITEMAP_RECOMMENDATION_RETENTION_REVISION == "0015_sitemap_recommendation_retention"
    database = tmp_path / "migration.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    configuration = alembic_configuration(url, backend_root=BACKEND_ROOT)
    command.upgrade(configuration, SITE_AUDIT_SETTINGS_REVISION)
    runtime = create_persistence_runtime(
        PersistenceConfiguration(enabled=True, database_path=database)
    )
    try:
        assert current_revision(runtime.engine) == SITE_AUDIT_SETTINGS_REVISION
        tables = set(inspect(runtime.engine).get_table_names())
        assert {
            "site_audit_global_settings_versions",
            "site_audit_profiles",
            "site_audit_profile_versions",
        } <= tables
        command.downgrade(configuration, SITEMAP_RECOMMENDATION_RETENTION_REVISION)
        assert current_revision(runtime.engine) == SITEMAP_RECOMMENDATION_RETENTION_REVISION
        assert not {
            "site_audit_global_settings_versions",
            "site_audit_profiles",
            "site_audit_profile_versions",
        }.intersection(inspect(runtime.engine).get_table_names())
        command.upgrade(configuration, SITE_AUDIT_SETTINGS_REVISION)
        assert current_revision(runtime.engine) == SITE_AUDIT_SETTINGS_REVISION
    finally:
        runtime.dispose()


def test_global_versions_profiles_constraints_history_and_cascade_are_durable(
    tmp_path: Path,
) -> None:
    runtime, service = _runtime(tmp_path)
    try:
        original = service.settings()
        assert original["version"] == 0
        configuration = dict(cast("dict[str, object]", original["configuration"]))
        configuration["default_report_page_size"] = 100
        saved = service.update_settings(configuration, expected_version=0, actor="admin-1")
        assert saved["version"] == 1
        with pytest.raises(SiteAuditSettingsError, match="site_audit_settings_version_conflict"):
            service.update_settings(configuration, expected_version=0, actor="admin-2")
        reverted = service.update_settings(
            cast("dict[str, object]", original["configuration"]),
            expected_version=1,
            actor="admin-1",
        )
        assert reverted["version"] == 2

        created = service.create_profile(_profile(), actor="admin-1")
        profile_id = str(created["profile_id"])
        assert created["seed_host"] == "www.example.com"
        assert created["current_version"] == 1
        changed = _profile("Example Store Updated")
        updated = service.update_profile(profile_id, changed, expected_version=1, actor="admin-2")
        assert updated["current_version"] == 2
        assert [item["version"] for item in service.profile_versions(profile_id)] == [2, 1]
        assert service.set_profile_state(profile_id, ProfileState.DISABLED)["state"] == "disabled"
        assert service.profiles(include_disabled=False, offset=0, limit=2)["total"] == 0
        assert service.profiles(include_disabled=True, offset=0, limit=2)["total"] == 1

        with runtime.transaction() as session:
            row = session.get(SiteAuditProfileModel, profile_id)
            assert row is not None
            session.delete(row)
        with runtime.engine.connect() as connection:
            remaining = connection.execute(
                text("SELECT count(*) FROM site_audit_profile_versions WHERE profile_id=:id"),
                {"id": profile_id},
            ).scalar_one()
        assert remaining == 0
    finally:
        runtime.dispose()


def test_real_site_authorization_defaults_suspended_and_is_versioned(tmp_path: Path) -> None:
    runtime, service = _runtime(tmp_path)
    try:
        initial = service.current_real_site_authorization()
        assert initial == {
            "enabled": False,
            "status": "suspended",
            "authorized_by": None,
            "global_settings_version": 0,
            "global_settings_hash": None,
            "default_limits": {
                "maximum_urls": 100,
                "maximum_depth": 3,
                "maximum_duration_seconds": 300,
                "maximum_accepted_bytes": 50_000_000,
                "maximum_concurrency": 1,
                "maximum_queue_size": 500,
                "minimum_request_delay_seconds": 1.0,
                "maximum_redirect_hops": 5,
                "maximum_response_bytes": 3_000_000,
            },
        }
        configuration = dict(cast("dict[str, object]", service.settings()["configuration"]))
        operations = dict(cast("dict[str, object]", configuration["real_site_operations"]))
        operations["enabled"] = True
        configuration["real_site_operations"] = operations

        saved = service.update_settings(configuration, expected_version=0, actor="admin-1")

        assert saved["version"] == 1
        assert service.current_real_site_authorization()["authorized_by"] == "admin-1"
        assert service.current_real_site_authorization()["status"] == "enabled"
    finally:
        runtime.dispose()


def test_effective_settings_and_sample_test_are_stateless_bounded_and_reproducible(
    tmp_path: Path,
) -> None:
    runtime, service = _runtime(tmp_path)
    try:
        profile = service.create_profile(_profile(), actor="admin")
        payload = {
            "profile_id": profile["profile_id"],
            "preset_accepted": True,
            "tracking_parameters_accepted": True,
            "preset_rule_states": {"wordpress.wp_json": True},
            "overrides": {
                "crawl_limit_overrides": {"maximum_urls": 25},
                "metadata_thresholds": {"title_minimum": 20},
                "enabled_modules": {"images": False},
                "disabled_rule_ids": ["wordpress.admin"],
                "rules": [
                    {
                        "rule_id": "audit.private",
                        "name": "Review private section",
                        "match_type": "path_starts_with",
                        "match_value": "/private/",
                        "action": "crawl_and_mark_for_review",
                        "reason": "Temporary audit review",
                        "reason_code": "audit_private",
                    }
                ],
            },
            "sample_urls": [
                "https://www.example.com/private/?gclid=x",
                "https://www.example.com/wp-admin/",
            ],
        }
        effective = service.effective_settings(payload, actor="operator")
        assert effective["site_profile"]["version"] == 1
        assert effective["preset"]["version"] == "wordpress-1"
        assert effective["crawl_limit_overrides"]["maximum_urls"] == 25
        assert effective["metadata_thresholds"]["title_minimum"] == 20
        assert effective["enabled_modules"]["images"] is False
        assert any(
            item["rule_id"] == "wordpress.admin" for item in effective["disabled_inherited_rules"]
        )
        assert any(item["rule_id"] == "tracking.gclid" for item in effective["effective_rules"])
        assert not any(
            item["rule_id"] == "tracking.utm_source" for item in effective["effective_rules"]
        )
        assert effective["protected_boundaries"]["ssrf"] == "enforced"
        tested = service.test_rules(payload, actor="operator")["test"]
        assert tested["network_access"] is False
        assert tested["discoveries_created"] is False
        assert tested["result_count"] == 2
        assert tested["results"][0]["normalized_url"] == ("https://www.example.com/private/")
        assert service.profiles(include_disabled=True, offset=0, limit=2)["total"] == 1
        without_tracking = service.effective_settings(
            {
                "preset_id": "wordpress",
                "preset_version": "wordpress-1",
                "preset_accepted": True,
                "tracking_parameters_accepted": False,
            },
            actor="operator",
        )
        assert not any(
            str(item["rule_id"]).startswith("tracking.")
            for item in without_tracking["effective_rules"]
        )
    finally:
        runtime.dispose()


def test_effective_settings_pin_global_profile_and_preset_versions(tmp_path: Path) -> None:
    runtime, service = _runtime(tmp_path)
    try:
        global_configuration = dict(cast("dict[str, object]", service.settings()["configuration"]))
        thresholds = dict(cast("dict[str, object]", global_configuration["metadata_thresholds"]))
        thresholds["description_minimum"] = 80
        global_configuration["metadata_thresholds"] = thresholds
        global_v1 = service.update_settings(global_configuration, expected_version=0, actor="admin")
        profile_v1 = service.create_profile(_profile(), actor="admin")
        payload = {
            "global_settings_version": 1,
            "profile_id": profile_v1["profile_id"],
            "profile_version": 1,
        }

        first = service.effective_settings(
            payload, actor="operator", resolved_at="2026-01-01T00:00:00+00:00"
        )
        changed_global = dict(global_configuration)
        changed_thresholds = dict(thresholds)
        changed_thresholds["description_minimum"] = 90
        changed_global["metadata_thresholds"] = changed_thresholds
        service.update_settings(changed_global, expected_version=1, actor="admin")
        changed_profile = _profile("Changed profile")
        changed_profile["crawl_limit_overrides"] = {"maximum_urls": 300}
        service.update_profile(
            str(profile_v1["profile_id"]), changed_profile, expected_version=1, actor="admin"
        )

        repeated = service.effective_settings(
            payload, actor="operator", resolved_at="2026-01-01T00:00:00+00:00"
        )
        assert first == repeated
        assert first["global_settings_version"] == global_v1["version"] == 1
        assert first["site_profile"]["version"] == 1
        assert first["metadata_thresholds"]["description_minimum"] == 80
        assert first["crawl_limit_overrides"]["maximum_urls"] == 250
        assert first["preset"]["version"] == "wordpress-1"

        with pytest.raises(
            SiteAuditSettingsError, match="site_audit_global_settings_version_not_found"
        ):
            service.effective_settings({"global_settings_version": 999}, actor="operator")
        with pytest.raises(SiteAuditSettingsError, match="site_profile_version_not_found"):
            service.effective_settings(
                {
                    "profile_id": profile_v1["profile_id"],
                    "profile_version": 999,
                },
                actor="operator",
            )
    finally:
        runtime.dispose()


class _RoleVerifier:
    def __init__(self, role: UserRole) -> None:
        self.role = role

    async def verify(self, request: Request) -> AccessDecision:
        request.state.authenticated_principal = AuthenticatedPrincipal(
            PrincipalType.USER,
            AuthenticationMethod.PASSWORD_SESSION,
            self.role,
            permissions_for_role(self.role),
            user_id=f"{self.role.value}-1",
        )
        return AccessDecision(AccessOutcome.ALLOWED, caller=InternalCallerContext("test"))


def _client(service: SiteAuditSettingsService, role: UserRole) -> TestClient:
    configuration = InternalApiConfiguration(
        mount_internal_routes=True,
        include_internal_routes_in_schema=True,
        include_internal_endpoints_in_docs=True,
        access_verifier=_RoleVerifier(role),
    )
    app = FastAPI()
    install_internal_api_error_handlers(app, configuration)
    app.include_router(create_site_audit_settings_router(service, configuration))
    return TestClient(app)


def test_private_routes_enforce_administrator_operator_and_viewer_boundaries(
    tmp_path: Path,
) -> None:
    runtime, service = _runtime(tmp_path)
    base = "/api/internal/v1/site-audits"
    try:
        with _client(service, UserRole.VIEWER) as viewer:
            assert viewer.get(f"{base}/presets").status_code == 403
            assert viewer.get(f"{base}/site-profiles").status_code == 403
        with _client(service, UserRole.OPERATOR) as operator:
            assert operator.get(f"{base}/presets").status_code == 200
            assert operator.get(f"{base}/site-profiles").status_code == 200
            assert operator.get(f"{base}/settings").status_code == 403
            assert (
                operator.post(
                    f"{base}/site-profiles", json={"configuration": _profile()}
                ).status_code
                == 403
            )
            assert (
                operator.post(f"{base}/effective-settings", json={"sample_urls": []}).status_code
                == 200
            )
            rule = {
                "rule_id": "audit.api",
                "name": "API sample",
                "match_type": "exact_path",
                "match_value": "/sample",
                "action": "crawl_and_mark_for_review",
                "reason": "API regression",
                "reason_code": "api_regression",
            }
            assert operator.post(f"{base}/rules/validate", json={"rule": rule}).json()["data"][
                "valid"
            ]
            tested = operator.post(
                f"{base}/rule-tests",
                json={
                    "overrides": {"rules": [rule]},
                    "sample_urls": ["https://example.com/sample"],
                },
            )
            assert tested.status_code == 200
            assert tested.json()["data"]["test"]["network_access"] is False
            invalid = operator.post(f"{base}/rule-tests", json={"sample_urls": []})
            assert invalid.status_code == 400
            assert invalid.json()["error"]["code"] == "site_audit_rule_test_limit"
        with _client(service, UserRole.ADMINISTRATOR) as administrator:
            assert administrator.get(f"{base}/settings").status_code == 200
            created = administrator.post(
                f"{base}/site-profiles", json={"configuration": _profile()}
            )
            assert created.status_code == 200
            profile_id = created.json()["data"]["profile_id"]
            assert (
                administrator.get(f"{base}/site-profiles/{profile_id}/versions").status_code == 200
            )
            assert (
                administrator.post(f"{base}/site-profiles/{profile_id}/archive").status_code == 200
            )
        assert permission_for_request("GET", f"{base}/settings") is Permission.SETTINGS_MANAGE
        assert permission_for_request("GET", f"{base}/presets") is Permission.JOBS_SUBMIT
        assert permission_for_request("POST", f"{base}/site-profiles") is Permission.SETTINGS_MANAGE
        assert permission_for_request("POST", f"{base}/rule-tests") is Permission.JOBS_SUBMIT
    finally:
        runtime.dispose()


def test_routes_are_opt_in_private_and_preview_is_explicitly_deferred(tmp_path: Path) -> None:
    runtime, service = _runtime(tmp_path)
    try:
        assert list(create_app().openapi()["paths"]) == ["/api/health"]
        with _client(service, UserRole.OPERATOR) as client:
            internal = client.post("/api/internal/v1/site-audits/rule-previews")
            assert internal.status_code == 409
            assert internal.json()["error"]["code"] == "site_audit_rule_preview_deferred"
            assert client.get("/api/site-audits/presets").status_code == 404
    finally:
        runtime.dispose()

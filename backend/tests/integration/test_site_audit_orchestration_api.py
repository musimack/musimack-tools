"""Private CSA-04 route, role, pagination, and error-boundary tests."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from musimack_tools.api.dependencies import permission_for_request
from musimack_tools.api.errors import install_internal_api_error_handlers
from musimack_tools.api.site_audit_orchestration import create_site_audit_orchestration_router
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
from musimack_tools.domain.site_audit_orchestration import SiteAuditOrchestrationError
from musimack_tools.main import create_app


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


class _Service:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def history(
        self,
        *,
        offset: int,
        page_size: int,
        lifecycle: str | None,
        search: str | None,
    ) -> dict[str, Any]:
        return {
            "items": (),
            "total": 0,
            "offset": offset,
            "page_size": page_size,
            "lifecycle": lifecycle,
            "search": search,
        }

    def create_draft(
        self, draft: dict[str, Any], *, actor: str, idempotency_key: str | None
    ) -> dict[str, Any]:
        self.calls.append(("create", (actor, idempotency_key)))
        return {"audit_id": "audit-created", "draft": draft, "revision": 1}

    def audit_detail(self, audit_id: str) -> dict[str, Any]:
        return {"audit": {"audit_id": audit_id, "revision": 1, "draft": {}}}

    def update_draft(
        self, audit_id: str, draft: dict[str, Any], *, expected_revision: int
    ) -> dict[str, Any]:
        return {"audit_id": audit_id, "revision": expected_revision + 1, "draft": draft}

    def validate_draft(self, audit_id: str, *, expected_revision: int) -> dict[str, Any]:
        return {"audit": {"audit_id": audit_id, "revision": expected_revision + 2}}

    async def preflight_draft(self, audit_id: str, *, expected_revision: int) -> dict[str, Any]:
        return {"audit": {"audit_id": audit_id, "revision": expected_revision + 2}}

    async def submit(self, audit_id: str, *, actor: str) -> dict[str, Any]:
        self.calls.append(("submit", actor))
        return {"audit_id": audit_id, "state": "queued"}

    async def cancel(self, audit_id: str) -> dict[str, Any]:
        self.calls.append(("cancel", audit_id))
        return {"audit_id": audit_id, "state": "cancel_requested"}

    async def retry(self, audit_id: str) -> dict[str, Any]:
        self.calls.append(("retry", audit_id))
        return {"audit_id": audit_id, "state": "queued"}

    async def reconcile(self, audit_id: str) -> dict[str, Any]:
        return {"audit_id": audit_id, "state": "running"}

    def status(self, audit_id: str) -> dict[str, Any]:
        if audit_id == "missing":
            raise SiteAuditOrchestrationError("site_audit_not_found", "Audit not found.")
        return {"audit_id": audit_id, "state": "running", "modules": ()}

    def summary(self, audit_id: str) -> dict[str, Any]:
        return {"audit_id": audit_id, "urls": 2}

    def pages(  # noqa: PLR0913 - fake mirrors the explicit bounded route contract.
        self,
        audit_id: str,
        *,
        offset: int,
        page_size: int,
        filters: dict[str, Any] | None = None,
        sort: str = "sequence",
        direction: str = "asc",
    ) -> dict[str, Any]:
        return {
            "audit_id": audit_id,
            "offset": offset,
            "page_size": page_size,
            "total": 0,
            "items": (),
            "filters": filters,
            "ordering": f"{sort}:{direction}",
        }

    def page_detail(self, audit_id: str, sequence: int) -> dict[str, Any]:
        return {"audit_id": audit_id, "sequence": sequence}

    def issues(
        self,
        audit_id: str,
        *,
        offset: int,
        page_size: int,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.pages(audit_id, offset=offset, page_size=page_size, filters=filters)

    def rules(self, audit_id: str, *, offset: int, page_size: int) -> dict[str, Any]:
        return self.pages(audit_id, offset=offset, page_size=page_size)

    def issue_detail(
        self, audit_id: str, group_id: str, *, offset: int, page_size: int
    ) -> dict[str, Any]:
        return {
            "audit_id": audit_id,
            "group_id": group_id,
            "offset": offset,
            "page_size": page_size,
        }

    def sitemap_comparison(
        self, audit_id: str, *, offset: int, page_size: int, filters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return self.pages(audit_id, offset=offset, page_size=page_size, filters=filters)

    def sitemap_documents(
        self, audit_id: str, *, offset: int, page_size: int, filters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return self.pages(audit_id, offset=offset, page_size=page_size, filters=filters)

    def exclusions(
        self, audit_id: str, *, offset: int, page_size: int, filters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return self.pages(audit_id, offset=offset, page_size=page_size, filters=filters)

    def evidence(self, audit_id: str) -> dict[str, Any]:
        return {"audit_id": audit_id, "body_content_retained": False}

    def settings_snapshot(self, audit_id: str) -> dict[str, Any]:
        return {"audit_id": audit_id, "configuration": {}}

    def archive(self, audit_id: str) -> dict[str, Any]:
        return {"audit_id": audit_id, "lifecycle": "archived"}

    def artifact_associations(self, audit_id: str) -> tuple[dict[str, Any], ...]:
        return ({"audit_id": audit_id, "filename": "site-audit-summary.md"},)

    def rebuild_summary(self, audit_id: str) -> dict[str, Any]:
        return {"audit_id": audit_id, "rebuilt": True}


def _client(service: _Service, role: UserRole) -> TestClient:
    configuration = InternalApiConfiguration(
        mount_internal_routes=True,
        include_internal_routes_in_schema=True,
        include_internal_endpoints_in_docs=True,
        access_verifier=_RoleVerifier(role),
    )
    app = FastAPI()
    install_internal_api_error_handlers(app, configuration)
    app.include_router(create_site_audit_orchestration_router(service, configuration))  # type: ignore[arg-type]
    return TestClient(app)


def test_roles_routes_errors_and_bounded_pagination() -> None:
    service = _Service()
    base = "/api/internal/v1/site-audits/audit-1"
    with _client(service, UserRole.VIEWER) as viewer:
        assert viewer.get("/api/internal/v1/site-audits").status_code == 200
        assert viewer.get(f"{base}").status_code == 200
        assert viewer.get(f"{base}/status").status_code == 200
        assert viewer.get(f"{base}/summary").status_code == 200
        assert viewer.post(f"{base}/submit").status_code == 403
        page = viewer.get(f"{base}/pages?offset=25&page_size=50")
        assert page.status_code == 200
        assert page.json()["data"]["offset"] == 25
        assert page.json()["data"]["page_size"] == 50
        bounded = viewer.get(f"{base}/pages?page_size=501")
        assert bounded.status_code == 400
        assert bounded.json()["error"]["code"] == "request_validation_failed"
        assert viewer.get(f"{base}/pages/7").json()["data"]["sequence"] == 7
        assert viewer.get(f"{base}/issues/group-1").status_code == 200
        filtered = viewer.get(
            f"{base}/pages?url=product&only_actionable=true&sort=severity&direction=desc"
        )
        assert filtered.status_code == 200
        assert filtered.json()["data"]["filters"]["url"] == "product"
        assert filtered.json()["data"]["filters"]["only_actionable"] is True
        assert filtered.json()["data"]["ordering"] == "severity:desc"
        assert viewer.get(f"{base}/sitemap-documents?parse_state=invalid").status_code == 200
        assert viewer.get(f"{base}/sitemap-comparisons").status_code == 200
        assert viewer.get(f"{base}/exclusions").status_code == 200
        assert viewer.get(f"{base}/evidence").json()["data"]["body_content_retained"] is False
        assert viewer.get(f"{base}/snapshot").status_code == 200
        assert viewer.post(f"{base}/archive").status_code == 403
    with _client(service, UserRole.OPERATOR) as operator:
        created = operator.post(
            "/api/internal/v1/site-audits",
            headers={"Idempotency-Key": "create-1"},
            json={"draft": {"seed_url": "https://example.com/"}},
        )
        assert created.status_code == 200
        assert service.calls[-1] == ("create", ("operator-1", "create-1"))
        assert (
            operator.patch(
                f"{base}/draft", json={"revision": 1, "draft": {"audit_name": "Edited"}}
            ).status_code
            == 200
        )
        assert operator.post(f"{base}/validate", json={"revision": 2}).status_code == 200
        assert operator.post(f"{base}/preflight", json={"revision": 4}).status_code == 200
        assert operator.post(f"{base}/submit").status_code == 200
        assert operator.post(f"{base}/cancel").status_code == 200
        assert operator.post(f"{base}/retry").status_code == 200
    with _client(service, UserRole.ADMINISTRATOR) as administrator:
        assert administrator.post(f"{base}/rebuild-summary").status_code == 200
        assert administrator.post(f"{base}/archive").status_code == 200
        missing = administrator.get("/api/internal/v1/site-audits/missing/status")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "site_audit_not_found"
        assert administrator.get("/api/site-audits/audit-1/status").status_code == 404
    assert permission_for_request("GET", f"{base}/status") is Permission.RUNS_VIEW
    assert permission_for_request("POST", f"{base}/cancel") is Permission.JOBS_CANCEL
    assert permission_for_request("POST", f"{base}/retry") is Permission.JOBS_SUBMIT
    assert (
        permission_for_request("GET", "/api/internal/v1/site-audits/presets")
        is Permission.JOBS_SUBMIT
    )
    assert permission_for_request("GET", "/api/internal/v1/site-audits") is Permission.RUNS_VIEW


def test_anonymous_access_fails_closed_and_default_application_is_health_only() -> None:
    service = _Service()
    configuration = InternalApiConfiguration(
        mount_internal_routes=True,
        include_internal_routes_in_schema=True,
        include_internal_endpoints_in_docs=True,
    )
    private_app = FastAPI()
    install_internal_api_error_handlers(private_app, configuration)
    private_app.include_router(
        create_site_audit_orchestration_router(service, configuration)  # type: ignore[arg-type]
    )
    with TestClient(private_app) as anonymous:
        response = anonymous.get("/api/internal/v1/site-audits/audit-1/status")
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "access_denied"
    assert list(create_app().openapi()["paths"]) == ["/api/health"]

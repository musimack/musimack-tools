from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from musimack_tools.api.authentication import create_authentication_router
from musimack_tools.authentication.service import AuthenticationError, AuthenticationService
from musimack_tools.core.config import Settings
from musimack_tools.deployment.application import create_production_app
from musimack_tools.deployment.settings import ProductionSettings
from musimack_tools.domain.api import InternalApiConfiguration
from musimack_tools.domain.authentication import (
    AuthenticationConfiguration,
    AuthenticationMode,
    UserRole,
    UserState,
)
from musimack_tools.persistence.auth_models import (
    AuthenticationAuditEventModel,
    AuthenticationSessionModel,
    LoginAttemptModel,
    UserCredentialModel,
)
from musimack_tools.persistence.base import Base
from musimack_tools.security.session_authentication import SessionAccessVerifier

if TYPE_CHECKING:
    from musimack_tools.api.dependencies import InternalApiApplication


def _service() -> tuple[AuthenticationService, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    configuration = AuthenticationConfiguration(
        enabled=True,
        mode=AuthenticationMode.USER_SESSION,
        require_secure_cookie=True,
    )
    return AuthenticationService(factory, configuration), factory


def test_bootstrap_sign_in_session_revocation_and_secret_storage() -> None:
    service, factory = _service()
    administrator = service.bootstrap_administrator(
        "Admin@Example.com", "Administrator", "correct horse battery staple"
    )
    assert administrator.role is UserRole.ADMINISTRATOR
    issued = service.sign_in(
        "admin@example.com", "correct horse battery staple", client_key="127.0.0.1"
    )
    assert issued.raw_token.startswith("session-")
    principal = service.authenticate_session(issued.raw_token)
    assert principal.user_id == administrator.user_id
    with factory() as database:
        credential = database.get(UserCredentialModel, administrator.user_id)
        session = database.get(AuthenticationSessionModel, principal.session_id)
        assert credential is not None
        assert len(credential.password_hash) == 64
        assert session is not None
        assert session.token_hash != issued.raw_token
        assert database.scalar(select(func.count()).select_from(AuthenticationAuditEventModel)) == 3
    service.sign_out(issued.raw_token, actor=principal)
    with pytest.raises(AuthenticationError) as captured:
        service.authenticate_session(issued.raw_token)
    assert captured.value.code == "authentication_session_revoked"


def test_user_lifecycle_role_change_and_failed_login_evidence() -> None:
    service, factory = _service()
    admin = service.bootstrap_administrator(
        "admin@example.com", "Administrator", "correct horse battery staple"
    )
    viewer = service.create_user(
        "viewer@example.com",
        "Read Only",
        UserRole.VIEWER,
        "another correct horse battery",
        UserState.ACTIVE,
    )
    issued = service.sign_in(viewer.email, "another correct horse battery", client_key="127.0.0.2")
    service.change_role(viewer.user_id, UserRole.OPERATOR)
    with pytest.raises(AuthenticationError) as captured:
        service.authenticate_session(issued.raw_token)
    assert captured.value.code == "authentication_session_revoked"
    with pytest.raises(AuthenticationError) as captured:
        service.sign_in(admin.email, "wrong password value", client_key="127.0.0.3")
    assert captured.value.code == "authentication_invalid_credentials"
    with factory() as database:
        assert database.scalar(select(func.count()).select_from(LoginAttemptModel)) == 2


def test_session_rotation_atomically_replaces_the_old_token() -> None:
    service, factory = _service()
    service.bootstrap_administrator(
        "admin@example.com", "Administrator", "correct horse battery staple"
    )
    issued = service.sign_in(
        "admin@example.com", "correct horse battery staple", client_key="127.0.0.4"
    )
    with factory.begin() as database:
        row = database.get(AuthenticationSessionModel, issued.principal.session_id)
        assert row is not None
        row.rotated_at = datetime.now(UTC) - timedelta(minutes=31)
    rotated = service.authenticate_and_rotate(issued.raw_token)
    assert rotated.principal.session_id == issued.principal.session_id
    assert rotated.raw_token != issued.raw_token
    with pytest.raises(AuthenticationError) as captured:
        service.authenticate_session(issued.raw_token)
    assert captured.value.code == "authentication_session_invalid"
    assert service.authenticate_session(rotated.raw_token).user_id == issued.principal.user_id
    diagnostics = service.diagnostics()
    assert diagnostics.active_users == 1
    assert diagnostics.administrators == 1
    assert diagnostics.active_sessions == 1
    assert diagnostics.cookie_security_ready
    service.sign_out(rotated.raw_token, actor=rotated.principal)
    assert service.cleanup_sessions(maximum_rows=1) == 1
    assert service.cleanup_sessions(maximum_rows=1) == 0


def test_password_change_preserves_current_and_revokes_other_sessions() -> None:
    service, _factory = _service()
    service.bootstrap_administrator(
        "admin@example.com", "Administrator", "correct horse battery staple"
    )
    current = service.sign_in(
        "admin@example.com", "correct horse battery staple", client_key="current"
    )
    other = service.sign_in("admin@example.com", "correct horse battery staple", client_key="other")
    service.change_password(
        current.principal,
        "correct horse battery staple",
        "new correct horse battery value",
    )
    assert service.authenticate_session(current.raw_token).user_id == current.principal.user_id
    with pytest.raises(AuthenticationError) as captured:
        service.authenticate_session(other.raw_token)
    assert captured.value.code == "authentication_session_revoked"
    with pytest.raises(AuthenticationError) as captured:
        service.sign_in("admin@example.com", "correct horse battery staple")
    assert captured.value.code == "authentication_invalid_credentials"
    assert (
        service.sign_in("admin@example.com", "new correct horse battery value").principal.user_id
        == current.principal.user_id
    )


def test_private_http_sign_in_cookie_me_user_and_audit_contracts() -> None:
    service, _factory = _service()
    service.bootstrap_administrator(
        "admin@example.com", "Administrator", "correct horse battery staple"
    )
    verifier = SessionAccessVerifier(service, service.configuration)
    configuration = InternalApiConfiguration(
        mount_internal_routes=True,
        include_internal_routes_in_schema=True,
        access_verifier=verifier,
    )
    application = FastAPI()
    router = create_authentication_router(service, configuration)
    application.include_router(router)
    routes = {
        (method, getattr(route, "path", ""))
        for route in router.routes
        for method in getattr(route, "methods", set())
        if getattr(route, "path", "").startswith("/api/internal/v1")
    }
    assert len(routes) == 16
    with TestClient(application, base_url="https://testserver") as client:
        response = client.post(
            "/api/internal/v1/auth/sign-in",
            json={
                "email": "admin@example.com",
                "password": "correct horse battery staple",
            },
        )
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert "musimack_session=" in cookie
        assert "HttpOnly" in cookie
        assert "Secure" in cookie
        assert "SameSite=strict" in cookie
        assert "Path=/api/internal/v1" in cookie
        me = client.get("/api/internal/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["role"] == "administrator"
        assert "auth_audit.view" in me.json()["permissions"]
        assert client.get("/api/internal/v1/users").status_code == 200
        assert client.get("/api/internal/v1/auth/audit").status_code == 200
        assert client.post("/api/internal/v1/auth/sign-out").status_code == 200


def test_expanded_production_composition_is_explicit_and_authorizes_viewer() -> None:
    service, _factory = _service()
    service.bootstrap_administrator(
        "admin@example.com", "Administrator", "correct horse battery staple"
    )
    service.create_user(
        "viewer@example.com",
        "Read Only",
        UserRole.VIEWER,
        "another correct horse battery",
        UserState.ACTIVE,
    )
    settings = ProductionSettings.model_validate(
        {
            "enabled": True,
            "authentication_enabled": True,
            "authentication_mode": "user_session",
            "include_openapi": True,
        }
    )
    application = create_production_app(
        cast("InternalApiApplication", object()),
        settings,
        Settings(),
        authentication=service,
    )
    assert len(application.openapi()["paths"]) == 25
    with TestClient(application, base_url="https://testserver") as client:
        signed_in = client.post(
            "/api/internal/v1/auth/sign-in",
            json={
                "email": "viewer@example.com",
                "password": "another correct horse battery",
            },
        )
        assert signed_in.status_code == 200
        assert client.get("/api/internal/v1/auth/me").status_code == 200
        denied = client.get("/api/internal/v1/users")
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "authorization_denied"
        assert service.audit_page(limit=1)[0].event_type == "authorization_denied"
        assert service.audit_page(limit=1)[0].permission == "users.view"

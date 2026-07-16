from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from musimack_tools.domain.authentication import (
    AUTH_AUDIT_VERSION,
    AUTH_COMPATIBILITY_VERSION,
    AUTHENTICATION_VERSION,
    AUTHORIZATION_VERSION,
    SESSION_VERSION,
    AuthenticationConfiguration,
    AuthenticationMode,
    Permission,
    UserRole,
    is_authorized,
    normalize_email,
    permissions_for_role,
    validate_password,
)
from musimack_tools.security.passwords import (
    hash_password,
    new_session_token,
    session_token_hash,
    valid_session_token,
    verify_password,
)


def test_exact_versions_modes_and_secure_defaults() -> None:
    configuration = AuthenticationConfiguration()
    assert AUTHENTICATION_VERSION == "seo-toolkit-authentication-v1"
    assert AUTHORIZATION_VERSION == "seo-toolkit-authorization-v1"
    assert SESSION_VERSION == "seo-toolkit-session-v1"
    assert AUTH_AUDIT_VERSION == "seo-toolkit-auth-audit-v1"
    assert AUTH_COMPATIBILITY_VERSION == "seo-toolkit-auth-compatibility-v1"
    assert tuple(AuthenticationMode) == (
        AuthenticationMode.SHARED_BEARER,
        AuthenticationMode.USER_SESSION,
        AuthenticationMode.HYBRID,
    )
    assert not configuration.enabled
    assert configuration.mode is AuthenticationMode.SHARED_BEARER
    assert configuration.require_secure_cookie
    assert configuration.same_site_policy == "strict"
    with pytest.raises(FrozenInstanceError):
        configuration.enabled = True  # type: ignore[misc]


@pytest.mark.parametrize(
    "changes",
    [
        {"authentication_version": "unknown"},
        {"authorization_version": "unknown"},
        {"session_version": "unknown"},
        {"session_lifetime_minutes": 0},
        {"session_idle_timeout_minutes": 1440},
        {"session_rotation_minutes": 480},
        {"session_max_active_per_user": 0},
        {"password_min_length": 7},
        {"password_hash_iterations": 599_999},
        {"password_max_failed_attempts": 0},
        {"password_lockout_minutes": 0},
        {"login_rate_limit_window_seconds": 0},
        {"login_rate_limit_max_attempts": 0},
        {"session_cookie_name": "bad cookie"},
        {"same_site_policy": "lax"},
    ],
)
def test_invalid_configuration_is_rejected(changes: dict[str, object]) -> None:
    values = {
        name: getattr(AuthenticationConfiguration(), name)
        for name in AuthenticationConfiguration.__dataclass_fields__
    }
    values.update(changes)
    with pytest.raises(ValueError):
        AuthenticationConfiguration(**values)


def test_exact_roles_permissions_and_deny_by_default() -> None:
    assert tuple(UserRole) == (UserRole.ADMINISTRATOR, UserRole.OPERATOR, UserRole.VIEWER)
    assert permissions_for_role(UserRole.ADMINISTRATOR) == frozenset(Permission)
    assert Permission.JOBS_SUBMIT in permissions_for_role(UserRole.OPERATOR)
    assert Permission.JOBS_SUBMIT not in permissions_for_role(UserRole.VIEWER)
    assert Permission.AUTH_AUDIT_VIEW not in permissions_for_role(UserRole.OPERATOR)
    assert not is_authorized("unknown", Permission.JOBS_VIEW)
    assert not is_authorized(UserRole.ADMINISTRATOR, "unknown")


def test_email_password_policy_hash_and_session_token_contract() -> None:
    configuration = AuthenticationConfiguration()
    assert normalize_email("  Admin@Example.COM ") == "admin@example.com"
    validate_password(
        "correct horse battery staple",
        email="admin@example.com",
        display_name="Administrator",
        configuration=configuration,
    )
    with pytest.raises(ValueError):
        validate_password(
            "admin@example.com",
            email="admin@example.com",
            display_name="Administrator",
            configuration=configuration,
        )
    encoded = hash_password("correct horse battery staple", iterations=600_000)
    assert encoded.algorithm == "pbkdf2-hmac-sha256"
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("incorrect value", encoded)
    token = new_session_token()
    assert valid_session_token(token)
    assert len(token) == 72
    assert len(session_token_hash(token)) == 64
    assert token not in session_token_hash(token)

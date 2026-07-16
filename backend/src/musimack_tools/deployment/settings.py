"""Environment-backed, secret-safe settings for the internal deployment boundary."""

from __future__ import annotations

import re
from ipaddress import ip_network
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from musimack_tools.domain.authentication import (
    AUTH_AUDIT_VERSION,
    AUTH_COMPATIBILITY_VERSION,
    AUTHENTICATION_VERSION,
    AUTHORIZATION_VERSION,
    SESSION_VERSION,
    AuthenticationConfiguration,
    AuthenticationMode,
)

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]+$")
_HEADER_NAME = re.compile(r"^[A-Za-z0-9-]+$")
_INVALID_IDENTIFIER = "credential identifier contains unsupported characters"
_INVALID_HEADER = "request ID header name is invalid"
_INVALID_ORIGIN = "CORS origins must be explicit HTTP or HTTPS origins"
_MISSING_CREDENTIAL = "an internal bearer credential is required when enabled"
_MISSING_CORS_ORIGINS = "explicit CORS origins are required when CORS is enabled"
_INSECURE_SESSION_COOKIE = "secure session cookies are required in production"
_TOO_MANY_POLICY_VALUES = "security allowlists may contain at most 32 entries"
_ORIGIN_TOO_LONG = "CORS origins may contain at most 2048 characters"
_MAXIMUM_POLICY_VALUES = 32
_MAXIMUM_ORIGIN_LENGTH = 2_048
StringTuple = Annotated[tuple[str, ...], NoDecode]


class ProductionSettings(BaseSettings):
    """Settings read only when explicit production composition is requested."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MUSIMACK_INTERNAL_API_",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    bearer_token: SecretStr | None = Field(default=None, repr=False)
    enabled: bool = False
    token_id: str = Field(default="internal-operator", min_length=1, max_length=64)
    allowed_origins: StringTuple = ()
    trusted_proxies: StringTuple = ()
    trusted_networks: StringTuple = ()
    include_openapi: bool = False
    request_id_header: str = Field(default="X-Request-ID", min_length=1, max_length=64)
    access_logging: bool = True
    security_headers: bool = True
    cors_enabled: bool = False
    maximum_forwarded_hops: int = Field(default=5, ge=1, le=10)
    maximum_forwarded_header_length: int = Field(default=1_024, ge=64, le=8_192)
    maximum_cors_age_seconds: int = Field(default=600, ge=0, le=3_600)
    authentication_enabled: bool = False
    authentication_mode: AuthenticationMode = AuthenticationMode.SHARED_BEARER
    authentication_version: str = AUTHENTICATION_VERSION
    authorization_version: str = AUTHORIZATION_VERSION
    session_version: str = SESSION_VERSION
    auth_audit_version: str = AUTH_AUDIT_VERSION
    compatibility_version: str = AUTH_COMPATIBILITY_VERSION
    session_cookie_name: str = "musimack_session"
    session_lifetime_minutes: int = 480
    session_idle_timeout_minutes: int = 60
    session_rotation_minutes: int = 30
    session_absolute_max_minutes: int = 1440
    session_max_active_per_user: int = 10
    password_min_length: int = 14
    password_max_length: int = 256
    password_hash_iterations: int = 600_000
    password_max_failed_attempts: int = 10
    password_lockout_minutes: int = 15
    login_rate_limit_window_seconds: int = 300
    login_rate_limit_max_attempts: int = 20
    shared_bearer_compatibility_enabled: bool = True
    shared_bearer_compatibility_admin: bool = True
    require_secure_cookie: bool = True
    same_site_policy: str = "strict"

    @field_validator("allowed_origins", "trusted_proxies", "trusted_networks", mode="before")
    @classmethod
    def parse_string_tuple(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return ()
            return tuple(item.strip() for item in stripped.split(","))
        return value

    @field_validator("token_id")
    @classmethod
    def validate_token_id(cls, value: str) -> str:
        if _SAFE_IDENTIFIER.fullmatch(value) is None:
            raise ValueError(_INVALID_IDENTIFIER)
        return value

    @field_validator("request_id_header")
    @classmethod
    def validate_request_id_header(cls, value: str) -> str:
        if _HEADER_NAME.fullmatch(value) is None:
            raise ValueError(_INVALID_HEADER)
        return value

    @field_validator("trusted_proxies", "trusted_networks")
    @classmethod
    def validate_networks(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > _MAXIMUM_POLICY_VALUES:
            raise ValueError(_TOO_MANY_POLICY_VALUES)
        for item in value:
            ip_network(item, strict=False)
        return value

    @field_validator("allowed_origins")
    @classmethod
    def validate_origins(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > _MAXIMUM_POLICY_VALUES:
            raise ValueError(_TOO_MANY_POLICY_VALUES)
        for origin in value:
            if len(origin) > _MAXIMUM_ORIGIN_LENGTH:
                raise ValueError(_ORIGIN_TOO_LONG)
            parsed = urlsplit(origin)
            if (
                origin == "*"
                or parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(_INVALID_ORIGIN)
        return value

    @field_validator("enabled")
    @classmethod
    def validate_enabled_credential(
        cls,
        value: bool,  # noqa: FBT001 - Pydantic validator signature.
        info: ValidationInfo,
    ) -> bool:
        del info
        return value

    @field_validator("cors_enabled")
    @classmethod
    def validate_cors_relationship(
        cls,
        value: bool,  # noqa: FBT001 - Pydantic validator signature.
        info: ValidationInfo,
    ) -> bool:
        if value and not info.data.get("allowed_origins"):
            raise ValueError(_MISSING_CORS_ORIGINS)
        return value

    @model_validator(mode="after")
    def validate_authentication_expansion(self) -> ProductionSettings:
        authentication_configuration(self)
        if (
            self.enabled
            and self.authentication_mode is not AuthenticationMode.USER_SESSION
            and (self.bearer_token is None or not self.bearer_token.get_secret_value())
        ):
            raise ValueError(_MISSING_CREDENTIAL)
        if self.enabled and self.authentication_enabled and not self.require_secure_cookie:
            raise ValueError(_INSECURE_SESSION_COOKIE)
        return self


def authentication_configuration(settings: ProductionSettings) -> AuthenticationConfiguration:
    """Project secret-free settings into the immutable domain contract."""
    return AuthenticationConfiguration(
        enabled=settings.authentication_enabled,
        mode=settings.authentication_mode,
        authentication_version=settings.authentication_version,
        authorization_version=settings.authorization_version,
        session_version=settings.session_version,
        auth_audit_version=settings.auth_audit_version,
        compatibility_version=settings.compatibility_version,
        session_cookie_name=settings.session_cookie_name,
        session_lifetime_minutes=settings.session_lifetime_minutes,
        session_idle_timeout_minutes=settings.session_idle_timeout_minutes,
        session_rotation_minutes=settings.session_rotation_minutes,
        session_absolute_max_minutes=settings.session_absolute_max_minutes,
        session_max_active_per_user=settings.session_max_active_per_user,
        password_min_length=settings.password_min_length,
        password_max_length=settings.password_max_length,
        password_hash_iterations=settings.password_hash_iterations,
        password_max_failed_attempts=settings.password_max_failed_attempts,
        password_lockout_minutes=settings.password_lockout_minutes,
        login_rate_limit_window_seconds=settings.login_rate_limit_window_seconds,
        login_rate_limit_max_attempts=settings.login_rate_limit_max_attempts,
        shared_bearer_compatibility_enabled=settings.shared_bearer_compatibility_enabled,
        shared_bearer_compatibility_admin=settings.shared_bearer_compatibility_admin,
        require_secure_cookie=settings.require_secure_cookie,
        same_site_policy=settings.same_site_policy,
    )

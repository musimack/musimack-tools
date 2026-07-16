"""Environment-backed, secret-safe settings for the internal deployment boundary."""

from __future__ import annotations

import re
from ipaddress import ip_network
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]+$")
_HEADER_NAME = re.compile(r"^[A-Za-z0-9-]+$")
_INVALID_IDENTIFIER = "credential identifier contains unsupported characters"
_INVALID_HEADER = "request ID header name is invalid"
_INVALID_ORIGIN = "CORS origins must be explicit HTTP or HTTPS origins"
_MISSING_CREDENTIAL = "an internal bearer credential is required when enabled"
_MISSING_CORS_ORIGINS = "explicit CORS origins are required when CORS is enabled"
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
        credential = info.data.get("bearer_token")
        if value and (not isinstance(credential, SecretStr) or not credential.get_secret_value()):
            raise ValueError(_MISSING_CREDENTIAL)
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

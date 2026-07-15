"""Deterministic, network-free URL normalization."""

import ipaddress
import re
from urllib.parse import SplitResult, urljoin, urlsplit, urlunsplit

from musimack_tools.domain.urls import MAX_PORT, NormalizedUrl, UrlErrorCode, UrlNormalizationError

_DEFAULT_PORTS = {"http": 80, "https": 443}
_MAX_HOSTNAME_LENGTH = 253
_INVALID_CHARACTER_PATTERN = re.compile(r"[\x00-\x20\x7f]")
_INVALID_PERCENT_PATTERN = re.compile(r"%(?![0-9A-Fa-f]{2})")
_PERCENT_ESCAPE_PATTERN = re.compile(r"%[0-9A-Fa-f]{2}")
_HOST_LABEL_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")


def normalize_hostname(value: str) -> str:
    """Normalize and validate a domain name or IP literal without DNS access."""
    if not value:
        raise UrlNormalizationError(UrlErrorCode.MISSING_HOSTNAME, "URL hostname is required")

    candidate = value.lower()
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        try:
            ascii_hostname = candidate.encode("idna").decode("ascii")
        except UnicodeError as error:
            raise UrlNormalizationError(
                UrlErrorCode.INVALID_HOSTNAME,
                "URL hostname cannot be IDNA-normalized",
            ) from error

        if len(ascii_hostname) > _MAX_HOSTNAME_LENGTH:
            raise UrlNormalizationError(
                UrlErrorCode.INVALID_HOSTNAME,
                "URL hostname exceeds 253 characters",
            ) from None
        labels = ascii_hostname.split(".")
        if not labels or any(not _HOST_LABEL_PATTERN.fullmatch(label) for label in labels):
            raise UrlNormalizationError(
                UrlErrorCode.INVALID_HOSTNAME,
                "URL hostname contains an invalid label",
            ) from None
        return ascii_hostname
    return address.compressed.lower()


def normalize_url(value: str, *, base: NormalizedUrl | None = None) -> NormalizedUrl:
    """Validate and normalize an absolute URL or a reference with an explicit base."""
    original = value
    if not value:
        raise UrlNormalizationError(UrlErrorCode.EMPTY_URL, "URL value cannot be empty")
    if _INVALID_CHARACTER_PATTERN.search(value):
        raise UrlNormalizationError(
            UrlErrorCode.INVALID_CHARACTER,
            "URL contains whitespace or a control character",
        )

    try:
        initial = urlsplit(value)
    except ValueError as error:
        raise UrlNormalizationError(UrlErrorCode.INVALID_URL, "URL cannot be parsed") from error

    if not initial.scheme and base is None:
        raise UrlNormalizationError(
            UrlErrorCode.MISSING_SCHEME,
            "Absolute seed URLs require an explicit http or https scheme",
        )

    resolved_value = urljoin(base.normalized, value) if base is not None else value
    try:
        parts = urlsplit(resolved_value)
    except ValueError as error:
        raise UrlNormalizationError(UrlErrorCode.INVALID_URL, "URL cannot be parsed") from error

    scheme, hostname, explicit_port, effective_port = _validated_authority(parts)

    path = parts.path or "/"
    _validate_percent_encoding(path)
    _validate_percent_encoding(parts.query)
    normalized_path = _uppercase_percent_escapes(_remove_dot_segments(path))
    normalized_query = _uppercase_percent_escapes(parts.query)

    host_for_authority = f"[{hostname}]" if ":" in hostname else hostname
    include_port = explicit_port is not None and explicit_port != _DEFAULT_PORTS[scheme]
    authority = f"{host_for_authority}:{effective_port}" if include_port else host_for_authority
    normalized = urlunsplit(SplitResult(scheme, authority, normalized_path, normalized_query, ""))
    origin = f"{scheme}://{authority}"

    # This module is the sole validation boundary permitted to use the guarded factory.
    return NormalizedUrl._from_validated_parts(  # noqa: SLF001
        original=original,
        normalized=normalized,
        scheme=scheme,
        hostname=hostname,
        effective_port=effective_port,
        origin=origin,
    )


def _validated_authority(parts: SplitResult) -> tuple[str, str, int | None, int]:
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS:
        raise UrlNormalizationError(
            UrlErrorCode.UNSUPPORTED_SCHEME,
            "Only http and https URLs are supported",
        )
    if parts.username is not None or parts.password is not None:
        raise UrlNormalizationError(
            UrlErrorCode.EMBEDDED_CREDENTIALS,
            "Embedded URL usernames and passwords are not allowed",
        )
    if parts.hostname is None:
        raise UrlNormalizationError(UrlErrorCode.MISSING_HOSTNAME, "URL hostname is required")

    hostname = normalize_hostname(parts.hostname)
    try:
        explicit_port = parts.port
    except ValueError as error:
        raise UrlNormalizationError(
            UrlErrorCode.INVALID_PORT,
            "URL port must be an integer between 1 and 65535",
        ) from error
    effective_port = explicit_port or _DEFAULT_PORTS[scheme]
    if not 1 <= effective_port <= MAX_PORT:
        raise UrlNormalizationError(
            UrlErrorCode.INVALID_PORT,
            "URL port must be between 1 and 65535",
        )
    return scheme, hostname, explicit_port, effective_port


def _validate_percent_encoding(value: str) -> None:
    if _INVALID_PERCENT_PATTERN.search(value):
        raise UrlNormalizationError(
            UrlErrorCode.INVALID_PERCENT_ENCODING,
            "URL contains an invalid percent escape",
        )


def _uppercase_percent_escapes(value: str) -> str:
    return _PERCENT_ESCAPE_PATTERN.sub(lambda match: match.group(0).upper(), value)


def _remove_dot_segments(path: str) -> str:
    """Apply RFC 3986 dot-segment removal without collapsing unrelated slashes."""
    remaining = path
    output = ""

    while remaining:
        if remaining.startswith("../"):
            remaining = remaining[3:]
        elif remaining.startswith(("./", "/./")):
            remaining = remaining[2:]
        elif remaining == "/.":
            remaining = "/"
        elif remaining.startswith("/../"):
            remaining = remaining[3:]
            output = _remove_last_path_segment(output)
        elif remaining == "/..":
            remaining = "/"
            output = _remove_last_path_segment(output)
        elif remaining in {".", ".."}:
            remaining = ""
        else:
            segment_end = remaining.find("/", 1 if remaining.startswith("/") else 0)
            if segment_end == -1:
                output += remaining
                remaining = ""
            else:
                output += remaining[:segment_end]
                remaining = remaining[segment_end:]

    return output or "/"


def _remove_last_path_segment(path: str) -> str:
    separator = path.rfind("/")
    return path[:separator] if separator >= 0 else ""

"""Immutable robots.txt retrieval, parse, and crawl-permission evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RobotsFetchOutcome(StrEnum):
    """Stable origin-level robots retrieval outcomes."""

    FETCHED = "fetched"
    NO_POLICY = "no_policy"
    ACCESS_DENIED = "access_denied"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
    FETCH_FAILED = "fetch_failed"
    RESPONSE_TOO_LARGE = "response_too_large"
    INVALID_RESPONSE = "invalid_response"


class RobotsParseOutcome(StrEnum):
    """Stable robots document parse outcomes."""

    PARSED = "parsed"
    EMPTY = "empty"
    NOT_APPLICABLE = "not_applicable"
    INVALID = "invalid"


class RobotsRuleKind(StrEnum):
    """Recognized path rule directives."""

    ALLOW = "allow"
    DISALLOW = "disallow"


class RobotsWarningCode(StrEnum):
    """Stable robots retrieval and parse warning codes."""

    NOT_FOUND = "robots_not_found"
    ACCESS_DENIED = "robots_access_denied"
    TEMPORARILY_UNAVAILABLE = "robots_temporarily_unavailable"
    FETCH_FAILED = "robots_fetch_failed"
    RESPONSE_TOO_LARGE = "robots_response_too_large"
    INVALID_CONTENT_TYPE = "robots_invalid_content_type"
    DECODE_WARNING = "robots_decode_warning"
    MALFORMED_LINE = "robots_malformed_line"
    LINE_TOO_LONG = "robots_line_too_long"
    LINE_LIMIT_EXCEEDED = "robots_line_limit_exceeded"
    UNKNOWN_DIRECTIVE = "robots_unknown_directive"
    INVALID_USER_AGENT = "robots_invalid_user_agent"
    INVALID_RULE = "robots_invalid_rule"
    INVALID_CRAWL_DELAY = "robots_invalid_crawl_delay"
    CONFLICTING_CRAWL_DELAY = "robots_conflicting_crawl_delay"
    INVALID_SITEMAP = "robots_invalid_sitemap"
    NO_MATCHING_GROUP = "robots_no_matching_group"


class CrawlPermissionReason(StrEnum):
    """Stable reasons for a robots crawl-permission decision."""

    ALLOWED_BY_ALLOW_RULE = "allowed_by_allow_rule"
    DENIED_BY_DISALLOW_RULE = "denied_by_disallow_rule"
    ALLOWED_NO_MATCHING_RULE = "allowed_no_matching_rule"
    ALLOWED_NO_ROBOTS_FILE = "allowed_no_robots_file"
    DENIED_ROBOTS_ACCESS_FORBIDDEN = "denied_robots_access_forbidden"
    DENIED_ROBOTS_TEMPORARILY_UNAVAILABLE = "denied_robots_temporarily_unavailable"
    DENIED_INVALID_ROBOTS_RESPONSE = "denied_invalid_robots_response"
    ALLOWED_NO_MATCHING_GROUP = "allowed_no_matching_group"
    ALLOWED_TEST_POLICY = "allowed_test_policy"


@dataclass(frozen=True, slots=True)
class RobotsWarning:
    """One bounded robots warning."""

    code: RobotsWarningCode
    explanation: str
    line_number: int | None = None
    observed_value: str | None = None


@dataclass(frozen=True, slots=True)
class RobotsUserAgent:
    """One user-agent declaration with source evidence."""

    value: str
    line_number: int


@dataclass(frozen=True, slots=True)
class RobotsRule:
    """One Allow or Disallow rule."""

    kind: RobotsRuleKind
    pattern: str
    line_number: int


@dataclass(frozen=True, slots=True)
class CrawlDelayEvidence:
    """One parsed or invalid Crawl-delay value."""

    raw_value: str
    seconds: float | None
    line_number: int


@dataclass(frozen=True, slots=True)
class SitemapDirective:
    """One observed Sitemap directive; it is never fetched here."""

    raw_value: str
    normalized_url: str | None
    line_number: int
    valid: bool


@dataclass(frozen=True, slots=True)
class UnsupportedRobotsDirective:
    """One unrecognized field retained as evidence."""

    field_name: str
    raw_value: str
    line_number: int


@dataclass(frozen=True, slots=True)
class RobotsUserAgentGroup:
    """One contiguous robots group and its directives."""

    group_index: int
    user_agents: tuple[RobotsUserAgent, ...]
    rules: tuple[RobotsRule, ...]
    crawl_delays: tuple[CrawlDelayEvidence, ...]
    unsupported_directives: tuple[UnsupportedRobotsDirective, ...]
    first_line_number: int


@dataclass(frozen=True, slots=True)
class RobotsParseResult:
    """Complete bounded parse evidence for one robots body."""

    outcome: RobotsParseOutcome
    groups: tuple[RobotsUserAgentGroup, ...]
    sitemap_directives: tuple[SitemapDirective, ...]
    unsupported_directives: tuple[UnsupportedRobotsDirective, ...]
    warnings: tuple[RobotsWarning, ...]
    line_count: int
    selected_encoding: str | None


@dataclass(frozen=True, slots=True)
class MatchedRobotsRule:
    """The winning rule and deterministic specificity evidence."""

    kind: RobotsRuleKind
    pattern: str
    line_number: int
    specificity: int


@dataclass(frozen=True, slots=True)
class RobotsOriginRecord:
    """Shared one-origin robots retrieval and parse evidence."""

    origin: str
    robots_url: str
    requested_url: str
    final_url: str
    fetch_outcome: RobotsFetchOutcome
    parse_result: RobotsParseResult
    status_code: int | None
    accepted_bytes: int
    fetch_attempted: bool
    temporary_unavailability: bool
    warnings: tuple[RobotsWarning, ...]
    fetch_failure_code: str | None = None


@dataclass(frozen=True, slots=True)
class CrawlPermissionDecision:
    """Robots permission evidence, distinct from page indexability."""

    evaluated_url: str
    origin: str
    robots_url: str
    fetch_outcome: RobotsFetchOutcome
    parse_outcome: RobotsParseOutcome
    selected_group_index: int | None
    matched_rule: MatchedRobotsRule | None
    allowed: bool
    reason_code: CrawlPermissionReason
    explanation: str
    cache_hit: bool
    warnings: tuple[RobotsWarning, ...]
    temporary_unavailability: bool
    newly_fetched_bytes: int
    evaluation_duration_seconds: float

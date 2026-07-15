"""Per-origin robots.txt retrieval, parsing, caching, and permission evaluation."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlsplit

from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.domain.fetching import FetchFailureCode, FetchOutcome, FetchRequest, FetchResult
from musimack_tools.domain.robots import (
    CrawlDelayEvidence,
    CrawlPermissionDecision,
    CrawlPermissionReason,
    MatchedRobotsRule,
    RobotsFetchOutcome,
    RobotsOriginRecord,
    RobotsParseOutcome,
    RobotsParseResult,
    RobotsRule,
    RobotsRuleKind,
    RobotsUserAgent,
    RobotsUserAgentGroup,
    RobotsWarning,
    RobotsWarningCode,
    SitemapDirective,
    UnsupportedRobotsDirective,
)
from musimack_tools.domain.urls import UrlNormalizationError

if TYPE_CHECKING:
    from musimack_tools.core.config import Settings
    from musimack_tools.domain.urls import CrawlScopePolicy, NormalizedUrl

_LOGGER = logging.getLogger(__name__)
_DEFAULT_BODY_LIMIT = 1_000_000
_HARD_BODY_LIMIT = 5_000_000
_DEFAULT_LINE_LENGTH = 8_192
_HARD_LINE_LENGTH = 65_536
_DEFAULT_LINE_COUNT = 10_000
_HARD_LINE_COUNT = 100_000
_STATUS_OK = 200
_STATUS_NO_CONTENT = 204
_STATUS_TOO_MANY_REQUESTS = 429
_SERVER_ERROR_MIN = 500
_SERVER_ERROR_MAX = 599
_SAFE_VALUE_LENGTH = 160
_USER_AGENT_PATTERN = re.compile(r"^(?:\*|[A-Za-z][A-Za-z0-9_-]*)$")
_TEMPORARY_FETCH_FAILURES = frozenset(
    {
        FetchFailureCode.CONNECT_TIMEOUT,
        FetchFailureCode.READ_TIMEOUT,
        FetchFailureCode.WRITE_TIMEOUT,
        FetchFailureCode.POOL_TIMEOUT,
        FetchFailureCode.REQUEST_DEADLINE_EXCEEDED,
        FetchFailureCode.TRANSPORT_ERROR,
        FetchFailureCode.DNS_RESOLUTION_FAILED,
    }
)
Clock = Callable[[], float]


class RobotsFetcher(Protocol):
    """Accepted safe-fetch interface used for robots retrieval."""

    async def fetch(self, request: FetchRequest, scope: CrawlScopePolicy) -> FetchResult:
        """Fetch one already normalized robots URL."""
        ...


class RobotsCache(Protocol):
    """Per-crawl origin cache interface."""

    def get(self, origin: str) -> RobotsOriginRecord | None:
        """Return cached origin evidence when available."""
        ...

    def set(self, origin: str, record: RobotsOriginRecord) -> None:
        """Store immutable origin evidence."""
        ...

    def records(self) -> tuple[RobotsOriginRecord, ...]:
        """Return records in stable insertion order."""
        ...


@dataclass(slots=True)
class InMemoryRobotsCache:
    """Simple process-local cache scoped to one crawl session."""

    _records: dict[str, RobotsOriginRecord] = field(default_factory=dict)

    def get(self, origin: str) -> RobotsOriginRecord | None:
        return self._records.get(origin)

    def set(self, origin: str, record: RobotsOriginRecord) -> None:
        self._records[origin] = record

    def records(self) -> tuple[RobotsOriginRecord, ...]:
        return tuple(self._records.values())


class RobotsCrawlSession(Protocol):
    """One-crawl robots permission and cache boundary."""

    async def evaluate(
        self,
        url: NormalizedUrl,
        scope: CrawlScopePolicy,
        correlation_id: str | None = None,
    ) -> CrawlPermissionDecision:
        """Evaluate one URL after obtaining its origin policy."""
        ...

    def origin_records(self) -> tuple[RobotsOriginRecord, ...]:
        """Return shared origin-level evidence."""
        ...


class RobotsSessionFactory(Protocol):
    """Create an isolated cache for each crawl."""

    def create_session(self) -> RobotsCrawlSession:
        """Return a fresh session."""
        ...


class RobotsTxtParser:
    """Deterministic bounded line-oriented robots parser."""

    def __init__(
        self,
        *,
        maximum_line_length: int = _DEFAULT_LINE_LENGTH,
        maximum_line_count: int = _DEFAULT_LINE_COUNT,
    ) -> None:
        if not 1 <= maximum_line_length <= _HARD_LINE_LENGTH:
            message = "robots maximum line length is outside the hard bounds"
            raise ValueError(message)
        if not 1 <= maximum_line_count <= _HARD_LINE_COUNT:
            message = "robots maximum line count is outside the hard bounds"
            raise ValueError(message)
        self._maximum_line_length = maximum_line_length
        self._maximum_line_count = maximum_line_count

    def parse(  # noqa: C901, PLR0912, PLR0915 - line grammar remains explicit and auditable.
        self, body: bytes
    ) -> RobotsParseResult:
        """Decode and parse one bounded robots body."""
        warnings: list[RobotsWarning] = []
        try:
            text = body.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError:
            text = body.decode("utf-8-sig", errors="replace")
            warnings.append(
                _warning(
                    RobotsWarningCode.DECODE_WARNING,
                    "robots.txt contained invalid UTF-8 and replacement decoding was used",
                )
            )
        lines = text.splitlines()
        if len(lines) > self._maximum_line_count:
            warnings.append(
                _warning(
                    RobotsWarningCode.LINE_LIMIT_EXCEEDED,
                    "robots.txt exceeded the configured line-count limit",
                    observed_value=str(len(lines)),
                )
            )
            lines = lines[: self._maximum_line_count]

        builders: list[_GroupBuilder] = []
        current: _GroupBuilder | None = None
        sitemaps: list[SitemapDirective] = []
        unsupported_global: list[UnsupportedRobotsDirective] = []
        for line_number, raw_line in enumerate(lines, start=1):
            if len(raw_line) > self._maximum_line_length:
                warnings.append(
                    _warning(
                        RobotsWarningCode.LINE_TOO_LONG,
                        "A robots.txt line exceeded the configured length and was ignored",
                        line_number,
                        raw_line[:_SAFE_VALUE_LENGTH],
                    )
                )
                continue
            content = raw_line.split("#", 1)[0].strip()
            if not content:
                continue
            field_name, separator, raw_value = content.partition(":")
            if not separator:
                warnings.append(
                    _warning(
                        RobotsWarningCode.MALFORMED_LINE,
                        "A robots.txt line has no field separator",
                        line_number,
                        content[:_SAFE_VALUE_LENGTH],
                    )
                )
                continue
            name = field_name.strip().lower()
            value = raw_value.strip()
            if not name:
                warnings.append(
                    _warning(
                        RobotsWarningCode.MALFORMED_LINE,
                        "A robots.txt line has an empty field name",
                        line_number,
                    )
                )
                continue
            if name == "user-agent":
                if not value or not _USER_AGENT_PATTERN.fullmatch(value):
                    warnings.append(
                        _warning(
                            RobotsWarningCode.INVALID_USER_AGENT,
                            "A User-agent directive is empty or is not a supported product token",
                            line_number,
                            value[:_SAFE_VALUE_LENGTH] if value else None,
                        )
                    )
                    continue
                if current is None or current.has_directives:
                    current = _GroupBuilder(len(builders), line_number)
                    builders.append(current)
                current.user_agents.append(RobotsUserAgent(value, line_number))
                continue
            if name == "sitemap":
                sitemaps.append(_parse_sitemap(value, line_number, warnings))
                continue
            if current is None or not current.user_agents:
                directive = UnsupportedRobotsDirective(name, value, line_number)
                unsupported_global.append(directive)
                warnings.append(
                    _warning(
                        RobotsWarningCode.UNKNOWN_DIRECTIVE,
                        "A directive outside a User-agent group was retained but not applied",
                        line_number,
                        name[:_SAFE_VALUE_LENGTH],
                    )
                )
                continue
            current.has_directives = True
            if name in {"allow", "disallow"}:
                kind = RobotsRuleKind.ALLOW if name == "allow" else RobotsRuleKind.DISALLOW
                if kind is RobotsRuleKind.ALLOW and not value:
                    warnings.append(
                        _warning(
                            RobotsWarningCode.INVALID_RULE,
                            "An empty Allow rule has no effect",
                            line_number,
                        )
                    )
                current.rules.append(RobotsRule(kind, value, line_number))
            elif name == "crawl-delay":
                current.crawl_delays.append(_parse_crawl_delay(value, line_number, warnings))
            else:
                current.unsupported.append(UnsupportedRobotsDirective(name, value, line_number))
                warnings.append(
                    _warning(
                        RobotsWarningCode.UNKNOWN_DIRECTIVE,
                        "An unsupported robots directive was retained but not applied",
                        line_number,
                        name[:_SAFE_VALUE_LENGTH],
                    )
                )

        groups = tuple(builder.freeze(warnings) for builder in builders)
        outcome = RobotsParseOutcome.EMPTY if not text.strip() else RobotsParseOutcome.PARSED
        return RobotsParseResult(
            outcome,
            groups,
            tuple(sitemaps),
            tuple(unsupported_global),
            tuple(warnings),
            len(lines),
            "utf-8",
        )


@dataclass(slots=True)
class _GroupBuilder:
    group_index: int
    first_line: int
    user_agents: list[RobotsUserAgent] = field(default_factory=list)
    rules: list[RobotsRule] = field(default_factory=list)
    crawl_delays: list[CrawlDelayEvidence] = field(default_factory=list)
    unsupported: list[UnsupportedRobotsDirective] = field(default_factory=list)
    has_directives: bool = False

    def freeze(self, warnings: list[RobotsWarning]) -> RobotsUserAgentGroup:
        values = {item.seconds for item in self.crawl_delays if item.seconds is not None}
        if len(values) > 1:
            warnings.append(
                _warning(
                    RobotsWarningCode.CONFLICTING_CRAWL_DELAY,
                    "A User-agent group contains conflicting Crawl-delay values",
                    self.first_line,
                )
            )
        return RobotsUserAgentGroup(
            self.group_index,
            tuple(self.user_agents),
            tuple(self.rules),
            tuple(self.crawl_delays),
            tuple(self.unsupported),
            self.first_line,
        )


class RobotsTxtService:
    """Factory for isolated robots sessions backed by the accepted safe fetcher."""

    def __init__(  # noqa: PLR0913 - dependencies are intentionally injectable.
        self,
        fetcher: RobotsFetcher,
        *,
        product_token: str | None = None,
        maximum_body_bytes: int = _DEFAULT_BODY_LIMIT,
        parser: RobotsTxtParser | None = None,
        clock: Clock = time.monotonic,
        cache_factory: Callable[[], RobotsCache] = InMemoryRobotsCache,
        logger: logging.Logger = _LOGGER,
    ) -> None:
        selected_product_token = product_token or "MusimackSEOToolkit"
        if not selected_product_token.strip():
            message = "robots product token cannot be empty"
            raise ValueError(message)
        if not 1 <= maximum_body_bytes <= _HARD_BODY_LIMIT:
            message = "robots body limit is outside the hard bounds"
            raise ValueError(message)
        self._fetcher = fetcher
        self._product_token = selected_product_token.strip()
        self._maximum_body_bytes = maximum_body_bytes
        self._parser = parser or RobotsTxtParser()
        self._clock = clock
        self._cache_factory = cache_factory
        self._logger = logger

    def create_session(self) -> RobotsCrawlSession:
        return _RobotsTxtCrawlSession(
            self._fetcher,
            self._product_token,
            self._maximum_body_bytes,
            self._parser,
            self._clock,
            self._cache_factory(),
            self._logger,
        )

    @classmethod
    def from_settings(
        cls,
        fetcher: RobotsFetcher,
        settings: Settings,
        *,
        clock: Clock = time.monotonic,
        cache_factory: Callable[[], RobotsCache] = InMemoryRobotsCache,
        logger: logging.Logger = _LOGGER,
    ) -> RobotsTxtService:
        """Build the service from validated application configuration."""
        parser = RobotsTxtParser(
            maximum_line_length=settings.robots_maximum_line_length,
            maximum_line_count=settings.robots_maximum_line_count,
        )
        return cls(
            fetcher,
            product_token=settings.robots_user_agent_product_token,
            maximum_body_bytes=settings.robots_maximum_response_body_bytes,
            parser=parser,
            clock=clock,
            cache_factory=cache_factory,
            logger=logger,
        )


class _RobotsTxtCrawlSession:
    def __init__(  # noqa: PLR0913 - session dependencies are explicit and testable.
        self,
        fetcher: RobotsFetcher,
        product_token: str,
        maximum_body_bytes: int,
        parser: RobotsTxtParser,
        clock: Clock,
        cache: RobotsCache,
        logger: logging.Logger,
    ) -> None:
        self._fetcher = fetcher
        self._product_token = product_token
        self._maximum_body_bytes = maximum_body_bytes
        self._parser = parser
        self._clock = clock
        self._cache = cache
        self._logger = logger
        self._lock = asyncio.Lock()
        self._in_flight: dict[str, asyncio.Task[RobotsOriginRecord]] = {}

    async def evaluate(
        self,
        url: NormalizedUrl,
        scope: CrawlScopePolicy,
        correlation_id: str | None = None,
    ) -> CrawlPermissionDecision:
        started = self._clock()
        cached = self._cache.get(url.origin)
        if cached is not None:
            self._logger.info("robots_cache_hit", extra={"origin": url.origin})
            return self._finish_decision(
                _evaluate_record(
                    cached,
                    url,
                    self._product_token,
                    cache_hit=True,
                    duration=self._clock() - started,
                )
            )

        async with self._lock:
            cached = self._cache.get(url.origin)
            if cached is not None:
                self._logger.info("robots_cache_hit", extra={"origin": url.origin})
                return self._finish_decision(
                    _evaluate_record(
                        cached,
                        url,
                        self._product_token,
                        cache_hit=True,
                        duration=self._clock() - started,
                    )
                )
            task = self._in_flight.get(url.origin)
            owner = task is None
            if task is None:
                task = asyncio.create_task(self._retrieve(url, scope, correlation_id))
                self._in_flight[url.origin] = task
        record = await task
        if owner:
            async with self._lock:
                self._cache.set(url.origin, record)
                self._in_flight.pop(url.origin, None)
        else:
            self._logger.info("robots_cache_hit", extra={"origin": url.origin})
        return self._finish_decision(
            _evaluate_record(
                record,
                url,
                self._product_token,
                cache_hit=not owner,
                duration=self._clock() - started,
            )
        )

    def origin_records(self) -> tuple[RobotsOriginRecord, ...]:
        return self._cache.records()

    async def _retrieve(
        self,
        url: NormalizedUrl,
        scope: CrawlScopePolicy,
        correlation_id: str | None,
    ) -> RobotsOriginRecord:
        robots_url = normalize_url(f"{url.origin}/robots.txt")
        self._logger.info("robots_fetch_started", extra={"origin": url.origin})
        fetch = await self._fetcher.fetch(FetchRequest(robots_url, correlation_id), scope)
        record = _record_from_fetch(
            fetch,
            url.origin,
            robots_url.normalized,
            self._maximum_body_bytes,
            self._parser,
        )
        for warning in record.warnings:
            self._logger.info(
                "robots_parse_warning",
                extra={"warning_code": warning.code.value, "line_number": warning.line_number},
            )
        self._logger.info(
            "robots_fetch_completed",
            extra={
                "origin": url.origin,
                "fetch_outcome": record.fetch_outcome.value,
                "status_code": record.status_code,
            },
        )
        return record

    def _finish_decision(self, decision: CrawlPermissionDecision) -> CrawlPermissionDecision:
        self._logger.info(
            "crawl_permission_allowed" if decision.allowed else "crawl_permission_denied",
            extra={"origin": decision.origin, "reason_code": decision.reason_code.value},
        )
        return decision


def _record_from_fetch(  # noqa: PLR0911 - status policy is intentionally explicit.
    fetch: FetchResult,
    origin: str,
    robots_url: str,
    maximum_body_bytes: int,
    parser: RobotsTxtParser,
) -> RobotsOriginRecord:
    if fetch.outcome is FetchOutcome.FAILURE:
        temporary = fetch.failure_code in _TEMPORARY_FETCH_FAILURES
        too_large = fetch.failure_code is FetchFailureCode.RESPONSE_TOO_LARGE
        outcome = (
            RobotsFetchOutcome.RESPONSE_TOO_LARGE
            if too_large
            else RobotsFetchOutcome.TEMPORARILY_UNAVAILABLE
            if temporary
            else RobotsFetchOutcome.FETCH_FAILED
        )
        code = (
            RobotsWarningCode.RESPONSE_TOO_LARGE
            if too_large
            else RobotsWarningCode.TEMPORARILY_UNAVAILABLE
            if temporary
            else RobotsWarningCode.FETCH_FAILED
        )
        warning = _warning(code, "robots.txt could not be retrieved safely")
        return _origin_record(
            fetch,
            origin=origin,
            robots_url=robots_url,
            outcome=outcome,
            parsed=_empty_parse(),
            temporary=temporary,
            warnings=(warning,),
        )

    status = fetch.status_code
    if status == _STATUS_OK:
        if fetch.actual_bytes_read > maximum_body_bytes or fetch.body_truncated:
            warning = _warning(
                RobotsWarningCode.RESPONSE_TOO_LARGE,
                "robots.txt exceeded the robots-specific response limit",
            )
            return _origin_record(
                fetch,
                origin=origin,
                robots_url=robots_url,
                outcome=RobotsFetchOutcome.RESPONSE_TOO_LARGE,
                parsed=_empty_parse(RobotsParseOutcome.INVALID),
                temporary=False,
                warnings=(warning,),
            )
        media_type = (fetch.content_type or "").split(";", 1)[0].strip().lower()
        if media_type not in {"", "text/plain", "application/octet-stream"}:
            warning = _warning(
                RobotsWarningCode.INVALID_CONTENT_TYPE,
                "robots.txt used a content type that is not accepted as plain text",
                observed_value=media_type[:_SAFE_VALUE_LENGTH],
            )
            return _origin_record(
                fetch,
                origin=origin,
                robots_url=robots_url,
                outcome=RobotsFetchOutcome.INVALID_RESPONSE,
                parsed=_empty_parse(RobotsParseOutcome.INVALID),
                temporary=False,
                warnings=(warning,),
            )
        parsed = parser.parse(fetch.body or b"")
        return _origin_record(
            fetch,
            origin=origin,
            robots_url=robots_url,
            outcome=RobotsFetchOutcome.FETCHED,
            parsed=parsed,
            temporary=False,
            warnings=parsed.warnings,
        )
    if status == _STATUS_NO_CONTENT:
        return _origin_record(
            fetch,
            origin=origin,
            robots_url=robots_url,
            outcome=RobotsFetchOutcome.NO_POLICY,
            parsed=_empty_parse(),
            temporary=False,
            warnings=(),
        )
    if status in {400, 404}:
        warning = _warning(
            RobotsWarningCode.NOT_FOUND, "No robots policy was found for this origin"
        )
        return _origin_record(
            fetch,
            origin=origin,
            robots_url=robots_url,
            outcome=RobotsFetchOutcome.NO_POLICY,
            parsed=_empty_parse(),
            temporary=False,
            warnings=(warning,),
        )
    if status in {401, 403}:
        warning = _warning(
            RobotsWarningCode.ACCESS_DENIED,
            "Access to robots.txt was denied, so the origin is conservatively blocked",
        )
        return _origin_record(
            fetch,
            origin=origin,
            robots_url=robots_url,
            outcome=RobotsFetchOutcome.ACCESS_DENIED,
            parsed=_empty_parse(),
            temporary=False,
            warnings=(warning,),
        )
    if status == _STATUS_TOO_MANY_REQUESTS or (
        status is not None and _SERVER_ERROR_MIN <= status <= _SERVER_ERROR_MAX
    ):
        warning = _warning(
            RobotsWarningCode.TEMPORARILY_UNAVAILABLE,
            "robots.txt is temporarily unavailable, so ordinary requests are blocked",
        )
        return _origin_record(
            fetch,
            origin=origin,
            robots_url=robots_url,
            outcome=RobotsFetchOutcome.TEMPORARILY_UNAVAILABLE,
            parsed=_empty_parse(),
            temporary=True,
            warnings=(warning,),
        )
    warning = _warning(
        RobotsWarningCode.FETCH_FAILED,
        "robots.txt returned an unsupported response status",
        observed_value=str(status),
    )
    return _origin_record(
        fetch,
        origin=origin,
        robots_url=robots_url,
        outcome=RobotsFetchOutcome.INVALID_RESPONSE,
        parsed=_empty_parse(RobotsParseOutcome.INVALID),
        temporary=False,
        warnings=(warning,),
    )


def _origin_record(  # noqa: PLR0913 - mirrors immutable origin evidence.
    fetch: FetchResult,
    *,
    origin: str,
    robots_url: str,
    outcome: RobotsFetchOutcome,
    parsed: RobotsParseResult,
    temporary: bool,
    warnings: tuple[RobotsWarning, ...],
) -> RobotsOriginRecord:
    return RobotsOriginRecord(
        origin=origin,
        robots_url=robots_url,
        requested_url=fetch.requested_url,
        final_url=fetch.final_url,
        fetch_outcome=outcome,
        parse_result=parsed,
        status_code=fetch.status_code,
        accepted_bytes=fetch.actual_bytes_read,
        fetch_attempted=True,
        temporary_unavailability=temporary,
        warnings=warnings,
        fetch_failure_code=(fetch.failure_code.value if fetch.failure_code is not None else None),
    )


def _evaluate_record(  # noqa: PLR0911 - each policy state has a distinct stable reason.
    record: RobotsOriginRecord,
    url: NormalizedUrl,
    product_token: str,
    *,
    cache_hit: bool,
    duration: float,
) -> CrawlPermissionDecision:
    if record.fetch_outcome is RobotsFetchOutcome.NO_POLICY:
        return _decision(
            record,
            url,
            cache_hit=cache_hit,
            duration=duration,
            selected_group_index=None,
            matched_rule=None,
            allowed=True,
            reason_code=CrawlPermissionReason.ALLOWED_NO_ROBOTS_FILE,
            explanation="No robots policy was found, so crawling is allowed",
        )
    if record.fetch_outcome is RobotsFetchOutcome.ACCESS_DENIED:
        return _decision(
            record,
            url,
            cache_hit=cache_hit,
            duration=duration,
            selected_group_index=None,
            matched_rule=None,
            allowed=False,
            reason_code=CrawlPermissionReason.DENIED_ROBOTS_ACCESS_FORBIDDEN,
            explanation="robots.txt access was forbidden, so this origin is denied",
        )
    if record.fetch_outcome is RobotsFetchOutcome.TEMPORARILY_UNAVAILABLE:
        return _decision(
            record,
            url,
            cache_hit=cache_hit,
            duration=duration,
            selected_group_index=None,
            matched_rule=None,
            allowed=False,
            reason_code=CrawlPermissionReason.DENIED_ROBOTS_TEMPORARILY_UNAVAILABLE,
            explanation="robots.txt is temporarily unavailable, so this URL is not requested",
        )
    if record.fetch_outcome is not RobotsFetchOutcome.FETCHED:
        return _decision(
            record,
            url,
            cache_hit=cache_hit,
            duration=duration,
            selected_group_index=None,
            matched_rule=None,
            allowed=False,
            reason_code=CrawlPermissionReason.DENIED_INVALID_ROBOTS_RESPONSE,
            explanation="robots.txt did not produce trustworthy permission evidence",
        )

    group = _select_group(record.parse_result.groups, product_token)
    if group is None:
        warning = _warning(
            RobotsWarningCode.NO_MATCHING_GROUP,
            "No matching User-agent group was found; crawling is allowed",
        )
        return _decision(
            record,
            url,
            cache_hit=cache_hit,
            duration=duration,
            selected_group_index=None,
            matched_rule=None,
            allowed=True,
            reason_code=CrawlPermissionReason.ALLOWED_NO_MATCHING_GROUP,
            explanation="No matching robots User-agent group or wildcard group was found",
            warnings=(*record.warnings, warning),
        )
    matched = _select_rule(group.rules, url)
    if matched is None:
        return _decision(
            record,
            url,
            cache_hit=cache_hit,
            duration=duration,
            selected_group_index=group.group_index,
            matched_rule=None,
            allowed=True,
            reason_code=CrawlPermissionReason.ALLOWED_NO_MATCHING_RULE,
            explanation="The selected robots group has no matching path rule",
        )
    allowed = matched.kind is RobotsRuleKind.ALLOW
    return _decision(
        record,
        url,
        cache_hit=cache_hit,
        duration=duration,
        selected_group_index=group.group_index,
        matched_rule=matched,
        allowed=allowed,
        reason_code=(
            CrawlPermissionReason.ALLOWED_BY_ALLOW_RULE
            if allowed
            else CrawlPermissionReason.DENIED_BY_DISALLOW_RULE
        ),
        explanation=(
            "An Allow rule won the longest-match evaluation"
            if allowed
            else "A Disallow rule won the longest-match evaluation"
        ),
    )


def _decision(  # noqa: PLR0913 - mirrors the explicit public decision evidence.
    record: RobotsOriginRecord,
    url: NormalizedUrl,
    *,
    cache_hit: bool,
    duration: float,
    selected_group_index: int | None,
    matched_rule: MatchedRobotsRule | None,
    allowed: bool,
    reason_code: CrawlPermissionReason,
    explanation: str,
    warnings: tuple[RobotsWarning, ...] | None = None,
) -> CrawlPermissionDecision:
    return CrawlPermissionDecision(
        evaluated_url=url.normalized,
        origin=url.origin,
        robots_url=record.robots_url,
        fetch_outcome=record.fetch_outcome,
        parse_outcome=record.parse_result.outcome,
        selected_group_index=selected_group_index,
        matched_rule=matched_rule,
        allowed=allowed,
        reason_code=reason_code,
        explanation=explanation,
        cache_hit=cache_hit,
        warnings=record.warnings if warnings is None else warnings,
        temporary_unavailability=record.temporary_unavailability,
        newly_fetched_bytes=0 if cache_hit else record.accepted_bytes,
        evaluation_duration_seconds=max(0.0, duration),
    )


def _select_group(
    groups: tuple[RobotsUserAgentGroup, ...], product_token: str
) -> RobotsUserAgentGroup | None:
    product = product_token.lower()
    candidates: list[tuple[int, int, RobotsUserAgentGroup]] = []
    for group in groups:
        specificities = [
            0 if agent.value.strip() == "*" else len(agent.value.strip())
            for agent in group.user_agents
            if agent.value.strip() == "*" or agent.value.strip().lower() in product
        ]
        if specificities:
            candidates.append((max(specificities), -group.group_index, group))
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], item[1]))[2]


def _select_rule(rules: tuple[RobotsRule, ...], url: NormalizedUrl) -> MatchedRobotsRule | None:
    parts = urlsplit(url.normalized)
    target = parts.path or "/"
    if parts.query:
        target = f"{target}?{parts.query}"
    matches: list[MatchedRobotsRule] = []
    for rule in rules:
        if rule.kind is RobotsRuleKind.DISALLOW and not rule.pattern:
            continue
        if not rule.pattern:
            continue
        if _rule_matches(rule.pattern, target):
            specificity = len(rule.pattern.rstrip("$").replace("*", ""))
            matches.append(
                MatchedRobotsRule(rule.kind, rule.pattern, rule.line_number, specificity)
            )
    if not matches:
        return None
    return max(
        matches,
        key=lambda item: (
            item.specificity,
            item.kind is RobotsRuleKind.ALLOW,
            -item.line_number,
        ),
    )


def _rule_matches(pattern: str, target: str) -> bool:
    anchored = pattern.endswith("$")
    content = pattern[:-1] if anchored else pattern
    expression = re.escape(content).replace(r"\*", ".*")
    suffix = "$" if anchored else ""
    return re.match(f"^{expression}{suffix}", target) is not None


def _parse_crawl_delay(
    value: str, line_number: int, warnings: list[RobotsWarning]
) -> CrawlDelayEvidence:
    try:
        parsed = Decimal(value)
        seconds = float(parsed) if parsed.is_finite() and parsed >= 0 else None
    except InvalidOperation, ValueError:
        seconds = None
    if seconds is None:
        warnings.append(
            _warning(
                RobotsWarningCode.INVALID_CRAWL_DELAY,
                "A Crawl-delay value is not a finite non-negative number",
                line_number,
                value[:_SAFE_VALUE_LENGTH],
            )
        )
    return CrawlDelayEvidence(value, seconds, line_number)


def _parse_sitemap(value: str, line_number: int, warnings: list[RobotsWarning]) -> SitemapDirective:
    try:
        normalized = normalize_url(value)
    except UrlNormalizationError, ValueError:
        warnings.append(
            _warning(
                RobotsWarningCode.INVALID_SITEMAP,
                "A Sitemap directive is not a valid absolute HTTP or HTTPS URL",
                line_number,
                value[:_SAFE_VALUE_LENGTH],
            )
        )
        return SitemapDirective(
            raw_value=value,
            normalized_url=None,
            line_number=line_number,
            valid=False,
        )
    return SitemapDirective(
        raw_value=value,
        normalized_url=normalized.normalized,
        line_number=line_number,
        valid=True,
    )


def _empty_parse(
    outcome: RobotsParseOutcome = RobotsParseOutcome.NOT_APPLICABLE,
) -> RobotsParseResult:
    return RobotsParseResult(outcome, (), (), (), (), 0, None)


def _warning(
    code: RobotsWarningCode,
    explanation: str,
    line_number: int | None = None,
    observed_value: str | None = None,
) -> RobotsWarning:
    return RobotsWarning(code, explanation, line_number, observed_value)

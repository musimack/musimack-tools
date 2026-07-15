"""Immutable X-Robots-Tag and combined indexability directive evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from musimack_tools.domain.html import MetaRobotsRecord, RobotsDirective


class DirectiveSource(StrEnum):
    """Source of an observed page-level robots directive."""

    META = "meta"
    X_ROBOTS_TAG = "x_robots_tag"


class IndexabilityWarningCode(StrEnum):
    """Stable X-Robots and combined-evidence warning codes."""

    EMPTY_X_ROBOTS_TAG = "empty_x_robots_tag"
    INVALID_X_ROBOTS_TAG = "invalid_x_robots_tag"
    UNKNOWN_X_ROBOTS_DIRECTIVE = "unknown_x_robots_directive"
    CONFLICTING_X_ROBOTS_DIRECTIVES = "conflicting_x_robots_directives"
    META_HEADER_INDEX_CONFLICT = "meta_header_index_conflict"
    META_HEADER_FOLLOW_CONFLICT = "meta_header_follow_conflict"
    PARAMETER_VALUE_CONFLICT = "parameter_value_conflict"
    CRAWLER_SPECIFIC_DIRECTIVE_DIFFERENCE = "crawler_specific_directive_difference"


class IndexabilityConflictKind(StrEnum):
    """Stable categories of contradictory directive evidence."""

    INDEX = "index"
    FOLLOW = "follow"
    PARAMETER = "parameter"
    SOURCE = "source"
    CRAWLER_SPECIFIC = "crawler_specific"


@dataclass(frozen=True, slots=True)
class IndexabilityWarning:
    """One controlled indexability-evidence warning."""

    code: IndexabilityWarningCode
    explanation: str
    occurrence_index: int | None = None
    observed_value: str | None = None


@dataclass(frozen=True, slots=True)
class HeaderDirectiveRecord:
    """One ordered X-Robots-Tag header value and its parsed directives."""

    raw_value: str
    agent_name: str | None
    directives: tuple[RobotsDirective, ...]
    occurrence_index: int


@dataclass(frozen=True, slots=True)
class XRobotsTagEvidence:
    """All preserved X-Robots-Tag observations."""

    records: tuple[HeaderDirectiveRecord, ...]
    warnings: tuple[IndexabilityWarning, ...]


@dataclass(frozen=True, slots=True)
class IndexabilityConflict:
    """One contradiction without a computed indexability verdict."""

    kind: IndexabilityConflictKind
    directive_name: str
    observed_values: tuple[str, ...]
    sources: tuple[DirectiveSource, ...]
    explanation: str


@dataclass(frozen=True, slots=True)
class CombinedIndexabilityEvidence:
    """Meta and header evidence retained separately with conflicts."""

    meta_robots: tuple[MetaRobotsRecord, ...]
    x_robots_tag: XRobotsTagEvidence
    conflicts: tuple[IndexabilityConflict, ...]
    warnings: tuple[IndexabilityWarning, ...]

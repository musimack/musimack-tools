"""Parse X-Robots-Tag and combine it with meta robots evidence."""

from __future__ import annotations

import logging
import re

from musimack_tools.domain.html import MetaRobotsRecord, RobotsDirective
from musimack_tools.domain.indexability import (
    CombinedIndexabilityEvidence,
    DirectiveSource,
    HeaderDirectiveRecord,
    IndexabilityConflict,
    IndexabilityConflictKind,
    IndexabilityWarning,
    IndexabilityWarningCode,
    XRobotsTagEvidence,
)

_LOGGER = logging.getLogger(__name__)
_KNOWN_DIRECTIVES = frozenset(
    {
        "index",
        "noindex",
        "follow",
        "nofollow",
        "none",
        "noarchive",
        "nosnippet",
        "noimageindex",
        "notranslate",
        "max-snippet",
        "max-image-preview",
        "max-video-preview",
        "unavailable_after",
    }
)
_PARAMETERIZED = frozenset(
    {"max-snippet", "max-image-preview", "max-video-preview", "unavailable_after"}
)
_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


class IndexabilityEvidenceParser:
    """Produce evidence only; never decide indexability or sitemap eligibility."""

    def __init__(self, *, logger: logging.Logger = _LOGGER) -> None:
        self._logger = logger

    def parse_x_robots_tag(self, raw_headers: tuple[str, ...]) -> XRobotsTagEvidence:
        """Parse ordered header values into generic and crawler-specific records."""
        records: list[HeaderDirectiveRecord] = []
        warnings: list[IndexabilityWarning] = []
        for index, raw in enumerate(raw_headers):
            stripped = raw.strip()
            if not stripped:
                warnings.append(
                    _warning(
                        IndexabilityWarningCode.EMPTY_X_ROBOTS_TAG,
                        "An X-Robots-Tag header has an empty value",
                        index,
                    )
                )
                records.append(HeaderDirectiveRecord(raw, None, (), index))
                continue
            agent, directive_text = _split_agent_prefix(stripped)
            if agent == "":
                warnings.append(
                    _warning(
                        IndexabilityWarningCode.INVALID_X_ROBOTS_TAG,
                        "An X-Robots-Tag crawler prefix is invalid",
                        index,
                        stripped[:80],
                    )
                )
                records.append(HeaderDirectiveRecord(raw, None, (), index))
                continue
            directives = _parse_directives(directive_text, index, warnings)
            records.append(HeaderDirectiveRecord(raw, agent, directives, index))

        _append_internal_conflicts(records, warnings)
        evidence = XRobotsTagEvidence(tuple(records), tuple(warnings))
        self._logger.info(
            "x_robots_parsed",
            extra={"header_count": len(raw_headers), "warning_count": len(warnings)},
        )
        return evidence

    def combine(
        self,
        meta_robots: tuple[MetaRobotsRecord, ...],
        x_robots_tag: XRobotsTagEvidence,
    ) -> CombinedIndexabilityEvidence:
        """Retain both sources and identify contradictions without a verdict."""
        conflicts: list[IndexabilityConflict] = []
        warnings = list(x_robots_tag.warnings)
        meta_directives = [
            directive
            for record in meta_robots
            if record.agent_name == "robots"
            for directive in record.directives
        ]
        header_directives = [
            directive
            for record in x_robots_tag.records
            if record.agent_name is None
            for directive in record.directives
        ]
        _append_binary_conflict(
            meta_directives,
            header_directives,
            "index",
            "noindex",
            IndexabilityConflictKind.INDEX,
            IndexabilityWarningCode.META_HEADER_INDEX_CONFLICT,
            conflicts,
            warnings,
        )
        _append_binary_conflict(
            meta_directives,
            header_directives,
            "follow",
            "nofollow",
            IndexabilityConflictKind.FOLLOW,
            IndexabilityWarningCode.META_HEADER_FOLLOW_CONFLICT,
            conflicts,
            warnings,
        )
        _append_parameter_conflicts(meta_directives, header_directives, conflicts, warnings)
        _append_crawler_differences(x_robots_tag.records, conflicts, warnings)
        if conflicts:
            self._logger.info(
                "indexability_conflict_observed", extra={"conflict_count": len(conflicts)}
            )
        return CombinedIndexabilityEvidence(
            meta_robots,
            x_robots_tag,
            tuple(conflicts),
            tuple(warnings),
        )


def _split_agent_prefix(value: str) -> tuple[str | None, str]:
    first, separator, remainder = value.partition(":")
    leading = first.strip().lower()
    if not separator or leading in _KNOWN_DIRECTIVES:
        return None, value
    if not leading or not _NAME_PATTERN.fullmatch(leading):
        return "", remainder
    return leading, remainder.strip()


def _parse_directives(
    value: str,
    occurrence_index: int,
    warnings: list[IndexabilityWarning],
) -> tuple[RobotsDirective, ...]:
    tokens: list[str] = []
    for chunk in value.split(","):
        stripped = chunk.strip()
        if not stripped:
            warnings.append(
                _warning(
                    IndexabilityWarningCode.INVALID_X_ROBOTS_TAG,
                    "X-Robots-Tag contains an empty directive",
                    occurrence_index,
                )
            )
            continue
        leading = stripped.split(":", 1)[0].strip().lower()
        if ":" in stripped and leading in _PARAMETERIZED:
            tokens.append(stripped)
        else:
            tokens.extend(stripped.split())

    directives: list[RobotsDirective] = []
    for token in tokens:
        name_part, separator, value_part = token.partition(":")
        name = name_part.strip().lower()
        parameter = value_part.strip() if separator else None
        valid = bool(_NAME_PATTERN.fullmatch(name)) and not (separator and not parameter)
        known = name in _KNOWN_DIRECTIVES
        directives.append(RobotsDirective(name, parameter, token, known))
        if not valid:
            warnings.append(
                _warning(
                    IndexabilityWarningCode.INVALID_X_ROBOTS_TAG,
                    "An X-Robots-Tag directive has invalid syntax",
                    occurrence_index,
                    token[:80],
                )
            )
        elif not known:
            warnings.append(
                _warning(
                    IndexabilityWarningCode.UNKNOWN_X_ROBOTS_DIRECTIVE,
                    "An X-Robots-Tag directive is not recognized",
                    occurrence_index,
                    name[:80],
                )
            )
    return tuple(directives)


def _append_internal_conflicts(
    records: list[HeaderDirectiveRecord], warnings: list[IndexabilityWarning]
) -> None:
    agents = {record.agent_name for record in records}
    for agent in agents:
        selected = [record for record in records if record.agent_name == agent]
        names = {item.name for record in selected for item in record.directives}
        if {"index", "noindex"} <= names or {"follow", "nofollow"} <= names:
            warnings.append(
                _warning(
                    IndexabilityWarningCode.CONFLICTING_X_ROBOTS_DIRECTIVES,
                    "X-Robots-Tag records for one audience contain conflicting directives",
                    selected[0].occurrence_index,
                )
            )


def _append_binary_conflict(  # noqa: PLR0913 - explicit conflict inputs keep sources distinct.
    meta: list[RobotsDirective],
    header: list[RobotsDirective],
    positive: str,
    negative: str,
    kind: IndexabilityConflictKind,
    warning_code: IndexabilityWarningCode,
    conflicts: list[IndexabilityConflict],
    warnings: list[IndexabilityWarning],
) -> None:
    meta_names = {item.name for item in meta}
    header_names = {item.name for item in header}
    if (positive in meta_names and negative in header_names) or (
        negative in meta_names and positive in header_names
    ):
        conflicts.append(
            IndexabilityConflict(
                kind,
                positive,
                tuple(sorted({positive, negative})),
                (DirectiveSource.META, DirectiveSource.X_ROBOTS_TAG),
                f"Meta robots and X-Robots-Tag disagree about {positive} behavior",
            )
        )
        warnings.append(_warning(warning_code, conflicts[-1].explanation))


def _append_parameter_conflicts(
    meta: list[RobotsDirective],
    header: list[RobotsDirective],
    conflicts: list[IndexabilityConflict],
    warnings: list[IndexabilityWarning],
) -> None:
    for name in sorted(_PARAMETERIZED):
        meta_values = {item.value for item in meta if item.name == name and item.value is not None}
        header_values = {
            item.value for item in header if item.name == name and item.value is not None
        }
        values = meta_values | header_values
        if len(values) > 1:
            conflicts.append(
                IndexabilityConflict(
                    IndexabilityConflictKind.PARAMETER,
                    name,
                    tuple(sorted(values)),
                    (DirectiveSource.META, DirectiveSource.X_ROBOTS_TAG),
                    f"Conflicting values were observed for {name}",
                )
            )
            warnings.append(
                _warning(
                    IndexabilityWarningCode.PARAMETER_VALUE_CONFLICT, conflicts[-1].explanation
                )
            )


def _append_crawler_differences(
    records: tuple[HeaderDirectiveRecord, ...] | list[HeaderDirectiveRecord],
    conflicts: list[IndexabilityConflict],
    warnings: list[IndexabilityWarning],
) -> None:
    generic = {
        (item.name, item.value)
        for record in records
        if record.agent_name is None
        for item in record.directives
    }
    for record in records:
        if record.agent_name is None:
            continue
        specific = {(item.name, item.value) for item in record.directives}
        if generic and specific != generic:
            conflicts.append(
                IndexabilityConflict(
                    IndexabilityConflictKind.CRAWLER_SPECIFIC,
                    record.agent_name,
                    tuple(sorted(f"{name}:{value or ''}" for name, value in specific)),
                    (DirectiveSource.X_ROBOTS_TAG,),
                    "Crawler-specific X-Robots directives differ from generic header directives",
                )
            )
            warnings.append(
                _warning(
                    IndexabilityWarningCode.CRAWLER_SPECIFIC_DIRECTIVE_DIFFERENCE,
                    conflicts[-1].explanation,
                    record.occurrence_index,
                    record.agent_name,
                )
            )


def _warning(
    code: IndexabilityWarningCode,
    explanation: str,
    occurrence_index: int | None = None,
    observed_value: str | None = None,
) -> IndexabilityWarning:
    return IndexabilityWarning(code, explanation, occurrence_index, observed_value)

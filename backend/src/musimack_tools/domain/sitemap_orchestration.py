"""Immutable contracts for sitemap generation and publication composition."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from musimack_tools.domain.sitemap_publication import (
    SITEMAP_PUBLICATION_VERSION,
    SitemapPublicationConfiguration,
    SitemapPublicationResult,
)

if TYPE_CHECKING:
    from musimack_tools.domain.sitemap import SitemapRecommendationProjection
    from musimack_tools.domain.sitemap_xml import SitemapXmlBundle
    from musimack_tools.sitemap.limits import SitemapXmlConfiguration


class SitemapGenerationState(StrEnum):
    """Explicit in-memory generation state."""

    GENERATED = "generated"


@dataclass(frozen=True, slots=True)
class SitemapOrchestrationRequest:
    """Inputs required for generation and optional publication."""

    recommendation_projection: SitemapRecommendationProjection
    xml_configuration: SitemapXmlConfiguration
    publication_configuration: SitemapPublicationConfiguration | None = None


@dataclass(frozen=True, slots=True)
class SitemapOrchestrationResult:
    """Complete immutable internal service result."""

    generation_state: SitemapGenerationState
    xml_bundle: SitemapXmlBundle
    publication_result: SitemapPublicationResult
    recommendation_rule_set_version: str
    xml_format_version: str
    publication_version: str = SITEMAP_PUBLICATION_VERSION

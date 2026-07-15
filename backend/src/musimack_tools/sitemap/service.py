"""Framework-independent sitemap generation and local publication composition."""

from __future__ import annotations

from musimack_tools.domain.sitemap_orchestration import (
    SitemapGenerationState,
    SitemapOrchestrationRequest,
    SitemapOrchestrationResult,
)
from musimack_tools.domain.sitemap_publication import (
    PublicationState,
    SitemapPublicationResult,
)
from musimack_tools.sitemap.publication import SitemapPublicationExecutor, plan_publication
from musimack_tools.sitemap.xml import SitemapXmlGenerator


class SitemapPublicationService:
    """Compose accepted recommendation, XML, planning, and execution boundaries."""

    def __init__(self, executor: SitemapPublicationExecutor | None = None) -> None:
        self._executor = executor or SitemapPublicationExecutor()

    def execute(self, request: SitemapOrchestrationRequest) -> SitemapOrchestrationResult:
        """Generate XML and optionally plan or execute one local publication package."""
        bundle = SitemapXmlGenerator(request.xml_configuration).generate(
            request.recommendation_projection
        )
        publication_configuration = request.publication_configuration
        if publication_configuration is None:
            publication_result = SitemapPublicationResult(
                state=PublicationState.NOT_REQUESTED,
                plan=None,
                published_files=(),
                failures=(),
                published_file_count=0,
                published_byte_count=0,
                manifest_sha256=None,
            )
        else:
            plan = plan_publication(
                bundle,
                request.recommendation_projection.rule_set_version,
                publication_configuration,
            )
            publication_result = self._executor.execute(plan)
        return SitemapOrchestrationResult(
            generation_state=SitemapGenerationState.GENERATED,
            xml_bundle=bundle,
            publication_result=publication_result,
            recommendation_rule_set_version=request.recommendation_projection.rule_set_version,
            xml_format_version=bundle.format_version,
        )

"""Pure raw-request preparation into accepted crawl-run contracts."""

from __future__ import annotations

from enum import StrEnum

from musimack_tools.application.profiles import APPLICATION_HARD_MAXIMA, profile_for
from musimack_tools.application.validation import (
    effective_limits,
    ordered_issues,
    validate_output_root,
)
from musimack_tools.crawl.normalization import normalize_hostname, normalize_url
from musimack_tools.crawl.scope import create_scope_policy
from musimack_tools.domain.application import (
    ApplicationCrawlLimits,
    ApplicationPreparationResult,
    ApplicationValidationReport,
    CrawlProfileName,
    PreparedApplicationRequest,
    RawApplicationCrawlRequest,
    RecommendationProfile,
    ScopeProfile,
    ValidationIssue,
    ValidationIssueCode,
    ValidationSeverity,
)
from musimack_tools.domain.crawl import CrawlRequest
from musimack_tools.domain.job_registry import CRAWL_JOB_REGISTRY_VERSION
from musimack_tools.domain.run import (
    CRAWL_RUN_ORCHESTRATION_VERSION,
    CrawlRunRequest,
    RunStage,
)
from musimack_tools.domain.run_summary import RunSummaryConfiguration
from musimack_tools.domain.sitemap import SITEMAP_RULE_SET_VERSION, RecommendationPolicy
from musimack_tools.domain.sitemap_publication import (
    SITEMAP_PUBLICATION_MANIFEST_VERSION,
    SITEMAP_PUBLICATION_VERSION,
    PublicationMode,
    SitemapPublicationConfiguration,
)
from musimack_tools.domain.sitemap_xml import SITEMAP_XML_FORMAT_VERSION
from musimack_tools.domain.urls import ScopeMode, UrlErrorCode, UrlNormalizationError
from musimack_tools.run.identity import run_identity
from musimack_tools.sitemap.limits import SitemapXmlConfiguration

_DOWNSTREAM_VERSIONS = (
    ("job_registry", CRAWL_JOB_REGISTRY_VERSION),
    ("run", CRAWL_RUN_ORCHESTRATION_VERSION),
    ("recommendation", SITEMAP_RULE_SET_VERSION),
    ("xml", SITEMAP_XML_FORMAT_VERSION),
    ("publication", SITEMAP_PUBLICATION_VERSION),
    ("manifest", SITEMAP_PUBLICATION_MANIFEST_VERSION),
)
_MAX_CALLER_LABEL_CHARACTERS = 200
_MISSING_PREPARATION = "validated request is missing required preparation evidence"


class ApplicationRequestPreparer:
    """Validate and prepare one request without network or filesystem mutation."""

    def __init__(self, maxima: ApplicationCrawlLimits | None = None) -> None:
        self._maxima = maxima or APPLICATION_HARD_MAXIMA

    def prepare(  # noqa: C901, PLR0912, PLR0915 - validators define evidence order.
        self,
        raw: RawApplicationCrawlRequest,
    ) -> ApplicationPreparationResult:
        issues: list[ValidationIssue] = []
        profile = profile_for(raw.crawl_profile)
        if profile is None:
            issues.append(
                ValidationIssue(
                    ValidationSeverity.ERROR,
                    ValidationIssueCode.UNSUPPORTED_PROFILE,
                    "The selected crawl profile is not supported",
                    "crawl_profile",
                    str(raw.crawl_profile),
                )
            )

        seed = None
        try:
            seed = normalize_url(raw.seed_url)
        except UrlNormalizationError as error:
            code = (
                ValidationIssueCode.UNSUPPORTED_SCHEME
                if error.code is UrlErrorCode.UNSUPPORTED_SCHEME
                else ValidationIssueCode.MISSING_HOST
                if error.code is UrlErrorCode.MISSING_HOSTNAME
                else ValidationIssueCode.INVALID_SEED_URL
            )
            issues.append(
                ValidationIssue(
                    ValidationSeverity.ERROR,
                    code,
                    "The seed URL is not a valid absolute HTTP or HTTPS URL",
                    "seed_url",
                )
            )

        scope_profile = _enum_value(ScopeProfile, raw.scope_profile)
        if scope_profile is None:
            issues.append(
                ValidationIssue(
                    ValidationSeverity.ERROR,
                    ValidationIssueCode.CONFLICTING_SCOPE_OPTIONS,
                    "The scope profile is not supported",
                    "scope_profile",
                    str(raw.scope_profile),
                )
            )
        normalized_hosts = _approved_hosts(raw.approved_hosts, issues)
        if scope_profile is ScopeProfile.APPROVED_HOSTS and not normalized_hosts:
            issues.append(
                ValidationIssue(
                    ValidationSeverity.ERROR,
                    ValidationIssueCode.CONFLICTING_SCOPE_OPTIONS,
                    "approved_hosts scope requires at least one valid additional host",
                    "approved_hosts",
                )
            )
        if scope_profile is not ScopeProfile.APPROVED_HOSTS and raw.approved_hosts:
            issues.append(
                ValidationIssue(
                    ValidationSeverity.ERROR,
                    ValidationIssueCode.CONFLICTING_SCOPE_OPTIONS,
                    "approved_hosts values require the approved_hosts scope profile",
                    "approved_hosts",
                )
            )

        recommendation_profile = _enum_value(RecommendationProfile, raw.recommendation_profile)
        if recommendation_profile is None:
            issues.append(
                ValidationIssue(
                    ValidationSeverity.ERROR,
                    ValidationIssueCode.UNSUPPORTED_PROFILE,
                    "The recommendation profile is not supported",
                    "recommendation_profile",
                    str(raw.recommendation_profile),
                )
            )

        limits = None
        if profile is not None:
            limits, limit_issues = effective_limits(
                profile.limits,
                raw.overrides,
                self._maxima,
            )
            issues.extend(limit_issues)

        recommend = (
            profile.recommendation_requested
            if profile is not None and raw.recommendation_requested is None
            else bool(raw.recommendation_requested)
        )
        xml = (
            profile.xml_requested
            if profile is not None and raw.xml_generation_requested is None
            else bool(raw.xml_generation_requested)
        )
        summary = (
            profile.summary_requested
            if profile is not None and raw.summary_writing_requested is None
            else bool(raw.summary_writing_requested)
        )
        if xml and not recommend:
            issues.append(_stage_issue("XML generation requires recommendation"))
        if raw.publication_requested and (not xml or not recommend):
            issues.append(_stage_issue("Publication requires recommendation and XML generation"))
        if raw.publication_requested:
            issues.extend(validate_output_root(raw.publication_root, "publication_root"))
        if summary:
            issues.extend(validate_output_root(raw.summary_root, "summary_root"))
        if raw.caller_label is not None and (
            not raw.caller_label.strip() or len(raw.caller_label) > _MAX_CALLER_LABEL_CHARACTERS
        ):
            issues.append(
                ValidationIssue(
                    ValidationSeverity.ERROR,
                    ValidationIssueCode.INVALID_CALLER_LABEL,
                    "Caller label must contain 1 to 200 non-blank characters",
                    "caller_label",
                )
            )

        _append_nonblocking_issues(
            issues,
            raw,
            profile.name if profile is not None else None,
            scope_profile,
            limits,
            summary,
        )

        stages = _stages(recommend, xml, raw.publication_requested, summary)
        prepared = None
        if not any(item.severity is ValidationSeverity.ERROR for item in issues):
            if seed is None or profile is None or limits is None or scope_profile is None:
                raise RuntimeError(_MISSING_PREPARATION)
            mode = {
                ScopeProfile.EXACT_HOST: ScopeMode.EXACT_HOST,
                ScopeProfile.INCLUDE_SUBDOMAINS: ScopeMode.INCLUDE_SUBDOMAINS,
                ScopeProfile.APPROVED_HOSTS: ScopeMode.APPROVED_HOSTS,
            }[scope_profile]
            scope = create_scope_policy(seed, mode=mode, approved_hosts=normalized_hosts)
            crawl_request = CrawlRequest(
                seed,
                scope,
                maximum_unique_urls=limits.maximum_urls,
                maximum_depth=limits.maximum_depth,
                maximum_duration_seconds=limits.maximum_duration_seconds,
                maximum_total_fetched_bytes=limits.maximum_accepted_bytes,
                maximum_concurrent_fetches=limits.maximum_concurrency,
                maximum_queued_urls=limits.maximum_queue_size,
                minimum_per_origin_delay_seconds=limits.minimum_request_delay_seconds,
                exclusion_rules=raw.exclusion_rules,
                strip_query_parameters=raw.strip_query_parameters,
            )
            publication = _publication_configuration(raw)
            summary_configuration = _summary_configuration(raw, summary)
            recommendation_policy = RecommendationPolicy(
                missing_canonical_requires_review=(
                    recommendation_profile is RecommendationProfile.STRICT
                ),
                crawler_specific_noindex_requires_review=(
                    recommendation_profile is RecommendationProfile.STRICT
                ),
            )
            run_request = CrawlRunRequest(
                crawl_request,
                stages,
                recommendation_policy=recommendation_policy,
                xml_configuration=SitemapXmlConfiguration(),
                publication_configuration=publication,
                summary_configuration=summary_configuration,
                caller_label=raw.caller_label.strip() if raw.caller_label is not None else None,
            )
            run_id, _digest = run_identity(run_request)
            prepared = PreparedApplicationRequest(
                run_request,
                run_id,
                seed.normalized,
                profile.name,
                limits,
                tuple(item.value for item in stages),
                _scope_summary(scope_profile, seed.hostname, normalized_hosts),
                publication,
                summary_configuration,
            )
        ordered = ordered_issues(issues)
        report = ApplicationValidationReport(
            valid=prepared is not None,
            issues=ordered,
            normalized_seed_url=prepared.normalized_seed_url if prepared is not None else None,
            selected_profile=(
                profile.name.value if profile is not None else str(raw.crawl_profile)
            ),
            requested_stages=tuple(item.value for item in stages),
            effective_limits=limits,
            scope_summary=prepared.scope_summary if prepared is not None else None,
            publication_requested=raw.publication_requested,
            summary_requested=summary,
            run_id=prepared.run_id if prepared is not None else None,
            downstream_versions=_DOWNSTREAM_VERSIONS,
        )
        return ApplicationPreparationResult(report, prepared)


def _enum_value[EnumValue: StrEnum](
    enum_type: type[EnumValue],
    value: EnumValue | str,
) -> EnumValue | None:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except ValueError:
        return None


def _approved_hosts(values: tuple[str, ...], issues: list[ValidationIssue]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        try:
            host = normalize_hostname(value)
        except UrlNormalizationError:
            issues.append(
                ValidationIssue(
                    ValidationSeverity.ERROR,
                    ValidationIssueCode.INVALID_APPROVED_HOST,
                    "An approved host is invalid",
                    "approved_hosts",
                    value,
                )
            )
            continue
        if host in normalized:
            issues.append(
                ValidationIssue(
                    ValidationSeverity.ERROR,
                    ValidationIssueCode.DUPLICATE_APPROVED_HOST,
                    "Approved hosts must be unique after normalization",
                    "approved_hosts",
                    value,
                )
            )
            continue
        normalized.append(host)
    return tuple(normalized)


def _stages(
    recommendation: bool,  # noqa: FBT001 - stage-selection flag.
    xml: bool,  # noqa: FBT001 - stage-selection flag.
    publication: bool,  # noqa: FBT001 - stage-selection flag.
    summary: bool,  # noqa: FBT001 - stage-selection flag.
) -> tuple[RunStage, ...]:
    selected = {RunStage.CRAWL}
    if recommendation:
        selected.add(RunStage.RECOMMEND)
    if xml:
        selected.add(RunStage.GENERATE_XML)
    if publication:
        selected.add(RunStage.PUBLISH)
    if summary:
        selected.add(RunStage.WRITE_SUMMARY)
    return tuple(item for item in RunStage if item in selected)


def _publication_configuration(
    raw: RawApplicationCrawlRequest,
) -> SitemapPublicationConfiguration | None:
    if not raw.publication_requested or raw.publication_root is None:
        return None
    return SitemapPublicationConfiguration(
        raw.publication_root,
        raw.existing_file_policy,
        raw.create_publication_directory,
        PublicationMode.DRY_RUN if raw.publication_dry_run else PublicationMode.PUBLISH,
    )


def _summary_configuration(
    raw: RawApplicationCrawlRequest,
    requested: bool,  # noqa: FBT001 - effective profile flag.
) -> RunSummaryConfiguration | None:
    if not requested or raw.summary_root is None:
        return None
    return RunSummaryConfiguration(
        raw.summary_root,
        raw.existing_file_policy,
        raw.create_summary_directory,
        raw.summary_dry_run,
    )


def _stage_issue(message: str) -> ValidationIssue:
    return ValidationIssue(
        ValidationSeverity.ERROR,
        ValidationIssueCode.INVALID_STAGE_DEPENDENCY,
        message,
        "requested_stages",
    )


def _append_nonblocking_issues(  # noqa: PLR0913 - explicit evidence inputs.
    issues: list[ValidationIssue],
    raw: RawApplicationCrawlRequest,
    profile: CrawlProfileName | None,
    scope: ScopeProfile | None,
    limits: object,
    summary: bool,  # noqa: FBT001 - effective profile flag.
) -> None:
    if not raw.publication_requested:
        issues.append(
            ValidationIssue(
                ValidationSeverity.INFO,
                ValidationIssueCode.PUBLICATION_DISABLED,
                "Local sitemap publication is not requested",
            )
        )
    if not summary:
        issues.append(
            ValidationIssue(
                ValidationSeverity.INFO,
                ValidationIssueCode.SUMMARY_DISABLED,
                "Local run-summary writing is not requested",
            )
        )
    if profile is CrawlProfileName.DEEP_CRAWL:
        issues.append(
            ValidationIssue(
                ValidationSeverity.WARNING,
                ValidationIssueCode.DEEP_PROFILE_SELECTED,
                "The deep crawl profile uses larger bounded resource limits",
            )
        )
    if scope in {ScopeProfile.INCLUDE_SUBDOMAINS, ScopeProfile.APPROVED_HOSTS}:
        issues.append(
            ValidationIssue(
                ValidationSeverity.WARNING,
                ValidationIssueCode.CROSS_HOST_SCOPE_ENABLED,
                "The selected scope can admit more than the exact seed hostname",
            )
        )
    if profile is CrawlProfileName.DEEP_CRAWL and limits is not None:
        issues.append(
            ValidationIssue(
                ValidationSeverity.WARNING,
                ValidationIssueCode.LARGE_CRAWL_CONFIGURATION,
                "The effective crawl configuration is large but remains bounded",
            )
        )
    if raw.publication_requested and raw.existing_file_policy.value == "overwrite":
        issues.append(
            ValidationIssue(
                ValidationSeverity.WARNING,
                ValidationIssueCode.PUBLICATION_OVERWRITE_ENABLED,
                "Existing publication targets may be atomically replaced",
            )
        )
    issues.append(
        ValidationIssue(
            ValidationSeverity.INFO,
            ValidationIssueCode.REQUEST_PREPARED,
            "Validation is side-effect free and submission remains authoritative",
        )
    )


def _scope_summary(
    profile: ScopeProfile,
    seed_host: str,
    approved_hosts: tuple[str, ...],
) -> str:
    suffix = f"; approved={','.join(approved_hosts)}" if approved_hosts else ""
    return f"{profile.value}; seed={seed_host}{suffix}"

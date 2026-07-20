"""Persistent queue, claim, lease, cancellation, retry, and recovery tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from sqlalchemy import func, select

from durable_helpers import FakeClock, durable_configuration, durable_repository
from musimack_tools.application.profiles import APPLICATION_HARD_MAXIMA
from musimack_tools.application.projections import project_result
from musimack_tools.domain.application import (
    ApplicationOutcomeCode,
    ApplicationServiceConfiguration,
)
from musimack_tools.domain.durable_execution import (
    DurableFailureCode,
    DurableJobState,
    LeaseOutcome,
    RetryPolicy,
    WorkerIdentity,
    WorkerState,
)
from musimack_tools.domain.job import (
    JobCancellationOutcome,
    JobLookupOutcome,
    JobSubmissionOutcome,
    JobSubmissionRequest,
)
from musimack_tools.domain.sitemap import (
    CanonicalSummary,
    GenericIndexabilitySummary,
    RecommendationConfigurationSnapshot,
    RecommendationDeterminacy,
    RecommendationState,
    RedirectSummary,
    RobotsPermissionSummary,
    SitemapReasonCode,
    SitemapRecommendation,
    SitemapRecommendationProjection,
)
from musimack_tools.persistence.durable_models import (
    DurableJobModel,
    DurableRecoveryEventModel,
    DurableSequenceModel,
    JobExecutionAttemptModel,
    JobLeaseModel,
    WorkerModel,
)
from persistence_helpers import (
    cleanup_persistence_test_artifacts,  # noqa: F401
    sample_progress,
    sample_request,
    sample_result,
)

if TYPE_CHECKING:
    from pathlib import Path

    from musimack_tools.persistence.durable_repository import (
        DurableSubmission,
        SQLAlchemyDurableExecutionRepository,
    )


def _submit(
    repository: SQLAlchemyDurableExecutionRepository, path: str = "/"
) -> tuple[str, DurableSubmission]:
    result = repository.submit(JobSubmissionRequest(sample_request(path)))
    assert result.result.outcome is JobSubmissionOutcome.ACCEPTED
    assert result.result.snapshot is not None
    return result.result.snapshot.job_id, result


def _recommendation(
    suffix: str,
    state: RecommendationState,
    reason: SitemapReasonCode,
) -> SitemapRecommendation:
    url = f"https://example.com/{suffix}"
    return SitemapRecommendation(
        evaluated_url=url,
        requested_url=url,
        final_url=url,
        state=state,
        determinacy=RecommendationDeterminacy.DETERMINATE,
        primary_reason=reason,
        hard_exclusion_reasons=(reason,) if state is RecommendationState.EXCLUDE else (),
        review_reasons=(reason,) if state is RecommendationState.REVIEW else (),
        warnings=(),
        metadata_warnings=(),
        fetch_failure_code=None,
        http_status=200,
        content_type="text/html",
        robots=RobotsPermissionSummary(available=True, allowed=True, reason_code="allowed"),
        indexability=GenericIndexabilitySummary(
            generic_directives=(),
            crawler_specific_directives=(),
            generic_index_conflict=False,
        ),
        canonical=CanonicalSummary(
            selected_url=url,
            valid_candidates=(url,),
            invalid_observation_count=0,
            conflicting=False,
        ),
        redirect=RedirectSummary(
            is_redirect_source=False,
            hop_count=0,
            final_url=url,
            target_independently_evaluated=None,
        ),
        configured_exclusions=(),
        rule_results=(),
        explanation=f"{state.value} fixture recommendation",
    )


def _recommendation_projection() -> SitemapRecommendationProjection:
    recommendations = (
        _recommendation(
            "include-guide", RecommendationState.INCLUDE, SitemapReasonCode.ELIGIBLE_HTML_PAGE
        ),
        _recommendation(
            "exclude-noindex", RecommendationState.EXCLUDE, SitemapReasonCode.GENERIC_NOINDEX
        ),
        _recommendation(
            "review-canonical", RecommendationState.REVIEW, SitemapReasonCode.INVALID_CANONICAL
        ),
        _recommendation(
            "indeterminate-fetch",
            RecommendationState.INDETERMINATE,
            SitemapReasonCode.MISSING_REQUIRED_EVIDENCE,
        ),
    )
    return SitemapRecommendationProjection(
        recommendations=recommendations,
        included_url_count=1,
        excluded_url_count=1,
        review_count=1,
        indeterminate_count=1,
        counts_by_primary_reason=(),
        metadata_warning_counts=(),
        duplicate_suppression_count=0,
        redirect_source_count=0,
        canonical_exclusion_count=0,
        noindex_exclusion_count=1,
        robots_denial_count=0,
        non_html_count=0,
        non_200_count=0,
        configuration=RecommendationConfigurationSnapshot(
            missing_canonical_requires_review=False,
            invalid_canonical_requires_review=True,
            ambiguous_sniffed_html_requires_review=False,
            crawler_specific_noindex_requires_review=False,
            severe_parser_recovery_requires_review=True,
            rule_set_version="sitemap-eligibility-v1",
        ),
        rule_set_version="sitemap-eligibility-v1",
    )


def test_submission_is_durable_and_has_queue_position(tmp_path: Path) -> None:
    runtime, repository = durable_repository(tmp_path)
    try:
        job_id, submission = _submit(repository)
        status = repository.status(job_id)
        assert submission.request_json is not None
        assert status is not None
        assert status.state is DurableJobState.QUEUED
        assert status.queue_position == 1
        assert repository.registry_snapshot().queued_job_ids == (job_id,)
    finally:
        runtime.dispose()


def test_repeated_submissions_have_unique_deterministic_attempts(tmp_path: Path) -> None:
    runtime, repository = durable_repository(tmp_path)
    try:
        first, _ = _submit(repository)
        second, _ = _submit(repository)
        assert first != second
        assert repository.status(first).submission_attempt == 1  # type: ignore[union-attr]
        assert repository.status(second).submission_attempt == 2  # type: ignore[union-attr]
    finally:
        runtime.dispose()


def test_concurrent_submission_sequence_allocation_has_no_duplicates(tmp_path: Path) -> None:
    runtime, repository = durable_repository(tmp_path)
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            submissions = tuple(
                pool.map(
                    lambda index: repository.submit(
                        JobSubmissionRequest(sample_request(f"/concurrent-{index}"))
                    ),
                    range(8),
                )
            )
        assert all(item.result.outcome is JobSubmissionOutcome.ACCEPTED for item in submissions)
        with runtime.transaction() as session:
            sequences = tuple(session.scalars(select(DurableJobModel.submission_sequence)))
        assert len(sequences) == len(set(sequences)) == 8
    finally:
        runtime.dispose()


def test_worker_registration_contains_only_bounded_operational_metadata(tmp_path: Path) -> None:
    runtime, repository = durable_repository(tmp_path)
    try:
        assert repository.register_worker(WorkerIdentity("worker-test"), 1) is WorkerState.READY
        with runtime.transaction() as session:
            worker = session.get(WorkerModel, "worker-test")
            assert worker is not None
            assert worker.state == WorkerState.READY.value
            assert worker.maximum_concurrency == 1
            assert set(worker.__table__.columns.keys()).isdisjoint(
                {"hostname", "username", "environment", "command_line", "secret"}
            )
    finally:
        runtime.dispose()


def test_claim_is_fifo_and_bounded_by_worker_capacity(tmp_path: Path) -> None:
    configuration = durable_configuration(maximum_concurrent_claimed_jobs=2, maximum_claim_batch=2)
    runtime, repository = durable_repository(tmp_path, configuration=configuration)
    try:
        first, _ = _submit(repository, "/one")
        second, _ = _submit(repository, "/two")
        third, _ = _submit(repository, "/three")
        repository.register_worker(WorkerIdentity("worker-test"), 2)
        claims = repository.claim("worker-test", 10)
        assert tuple(claim.job_id for claim in claims) == (first, second)
        assert repository.claim("worker-test") == ()
        assert repository.status(third).queue_position == 1  # type: ignore[union-attr]
    finally:
        runtime.dispose()


def test_two_workers_cannot_claim_the_same_job(tmp_path: Path) -> None:
    runtime, repository = durable_repository(tmp_path)
    try:
        job_id, _ = _submit(repository)
        repository.register_worker(WorkerIdentity("worker-one"), 1)
        repository.register_worker(WorkerIdentity("worker-two"), 1)
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = tuple(pool.map(repository.claim, ("worker-one", "worker-two")))
        winners = tuple(claim for batch in claims for claim in batch)
        assert len(winners) == 1
        assert winners[0].job_id == job_id
        with runtime.transaction() as session:
            active = session.scalar(
                select(func.count()).select_from(JobLeaseModel).where(JobLeaseModel.active)
            )
        assert active == 1
    finally:
        runtime.dispose()


def test_claim_creates_lease_and_execution_attempt(tmp_path: Path) -> None:
    runtime, repository = durable_repository(tmp_path)
    try:
        job_id, _ = _submit(repository)
        repository.register_worker(WorkerIdentity("worker-test"), 1)
        claim = repository.claim("worker-test")[0]
        assert claim.job_id == job_id
        assert claim.lease_token.startswith("lease-")
        assert len(claim.lease_token) == 38
        assert claim.lease_generation == 1
        with runtime.transaction() as session:
            lease = session.scalar(select(JobLeaseModel))
            attempt = session.scalar(select(JobExecutionAttemptModel))
            assert lease is not None and lease.active
            assert attempt is not None and attempt.execution_number == 1
    finally:
        runtime.dispose()


def test_operational_logs_are_keyed_and_never_include_lease_tokens(tmp_path: Path) -> None:
    runtime, repository = durable_repository(tmp_path)
    try:
        with patch("musimack_tools.persistence.durable_repository._LOGGER") as logger:
            _submit(repository)
            repository.register_worker(WorkerIdentity("worker-test"), 1)
            claim = repository.claim("worker-test")[0]
        rendered = repr(logger.info.call_args_list)
        assert "durable_worker_registered" in rendered
        assert "durable_job_claimed" in rendered
        assert claim.lease_token not in rendered
    finally:
        runtime.dispose()


@pytest.mark.parametrize(
    ("mutation", "outcome"),
    [
        ({"worker_id": "worker-other"}, LeaseOutcome.WRONG_WORKER),
        ({"lease_token": "lease-ffffffffffffffffffffffffffffffff"}, LeaseOutcome.WRONG_TOKEN),
        ({"lease_generation": 99}, LeaseOutcome.NOT_FOUND),
    ],
)
def test_heartbeat_rejects_invalid_lease_evidence(
    tmp_path: Path, mutation: dict[str, object], outcome: LeaseOutcome
) -> None:
    runtime, repository = durable_repository(tmp_path)
    try:
        _submit(repository)
        repository.register_worker(WorkerIdentity("worker-test"), 1)
        claim = repository.claim("worker-test")[0]
        mutated = replace(claim, **mutation)  # type: ignore[arg-type]
        assert repository.heartbeat(mutated).outcome is outcome
    finally:
        runtime.dispose()


def test_heartbeat_extends_lease_only_at_bounded_interval(tmp_path: Path) -> None:
    clock = FakeClock()
    runtime, repository = durable_repository(tmp_path, clock=clock)
    try:
        _submit(repository)
        repository.register_worker(WorkerIdentity("worker-test"), 1)
        claim = repository.claim("worker-test")[0]
        initial = repository.heartbeat(claim).expires_at
        clock.advance(10)
        extended = repository.heartbeat(claim).expires_at
        assert initial == claim.expires_at
        assert extended is not None and extended > claim.expires_at
    finally:
        runtime.dispose()


def test_concurrent_heartbeats_preserve_one_active_lease(tmp_path: Path) -> None:
    clock = FakeClock()
    runtime, repository = durable_repository(tmp_path, clock=clock)
    try:
        _submit(repository)
        repository.register_worker(WorkerIdentity("worker-test"), 1)
        claim = repository.claim("worker-test")[0]
        clock.advance(10)
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = tuple(pool.map(repository.heartbeat, (claim, claim)))
        assert all(item.outcome is LeaseOutcome.ACCEPTED for item in outcomes)
        with runtime.transaction() as session:
            active = session.scalar(
                select(func.count()).select_from(JobLeaseModel).where(JobLeaseModel.active)
            )
        assert active == 1
    finally:
        runtime.dispose()


def test_expired_lease_rejects_heartbeat(tmp_path: Path) -> None:
    clock = FakeClock()
    runtime, repository = durable_repository(tmp_path, clock=clock)
    try:
        _submit(repository)
        repository.register_worker(WorkerIdentity("worker-test"), 1)
        claim = repository.claim("worker-test")[0]
        clock.advance(31)
        result = repository.heartbeat(claim)
        assert result.outcome is LeaseOutcome.EXPIRED
        assert result.failure_code is DurableFailureCode.LEASE_EXPIRED
    finally:
        runtime.dispose()


def test_queued_cancellation_is_idempotent_and_never_claimed(tmp_path: Path) -> None:
    runtime, repository = durable_repository(tmp_path)
    try:
        job_id, _ = _submit(repository)
        first = repository.request_cancellation(job_id)
        second = repository.request_cancellation(job_id)
        repository.register_worker(WorkerIdentity("worker-test"), 1)
        assert first.outcome is JobCancellationOutcome.CANCELLED_WHILE_QUEUED
        assert second.outcome is JobCancellationOutcome.ALREADY_TERMINAL
        assert repository.claim("worker-test") == ()
        assert repository.status(job_id).state is DurableJobState.CANCELLED  # type: ignore[union-attr]
    finally:
        runtime.dispose()


def test_claimed_cancellation_is_observed_before_execution(tmp_path: Path) -> None:
    runtime, repository = durable_repository(tmp_path)
    try:
        job_id, _ = _submit(repository)
        repository.register_worker(WorkerIdentity("worker-test"), 1)
        claim = repository.claim("worker-test")[0]
        assert repository.request_cancellation(job_id).outcome is JobCancellationOutcome.REQUESTED
        state = repository.fail_execution(claim, DurableFailureCode.CANCELLATION_REQUESTED.value)
        assert state is DurableJobState.CANCELLED
        assert repository.status(job_id).cancellation_requested  # type: ignore[union-attr]
    finally:
        runtime.dispose()


def test_progress_and_terminal_result_are_persisted(tmp_path: Path) -> None:
    runtime, repository = durable_repository(tmp_path)
    try:
        request = sample_request()
        job_id, _ = _submit(repository)
        repository.register_worker(WorkerIdentity("worker-test"), 1)
        claim = repository.claim("worker-test")[0]
        assert repository.mark_running(claim).outcome is LeaseOutcome.ACCEPTED
        assert repository.record_progress(claim, sample_progress())
        assert repository.record_progress(claim, sample_progress(2))
        assert repository.complete(claim, sample_result(request)) is DurableJobState.COMPLETED
        progress = repository.progress(job_id)
        assert progress.latest is not None
        assert progress.latest.sequence == 2
        assert tuple(item.sequence for item in progress.history) == (1, 2)
        lookup = repository.lookup(job_id)
        assert lookup.outcome is JobLookupOutcome.FOUND
        assert lookup.snapshot is not None
        assert lookup.snapshot.latest_progress is not None
        assert lookup.snapshot.latest_progress.urls_discovered == 2
        assert repository.status(job_id).final_result_available  # type: ignore[union-attr]
        result = repository.result(job_id)
        assert result.full_result is None
        assert result.durable_projection is not None
        assert result.durable_projection.run_lifecycle == "completed"
        projection = project_result(
            result, ApplicationServiceConfiguration(maxima=APPLICATION_HARD_MAXIMA)
        )
        assert projection.outcome is ApplicationOutcomeCode.FOUND
        assert projection.stage_states == (("crawl", "completed"),)
        legacy = repository.recommendations(job_id, offset=0, limit=25)
        assert legacy.outcome is JobLookupOutcome.FOUND
        assert not legacy.details_available
        assert not repository.recommendation_detail(job_id, 1).details_available
    finally:
        runtime.dispose()


def test_recommendations_are_filterable_bounded_and_restart_safe(tmp_path: Path) -> None:
    runtime, repository = durable_repository(tmp_path)
    request = sample_request()
    try:
        job_id, _ = _submit(repository)
        repository.register_worker(WorkerIdentity("worker-test"), 1)
        claim = repository.claim("worker-test")[0]
        result = replace(
            sample_result(request), recommendation_projection=_recommendation_projection()
        )
        assert repository.complete(claim, result) is DurableJobState.COMPLETED
        page = repository.recommendations(job_id, offset=0, limit=2)
        assert page.details_available
        assert page.total == 4
        assert len(page.items) == 2
        assert [item.sequence for item in page.items] == [1, 2]
        assert repository.recommendations(job_id, offset=0, limit=500).limit == 500
        assert repository.recommendations(job_id, offset=0, limit=50_001).limit == 50_000
        result_counts = dict(repository.result(job_id).durable_projection.recommendation_counts)  # type: ignore[union-attr]
        assert sum(result_counts.values()) == page.total
        assert {
            item.state for item in repository.recommendations(job_id, offset=0, limit=25).items
        } == {"include", "exclude", "review", "indeterminate"}
        assert (
            repository.recommendations(job_id, offset=0, limit=25, state="review")
            .items[0]
            .url.endswith("review-canonical")
        )
        assert (
            repository.recommendations(job_id, offset=0, limit=25, reason="generic_noindex")
            .items[0]
            .state
            == "exclude"
        )
        for reason in (
            "eligible",
            "eligible html page",
            "ELIGIBLE HTML PAGE",
            "  eligible_html_page  ",
        ):
            reason_page = repository.recommendations(job_id, offset=0, limit=25, reason=reason)
            assert reason_page.total == 1
            assert reason_page.items[0].url.endswith("include-guide")
        assert (
            repository.recommendations(job_id, offset=0, limit=25, reason="canonical")
            .items[0]
            .url.endswith("review-canonical")
        )
        assert repository.recommendations(job_id, offset=0, limit=25, reason="   ").total == 4
        detail = repository.recommendation_detail(job_id, 2)
        assert detail.details_available and detail.item is not None
        assert detail.item.recommendation.sequence == 2
        assert detail.item.reason_codes == ("generic_noindex",)
        assert detail.item.rule_evidence == ()
        assert detail.item.evidence_id is None
        assert repository.recommendation_detail(job_id, 99).item is None
        assert (
            repository.recommendations(job_id, offset=0, limit=25, text="INCLUDE-GUIDE")
            .items[0]
            .state
            == "include"
        )
    finally:
        runtime.dispose()

    restarted_runtime, restarted = durable_repository(tmp_path)
    try:
        page = restarted.recommendations(job_id, offset=0, limit=25)
        assert page.details_available
        assert page.total == 4
        assert page.rule_set_version == "sitemap-eligibility-v1"
        detail = restarted.recommendation_detail(job_id, 2)
        assert detail.item is not None
        assert detail.item.recommendation.primary_reason == "generic_noindex"
    finally:
        restarted_runtime.dispose()


def test_retry_wait_uses_new_availability_and_same_job_id(tmp_path: Path) -> None:
    clock = FakeClock()
    configuration = durable_configuration(retry_policy=RetryPolicy.RETRY_TRANSIENT)
    runtime, repository = durable_repository(tmp_path, clock=clock, configuration=configuration)
    try:
        job_id, _ = _submit(repository)
        repository.register_worker(WorkerIdentity("worker-test"), 1)
        first = repository.claim("worker-test")[0]
        state = repository.fail_execution(first, "database_locked")
        assert state is DurableJobState.RETRY_WAIT
        assert repository.claim("worker-test") == ()
        clock.advance(5)
        second = repository.claim("worker-test")[0]
        assert second.job_id == job_id
        assert second.execution_number == 2
        assert second.lease_generation == 2
        assert second.lease_token != first.lease_token
    finally:
        runtime.dispose()


def test_retry_does_not_starve_newer_queued_submission(tmp_path: Path) -> None:
    clock = FakeClock()
    configuration = durable_configuration(retry_policy=RetryPolicy.RETRY_TRANSIENT)
    runtime, repository = durable_repository(tmp_path, clock=clock, configuration=configuration)
    try:
        first_job, _ = _submit(repository, "/first")
        repository.register_worker(WorkerIdentity("worker-test"), 1)
        first_claim = repository.claim("worker-test")[0]
        _submit(repository, "/newer")
        repository.fail_execution(first_claim, "database_locked")
        clock.advance(5)
        next_claim = repository.claim("worker-test")[0]
        assert next_claim.job_id != first_job
    finally:
        runtime.dispose()


def test_stale_recovery_retries_eligible_lease_and_is_idempotent(tmp_path: Path) -> None:
    clock = FakeClock()
    configuration = durable_configuration(retry_policy=RetryPolicy.RETRY_TRANSIENT)
    runtime, repository = durable_repository(tmp_path, clock=clock, configuration=configuration)
    try:
        job_id, _ = _submit(repository)
        repository.register_worker(WorkerIdentity("worker-test"), 1)
        repository.claim("worker-test")
        clock.advance(46)
        report = repository.recover_stale()
        again = repository.recover_stale()
        assert report.stale_workers == 1
        assert report.stale_leases == 1
        assert report.jobs_retried == 1
        assert report.recovered_job_ids == (job_id,)
        assert again.stale_leases == 0
        with runtime.transaction() as session:
            assert session.scalar(select(func.count()).select_from(DurableRecoveryEventModel)) == 1
    finally:
        runtime.dispose()


def test_stale_recovery_never_retries_cancelled_job(tmp_path: Path) -> None:
    clock = FakeClock()
    configuration = durable_configuration(retry_policy=RetryPolicy.RETRY_TRANSIENT)
    runtime, repository = durable_repository(tmp_path, clock=clock, configuration=configuration)
    try:
        job_id, _ = _submit(repository)
        repository.register_worker(WorkerIdentity("worker-test"), 1)
        repository.claim("worker-test")
        repository.request_cancellation(job_id)
        clock.advance(46)
        report = repository.recover_stale()
        assert report.jobs_cancelled == 1
        assert report.jobs_retried == 0
        assert repository.status(job_id).state is DurableJobState.CANCELLED  # type: ignore[union-attr]
    finally:
        runtime.dispose()


def test_restart_keeps_queue_and_invalidates_old_released_lease(tmp_path: Path) -> None:
    clock = FakeClock()
    configuration = durable_configuration(retry_policy=RetryPolicy.RETRY_TRANSIENT)
    runtime, first_repository = durable_repository(
        tmp_path, clock=clock, configuration=configuration
    )
    job_id, _ = _submit(first_repository)
    first_repository.register_worker(WorkerIdentity("worker-test"), 1)
    old_claim = first_repository.claim("worker-test")[0]
    clock.advance(46)
    first_repository.recover_stale()
    runtime.dispose()

    runtime, restarted = durable_repository(tmp_path, clock=clock, configuration=configuration)
    try:
        restarted.register_worker(WorkerIdentity("worker-test"), 1)
        clock.advance(5)
        new_claim = restarted.claim("worker-test")[0]
        assert new_claim.job_id == job_id
        assert new_claim.lease_generation == old_claim.lease_generation + 1
        assert restarted.heartbeat(old_claim).outcome is LeaseOutcome.STALE_GENERATION
    finally:
        runtime.dispose()


def test_diagnostics_are_bounded_and_exclude_tokens_and_paths(tmp_path: Path) -> None:
    runtime, repository = durable_repository(tmp_path)
    try:
        _submit(repository)
        repository.register_worker(WorkerIdentity("worker-test"), 1)
        repository.claim("worker-test")
        diagnostics = repository.diagnostics("worker-test", recovery_complete=True)
        portable = repr(diagnostics)
        assert diagnostics.claimed_jobs == 1
        assert diagnostics.worker_state is WorkerState.READY
        assert "lease-" not in portable
        assert str(tmp_path) not in portable
    finally:
        runtime.dispose()


def test_sequence_names_are_explicit_and_values_positive(tmp_path: Path) -> None:
    runtime, repository = durable_repository(tmp_path)
    try:
        _submit(repository)
        repository.register_worker(WorkerIdentity("worker-test"), 1)
        repository.claim("worker-test")
        with runtime.transaction() as session:
            rows = session.execute(
                select(
                    DurableSequenceModel.sequence_name,
                    DurableSequenceModel.current_value,
                )
            )
            sequences = {name: value for name, value in rows}  # noqa: C416
        assert {
            "submission",
            "availability",
            "worker_startup",
            "claim",
            "execution_attempt",
        } <= set(sequences)
        assert all(value > 0 for value in sequences.values())
    finally:
        runtime.dispose()

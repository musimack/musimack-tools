"""One deterministic retry classifier for durable execution."""

from __future__ import annotations

from typing import TYPE_CHECKING

from musimack_tools.domain.durable_execution import (
    DurableExecutionConfiguration,
    RetryDecision,
    RetryEvaluation,
    RetryPolicy,
)

if TYPE_CHECKING:
    from datetime import datetime

_NEVER_RETRY = frozenset(
    {
        "authentication_failed",
        "invalid_request",
        "unsupported_configuration",
        "robots_denied",
        "noindex",
        "canonical_exclusion",
        "durable_cancellation_requested",
    }
)


def classify_retry(  # noqa: PLR0911, PLR0913 - one exhaustive deterministic classifier.
    configuration: DurableExecutionConfiguration,
    *,
    now: datetime,
    failure_codes: tuple[str, ...],
    retry_count: int,
    cancellation_requested: bool,
    terminal_success: bool,
) -> RetryEvaluation:
    if cancellation_requested:
        return RetryEvaluation(
            decision=RetryDecision.CANCEL,
            retryable=False,
            next_eligible_at=None,
            explanation="Cancellation is terminal",
        )
    if terminal_success:
        return RetryEvaluation(
            decision=RetryDecision.TERMINAL,
            retryable=False,
            next_eligible_at=None,
            explanation="Execution completed",
        )
    if retry_count + 1 >= configuration.maximum_attempts:
        return RetryEvaluation(
            decision=RetryDecision.DO_NOT_RETRY,
            retryable=False,
            next_eligible_at=None,
            explanation="Maximum execution attempts reached",
        )
    if configuration.retry_policy is RetryPolicy.NEVER:
        return RetryEvaluation(
            decision=RetryDecision.DO_NOT_RETRY,
            retryable=False,
            next_eligible_at=None,
            explanation="Retries are disabled",
        )
    if any(code in _NEVER_RETRY for code in failure_codes):
        return RetryEvaluation(
            decision=RetryDecision.DO_NOT_RETRY,
            retryable=False,
            next_eligible_at=None,
            explanation="Failure is explicitly non-retryable",
        )
    retryable = any(code in configuration.retryable_failure_codes for code in failure_codes)
    if (
        configuration.retry_policy in {RetryPolicy.RETRY_TRANSIENT, RetryPolicy.RETRY_SELECTED}
        and retryable
    ):
        retry_number = retry_count + 1
        return RetryEvaluation(
            decision=RetryDecision.RETRY,
            retryable=True,
            next_eligible_at=now + configuration.retry_delay(retry_number),
            explanation="Stable failure code is retryable",
        )
    return RetryEvaluation(
        decision=RetryDecision.DO_NOT_RETRY,
        retryable=False,
        next_eligible_at=None,
        explanation="No retryable stable failure code was present",
    )

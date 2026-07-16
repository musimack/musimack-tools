"""Durable versions, configuration, identity, retry, and serialization tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from durable_helpers import durable_configuration
from musimack_tools.domain.durable_execution import (
    DURABLE_EXECUTION_VERSION,
    WORKER_PROTOCOL_VERSION,
    DurableExecutionConfiguration,
    DurableJobState,
    RetryDecision,
    RetryDelaySchedule,
    RetryPolicy,
    WorkerIdentity,
    WorkerState,
    require_aware_utc,
)
from musimack_tools.durable.retry import classify_retry
from musimack_tools.durable.serialization import deserialize_run_request, serialize_run_request
from musimack_tools.run.identity import run_identity
from persistence_helpers import sample_request


def test_versions_are_exact() -> None:
    assert DURABLE_EXECUTION_VERSION == "seo-toolkit-durable-execution-v1"
    assert WORKER_PROTOCOL_VERSION == "seo-toolkit-worker-protocol-v1"


@pytest.mark.parametrize(
    "value",
    ["worker-a", "worker-a1", "worker-safe.label", "worker-safe_label", "worker-safe-label"],
)
def test_worker_identity_accepts_safe_values(value: str) -> None:
    assert WorkerIdentity(value).value == value


@pytest.mark.parametrize(
    "value",
    ["worker-", "worker-A", "worker a", "host", "worker-/path", "worker-a@b", "worker-" + "a" * 65],
)
def test_worker_identity_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(ValueError, match="bounded"):
        WorkerIdentity(value)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"enabled": True}, "scheduler mode"),
        ({"worker_enabled": True}, "explicit worker ID"),
        ({"heartbeat_interval_seconds": 30.0}, "heartbeat interval"),
        ({"stale_after_seconds": 29.0}, "stale threshold"),
        ({"maximum_claim_batch": 2}, "claim batch"),
        ({"retry_delay_seconds": 61.0}, "retry delay"),
        ({"maximum_attempts": 0}, "bounds"),
        ({"durable_execution_version": "future"}, "unsupported durable"),
        ({"worker_protocol_version": "future"}, "unsupported worker"),
    ],
)
def test_configuration_rejects_invalid_contracts(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        DurableExecutionConfiguration(**changes)  # type: ignore[arg-type]


def test_configuration_is_immutable() -> None:
    configuration = durable_configuration()
    with pytest.raises(FrozenInstanceError):
        configuration.maximum_attempts = 5  # type: ignore[misc]


@pytest.mark.parametrize(
    ("schedule", "retry_number", "expected"),
    [
        (RetryDelaySchedule.FIXED, 1, 5.0),
        (RetryDelaySchedule.FIXED, 3, 5.0),
        (RetryDelaySchedule.LINEAR, 1, 5.0),
        (RetryDelaySchedule.LINEAR, 3, 15.0),
        (RetryDelaySchedule.LINEAR, 20, 60.0),
    ],
)
def test_retry_delay_is_deterministic(
    schedule: RetryDelaySchedule, retry_number: int, expected: float
) -> None:
    configuration = durable_configuration(retry_delay_schedule=schedule)
    assert configuration.retry_delay(retry_number).total_seconds() == expected


@pytest.mark.parametrize(
    ("policy", "codes", "cancelled", "successful", "retry_count", "decision"),
    [
        (RetryPolicy.NEVER, ("database_locked",), False, False, 0, RetryDecision.DO_NOT_RETRY),
        (RetryPolicy.RETRY_TRANSIENT, ("database_locked",), False, False, 0, RetryDecision.RETRY),
        (
            RetryPolicy.RETRY_SELECTED,
            ("worker_lease_expired",),
            False,
            False,
            0,
            RetryDecision.RETRY,
        ),
        (
            RetryPolicy.RETRY_TRANSIENT,
            ("validation_failed",),
            False,
            False,
            0,
            RetryDecision.DO_NOT_RETRY,
        ),
        (RetryPolicy.RETRY_TRANSIENT, ("database_locked",), True, False, 0, RetryDecision.CANCEL),
        (RetryPolicy.RETRY_TRANSIENT, (), False, True, 0, RetryDecision.TERMINAL),
        (
            RetryPolicy.RETRY_TRANSIENT,
            ("database_locked",),
            False,
            False,
            2,
            RetryDecision.DO_NOT_RETRY,
        ),
    ],
)
def test_retry_classifier_is_bounded(  # noqa: PLR0913
    policy: RetryPolicy,
    codes: tuple[str, ...],
    cancelled: bool,  # noqa: FBT001
    successful: bool,  # noqa: FBT001
    retry_count: int,
    decision: RetryDecision,
) -> None:
    evaluation = classify_retry(
        durable_configuration(retry_policy=policy),
        now=datetime(2030, 1, 1, tzinfo=UTC),
        failure_codes=codes,
        retry_count=retry_count,
        cancellation_requested=cancelled,
        terminal_success=successful,
    )
    assert evaluation.decision is decision


def test_run_request_round_trips_without_identity_change() -> None:
    request = sample_request("/durable?q=1")
    restored = deserialize_run_request(serialize_run_request(request))
    assert restored == request
    assert run_identity(restored) == run_identity(request)


@pytest.mark.parametrize("value", ["", "null", "[]", "{}", '{"version":"future"}'])
def test_invalid_serialized_request_is_rejected(value: str) -> None:
    with pytest.raises((TypeError, ValueError)):
        deserialize_run_request(value)


@pytest.mark.parametrize(
    ("state", "terminal"),
    [(state, state.value in {"stopped", "failed", "stale"}) for state in WorkerState],
)
def test_worker_terminal_states(state: WorkerState, terminal: bool) -> None:  # noqa: FBT001
    assert state.terminal is terminal


@pytest.mark.parametrize(
    ("state", "terminal"),
    [
        (
            state,
            state.value
            in {
                "cancelled",
                "completed",
                "completed_with_warnings",
                "failed",
                "partially_completed",
            },
        )
        for state in DurableJobState
    ],
)
def test_durable_terminal_states(
    state: DurableJobState,
    terminal: bool,  # noqa: FBT001
) -> None:
    assert state.terminal is terminal


def test_aware_timestamp_is_normalized_to_utc() -> None:
    value = datetime(2030, 1, 1, tzinfo=UTC)
    assert require_aware_utc(value) is value


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        require_aware_utc(datetime(2030, 1, 1))  # noqa: DTZ001 - deliberate invalid input.

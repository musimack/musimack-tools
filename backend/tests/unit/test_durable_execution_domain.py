"""Durable versions, configuration, identity, retry, and serialization tests."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, asdict, replace
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
from musimack_tools.persistence.mapping import (
    durable_result_projection,
    durable_result_projection_json,
    load_durable_result_projection,
)
from musimack_tools.run.identity import run_identity
from persistence_helpers import sample_request, sample_result


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
    request = replace(sample_request("/durable?q=1"), execution_identity="audit:execution-1")
    restored = deserialize_run_request(serialize_run_request(request))
    assert restored == request
    assert run_identity(restored) == run_identity(request)


def test_legacy_run_request_without_execution_identity_remains_readable() -> None:
    serialized = serialize_run_request(sample_request("/legacy"))
    payload = json.loads(serialized)
    payload.pop("execution_identity")

    restored = deserialize_run_request(json.dumps(payload))

    assert restored.execution_identity is None


def test_durable_result_serializes_elapsed_time_and_reads_legacy_monotonic_markers() -> None:
    request = sample_request("/timing")
    serialized = durable_result_projection_json(sample_result(request))
    assert "crawl_started_at_seconds" not in serialized
    assert "crawl_ended_at_seconds" not in serialized
    assert "crawl_elapsed_seconds" in serialized

    legacy = asdict(durable_result_projection(sample_result(request)))
    legacy.pop("crawl_elapsed_seconds")
    legacy["crawl_started_at_seconds"] = 100.0
    legacy["crawl_ended_at_seconds"] = 112.5
    restored = load_durable_result_projection(json.dumps(legacy))

    assert restored.crawl_elapsed_seconds == 12.5
    legacy["crawl_ended_at_seconds"] = 99.0
    assert load_durable_result_projection(json.dumps(legacy)).crawl_elapsed_seconds is None


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

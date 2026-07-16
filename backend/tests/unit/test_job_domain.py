"""Immutable job-domain, registry-configuration, and identity contracts."""

from __future__ import annotations

import dataclasses
import re
from typing import TYPE_CHECKING

import pytest

from musimack_tools.domain.job import (
    JobCancellationOutcome,
    JobLookupOutcome,
    JobState,
    JobSubmissionFailureCode,
    JobSubmissionOutcome,
    JobWaitOutcome,
)
from musimack_tools.domain.job_registry import (
    CRAWL_JOB_REGISTRY_VERSION,
    DuplicateSubmissionPolicy,
    JobRegistryConfiguration,
    PayloadRetentionPolicy,
    RegistryState,
    ShutdownPolicy,
    TerminalRetentionPolicy,
)
from musimack_tools.jobs.identity import job_identifier

if TYPE_CHECKING:
    from enum import StrEnum


@pytest.mark.parametrize("state", list(JobState))
def test_job_state_values_are_stable_and_terminal_typed(state: JobState) -> None:
    assert state.value
    assert state.terminal is (
        state.value
        in {
            "cancelled",
            "completed",
            "completed_with_warnings",
            "failed",
            "partially_completed",
            "evicted",
        }
    )


@pytest.mark.parametrize(
    "enum_value",
    [
        *RegistryState,
        *DuplicateSubmissionPolicy,
        *TerminalRetentionPolicy,
        *PayloadRetentionPolicy,
        *ShutdownPolicy,
        *JobSubmissionOutcome,
        *JobSubmissionFailureCode,
        *JobLookupOutcome,
        *JobCancellationOutcome,
        *JobWaitOutcome,
    ],
)
def test_job_and_registry_enums_have_nonempty_stable_values(enum_value: StrEnum) -> None:
    assert enum_value.value


def test_registry_defaults_are_bounded_and_versioned() -> None:
    configuration = JobRegistryConfiguration()
    assert configuration.maximum_concurrent_jobs == 2
    assert configuration.maximum_queued_jobs == 10
    assert configuration.maximum_retained_terminal_jobs == 100
    assert configuration.duplicate_policy is DuplicateSubmissionPolicy.REJECT_ACTIVE_DUPLICATE
    assert configuration.payload_retention_policy is PayloadRetentionPolicy.FULL_RESULT
    assert not configuration.retain_progress_history
    assert configuration.registry_version == CRAWL_JOB_REGISTRY_VERSION


@pytest.mark.parametrize(
    "configuration",
    [
        JobRegistryConfiguration(maximum_concurrent_jobs=1),
        JobRegistryConfiguration(maximum_queued_jobs=0),
        JobRegistryConfiguration(maximum_retained_terminal_jobs=0),
        JobRegistryConfiguration(
            retain_progress_history=True,
            maximum_retained_progress_events=1,
        ),
    ],
)
def test_valid_registry_boundary_configurations(configuration: JobRegistryConfiguration) -> None:
    assert configuration.registry_version == CRAWL_JOB_REGISTRY_VERSION


@pytest.mark.parametrize(
    "overrides",
    [
        {"maximum_concurrent_jobs": 0},
        {"maximum_queued_jobs": -1},
        {"maximum_retained_terminal_jobs": -1},
        {"retain_progress_history": True, "maximum_retained_progress_events": 0},
        {"registry_version": "future"},
    ],
)
def test_invalid_registry_configuration_is_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        JobRegistryConfiguration(**overrides)  # type: ignore[arg-type]


def test_registry_configuration_is_immutable() -> None:
    configuration = JobRegistryConfiguration()
    with pytest.raises(dataclasses.FrozenInstanceError):
        configuration.maximum_concurrent_jobs = 9  # type: ignore[misc]


@pytest.mark.parametrize("attempt", [1, 2, 12, 9_999])
def test_job_identifier_is_deterministic_and_attempt_based(attempt: int) -> None:
    value = job_identifier("run-4f82d76a1b42", attempt)
    assert value == f"job-4f82d76a1b42-{attempt:04d}"
    assert re.fullmatch(r"job-[0-9a-f]{12}-[0-9]{4,}", value)


@pytest.mark.parametrize(
    ("run_id", "attempt"),
    [("bad", 1), ("run-4F82D76A1B42", 1), ("run-4f82d76a1b42", 0)],
)
def test_invalid_job_identifier_inputs_are_rejected(run_id: str, attempt: int) -> None:
    with pytest.raises(ValueError):
        job_identifier(run_id, attempt)


def test_identity_contains_no_random_or_time_component() -> None:
    assert job_identifier("run-4f82d76a1b42", 1) == job_identifier("run-4f82d76a1b42", 1)

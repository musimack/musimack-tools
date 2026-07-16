"""History configuration, filters, availability, and pagination contracts."""

from datetime import UTC, datetime, timedelta

import pytest

from musimack_tools.deployment.history import HistorySettings
from musimack_tools.domain.history import (
    HISTORY_API_VERSION,
    HISTORY_JOB_ORDERING,
    HISTORY_PAGINATION_VERSION,
    HISTORY_RUN_ORDERING,
    HISTORY_SERVICE_VERSION,
    HistoryAvailability,
    HistoryConfiguration,
    HistoryFailureCode,
    JobHistoryFilter,
    RunHistoryFilter,
)


def test_history_is_disabled_and_exactly_versioned_by_default() -> None:
    configuration = HistoryConfiguration()
    assert not configuration.enabled
    assert configuration.service_version == HISTORY_SERVICE_VERSION
    assert configuration.api_version == HISTORY_API_VERSION
    assert configuration.pagination_version == HISTORY_PAGINATION_VERSION
    assert HISTORY_JOB_ORDERING == "submitted_sequence_desc_job_id_desc-v1"
    assert HISTORY_RUN_ORDERING == "submitted_sequence_desc_run_id_desc-v1"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"service_version": "unknown"}, "service version"),
        ({"api_version": "unknown"}, "API version"),
        ({"pagination_version": "unknown"}, "pagination version"),
        ({"default_page_size": 0}, "default page size"),
        ({"maximum_page_size": 0}, "maximum page size"),
        ({"default_page_size": 101, "maximum_page_size": 100}, "default page size"),
        ({"maximum_attempts_per_job": 0}, "related-record"),
        ({"maximum_artifacts_per_run": 1001}, "related-record"),
    ],
)
def test_history_configuration_rejects_unbounded_or_unsupported_values(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        HistoryConfiguration(**changes)  # type: ignore[arg-type]


def test_history_settings_are_frozen_and_map_exactly() -> None:
    settings = HistorySettings.model_validate(
        {"enabled": True, "default_page_size": 10, "maximum_page_size": 20}
    )
    configuration = settings.to_configuration()
    assert configuration.enabled
    assert configuration.default_page_size == 10
    assert configuration.maximum_page_size == 20
    with pytest.raises(Exception):  # noqa: B017 - Pydantic raises a frozen-instance error.
        settings.enabled = False


def test_filter_ranges_and_scheduler_mode_are_typed_and_validated() -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="submission range"):
        JobHistoryFilter(submitted_from=now, submitted_to=now - timedelta(seconds=1))
    with pytest.raises(ValueError, match="scheduler mode"):
        JobHistoryFilter(scheduler_mode="remote")
    with pytest.raises(ValueError, match="start range"):
        RunHistoryFilter(started_from=now, started_to=now - timedelta(seconds=1))
    assert JobHistoryFilter(state="completed", recovered=True).canonical() == (
        ("state", "completed"),
        ("recovered", "true"),
    )


def test_availability_and_failure_codes_are_stable() -> None:
    assert {state.value for state in HistoryAvailability} >= {
        "full",
        "metadata_only",
        "artifact_missing",
        "artifact_expired",
        "artifact_deleted",
        "result_unavailable",
        "evicted",
        "interrupted",
        "retained",
    }
    assert HistoryFailureCode.INVALID_CURSOR.value == "history_invalid_cursor"
    assert HistoryFailureCode.JOB_NOT_FOUND.value == "history_job_not_found"

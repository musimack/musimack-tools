"""Environment-backed configuration for optional durable execution."""

from __future__ import annotations

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from musimack_tools.domain.durable_execution import (
    DurableExecutionConfiguration,
    OrphanedLeasePolicy,
    RetryDelaySchedule,
    RetryPolicy,
    SchedulerMode,
    WorkerIdentity,
    WorkerShutdownPolicy,
)

_WORKER_REQUIRES_DURABLE = "worker requires durable execution"
_WORKER_REQUIRES_ID = "worker requires an explicit worker ID"


class DurableExecutionSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MUSIMACK_",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    durable_execution_enabled: bool = False
    worker_enabled: bool = False
    worker_id: str | None = None
    worker_max_concurrency: int = Field(default=1, ge=1, le=64)
    worker_poll_interval_seconds: float = Field(default=1.0, gt=0, le=60)
    worker_lease_duration_seconds: float = Field(default=30.0, gt=0, le=3600)
    worker_heartbeat_interval_seconds: float = Field(default=10.0, gt=0, le=600)
    worker_stale_after_seconds: float = Field(default=45.0, gt=0, le=7200)
    worker_max_claim_batch: int = Field(default=1, ge=1, le=64)
    worker_retry_policy: RetryPolicy = RetryPolicy.NEVER
    worker_retry_delay_schedule: RetryDelaySchedule = RetryDelaySchedule.FIXED
    worker_retry_delay_seconds: float = Field(default=5.0, gt=0, le=3600)
    worker_maximum_retry_delay_seconds: float = Field(default=60.0, gt=0, le=86400)
    worker_maximum_attempts: int = Field(default=3, ge=1, le=100)
    worker_retryable_failure_codes: tuple[str, ...] = (
        "database_locked",
        "temporary_network_failure",
        "worker_lease_expired",
        "internal_service_temporarily_unavailable",
    )
    worker_shutdown_grace_period_seconds: float = Field(default=30.0, gt=0, le=3600)
    worker_startup_stale_job_recovery: bool = True
    worker_orphaned_lease_policy: OrphanedLeasePolicy = OrphanedLeasePolicy.RECOVER
    worker_shutdown_policy: WorkerShutdownPolicy = (
        WorkerShutdownPolicy.DRAIN_ACTIVE_AND_STOP_CLAIMING
    )
    worker_maximum_consecutive_heartbeat_failures: int = Field(default=3, ge=1, le=100)

    @model_validator(mode="after")
    def validate_worker_boundary(self) -> DurableExecutionSettings:
        if self.worker_enabled and not self.durable_execution_enabled:
            raise ValueError(_WORKER_REQUIRES_DURABLE)
        if self.worker_enabled and self.worker_id is None:
            raise ValueError(_WORKER_REQUIRES_ID)
        return self

    def to_configuration(self) -> DurableExecutionConfiguration:
        enabled = self.durable_execution_enabled
        return DurableExecutionConfiguration(
            enabled=enabled,
            worker_enabled=self.worker_enabled,
            worker_id=WorkerIdentity(self.worker_id) if self.worker_id is not None else None,
            scheduler_mode=SchedulerMode.DURABLE if enabled else SchedulerMode.IN_MEMORY,
            maximum_concurrent_claimed_jobs=self.worker_max_concurrency,
            poll_interval_seconds=self.worker_poll_interval_seconds,
            lease_duration_seconds=self.worker_lease_duration_seconds,
            heartbeat_interval_seconds=self.worker_heartbeat_interval_seconds,
            stale_after_seconds=self.worker_stale_after_seconds,
            maximum_claim_batch=self.worker_max_claim_batch,
            retry_policy=self.worker_retry_policy,
            retry_delay_schedule=self.worker_retry_delay_schedule,
            retry_delay_seconds=self.worker_retry_delay_seconds,
            maximum_retry_delay_seconds=self.worker_maximum_retry_delay_seconds,
            maximum_attempts=self.worker_maximum_attempts,
            retryable_failure_codes=frozenset(self.worker_retryable_failure_codes),
            shutdown_grace_period_seconds=self.worker_shutdown_grace_period_seconds,
            startup_stale_job_recovery=self.worker_startup_stale_job_recovery,
            orphaned_lease_policy=self.worker_orphaned_lease_policy,
            shutdown_policy=self.worker_shutdown_policy,
            maximum_consecutive_heartbeat_failures=(
                self.worker_maximum_consecutive_heartbeat_failures
            ),
        )

"""Framework-independent single-machine durable worker service."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from logging import getLogger
from typing import TYPE_CHECKING

from musimack_tools.crawl.cancellation import CrawlCancellationToken
from musimack_tools.domain.durable_execution import (
    DurableClaim,
    DurableFailureCode,
    DurableRecoveryReport,
    LeaseOutcome,
    WorkerShutdownPolicy,
    WorkerShutdownReport,
    WorkerStartupReport,
    WorkerState,
)

if TYPE_CHECKING:
    from musimack_tools.domain.run import CrawlRunResult
    from musimack_tools.domain.run_progress import RunProgressEvent
    from musimack_tools.jobs.coordinator import JobRunServiceFactory
    from musimack_tools.persistence.durable_repository import (
        SQLAlchemyDurableExecutionRepository,
    )

Sleep = Callable[[float], Awaitable[None]]
ResultObserver = Callable[[str, "CrawlRunResult"], None]
ReconciliationObserver = Callable[[], Awaitable[int]]
_INVALID_WORKER_CONFIGURATION = "durable worker requires explicit enabled configuration"
_LOGGER = getLogger(__name__)


class _DurableProgressSink:
    def __init__(
        self, repository: SQLAlchemyDurableExecutionRepository, claim: DurableClaim
    ) -> None:
        self._repository = repository
        self._claim = claim

    async def on_progress(self, event: RunProgressEvent) -> None:
        self._repository.record_progress(self._claim, event)


class DurableWorkerService:
    """Claim and execute persisted jobs without owning crawl or run semantics."""

    def __init__(
        self,
        repository: SQLAlchemyDurableExecutionRepository,
        run_service_factory: JobRunServiceFactory,
        *,
        sleep: Sleep = asyncio.sleep,
        result_observer: ResultObserver | None = None,
        reconciliation_observer: ReconciliationObserver | None = None,
    ) -> None:
        configuration = repository.configuration
        if not configuration.worker_enabled or configuration.worker_id is None:
            raise ValueError(_INVALID_WORKER_CONFIGURATION)
        self._repository = repository
        self._factory = run_service_factory
        self._sleep = sleep
        self._result_observer = result_observer
        self._reconciliation_observer = reconciliation_observer
        self._configuration = configuration
        self._worker_id = configuration.worker_id.value
        self._stop_requested = asyncio.Event()
        self._polling_task: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._tokens: dict[str, CrawlCancellationToken] = {}
        self._startup: WorkerStartupReport | None = None
        self._shutdown: WorkerShutdownReport | None = None

    @property
    def startup_report(self) -> WorkerStartupReport | None:
        return self._startup

    async def start(self) -> WorkerStartupReport:
        if self._startup is not None:
            return self._startup
        worker_identity = self._configuration.worker_id
        if worker_identity is None:  # Defensive narrowing for statically typed composition.
            raise ValueError(_INVALID_WORKER_CONFIGURATION)
        self._repository.register_worker(
            worker_identity, self._configuration.maximum_concurrent_claimed_jobs
        )
        recovery = (
            self._repository.recover_stale()
            if self._configuration.startup_stale_job_recovery
            else DurableRecoveryReport(
                stale_workers=0,
                stale_leases=0,
                jobs_retried=0,
                jobs_cancelled=0,
                jobs_failed=0,
                recovered_job_ids=(),
                recovery_complete=True,
            )
        )
        self._repository.set_worker_state(self._worker_id, WorkerState.READY)
        self._startup = WorkerStartupReport(
            worker_id=self._worker_id,
            registered=True,
            recovery=recovery,
            polling_ready=True,
        )
        self._polling_task = asyncio.create_task(self._poll(), name=f"{self._worker_id}-poll")
        _LOGGER.info("durable_worker_polling_started", extra={"worker_id": self._worker_id})
        return self._startup

    async def run_once(self) -> int:
        if self._reconciliation_observer is not None and not self._stop_requested.is_set():
            try:
                await self._reconciliation_observer()
            except Exception:  # Parent recovery must not stop crawl claims.
                _LOGGER.exception(
                    "site_audit_reconciliation_scan_failed",
                    extra={"worker_id": self._worker_id},
                )
        capacity = self._configuration.maximum_concurrent_claimed_jobs - len(self._tasks)
        if capacity <= 0 or self._stop_requested.is_set():
            return 0
        claims = self._repository.claim(
            self._worker_id,
            min(capacity, self._configuration.maximum_claim_batch),
        )
        for claim in claims:
            task = asyncio.create_task(self._execute(claim), name=f"durable-{claim.job_id}")
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        return len(claims)

    async def shutdown(self) -> WorkerShutdownReport:
        if self._shutdown is not None:
            return WorkerShutdownReport(
                worker_id=self._shutdown.worker_id,
                active_jobs_completed=self._shutdown.active_jobs_completed,
                cancellations_requested=self._shutdown.cancellations_requested,
                leases_released=self._shutdown.leases_released,
                orphan_tasks=self._shutdown.orphan_tasks,
                repeated=True,
                final_state=self._shutdown.final_state,
            )
        self._stop_requested.set()
        self._repository.set_worker_state(self._worker_id, WorkerState.DRAINING)
        _LOGGER.info("durable_worker_draining", extra={"worker_id": self._worker_id})
        cancellations = 0
        if self._configuration.shutdown_policy is WorkerShutdownPolicy.REQUEST_ACTIVE_CANCELLATION:
            for token in self._tokens.values():
                token.cancel()
                cancellations += 1
        active = tuple(self._tasks)
        if active:
            _done, pending = await asyncio.wait(
                active,
                timeout=self._configuration.shutdown_grace_period_seconds,
            )
        else:
            pending = set()
        if self._polling_task is not None:
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    asyncio.shield(self._polling_task),
                    timeout=self._configuration.poll_interval_seconds + 1,
                )
        final = WorkerState.STOPPED if not pending else WorkerState.FAILED
        self._repository.set_worker_state(self._worker_id, final)
        self._shutdown = WorkerShutdownReport(
            worker_id=self._worker_id,
            active_jobs_completed=len(active) - len(pending),
            cancellations_requested=cancellations,
            leases_released=len(active) - len(pending),
            orphan_tasks=len(pending),
            repeated=False,
            final_state=final,
        )
        _LOGGER.info(
            "durable_worker_stopped",
            extra={
                "worker_id": self._worker_id,
                "worker_state": final.value,
                "orphan_tasks": len(pending),
            },
        )
        return self._shutdown

    async def _poll(self) -> None:
        while not self._stop_requested.is_set():
            try:
                await self.run_once()
            except Exception:  # Transient repository faults must not kill polling.
                _LOGGER.exception(
                    "durable_claim_failed",
                    extra={
                        "worker_id": self._worker_id,
                        "failure_code": DurableFailureCode.CLAIM_FAILED.value,
                    },
                )
            await self._sleep(self._configuration.poll_interval_seconds)

    async def _execute(self, claim: DurableClaim) -> None:
        token = CrawlCancellationToken()
        self._tokens[claim.job_id] = token
        heartbeat_stop = asyncio.Event()
        heartbeat = asyncio.create_task(
            self._heartbeat(claim, token, heartbeat_stop), name=f"heartbeat-{claim.job_id}"
        )
        try:
            if self._repository.cancellation_requested(claim.job_id):
                token.cancel()
                _LOGGER.info(
                    "durable_cancellation_observed",
                    extra={"job_id": claim.job_id, "worker_id": claim.worker_id},
                )
                self._repository.fail_execution(
                    claim, DurableFailureCode.CANCELLATION_REQUESTED.value
                )
                return
            running = self._repository.mark_running(claim)
            if running.outcome is not LeaseOutcome.ACCEPTED:
                return
            request = self._repository.load_request(claim)
            executor = self._factory(token, _DurableProgressSink(self._repository, claim))
            result = await executor.execute(request)
            if self._result_observer is not None:
                self._result_observer(claim.job_id, result)
            self._repository.complete(claim, result)
        except Exception:  # noqa: BLE001 - worker boundary maps unexpected failures.
            with suppress(Exception):  # Failure remains bounded at the worker boundary.
                self._repository.fail_execution(claim, DurableFailureCode.EXECUTION_FAILED.value)
        finally:
            heartbeat_stop.set()
            await heartbeat
            self._tokens.pop(claim.job_id, None)

    async def _heartbeat(
        self,
        claim: DurableClaim,
        token: CrawlCancellationToken,
        stop: asyncio.Event,
    ) -> None:
        failures = 0
        while not stop.is_set():
            try:
                await asyncio.wait_for(
                    stop.wait(), timeout=self._configuration.heartbeat_interval_seconds
                )
                continue
            except TimeoutError:
                pass
            if self._repository.cancellation_requested(claim.job_id):
                token.cancel()
            outcome = self._repository.heartbeat(claim)
            if outcome.outcome is LeaseOutcome.ACCEPTED:
                failures = 0
                continue
            failures += 1
            _LOGGER.warning(
                "durable_heartbeat_failed",
                extra={
                    "job_id": claim.job_id,
                    "worker_id": claim.worker_id,
                    "failure_code": (
                        outcome.failure_code.value if outcome.failure_code is not None else None
                    ),
                    "consecutive_failures": failures,
                },
            )
            if failures >= self._configuration.maximum_consecutive_heartbeat_failures:
                token.cancel()
                self._repository.set_worker_state(self._worker_id, WorkerState.FAILED)
                return

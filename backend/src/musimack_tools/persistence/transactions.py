"""Stable SQLAlchemy failure mapping for short persistence units of work."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

from musimack_tools.domain.persistence import (
    PersistenceFailureCode,
    PersistenceOperationResult,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class PersistenceOperationError(RuntimeError):
    def __init__(self, code: PersistenceFailureCode, operation: str) -> None:
        super().__init__(f"{operation} failed with stable persistence code {code.value}")
        self.code = code
        self.operation = operation


def map_database_error(error: SQLAlchemyError, *, write: bool) -> PersistenceFailureCode:
    if isinstance(error, IntegrityError):
        return PersistenceFailureCode.DATABASE_INTEGRITY_ERROR
    if isinstance(error, OperationalError) and "locked" in str(error).lower():
        return PersistenceFailureCode.DATABASE_LOCKED
    return (
        PersistenceFailureCode.DATABASE_WRITE_FAILED
        if write
        else PersistenceFailureCode.DATABASE_READ_FAILED
    )


def safely_record[T](operation: str, callback: Callable[[], T]) -> PersistenceOperationResult:
    try:
        callback()
    except LookupError:
        return PersistenceOperationResult(
            succeeded=False,
            failure_code=PersistenceFailureCode.RECORD_NOT_FOUND,
            explanation=f"Persistence operation {operation} could not find its record",
        )
    except SQLAlchemyError as error:
        return PersistenceOperationResult(
            succeeded=False,
            failure_code=map_database_error(error, write=True),
            explanation=f"Persistence operation {operation} did not complete",
        )
    return PersistenceOperationResult(succeeded=True)

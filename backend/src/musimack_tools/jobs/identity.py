"""Deterministic job-attempt identifiers."""

from __future__ import annotations

import re

_RUN_ID = re.compile(r"run-([0-9a-f]{12})\Z")


def job_identifier(run_id: str, attempt_number: int) -> str:
    """Build one stable registry-local execution-attempt identifier."""
    match = _RUN_ID.fullmatch(run_id)
    if match is None:
        message = "run ID must use the accepted display format"
        raise ValueError(message)
    if attempt_number < 1:
        message = "job attempt number must be positive"
        raise ValueError(message)
    return f"job-{match.group(1)}-{attempt_number:04d}"

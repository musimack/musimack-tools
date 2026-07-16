"""Retention planning helpers using deterministic sequence ordering."""

from __future__ import annotations

_INVALID_MAXIMUM = "retention maximum cannot be negative"


def oldest_excess_sequences(sequences: tuple[int, ...], maximum: int) -> tuple[int, ...]:
    if maximum < 0:
        raise ValueError(_INVALID_MAXIMUM)
    ordered = tuple(sorted(sequences))
    return ordered[: max(0, len(ordered) - maximum)]

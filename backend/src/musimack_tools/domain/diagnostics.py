"""Immutable deterministic diagnostic artifact contracts."""

from dataclasses import dataclass
from enum import StrEnum

DIAGNOSTICS_SCHEMA_VERSION = "seo-toolkit-diagnostics-v1"


class DiagnosticFormat(StrEnum):
    JSON = "json"
    MARKDOWN = "markdown"


@dataclass(frozen=True, slots=True)
class DiagnosticArtifact:
    format: DiagnosticFormat
    content: bytes
    byte_count: int
    sha256: str
    schema_version: str = DIAGNOSTICS_SCHEMA_VERSION

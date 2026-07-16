"""Deterministic JSON and Markdown diagnostics for bounded application records."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from musimack_tools.domain.diagnostics import (
    DIAGNOSTICS_SCHEMA_VERSION,
    DiagnosticArtifact,
    DiagnosticFormat,
)


def serialize_json(value: object) -> DiagnosticArtifact:
    payload = _payload(value)
    content = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    return _artifact(DiagnosticFormat.JSON, content)


def serialize_markdown(value: object, title: str) -> DiagnosticArtifact:
    payload = _payload(value)
    lines = [
        f"# {title}",
        "",
        f"- Diagnostics schema: `{DIAGNOSTICS_SCHEMA_VERSION}`",
        "",
        "## Evidence",
        "",
        "```json",
        *json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).splitlines(),
        "```",
        "",
    ]
    return _artifact(DiagnosticFormat.MARKDOWN, "\n".join(lines).encode())


def _payload(value: object) -> dict[str, object]:
    converted = _safe(value)
    if not isinstance(converted, dict):
        converted = {"value": converted}
    return {"diagnostics_schema_version": DIAGNOSTICS_SCHEMA_VERSION, **converted}


def _safe(value: Any) -> Any:  # noqa: ANN401, PLR0911 - explicit recursive type cases.
    if is_dataclass(value) and not isinstance(value, type):
        return _safe(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return "<configured-local-path>"
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return f"<{type(value).__name__}>"


def _artifact(format_: DiagnosticFormat, content: bytes) -> DiagnosticArtifact:
    return DiagnosticArtifact(
        format_,
        content,
        len(content),
        hashlib.sha256(content).hexdigest(),
    )

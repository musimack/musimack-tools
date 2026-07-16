"""Safe deterministic mapping from accepted domain evidence to storage values."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

from musimack_tools.run.identity import configuration_snapshot

if TYPE_CHECKING:
    from musimack_tools.domain.persistence import ArtifactType
    from musimack_tools.domain.run import CrawlRunRequest, CrawlRunResult


def canonical_configuration(request: CrawlRunRequest) -> tuple[str, str]:
    payload = asdict(configuration_snapshot(request))
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return content, digest


def safe_url(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def safe_message(value: str, maximum: int = 512) -> str:
    normalized = " ".join(value.split())
    return normalized[:maximum]


def stage_states_json(result: CrawlRunResult) -> str:
    return json.dumps(
        [{"stage": item.stage.value, "state": item.state.value} for item in result.stages],
        sort_keys=True,
        separators=(",", ":"),
    )


def artifact_identifier(run_id: str, kind: ArtifactType, logical_name: str) -> str:
    digest = hashlib.sha256(f"{run_id}\0{kind.value}\0{logical_name}".encode()).hexdigest()
    return f"artifact-{digest[:32]}"


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()

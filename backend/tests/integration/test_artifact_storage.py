"""Durable artifact registration, retrieval, cleanup, reconciliation, and API tests."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from musimack_tools.artifacts.repository import SQLAlchemyArtifactRepository
from musimack_tools.artifacts.service import ArtifactService
from musimack_tools.core.config import Settings
from musimack_tools.deployment.application import create_production_app
from musimack_tools.deployment.settings import ProductionSettings
from musimack_tools.domain.artifacts import (
    ArtifactError,
    ArtifactIntegrityState,
    ArtifactLifecycleState,
    ArtifactRecord,
    ArtifactStorageConfiguration,
    ArtifactStorageRootConfiguration,
    ArtifactType,
)
from musimack_tools.domain.persistence import PersistenceConfiguration
from musimack_tools.domain.sitemap_publication import (
    PublicationDocumentType,
    PublicationState,
    PublishedFileResult,
    SitemapPublicationResult,
)
from musimack_tools.domain.sitemap_xml import (
    GeneratedSitemapDocument,
    SitemapSerializationCounts,
    SitemapUrlEntry,
    SitemapXmlBundle,
)
from musimack_tools.persistence.engine import create_persistence_runtime
from musimack_tools.persistence.migrations import upgrade_to_head
from musimack_tools.persistence.repositories import SQLAlchemyPersistenceRepository
from musimack_tools.sitemap.limits import SitemapXmlConfiguration
from persistence_helpers import BACKEND_ROOT, sample_request, sample_result, sample_snapshot

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from musimack_tools.persistence.engine import PersistenceRuntime

_TOKEN = "artifact-integration-token"  # noqa: S105 - inert test credential.


class _UnusedApplicationService:
    """Production route construction does not call application methods."""


@pytest.fixture
def artifact_runtime(tmp_path: Path) -> Iterator[tuple[PersistenceRuntime, str, str]]:
    database = tmp_path / "artifact.sqlite"
    upgrade_to_head(f"sqlite+pysqlite:///{database.as_posix()}", backend_root=BACKEND_ROOT)
    runtime = create_persistence_runtime(
        PersistenceConfiguration(enabled=True, database_path=database)
    )
    request = sample_request("/artifacts")
    snapshot = sample_snapshot(request)
    assert SQLAlchemyPersistenceRepository(runtime).record_submission(snapshot, request).succeeded
    try:
        yield runtime, snapshot.job_id, snapshot.run_id
    finally:
        runtime.dispose()


def _service(
    runtime: PersistenceRuntime,
    root: Path,
    *,
    now: list[datetime] | None = None,
    retention_days: int | None = 90,
) -> ArtifactService:
    root.mkdir(exist_ok=True)
    configuration = ArtifactStorageConfiguration(
        enabled=True,
        roots=(ArtifactStorageRootConfiguration("default", root),),
        retention_days=retention_days,
        stream_chunk_bytes=1_024,
    )
    service = ArtifactService(
        configuration,
        SQLAlchemyArtifactRepository(runtime),
        clock=(None if now is None else lambda: now[0]),
    )
    assert service.readiness()[0].ready
    return service


def _write_managed(  # noqa: PLR0913
    service: ArtifactService,
    root: Path,
    job_id: str,
    run_id: str,
    filename: str,
    content: bytes,
) -> str:
    relative = service.managed_relative_path(job_id, run_id, filename)
    target = root.joinpath(*relative.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return relative


def _register(  # noqa: PLR0913
    service: ArtifactService,
    root: Path,
    job_id: str,
    run_id: str,
    *,
    filename: str = "sitemap.xml",
    content: bytes = b"<urlset/>",
    artifact_type: ArtifactType = ArtifactType.SITEMAP_XML,
) -> ArtifactRecord:
    relative = _write_managed(service, root, job_id, run_id, filename, content)
    return service.register(
        job_id=job_id,
        run_id=run_id,
        artifact_type=artifact_type,
        relative_path=relative,
        expected_byte_count=len(content),
        expected_sha256=hashlib.sha256(content).hexdigest(),
    )


def test_registration_is_verified_idempotent_restart_safe_and_streamed(
    artifact_runtime: tuple[PersistenceRuntime, str, str], tmp_path: Path
) -> None:
    runtime, job_id, run_id = artifact_runtime
    root = tmp_path / "root"
    service = _service(runtime, root)
    record = _register(service, root, job_id, run_id)
    assert record.lifecycle_state is ArtifactLifecycleState.AVAILABLE
    assert record.integrity_state is ArtifactIntegrityState.VERIFIED
    repeated = service.register(
        job_id=job_id,
        run_id=run_id,
        artifact_type=ArtifactType.SITEMAP_XML,
        relative_path=record.relative_path,
        expected_byte_count=record.expected_byte_count,
        expected_sha256=record.expected_sha256,
    )
    assert repeated.artifact_id == record.artifact_id
    restarted = _service(runtime, root)
    descriptor = restarted.prepare_download(record.artifact_id)
    chunks = tuple(descriptor.iterator_factory())
    assert b"".join(chunks) == b"<urlset/>"
    assert all(len(chunk) <= 1_024 for chunk in chunks)
    assert str(root) not in repr(record)


def test_changed_missing_and_oversize_files_are_not_downloaded(
    artifact_runtime: tuple[PersistenceRuntime, str, str], tmp_path: Path
) -> None:
    runtime, job_id, run_id = artifact_runtime
    root = tmp_path / "root"
    service = _service(runtime, root)
    record = _register(service, root, job_id, run_id)
    root.joinpath(*record.relative_path.split("/")).write_bytes(b"changed")
    with pytest.raises(ArtifactError):
        service.prepare_download(record.artifact_id)
    assert service.get(record.artifact_id).lifecycle_state is ArtifactLifecycleState.CORRUPT
    root.joinpath(*record.relative_path.split("/")).unlink()
    assert service.verify(record.artifact_id).lifecycle_state is ArtifactLifecycleState.MISSING
    with pytest.raises(ArtifactError):
        service.register(
            job_id=job_id,
            run_id=run_id,
            artifact_type=ArtifactType.SITEMAP_XML,
            relative_path=service.managed_relative_path(job_id, run_id, "large.xml"),
            expected_byte_count=service.configuration.maximum_file_bytes + 1,
            expected_sha256="a" * 64,
        )


def test_file_replacement_after_download_authorization_is_blocked(
    artifact_runtime: tuple[PersistenceRuntime, str, str], tmp_path: Path
) -> None:
    runtime, job_id, run_id = artifact_runtime
    root = tmp_path / "root"
    service = _service(runtime, root)
    record = _register(service, root, job_id, run_id)
    descriptor = service.prepare_download(record.artifact_id)
    root.joinpath(*record.relative_path.split("/")).write_bytes(b"<changed>")
    with pytest.raises(ArtifactError):
        tuple(descriptor.iterator_factory())


def test_retention_cleanup_and_reconciliation_are_bounded_and_safe(
    artifact_runtime: tuple[PersistenceRuntime, str, str], tmp_path: Path
) -> None:
    runtime, job_id, run_id = artifact_runtime
    now = [datetime(2026, 1, 1, tzinfo=UTC)]
    root = tmp_path / "root"
    service = _service(runtime, root, now=now, retention_days=1)
    retained = _register(service, root, job_id, run_id, filename="retained.xml")
    service.retain(retained.artifact_id)
    other = _register(service, root, job_id, run_id, filename="expired.xml")
    now[0] += timedelta(days=2)
    plan = service.cleanup(dry_run=True)
    assert other.artifact_id in plan.artifact_ids
    result = service.cleanup()
    assert result.deleted == 1
    assert service.get(other.artifact_id).lifecycle_state is ArtifactLifecycleState.DELETED
    assert root.joinpath(*retained.relative_path.split("/")).exists()
    _write_managed(service, root, job_id, run_id, "orphan.xml", b"orphan")
    reconciled = service.reconcile()
    assert reconciled.orphans == 1


def test_manifest_consistency_and_safe_metadata_projection(
    artifact_runtime: tuple[PersistenceRuntime, str, str], tmp_path: Path
) -> None:
    runtime, job_id, run_id = artifact_runtime
    root = tmp_path / "root"
    service = _service(runtime, root)
    xml = _register(service, root, job_id, run_id)
    content = (
        '{"files":[{"logical_name":"sitemap.xml","byte_count":9,"sha256":"'
        + xml.expected_sha256
        + '"}]}'
    ).encode()
    manifest = _register(
        service,
        root,
        job_id,
        run_id,
        filename="sitemap-manifest.json",
        content=content,
        artifact_type=ArtifactType.PUBLICATION_MANIFEST,
    )
    assert manifest.integrity_state is ArtifactIntegrityState.VERIFIED


def test_terminal_run_output_registration_reuses_successful_publication_file(
    artifact_runtime: tuple[PersistenceRuntime, str, str], tmp_path: Path
) -> None:
    runtime, job_id, run_id = artifact_runtime
    root = tmp_path / "root"
    service = _service(runtime, root)
    content = b"<urlset/>"
    relative = _write_managed(service, root, job_id, run_id, "published.xml", content)
    target = root.joinpath(*relative.split("/"))
    base = sample_result(sample_request("/artifacts"))
    result = replace(
        base,
        publication_result=SitemapPublicationResult(
            PublicationState.PUBLISHED,
            None,
            (
                PublishedFileResult(
                    "published.xml",
                    PublicationDocumentType.URL_SITEMAP,
                    target,
                    len(content),
                    hashlib.sha256(content).hexdigest(),
                    replaced_existing=False,
                ),
            ),
            (),
            1,
            len(content),
            None,
        ),
    )
    batch = service.register_run_result(job_id, result)
    assert len(batch.registered) == 1
    assert batch.failure_codes == ()
    assert target.read_bytes() == content


def test_generated_xml_is_durably_retained_without_publication_or_summary(
    artifact_runtime: tuple[PersistenceRuntime, str, str], tmp_path: Path
) -> None:
    runtime, job_id, _ = artifact_runtime
    root = tmp_path / "root"
    service = _service(runtime, root)
    locations = tuple(f"https://example.test/page-{position}" for position in range(30))
    content = (
        "<urlset>"
        + "".join(f"<url><loc>{location}</loc></url>" for location in locations)
        + "</urlset>\n"
    ).encode()
    document = GeneratedSitemapDocument(
        "sitemap.xml",
        tuple(SitemapUrlEntry(location, position) for position, location in enumerate(locations)),
        content,
        len(content),
        len(locations),
    )
    bundle = SitemapXmlBundle(
        (document,),
        None,
        (),
        (),
        (),
        SitemapSerializationCounts(30, 30, 0, 30, 0, 0, 1),
        SitemapXmlConfiguration(),
    )
    result = replace(sample_result(sample_request("/artifacts")), xml_bundle=bundle)
    assert result.publication_result is None
    assert result.summary_write_result is None

    first = service.register_run_result(job_id, result)
    repeated = service.register_run_result(job_id, result)

    assert first.failure_codes == repeated.failure_codes == ()
    assert len(first.registered) == len(repeated.registered) == 1
    assert first.registered[0].artifact_id == repeated.registered[0].artifact_id
    assert len(service.list()) == 1
    record = first.registered[0]
    assert record.artifact_type is ArtifactType.SITEMAP_XML
    assert record.filename == "sitemap.xml"
    assert record.expected_byte_count == len(content)
    assert record.expected_sha256 == hashlib.sha256(content).hexdigest()
    restarted = _service(runtime, root)
    descriptor = restarted.prepare_download(record.artifact_id)
    assert b"".join(descriptor.iterator_factory()) == content
    assert content.count(b"<loc>") == 30
    assert len(set(locations)) == 30
    assert descriptor.content_type == "application/xml"


def test_production_adds_exactly_three_private_artifact_routes(
    artifact_runtime: tuple[PersistenceRuntime, str, str], tmp_path: Path
) -> None:
    runtime, job_id, run_id = artifact_runtime
    root = tmp_path / "root"
    service = _service(runtime, root)
    record = _register(service, root, job_id, run_id)
    application = create_production_app(
        _UnusedApplicationService(),  # type: ignore[arg-type]
        ProductionSettings.model_validate(
            {"enabled": True, "bearer_token": _TOKEN, "include_openapi": True}
        ),
        Settings(),
        artifacts=service,
    )
    internal = {
        path for path in application.openapi()["paths"] if path.startswith("/api/internal/v1")
    }
    assert len(internal) == 15
    assert {
        "/api/internal/v1/artifacts",
        "/api/internal/v1/artifacts/{artifact_id}",
        "/api/internal/v1/artifacts/{artifact_id}/download",
    } <= internal
    client = TestClient(
        application,
        client=("203.0.113.10", 50_000),
        raise_server_exceptions=False,
    )
    assert client.get("/api/internal/v1/artifacts").status_code == 401
    response = client.get(
        f"/api/internal/v1/artifacts/{record.artifact_id}",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )
    assert response.status_code == 200
    assert str(root) not in response.text
    download = client.get(
        f"/api/internal/v1/artifacts/{record.artifact_id}/download",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )
    assert download.content == b"<urlset/>"
    assert download.headers["content-disposition"] == 'attachment; filename="sitemap.xml"'
    assert "nosniff" in download.headers["x-content-type-options"]

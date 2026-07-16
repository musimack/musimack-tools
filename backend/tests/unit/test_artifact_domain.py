"""Artifact configuration, type, lifecycle, and path-safety contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from musimack_tools.artifacts.path_safety import validate_filename, validate_relative_path
from musimack_tools.deployment.artifacts import ArtifactStorageSettings
from musimack_tools.domain.artifacts import (
    ARTIFACT_RECONCILIATION_VERSION,
    ARTIFACT_RETRIEVAL_VERSION,
    ARTIFACT_STORAGE_VERSION,
    ARTIFACT_TYPE_POLICIES,
    ArtifactError,
    ArtifactLifecycleState,
    ArtifactStorageConfiguration,
    ArtifactStorageRootConfiguration,
    ArtifactType,
    validate_artifact_transition,
)


def test_artifact_versions_types_and_lifecycle_are_exact() -> None:
    assert ARTIFACT_STORAGE_VERSION == "seo-toolkit-artifact-storage-v1"
    assert ARTIFACT_RETRIEVAL_VERSION == "seo-toolkit-artifact-retrieval-v1"
    assert ARTIFACT_RECONCILIATION_VERSION == "seo-toolkit-artifact-reconciliation-v1"
    assert {item.value for item in ArtifactType} == {
        "sitemap_xml",
        "sitemap_index",
        "publication_manifest",
        "run_summary_json",
        "run_summary_markdown",
        "csv_export",
    }
    assert {item.value for item in ArtifactLifecycleState} == {
        "planned",
        "available",
        "missing",
        "corrupt",
        "expired",
        "deleted",
        "retained",
    }
    assert ARTIFACT_TYPE_POLICIES[ArtifactType.SITEMAP_XML].content_type == "application/xml"


def test_storage_is_disabled_by_default_and_csv_is_not_enabled() -> None:
    configuration = ArtifactStorageConfiguration()
    assert not configuration.enabled
    assert not configuration.type_enabled(ArtifactType.CSV_EXPORT)
    assert configuration.roots == ()


def test_enabled_storage_requires_explicit_absolute_unique_nonoverlapping_roots(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="explicit root"):
        ArtifactStorageConfiguration(enabled=True)
    with pytest.raises(ValueError, match="absolute"):
        ArtifactStorageRootConfiguration("default", Path("relative"))
    first = ArtifactStorageRootConfiguration("first", tmp_path / "first")
    nested = ArtifactStorageRootConfiguration("nested", tmp_path / "first" / "nested")
    with pytest.raises(ValueError, match="overlap"):
        ArtifactStorageConfiguration(enabled=True, default_root_id="first", roots=(first, nested))
    with pytest.raises(ValueError, match="unique"):
        ArtifactStorageConfiguration(
            enabled=True,
            default_root_id="first",
            roots=(first, ArtifactStorageRootConfiguration("first", tmp_path / "second")),
        )


@pytest.mark.parametrize(
    "value",
    [
        "../escape.xml",
        "/absolute.xml",
        "C:/drive.xml",
        "//server/share.xml",
        "safe\\ambiguous.xml",
        "jobs//empty.xml",
        "jobs/CON.xml",
        "jobs/file.xml:stream",
        "jobs/header\r\nInjected.xml",
    ],
)
def test_unsafe_relative_paths_are_rejected(value: str) -> None:
    with pytest.raises(ArtifactError):
        validate_relative_path(value)


@pytest.mark.parametrize("value", ["CON", "NUL.txt", "bad/name", "bad\\name", "x\r\nY"])
def test_unsafe_download_filenames_are_rejected(value: str) -> None:
    with pytest.raises(ArtifactError):
        validate_filename(value)


def test_configuration_rejects_unknown_versions_and_invalid_bounds(tmp_path: Path) -> None:
    root = ArtifactStorageRootConfiguration("default", tmp_path)
    with pytest.raises(ValueError, match="unsupported artifact storage"):
        ArtifactStorageConfiguration(storage_version="future")
    with pytest.raises(ValueError, match="stream chunk"):
        ArtifactStorageConfiguration(
            enabled=True,
            roots=(root,),
            maximum_file_bytes=2_000,
            stream_chunk_bytes=4_000,
        )
    with pytest.raises(ValueError, match="retention"):
        ArtifactStorageConfiguration(retention_days=0)


def test_environment_settings_parse_explicit_roots_without_creating_them(tmp_path: Path) -> None:
    root = tmp_path / "not-created"
    settings = ArtifactStorageSettings.model_validate(
        {"enabled": True, "storage_roots": f"default={root}"}
    )
    configuration = settings.to_configuration()
    assert configuration.enabled
    assert configuration.roots[0].path == root
    assert not root.exists()


def test_invalid_lifecycle_transition_is_typed() -> None:
    with pytest.raises(ArtifactError):
        validate_artifact_transition(
            ArtifactLifecycleState.DELETED, ArtifactLifecycleState.AVAILABLE
        )

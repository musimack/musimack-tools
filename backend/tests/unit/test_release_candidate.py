"""Tests for deterministic, safe release-candidate packaging."""

from __future__ import annotations

import json
import zipfile
from typing import TYPE_CHECKING

import pytest

from musimack_tools.release import candidate as release
from musimack_tools.release.candidate import (
    RELEASE_MANIFEST_VERSION,
    ReleaseCandidateError,
    ReleaseCandidateResult,
    create_release_candidate,
    validate_candidate_identifier,
    validate_git_commit,
    verify_release_candidate,
)

if TYPE_CHECKING:
    from pathlib import Path

_COMMIT = "a" * 40
_EPOCH = 1_700_000_000
_TOOLS = {"git": "git version test", "node": "v24.15.0", "npm": "11.12.1", "python": "3.14.4"}
_SYNTHETIC_ARCHIVE_ERROR = "synthetic archive failure"


@pytest.fixture
def release_repository(tmp_path: Path) -> Path:
    """Create the exact minimal approved release source shape."""

    for relative in (*release._REQUIRED_FILES, *release._REQUIRED_DOCUMENTS):  # noqa: SLF001
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"fixture:{relative}\n", encoding="utf-8")
    values = {
        "backend/alembic/env.py": "# migration environment\n",
        "backend/alembic/versions/0013_example.py": "revision = '0013_website_migration_qa'\n",
        "backend/src/musimack_tools/example.py": "VALUE = 1\n",
        "frontend/dist/index.html": "<!doctype html><title>Musimack</title>\n",
        "frontend/dist/assets/index-12345678.js": "console.log('release fixture')\n",
    }
    for relative, content in values.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    "value",
    ["rc-phase28-validation", "rc-2026.07.18-1", "rc-a", "rc-build.1"],
)
def test_candidate_identifier_accepts_bounded_lowercase_values(value: str) -> None:
    assert validate_candidate_identifier(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "phase28",
        "RC-phase28",
        "rc-../escape",
        "rc-a..b",
        "rc-a b",
        "rc-a;echo",
        "rc-a$(whoami)",
        "rc-é",
        "rc-" + "a" * 62,
        "rc-trailing-",
    ],
)
def test_candidate_identifier_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(ReleaseCandidateError, match="candidate_identifier_invalid"):
        validate_candidate_identifier(value)


def test_git_commit_requires_complete_lowercase_sha() -> None:
    assert validate_git_commit(_COMMIT) == _COMMIT
    for value in ("a" * 39, "A" * 40, "g" * 40, "main", "a" * 41):
        with pytest.raises(ReleaseCandidateError, match="git_commit_invalid"):
            validate_git_commit(value)


def test_candidate_manifest_and_archive_are_complete_and_safe(
    release_repository: Path, tmp_path: Path
) -> None:
    result = _create(release_repository, tmp_path / "candidate")
    manifest = json.loads(result.manifest.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == RELEASE_MANIFEST_VERSION
    assert manifest["candidate_identifier"] == "rc-phase28-validation"
    assert manifest["git_commit"] == _COMMIT
    assert manifest["migration"] == {
        "head": "0017_combined_site_audit_persistence",
        "parent": "0016_site_audit_settings",
    }
    assert manifest["source_timestamp_utc"] == "2023-11-14T22:13:20Z"
    assert manifest["tool_versions"] == _TOOLS
    assert manifest["known_limitations"] == "docs/known-limitations.md"
    paths = [item["path"] for item in manifest["files"]]
    assert paths == sorted(paths)
    assert "backend/src/musimack_tools/example.py" in paths
    assert "docs/final-acceptance.md" in paths
    assert "docs/known-limitations.md" in paths
    assert "docs/security-review.md" in paths
    assert "docs/accessibility-review.md" in paths
    assert "docs/release-readiness.md" in paths
    assert "frontend/dist/assets/index-12345678.js" in paths
    assert not any("tests" in path or "node_modules" in path for path in paths)
    serialized = result.manifest.read_text(encoding="utf-8")
    assert str(release_repository) not in serialized
    assert str(tmp_path) not in serialized
    assert "David Wallace" not in serialized
    review_password = "Musimack-" + "local-review-2026!"
    assert review_password not in serialized
    with zipfile.ZipFile(result.archive) as archive:
        assert archive.namelist() == [*paths, "release-manifest.json"]
        assert all(item.date_time == (1980, 1, 1, 0, 0, 0) for item in archive.infolist())
    assert verify_release_candidate(result.output_directory) == result


def test_repeated_packaging_is_byte_reproducible(release_repository: Path, tmp_path: Path) -> None:
    first = _create(release_repository, tmp_path / "first")
    second = _create(release_repository, tmp_path / "second")
    assert first.archive.read_bytes() == second.archive.read_bytes()
    assert first.manifest.read_bytes() == second.manifest.read_bytes()
    assert first.checksums.read_bytes() == second.checksums.read_bytes()


def test_prohibited_generated_files_are_excluded(release_repository: Path, tmp_path: Path) -> None:
    prohibited = release_repository / "backend/src/musimack_tools/__pycache__/example.pyc"
    prohibited.parent.mkdir()
    prohibited.write_bytes(b"compiled")
    result = _create(release_repository, tmp_path / "candidate")
    with zipfile.ZipFile(result.archive) as archive:
        assert not any(
            "__pycache__" in name or name.endswith(".pyc") for name in archive.namelist()
        )


def test_existing_destination_is_rejected(release_repository: Path, tmp_path: Path) -> None:
    destination = tmp_path / "existing"
    destination.mkdir()
    with pytest.raises(ReleaseCandidateError, match="output_destination_exists"):
        _create(release_repository, destination)


def test_linked_source_is_rejected_without_platform_privilege(
    release_repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = release_repository / "backend/src/musimack_tools/example.py"
    original = release._unsafe_link  # noqa: SLF001
    monkeypatch.setattr(release, "_unsafe_link", lambda path: path == target or original(path))
    with pytest.raises(ReleaseCandidateError, match="release_source"):
        _create(release_repository, tmp_path / "candidate")


def test_failure_cleans_private_staging_directory(
    release_repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OSError(_SYNTHETIC_ARCHIVE_ERROR)

    monkeypatch.setattr(release, "_write_archive", fail)
    destination = tmp_path / "candidate"
    with pytest.raises(OSError, match="synthetic"):
        _create(release_repository, destination)
    assert not destination.exists()
    assert not tuple(tmp_path.glob(".candidate.tmp-*"))


@pytest.mark.parametrize("missing", ["release-manifest.json", "CHECKSUMS.sha256"])
def test_missing_candidate_metadata_is_rejected(
    release_repository: Path, tmp_path: Path, missing: str
) -> None:
    result = _create(release_repository, tmp_path / "candidate")
    (result.output_directory / missing).unlink()
    with pytest.raises(ReleaseCandidateError, match="candidate_metadata_missing"):
        verify_release_candidate(result.output_directory)


def test_missing_candidate_archive_is_rejected(release_repository: Path, tmp_path: Path) -> None:
    result = _create(release_repository, tmp_path / "candidate")
    result.archive.unlink()
    with pytest.raises(ReleaseCandidateError, match="candidate_metadata_missing"):
        verify_release_candidate(result.output_directory)


def test_missing_required_source_is_rejected(release_repository: Path, tmp_path: Path) -> None:
    (release_repository / "README.md").unlink()
    with pytest.raises(ReleaseCandidateError, match="release_source_file_invalid"):
        _create(release_repository, tmp_path / "candidate")


def test_corrupted_archive_is_rejected(release_repository: Path, tmp_path: Path) -> None:
    result = _create(release_repository, tmp_path / "candidate")
    with result.archive.open("ab") as handle:
        handle.write(b"tampered")
    with pytest.raises(ReleaseCandidateError, match="candidate_checksum_mismatch"):
        verify_release_candidate(result.output_directory)


def test_manifest_path_traversal_is_rejected(release_repository: Path, tmp_path: Path) -> None:
    result = _create(release_repository, tmp_path / "candidate")
    value = json.loads(result.manifest.read_text(encoding="utf-8"))
    value["files"][0]["path"] = "../escape"
    result.manifest.write_text(json.dumps(value), encoding="utf-8")
    checksums = result.checksums.read_text(encoding="utf-8")
    old_hash = result.manifest_sha256
    new_hash = release._sha256(result.manifest)  # noqa: SLF001
    result.checksums.write_text(checksums.replace(old_hash, new_hash), encoding="utf-8")
    with pytest.raises(ReleaseCandidateError, match="release_relative_path_invalid"):
        verify_release_candidate(result.output_directory)


def _create(repository: Path, destination: Path) -> ReleaseCandidateResult:
    return create_release_candidate(
        repository,
        destination,
        candidate_identifier="rc-phase28-validation",
        git_commit=_COMMIT,
        source_timestamp_epoch=_EPOCH,
        tool_versions=_TOOLS,
        validation_summary={"backend": "passed", "frontend": "passed"},
    )

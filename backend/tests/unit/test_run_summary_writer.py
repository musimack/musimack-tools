"""Safe deterministic run-summary writer tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from musimack_tools.domain.run_summary import (
    RunSummaryArtifact,
    RunSummaryConfiguration,
    RunSummaryFormat,
    RunSummaryWriteState,
)
from musimack_tools.domain.sitemap_publication import ExistingFilePolicy
from musimack_tools.run.summary import RunSummaryWriter


def _artifacts() -> tuple[RunSummaryArtifact, ...]:
    return (
        RunSummaryArtifact("run-summary.json", RunSummaryFormat.JSON, b"{}\n", 3, "a" * 64),
        RunSummaryArtifact("run-summary.md", RunSummaryFormat.MARKDOWN, b"# Run\n", 6, "b" * 64),
    )


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    result = RunSummaryWriter().write(_artifacts(), RunSummaryConfiguration(tmp_path, dry_run=True))
    assert result.state is RunSummaryWriteState.DRY_RUN
    assert tuple(tmp_path.iterdir()) == ()


def test_missing_root_is_blocked_when_creation_disabled(tmp_path: Path) -> None:
    result = RunSummaryWriter().write(_artifacts(), RunSummaryConfiguration(tmp_path / "missing"))
    assert result.state is RunSummaryWriteState.BLOCKED
    assert result.failures[0].code == "output_root_missing"


def test_missing_root_is_created_and_both_files_are_written(tmp_path: Path) -> None:
    root = tmp_path / "new"
    result = RunSummaryWriter().write(
        _artifacts(), RunSummaryConfiguration(root, create_output_directory=True)
    )
    assert result.state is RunSummaryWriteState.WRITTEN
    assert [item.logical_name for item in result.written_files] == [
        "run-summary.json",
        "run-summary.md",
    ]
    assert (root / "run-summary.json").read_bytes() == b"{}\n"
    assert not tuple(root.glob(".*.tmp"))


def test_relative_output_root_is_rejected() -> None:
    result = RunSummaryWriter().write(
        _artifacts(), RunSummaryConfiguration(Path("relative"), dry_run=True)
    )
    assert result.failures[0].code == "output_root_not_absolute"


def test_git_output_root_is_rejected(tmp_path: Path) -> None:
    result = RunSummaryWriter().write(
        _artifacts(), RunSummaryConfiguration(tmp_path / ".git", dry_run=True)
    )
    assert result.failures[0].code == "output_root_prohibited"


def test_output_root_file_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "file"
    root.write_text("x")
    result = RunSummaryWriter().write(_artifacts(), RunSummaryConfiguration(root))
    assert result.failures[0].code == "output_root_is_file"


def test_fail_if_exists_does_not_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "run-summary.json"
    target.write_bytes(b"existing")
    result = RunSummaryWriter().write(_artifacts(), RunSummaryConfiguration(tmp_path))
    assert result.state is RunSummaryWriteState.BLOCKED
    assert target.read_bytes() == b"existing"
    assert result.failures[0].code == "target_exists"


def test_overwrite_replaces_both_fixed_files(tmp_path: Path) -> None:
    for artifact in _artifacts():
        (tmp_path / artifact.logical_name).write_bytes(b"old")
    result = RunSummaryWriter().write(
        _artifacts(),
        RunSummaryConfiguration(tmp_path, ExistingFilePolicy.OVERWRITE),
    )
    assert result.state is RunSummaryWriteState.WRITTEN
    assert all(item.replaced_existing for item in result.written_files)


@pytest.mark.skipif(not hasattr(Path, "is_junction"), reason="junction API unavailable")
def test_writer_uses_fixed_logical_names_only() -> None:
    assert {item.logical_name for item in _artifacts()} == {
        "run-summary.json",
        "run-summary.md",
    }


def test_writer_rejects_traversal_artifact_name(tmp_path: Path) -> None:
    malicious = (
        RunSummaryArtifact("../escape.json", RunSummaryFormat.JSON, b"{}\n", 3, "a" * 64),
        _artifacts()[1],
    )
    result = RunSummaryWriter().write(malicious, RunSummaryConfiguration(tmp_path))
    assert result.failures[0].code == "invalid_logical_filename"
    assert not (tmp_path.parent / "escape.json").exists()

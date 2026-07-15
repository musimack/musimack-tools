"""Security, planning, conflict, and atomic local publication tests."""

from __future__ import annotations

import errno
import hashlib
import os
import shutil
import subprocess
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

import musimack_tools.sitemap.publication as publication_module
from musimack_tools.domain.sitemap_publication import (
    ExistingFilePolicy,
    PlannedPublicationFile,
    PublicationFailureCode,
    PublicationMode,
    PublicationPlanState,
    PublicationState,
    SitemapPublicationConfiguration,
)
from musimack_tools.domain.sitemap_xml import (
    GeneratedSitemapDocument,
    GeneratedSitemapIndex,
    SitemapIndexEntry,
    SitemapSerializationCounts,
    SitemapUrlEntry,
    SitemapXmlBundle,
)
from musimack_tools.sitemap.limits import SitemapXmlConfiguration
from musimack_tools.sitemap.publication import (
    AtomicWriteError,
    LocalAtomicWriter,
    SitemapPublicationExecutor,
    link_kind_is_unsafe,
    plan_publication,
    validate_logical_filename,
)

_SYMLINK_CAPABILITY_ERRNOS = frozenset({errno.EACCES, errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP})
_SYMLINK_CAPABILITY_WINERRORS = frozenset({5, 50, 1_314})


def _document(name: str, location: str) -> GeneratedSitemapDocument:
    content = f"<urlset><url><loc>{location}</loc></url></urlset>\n".encode()
    return GeneratedSitemapDocument(
        logical_name=name,
        entries=(SitemapUrlEntry(location, 0),),
        xml_bytes=content,
        byte_count=len(content),
        entry_count=1,
    )


def _bundle(*, split: bool = False, index: bool = False) -> SitemapXmlBundle:
    documents = (
        (
            _document("sitemap-1.xml", "https://example.test/a"),
            _document("sitemap-2.xml", "https://example.test/b"),
        )
        if split
        else (_document("sitemap.xml", "https://example.test/a"),)
    )
    index_document = None
    if index:
        content = b"<sitemapindex><sitemap><loc>maps</loc></sitemap></sitemapindex>\n"
        index_document = GeneratedSitemapIndex(
            logical_name="sitemap-index.xml",
            entries=(SitemapIndexEntry("sitemap-1.xml", "https://example.test/maps"),),
            xml_bytes=content,
            byte_count=len(content),
            entry_count=len(documents),
        )
    counts = SitemapSerializationCounts(
        considered_recommendations=len(documents),
        include_recommendation_inputs=len(documents),
        skipped_non_include=0,
        unique_entries_emitted=len(documents),
        duplicate_suppression_count=0,
        rejected_entry_count=0,
        document_count=len(documents),
    )
    return SitemapXmlBundle(
        documents=documents,
        index_document=index_document,
        rejections=(),
        warnings=(),
        split_events=(),
        counts=counts,
        configuration_snapshot=SitemapXmlConfiguration(),
    )


def _configuration(
    root: Path,
    *,
    policy: ExistingFilePolicy = ExistingFilePolicy.FAIL_IF_EXISTS,
    mode: PublicationMode = PublicationMode.PUBLISH,
    create: bool = False,
) -> SitemapPublicationConfiguration:
    return SitemapPublicationConfiguration(root, policy, create, mode)


def _create_symlink_or_skip(link: Path, target: Path, *, target_is_directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as error:
        winerror = getattr(error, "winerror", None)
        if error.errno in _SYMLINK_CAPABILITY_ERRNOS or winerror in (_SYMLINK_CAPABILITY_WINERRORS):
            pytest.skip(
                "Symlink creation capability unavailable "
                f"(errno={error.errno}, winerror={winerror})."
            )
        raise


def _create_windows_junction_or_fail(link: Path, target: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows junction behavior requires Windows.")
    command = shutil.which("cmd.exe")
    if command is None:
        pytest.skip("Windows junction capability unavailable because cmd.exe was not found.")
    completed = subprocess.run(  # noqa: S603 -- fixed local Windows junction capability probe.
        [command, "/d", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        pytest.fail(
            "Windows junction creation unexpectedly failed: "
            f"stdout={completed.stdout!r}, stderr={completed.stderr!r}"
        )
    assert link.is_junction(), "mklink /J succeeded but pathlib did not classify the junction"


@pytest.mark.parametrize(
    "name",
    ["sitemap.xml", "sitemap-1.xml", "sitemap-index.xml", "sitemap-manifest.json"],
)
def test_safe_logical_filenames(name: str) -> None:
    assert validate_logical_filename(name) is None


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("", PublicationFailureCode.INVALID_LOGICAL_FILENAME),
        ("../sitemap.xml", PublicationFailureCode.UNSAFE_PATH),
        (r"..\sitemap.xml", PublicationFailureCode.UNSAFE_PATH),
        ("/absolute/sitemap.xml", PublicationFailureCode.UNSAFE_PATH),
        (r"C:\exports\sitemap.xml", PublicationFailureCode.UNSAFE_PATH),
        (r"C:sitemap.xml", PublicationFailureCode.UNSAFE_PATH),
        (r"\\server\share\sitemap.xml", PublicationFailureCode.UNSAFE_PATH),
        ("folder/sitemap.xml", PublicationFailureCode.UNSAFE_PATH),
        (r"folder\sitemap.xml", PublicationFailureCode.UNSAFE_PATH),
        ("sitemap\x00.xml", PublicationFailureCode.INVALID_LOGICAL_FILENAME),
        ("CON.xml", PublicationFailureCode.INVALID_LOGICAL_FILENAME),
        ("sitemap.xml.", PublicationFailureCode.INVALID_LOGICAL_FILENAME),
    ],
)
def test_unsafe_logical_filenames_have_stable_reasons(
    name: str, reason: PublicationFailureCode
) -> None:
    assert validate_logical_filename(name) is reason


def test_publication_configuration_defaults_are_safe_and_immutable(tmp_path: Path) -> None:
    configuration = SitemapPublicationConfiguration(tmp_path)
    assert configuration.existing_file_policy is ExistingFilePolicy.FAIL_IF_EXISTS
    assert configuration.create_output_directory is False
    assert configuration.mode is PublicationMode.PUBLISH
    with pytest.raises(FrozenInstanceError):
        configuration.create_output_directory = True  # type: ignore[misc]


def test_configuration_requires_path_and_typed_policy(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match=r"pathlib\.Path"):
        SitemapPublicationConfiguration(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="ExistingFilePolicy"):
        SitemapPublicationConfiguration(tmp_path, "overwrite")  # type: ignore[arg-type]


def test_single_sitemap_plan_has_manifest_last_and_exact_integrity(tmp_path: Path) -> None:
    bundle = _bundle()
    plan = plan_publication(bundle, "rules-v1", _configuration(tmp_path))

    assert plan.state is PublicationPlanState.READY
    assert [item.logical_name for item in plan.files] == ["sitemap.xml", "sitemap-manifest.json"]
    assert all(item.target_path.parent == tmp_path.resolve() for item in plan.files)
    assert plan.files[0].content == bundle.documents[0].xml_bytes
    assert plan.files[0].sha256 == hashlib.sha256(bundle.documents[0].xml_bytes).hexdigest()


def test_split_plan_orders_documents_index_then_manifest(tmp_path: Path) -> None:
    plan = plan_publication(_bundle(split=True, index=True), "rules-v1", _configuration(tmp_path))
    assert [item.logical_name for item in plan.files] == [
        "sitemap-1.xml",
        "sitemap-2.xml",
        "sitemap-index.xml",
        "sitemap-manifest.json",
    ]


def test_missing_root_creation_disabled_blocks_plan(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    plan = plan_publication(_bundle(), "rules-v1", _configuration(root))
    assert plan.state is PublicationPlanState.BLOCKED
    assert plan.failures[0].code is PublicationFailureCode.OUTPUT_ROOT_MISSING
    assert not root.exists()


def test_missing_root_creation_enabled_plans_without_creating(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    plan = plan_publication(_bundle(), "rules-v1", _configuration(root, create=True))
    assert plan.state is PublicationPlanState.READY
    assert plan.output_directory_would_be_created is True
    assert not root.exists()


def test_relative_root_is_rejected_without_resolution() -> None:
    plan = plan_publication(_bundle(), "rules-v1", _configuration(Path("exports"), create=True))
    assert plan.state is PublicationPlanState.BLOCKED
    assert plan.failures[0].code is PublicationFailureCode.OUTPUT_ROOT_NOT_ABSOLUTE


def test_output_root_that_is_file_is_blocked(tmp_path: Path) -> None:
    root = tmp_path / "file"
    root.write_text("not a directory", encoding="utf-8")
    plan = plan_publication(_bundle(), "rules-v1", _configuration(root))
    assert plan.failures[0].code is PublicationFailureCode.OUTPUT_ROOT_IS_FILE


def test_git_metadata_root_is_prohibited(tmp_path: Path) -> None:
    root = tmp_path / ".git" / "exports"
    plan = plan_publication(_bundle(), "rules-v1", _configuration(root, create=True))
    assert plan.failures[0].code is PublicationFailureCode.OUTPUT_ROOT_PROHIBITED


def test_existing_target_blocks_all_under_default_policy(tmp_path: Path) -> None:
    existing = tmp_path / "sitemap.xml"
    existing.write_bytes(b"keep")
    plan = plan_publication(_bundle(), "rules-v1", _configuration(tmp_path))
    result = SitemapPublicationExecutor().execute(plan)

    assert plan.state is PublicationPlanState.BLOCKED
    assert result.state is PublicationState.BLOCKED
    assert result.published_files == ()
    assert existing.read_bytes() == b"keep"
    assert not (tmp_path / "sitemap-manifest.json").exists()


def test_multiple_conflicts_are_reported_in_package_order(tmp_path: Path) -> None:
    for name in ("sitemap.xml", "sitemap-manifest.json"):
        (tmp_path / name).write_bytes(b"existing")
    plan = plan_publication(_bundle(), "rules-v1", _configuration(tmp_path))
    assert [item.logical_name for item in plan.failures] == [
        "sitemap.xml",
        "sitemap-manifest.json",
    ]


def test_existing_target_directory_is_blocked_even_for_overwrite(tmp_path: Path) -> None:
    (tmp_path / "sitemap.xml").mkdir()
    plan = plan_publication(
        _bundle(),
        "rules-v1",
        _configuration(tmp_path, policy=ExistingFilePolicy.OVERWRITE),
    )
    assert plan.failures[0].code is PublicationFailureCode.TARGET_IS_DIRECTORY


def test_case_variant_package_collision_is_blocked(tmp_path: Path) -> None:
    bundle = _bundle(split=True)
    second = replace(bundle.documents[1], logical_name="SITEMAP-1.XML")
    plan = plan_publication(
        replace(bundle, documents=(bundle.documents[0], second)),
        "rules-v1",
        _configuration(tmp_path),
    )
    assert PublicationFailureCode.CASE_NORMALIZED_COLLISION in {item.code for item in plan.failures}


def test_reserved_manifest_collision_is_blocked(tmp_path: Path) -> None:
    bundle = _bundle()
    document = replace(bundle.documents[0], logical_name="sitemap-manifest.json")
    plan = plan_publication(
        replace(bundle, documents=(document,)),
        "rules-v1",
        _configuration(tmp_path),
    )
    codes = {item.code for item in plan.failures}
    assert PublicationFailureCode.RESERVED_MANIFEST_COLLISION in codes
    assert PublicationFailureCode.DUPLICATE_LOGICAL_FILENAME in codes


def test_plan_is_immutable_and_deterministic(tmp_path: Path) -> None:
    configuration = _configuration(tmp_path)
    first = plan_publication(_bundle(), "rules-v1", configuration)
    second = plan_publication(_bundle(), "rules-v1", configuration)
    assert first == second
    with pytest.raises(FrozenInstanceError):
        first.state = PublicationPlanState.BLOCKED  # type: ignore[misc]


def test_dry_run_returns_exact_plan_and_writes_nothing(tmp_path: Path) -> None:
    plan = plan_publication(
        _bundle(),
        "rules-v1",
        _configuration(tmp_path, mode=PublicationMode.DRY_RUN),
    )
    result = SitemapPublicationExecutor().execute(plan)
    assert result.state is PublicationState.DRY_RUN
    assert result.plan == plan
    assert result.manifest_sha256 == plan.manifest_artifact.sha256
    assert list(tmp_path.iterdir()) == []


def test_dry_run_missing_creatable_root_does_not_create_directory(tmp_path: Path) -> None:
    root = tmp_path / "preview"
    plan = plan_publication(
        _bundle(),
        "rules-v1",
        _configuration(root, mode=PublicationMode.DRY_RUN, create=True),
    )
    result = SitemapPublicationExecutor().execute(plan)
    assert result.state is PublicationState.DRY_RUN
    assert not root.exists()


def test_real_publication_writes_exact_xml_and_manifest(tmp_path: Path) -> None:
    bundle = _bundle()
    plan = plan_publication(bundle, "rules-v1", _configuration(tmp_path))
    result = SitemapPublicationExecutor().execute(plan)

    assert result.state is PublicationState.PUBLISHED
    assert result.published_file_count == 2
    assert (tmp_path / "sitemap.xml").read_bytes() == bundle.documents[0].xml_bytes
    assert (tmp_path / "sitemap-manifest.json").read_bytes() == plan.manifest_artifact.content
    assert result.published_byte_count == sum(item.byte_count for item in plan.files)
    assert not list(tmp_path.glob("*.tmp"))


def test_real_publication_creates_explicitly_allowed_directory(tmp_path: Path) -> None:
    root = tmp_path / "export"
    plan = plan_publication(_bundle(), "rules-v1", _configuration(root, create=True))
    result = SitemapPublicationExecutor().execute(plan)
    assert result.state is PublicationState.PUBLISHED
    assert root.is_dir()


def test_overwrite_atomically_replaces_package_and_preserves_unrelated_file(tmp_path: Path) -> None:
    unrelated = tmp_path / "notes.txt"
    unrelated.write_bytes(b"untouched")
    for name in ("sitemap.xml", "sitemap-manifest.json"):
        (tmp_path / name).write_bytes(b"old")
    plan = plan_publication(
        _bundle(),
        "rules-v1",
        _configuration(tmp_path, policy=ExistingFilePolicy.OVERWRITE),
    )
    result = SitemapPublicationExecutor().execute(plan)

    assert result.state is PublicationState.PUBLISHED
    assert all(item.replaced_existing for item in result.published_files)
    assert unrelated.read_bytes() == b"untouched"
    assert all(item.target_path.read_bytes() == item.content for item in plan.files)


def test_repeated_overwrite_produces_identical_files(tmp_path: Path) -> None:
    configuration = _configuration(tmp_path, policy=ExistingFilePolicy.OVERWRITE)
    first_plan = plan_publication(_bundle(), "rules-v1", configuration)
    SitemapPublicationExecutor().execute(first_plan)
    first = {item.name: item.read_bytes() for item in tmp_path.iterdir()}
    second_plan = plan_publication(_bundle(), "rules-v1", configuration)
    SitemapPublicationExecutor().execute(second_plan)
    second = {item.name: item.read_bytes() for item in tmp_path.iterdir()}
    assert first == second


def test_split_package_publishes_documents_index_and_manifest(tmp_path: Path) -> None:
    plan = plan_publication(_bundle(split=True, index=True), "rules-v1", _configuration(tmp_path))
    result = SitemapPublicationExecutor().execute(plan)
    assert result.state is PublicationState.PUBLISHED
    assert [item.name for item in sorted(tmp_path.iterdir())] == [
        "sitemap-1.xml",
        "sitemap-2.xml",
        "sitemap-index.xml",
        "sitemap-manifest.json",
    ]


class _FailSecondWriter:
    def __init__(self) -> None:
        self._calls = 0
        self._local = LocalAtomicWriter()

    def write(self, planned_file: PlannedPublicationFile, policy: ExistingFilePolicy) -> None:
        self._calls += 1
        if self._calls == 2:
            raise AtomicWriteError(PublicationFailureCode.WRITE_FAILED)
        self._local.write(planned_file, policy)


def test_later_failure_returns_partial_result_without_temp_files(tmp_path: Path) -> None:
    plan = plan_publication(_bundle(), "rules-v1", _configuration(tmp_path))
    result = SitemapPublicationExecutor(_FailSecondWriter()).execute(plan)

    assert result.state is PublicationState.PARTIALLY_FAILED
    assert [item.logical_name for item in result.published_files] == ["sitemap.xml"]
    assert result.failures[0].code is PublicationFailureCode.WRITE_FAILED
    assert (tmp_path / "sitemap.xml").exists()
    assert not (tmp_path / "sitemap-manifest.json").exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_injected_write_failure_cleans_secure_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_write(_temporary: object, _content: bytes) -> None:
        raise AtomicWriteError(PublicationFailureCode.WRITE_FAILED)

    monkeypatch.setattr(publication_module, "_write_and_flush", fail_write)
    plan = plan_publication(_bundle(), "rules-v1", _configuration(tmp_path))
    result = SitemapPublicationExecutor().execute(plan)

    assert result.state is PublicationState.BLOCKED
    assert result.failures[0].code is PublicationFailureCode.WRITE_FAILED
    assert list(tmp_path.iterdir()) == []


def test_injected_replace_failure_cleans_temp_and_preserves_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    existing = tmp_path / "sitemap.xml"
    existing.write_bytes(b"old")
    original_replace = Path.replace

    def fail_sitemap_replace(path: Path, target: Path) -> Path:
        if target.name == "sitemap.xml":
            raise OSError("injected")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_sitemap_replace)
    plan = plan_publication(
        _bundle(),
        "rules-v1",
        _configuration(tmp_path, policy=ExistingFilePolicy.OVERWRITE),
    )
    result = SitemapPublicationExecutor().execute(plan)

    assert result.state is PublicationState.BLOCKED
    assert result.failures[0].code is PublicationFailureCode.ATOMIC_REPLACE_FAILED
    assert existing.read_bytes() == b"old"
    assert not list(tmp_path.glob("*.tmp"))


def test_target_appearing_after_preflight_is_preserved_without_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_hardlink = Path.hardlink_to
    competing_content = b"competing-process"

    def create_competing_target(link: Path, temporary: Path) -> None:
        link.write_bytes(competing_content)
        original_hardlink(link, temporary)

    monkeypatch.setattr(Path, "hardlink_to", create_competing_target)
    plan = plan_publication(_bundle(), "rules-v1", _configuration(tmp_path))
    result = SitemapPublicationExecutor().execute(plan)

    assert result.state is PublicationState.BLOCKED
    assert result.failures[0].code is PublicationFailureCode.TARGET_EXISTS
    assert (tmp_path / "sitemap.xml").read_bytes() == competing_content
    assert not (tmp_path / "sitemap-manifest.json").exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_unsupported_no_clobber_primitive_fails_without_replace_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unsupported_hardlink(_link: Path, _temporary: Path) -> None:
        raise OSError(errno.EOPNOTSUPP, "injected unsupported hard link")

    def forbidden_replace(_path: Path, _target: Path) -> Path:
        pytest.fail("fail_if_exists must never fall back to replacement")

    monkeypatch.setattr(Path, "hardlink_to", unsupported_hardlink)
    monkeypatch.setattr(Path, "replace", forbidden_replace)
    plan = plan_publication(_bundle(), "rules-v1", _configuration(tmp_path))
    result = SitemapPublicationExecutor().execute(plan)

    assert result.state is PublicationState.BLOCKED
    assert result.failures[0].code is (PublicationFailureCode.NO_CLOBBER_FINALIZATION_UNSUPPORTED)
    assert not (tmp_path / "sitemap.xml").exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_no_clobber_permission_failure_has_distinct_typed_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def denied_hardlink(_link: Path, _temporary: Path) -> None:
        raise PermissionError(errno.EACCES, "injected permission denial")

    monkeypatch.setattr(Path, "hardlink_to", denied_hardlink)
    plan = plan_publication(_bundle(), "rules-v1", _configuration(tmp_path))
    result = SitemapPublicationExecutor().execute(plan)

    assert result.state is PublicationState.BLOCKED
    assert result.failures[0].code is (
        PublicationFailureCode.NO_CLOBBER_FINALIZATION_PERMISSION_DENIED
    )
    assert not (tmp_path / "sitemap.xml").exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_other_no_clobber_failure_has_distinct_typed_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failed_hardlink(_link: Path, _temporary: Path) -> None:
        raise OSError(errno.EIO, "injected finalization failure")

    monkeypatch.setattr(Path, "hardlink_to", failed_hardlink)
    plan = plan_publication(_bundle(), "rules-v1", _configuration(tmp_path))
    result = SitemapPublicationExecutor().execute(plan)

    assert result.state is PublicationState.BLOCKED
    assert result.failures[0].code is PublicationFailureCode.NO_CLOBBER_FINALIZATION_FAILED
    assert not (tmp_path / "sitemap.xml").exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_later_no_clobber_capability_failure_preserves_partial_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_hardlink = Path.hardlink_to

    def fail_manifest_hardlink(link: Path, temporary: Path) -> None:
        if link.name == "sitemap-manifest.json":
            raise OSError(errno.EOPNOTSUPP, "injected unsupported hard link")
        original_hardlink(link, temporary)

    monkeypatch.setattr(Path, "hardlink_to", fail_manifest_hardlink)
    plan = plan_publication(_bundle(), "rules-v1", _configuration(tmp_path))
    result = SitemapPublicationExecutor().execute(plan)

    assert result.state is PublicationState.PARTIALLY_FAILED
    assert [item.logical_name for item in result.published_files] == ["sitemap.xml"]
    assert [item.code for item in result.failures] == [
        PublicationFailureCode.NO_CLOBBER_FINALIZATION_UNSUPPORTED,
        PublicationFailureCode.PARTIAL_PACKAGE_PUBLICATION,
    ]
    assert not (tmp_path / "sitemap-manifest.json").exists()
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize(
    ("is_symlink", "is_junction", "unsafe"),
    [
        (False, False, False),
        (True, False, True),
        (False, True, True),
        (True, True, True),
    ],
)
def test_platform_neutral_link_kind_classification(
    *, is_symlink: bool, is_junction: bool, unsafe: bool
) -> None:
    assert link_kind_is_unsafe(is_symlink=is_symlink, is_junction=is_junction) is unsafe


def test_target_symlink_is_blocked_when_platform_supports_it(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside")
    target = tmp_path / "sitemap.xml"
    _create_symlink_or_skip(target, outside)

    plan = plan_publication(
        _bundle(),
        "rules-v1",
        _configuration(tmp_path, policy=ExistingFilePolicy.OVERWRITE),
    )
    assert plan.state is PublicationPlanState.BLOCKED
    assert plan.failures[0].code is PublicationFailureCode.TARGET_UNSAFE_SYMLINK
    assert outside.read_bytes() == b"outside"


def test_symlinked_output_root_is_blocked_when_platform_supports_it(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    _create_symlink_or_skip(linked, real, target_is_directory=True)
    plan = plan_publication(_bundle(), "rules-v1", _configuration(linked))
    assert plan.failures[0].code is PublicationFailureCode.OUTPUT_ROOT_UNSAFE_SYMLINK


def test_symlinked_output_root_ancestor_is_blocked_when_platform_supports_it(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    _create_symlink_or_skip(linked, real, target_is_directory=True)

    plan = plan_publication(
        _bundle(),
        "rules-v1",
        _configuration(linked / "child", create=True),
    )

    assert plan.failures[0].code is PublicationFailureCode.OUTPUT_ROOT_UNSAFE_SYMLINK
    assert not (real / "child").exists()


def test_windows_junction_output_root_is_blocked(tmp_path: Path) -> None:
    real = tmp_path / "junction-real"
    real.mkdir()
    junction = tmp_path / "junction-root"
    _create_windows_junction_or_fail(junction, real)
    try:
        plan = plan_publication(_bundle(), "rules-v1", _configuration(junction))
        assert plan.failures[0].code is PublicationFailureCode.OUTPUT_ROOT_UNSAFE_SYMLINK
    finally:
        junction.rmdir()


def test_windows_junction_output_root_ancestor_is_blocked(tmp_path: Path) -> None:
    real = tmp_path / "junction-real"
    real.mkdir()
    junction = tmp_path / "junction-root"
    _create_windows_junction_or_fail(junction, real)
    try:
        plan = plan_publication(
            _bundle(),
            "rules-v1",
            _configuration(junction / "child", create=True),
        )
        assert plan.failures[0].code is PublicationFailureCode.OUTPUT_ROOT_UNSAFE_SYMLINK
        assert not (real / "child").exists()
    finally:
        junction.rmdir()

"""Tests for deterministic sitemap publication manifests and integrity evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import TYPE_CHECKING

from musimack_tools.domain.sitemap_publication import (
    SITEMAP_PUBLICATION_MANIFEST_VERSION,
    ExistingFilePolicy,
    PublicationDocumentType,
    SitemapPublicationConfiguration,
)
from musimack_tools.domain.sitemap_xml import (
    GeneratedSitemapDocument,
    GeneratedSitemapIndex,
    SitemapBundleWarning,
    SitemapBundleWarningCode,
    SitemapIndexEntry,
    SitemapSerializationCounts,
    SitemapUrlEntry,
    SitemapXmlBundle,
)
from musimack_tools.sitemap.limits import SitemapXmlConfiguration
from musimack_tools.sitemap.manifest import build_manifest, sha256_hex

if TYPE_CHECKING:
    from pathlib import Path


def _bundle(*, split: bool = False, index: bool = False, unicode: bool = False) -> SitemapXmlBundle:
    locations = ["https://example.test/café" if unicode else "https://example.test/a"]
    if split:
        locations.append("https://example.test/b")
    documents = tuple(
        GeneratedSitemapDocument(
            logical_name=(f"sitemap-{position}.xml" if split else "sitemap.xml"),
            entries=(SitemapUrlEntry(location, position - 1),),
            xml_bytes=f"<urlset><url><loc>{location}</loc></url></urlset>\n".encode(),
            byte_count=len(f"<urlset><url><loc>{location}</loc></url></urlset>\n".encode()),
            entry_count=1,
        )
        for position, location in enumerate(locations, start=1)
    )
    index_document = None
    if index:
        index_bytes = b"<sitemapindex><sitemap><loc>maps</loc></sitemap></sitemapindex>\n"
        index_document = GeneratedSitemapIndex(
            logical_name="sitemap-index.xml",
            entries=(SitemapIndexEntry(documents[0].logical_name, "https://example.test/maps"),),
            xml_bytes=index_bytes,
            byte_count=len(index_bytes),
            entry_count=len(documents),
        )
    warning = (
        ()
        if not split or index
        else (
            SitemapBundleWarning(
                SitemapBundleWarningCode.INDEX_BLOCKED_MISSING_BASE_URL,
                "Missing base.",
            ),
        )
    )
    counts = SitemapSerializationCounts(
        considered_recommendations=len(locations) + 1,
        include_recommendation_inputs=len(locations),
        skipped_non_include=1,
        unique_entries_emitted=len(locations),
        duplicate_suppression_count=2,
        rejected_entry_count=1,
        document_count=len(documents),
    )
    return SitemapXmlBundle(
        documents=documents,
        index_document=index_document,
        rejections=(),
        warnings=warning,
        split_events=(),
        counts=counts,
        configuration_snapshot=SitemapXmlConfiguration(),
    )


def _configuration(tmp_path: Path) -> SitemapPublicationConfiguration:
    return SitemapPublicationConfiguration(output_root=tmp_path)


def test_sha256_known_fixture_includes_final_newline() -> None:
    content = b"sitemap\n"
    assert sha256_hex(content) == hashlib.sha256(content).hexdigest()
    assert sha256_hex(content) != sha256_hex(content.rstrip())


def test_single_sitemap_manifest_contains_exact_versions_and_counts(tmp_path: Path) -> None:
    artifact = build_manifest(_bundle(), "sitemap-eligibility-v1", _configuration(tmp_path))

    assert artifact.manifest.schema_version == SITEMAP_PUBLICATION_MANIFEST_VERSION
    assert artifact.manifest.xml_format_version == "sitemap-xml-v1"
    assert artifact.manifest.recommendation_rule_set_version == "sitemap-eligibility-v1"
    assert artifact.manifest.xml_file_count == 1
    assert artifact.manifest.total_serialized_url_entries == 1
    assert artifact.manifest.duplicate_suppression_count == 2
    assert artifact.manifest.rejected_url_count == 1
    assert artifact.manifest.skipped_non_include_count == 1


def test_manifest_file_hash_and_byte_count_match_exact_xml(tmp_path: Path) -> None:
    bundle = _bundle()
    artifact = build_manifest(bundle, "rules-v1", _configuration(tmp_path))
    record = artifact.manifest.files[0]

    assert record.byte_count == len(bundle.documents[0].xml_bytes)
    assert record.sha256 == hashlib.sha256(bundle.documents[0].xml_bytes).hexdigest()
    assert record.document_type is PublicationDocumentType.URL_SITEMAP


def test_multi_document_manifest_orders_documents_then_index(tmp_path: Path) -> None:
    artifact = build_manifest(
        _bundle(split=True, index=True),
        "rules-v1",
        _configuration(tmp_path),
    )

    assert [item.logical_name for item in artifact.manifest.files] == [
        "sitemap-1.xml",
        "sitemap-2.xml",
        "sitemap-index.xml",
    ]
    assert artifact.manifest.index_present is True
    assert artifact.manifest.url_sitemap_document_count == 2


def test_index_blockage_is_preserved_without_fabricated_index(tmp_path: Path) -> None:
    artifact = build_manifest(_bundle(split=True), "rules-v1", _configuration(tmp_path))

    assert artifact.manifest.index_present is False
    assert artifact.manifest.index_blockage_codes == ("index_blocked_missing_base_url",)
    assert [item.logical_name for item in artifact.manifest.files] == [
        "sitemap-1.xml",
        "sitemap-2.xml",
    ]


def test_manifest_json_format_is_deterministic_sorted_utf8_with_final_newline(
    tmp_path: Path,
) -> None:
    configuration = _configuration(tmp_path)
    first = build_manifest(_bundle(unicode=True), "rules-v1", configuration)
    second = build_manifest(_bundle(unicode=True), "rules-v1", configuration)

    assert first == second
    assert first.content == second.content
    assert first.content.endswith(b"\n")
    assert (
        b"caf\xc3\xa9" not in first.content
    )  # URLs are described by hashes, not copied into JSON.
    assert json.loads(first.content)["schema_version"] == SITEMAP_PUBLICATION_MANIFEST_VERSION
    assert first.sha256 == hashlib.sha256(first.content).hexdigest()
    assert first.byte_count == len(first.content)


def test_manifest_excludes_self_hash_paths_and_machine_fields(tmp_path: Path) -> None:
    artifact = build_manifest(_bundle(), "rules-v1", _configuration(tmp_path))
    value = json.loads(artifact.content)
    text = artifact.content.decode()

    assert "manifest_sha256" not in value
    assert "sitemap-manifest.json" not in [item["logical_name"] for item in value["files"]]
    assert str(tmp_path) not in text
    for prohibited in ("timestamp", "username", "hostname", "output_root", "machine"):
        assert prohibited not in text.casefold()


def test_manifest_safe_configuration_summary_excludes_mode_and_root(tmp_path: Path) -> None:
    configuration = SitemapPublicationConfiguration(
        output_root=tmp_path,
        existing_file_policy=ExistingFilePolicy.OVERWRITE,
        create_output_directory=True,
    )
    value = json.loads(build_manifest(_bundle(), "rules-v1", configuration).content)

    assert value["existing_file_policy"] == "overwrite"
    assert value["create_output_directory"] is True
    assert "mode" not in value
    assert "output_root" not in value


def test_changed_xml_changes_file_hash_manifest_and_manifest_hash(tmp_path: Path) -> None:
    bundle = _bundle()
    changed_document = replace(
        bundle.documents[0],
        xml_bytes=b"<urlset>changed</urlset>\n",
        byte_count=len(b"<urlset>changed</urlset>\n"),
    )
    changed = replace(bundle, documents=(changed_document,))

    first = build_manifest(bundle, "rules-v1", _configuration(tmp_path))
    second = build_manifest(changed, "rules-v1", _configuration(tmp_path))

    assert first.manifest.files[0].sha256 != second.manifest.files[0].sha256
    assert first.content != second.content
    assert first.sha256 != second.sha256


def test_total_xml_bytes_include_index_when_present(tmp_path: Path) -> None:
    bundle = _bundle(split=True, index=True)
    manifest = build_manifest(bundle, "rules-v1", _configuration(tmp_path)).manifest
    expected = sum(item.byte_count for item in bundle.documents)
    assert bundle.index_document is not None
    expected += bundle.index_document.byte_count
    assert manifest.total_xml_bytes == expected

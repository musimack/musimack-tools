"""Deterministic sitemap package manifest and integrity generation."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from musimack_tools.domain.sitemap_publication import (
    SITEMAP_MANIFEST_LOGICAL_NAME,
    SITEMAP_PUBLICATION_MANIFEST_VERSION,
    ManifestArtifact,
    ManifestFileRecord,
    PublicationDocumentType,
    SitemapPublicationConfiguration,
    SitemapPublicationManifest,
)

if TYPE_CHECKING:
    from musimack_tools.domain.sitemap_xml import SitemapXmlBundle


def sha256_hex(content: bytes) -> str:
    """Return lowercase SHA-256 evidence for exact immutable bytes."""
    return hashlib.sha256(content).hexdigest()


def build_manifest(
    bundle: SitemapXmlBundle,
    recommendation_rule_set_version: str,
    configuration: SitemapPublicationConfiguration,
) -> ManifestArtifact:
    """Build deterministic JSON describing XML payload files, excluding itself."""
    file_records = tuple(_file_records(bundle))
    manifest = SitemapPublicationManifest(
        schema_version=SITEMAP_PUBLICATION_MANIFEST_VERSION,
        xml_format_version=bundle.format_version,
        recommendation_rule_set_version=recommendation_rule_set_version,
        xml_file_count=len(file_records),
        url_sitemap_document_count=len(bundle.documents),
        index_present=bundle.index_document is not None,
        total_serialized_url_entries=bundle.total_entries,
        total_xml_bytes=sum(item.byte_count for item in file_records),
        duplicate_suppression_count=bundle.counts.duplicate_suppression_count,
        rejected_url_count=bundle.counts.rejected_entry_count,
        skipped_non_include_count=bundle.counts.skipped_non_include,
        index_blockage_codes=tuple(item.code.value for item in bundle.warnings),
        existing_file_policy=configuration.existing_file_policy,
        create_output_directory=configuration.create_output_directory,
        files=file_records,
    )
    content = _serialize_manifest(manifest)
    return ManifestArtifact(
        logical_name=SITEMAP_MANIFEST_LOGICAL_NAME,
        manifest=manifest,
        content=content,
        byte_count=len(content),
        sha256=sha256_hex(content),
    )


def _file_records(bundle: SitemapXmlBundle) -> list[ManifestFileRecord]:
    records = [
        ManifestFileRecord(
            logical_name=document.logical_name,
            document_type=PublicationDocumentType.URL_SITEMAP,
            media_type=document.media_type,
            byte_count=document.byte_count,
            sha256=sha256_hex(document.xml_bytes),
            entry_count=document.entry_count,
        )
        for document in bundle.documents
    ]
    if bundle.index_document is not None:
        index = bundle.index_document
        records.append(
            ManifestFileRecord(
                logical_name=index.logical_name,
                document_type=PublicationDocumentType.SITEMAP_INDEX,
                media_type=index.media_type,
                byte_count=index.byte_count,
                sha256=sha256_hex(index.xml_bytes),
                entry_count=index.entry_count,
            )
        )
    return records


def _serialize_manifest(manifest: SitemapPublicationManifest) -> bytes:
    value = {
        "create_output_directory": manifest.create_output_directory,
        "duplicate_suppression_count": manifest.duplicate_suppression_count,
        "existing_file_policy": manifest.existing_file_policy.value,
        "files": [
            {
                "byte_count": item.byte_count,
                "document_type": item.document_type.value,
                "entry_count": item.entry_count,
                "logical_name": item.logical_name,
                "media_type": item.media_type,
                "sha256": item.sha256,
            }
            for item in manifest.files
        ],
        "index_blockage_codes": list(manifest.index_blockage_codes),
        "index_present": manifest.index_present,
        "recommendation_rule_set_version": manifest.recommendation_rule_set_version,
        "rejected_url_count": manifest.rejected_url_count,
        "schema_version": manifest.schema_version,
        "skipped_non_include_count": manifest.skipped_non_include_count,
        "total_serialized_url_entries": manifest.total_serialized_url_entries,
        "total_xml_bytes": manifest.total_xml_bytes,
        "url_sitemap_document_count": manifest.url_sitemap_document_count,
        "xml_file_count": manifest.xml_file_count,
        "xml_format_version": manifest.xml_format_version,
    }
    return f"{json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)}\n".encode()

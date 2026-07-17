"""Phase 23 policy, identity, anchor, and cursor contracts."""

from __future__ import annotations

import pytest

from musimack_tools.domain.internal_link import (
    PAGE_ORDERING,
    InternalLinkConfiguration,
    audit_identity,
    decode_cursor,
    encode_cursor,
    filter_fingerprint,
    is_url_anchor,
    normalize_anchor,
)


def test_anchor_normalization_is_bounded_and_deterministic() -> None:
    assert normalize_anchor("  Useful\n  GUIDE ") == "useful guide"
    assert len(normalize_anchor("x" * 1_000)) == 512
    assert is_url_anchor("https://example.com/guide")
    assert not is_url_anchor("useful guide")


def test_cursor_binds_resource_order_and_filters() -> None:
    fingerprint = filter_fingerprint({"severity": "high"})
    cursor = encode_cursor("pages", PAGE_ORDERING, fingerprint, 20)
    assert decode_cursor(cursor, "pages", PAGE_ORDERING, fingerprint) == 20
    with pytest.raises(ValueError, match="cursor_filter_mismatch"):
        decode_cursor(cursor, "edges", PAGE_ORDERING, fingerprint)


def test_configuration_and_audit_identity_are_stable() -> None:
    first = InternalLinkConfiguration(enabled=True)
    second = InternalLinkConfiguration(enabled=True)
    assert audit_identity("run-1", first) == audit_identity("run-1", second)
    with pytest.raises(ValueError, match="page sizes"):
        InternalLinkConfiguration(default_page_size=201, maximum_page_size=200)

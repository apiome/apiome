"""Unit tests for MCP catalog collection validation (V2-MCP-36.4 / MCAT-22.4, #4667)."""

import pytest

from app.mcp_collections import (
    CollectionValidationError,
    MAX_COLLECTION_MEMBERS,
    merge_member_ids,
    normalize_collection_description,
    normalize_collection_member_ids,
    normalize_collection_name,
    normalize_collection_slug,
    slugify_collection_name,
)


def test_normalize_collection_name_strips():
    assert normalize_collection_name("  Geo tools  ") == "Geo tools"


def test_normalize_collection_name_rejects_empty():
    with pytest.raises(CollectionValidationError, match="required"):
        normalize_collection_name("   ")


def test_slugify_collection_name():
    assert slugify_collection_name("Our Approved MCP Servers!") == "our-approved-mcp-servers"


def test_normalize_collection_slug_derives_from_name():
    assert normalize_collection_slug(None, fallback_name="Geo Tools") == "geo-tools"


def test_normalize_collection_slug_rejects_invalid():
    with pytest.raises(CollectionValidationError, match="lowercase"):
        normalize_collection_slug("Bad Slug!")


def test_normalize_collection_description_optional():
    assert normalize_collection_description(None) is None
    assert normalize_collection_description("  ") is None
    assert normalize_collection_description("  Curated list  ") == "Curated list"


def test_normalize_collection_member_ids_dedupes():
    ids = normalize_collection_member_ids(["a", "b", "a"])
    assert ids == ["a", "b"]


def test_normalize_collection_member_ids_rejects_non_array():
    with pytest.raises(CollectionValidationError, match="array"):
        normalize_collection_member_ids("bad")


def test_normalize_collection_member_ids_caps_size():
    with pytest.raises(CollectionValidationError, match=str(MAX_COLLECTION_MEMBERS)):
        normalize_collection_member_ids([str(i) for i in range(MAX_COLLECTION_MEMBERS + 1)])


def test_merge_member_ids_preserves_order():
    assert merge_member_ids(["a", "b"], ["c", "a"]) == ["a", "b", "c"]

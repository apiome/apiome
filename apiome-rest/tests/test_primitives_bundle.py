"""Unit tests for the Apiome type-definition bundle importer (#3462).

Covers :mod:`app.primitives_bundle` — expanding a parsed ``.json`` bundle document and a
``.zip`` archive into discrete interlinked types, capturing inter-type ``$ref`` edges,
validating each fragment, and raising a clear :class:`BundleError` for a malformed bundle.
These are pure (no network/DB), so they assert the parsed types, internal refs, warnings,
and errors directly.
"""

import io
import zipfile

import pytest

from app.primitives_bundle import (
    BundleError,
    build_bundle_internal_ref_edges,
    bundle_internal_ref_target,
    expand_zip_bundle,
    parse_type_def_bundle,
)

# ===========================================================================
# inter-type ref capture
# ===========================================================================


def test_bundle_ref_target_recognizes_types_container():
    assert bundle_internal_ref_target("#/types/Money") == "Money"
    assert bundle_internal_ref_target("#/types/Money/properties/c") == "Money"


def test_bundle_ref_target_recognizes_defs_and_definitions():
    # Reuses the parser's $defs / definitions handling (#3461).
    assert bundle_internal_ref_target("#/$defs/Date") == "Date"
    assert bundle_internal_ref_target("#/definitions/Date") == "Date"


def test_bundle_ref_target_ignores_registry_and_external_refs():
    assert bundle_internal_ref_target("../primitives/string") is None
    assert bundle_internal_ref_target("https://example.com/x") is None
    assert bundle_internal_ref_target("#/properties/x") is None
    assert bundle_internal_ref_target(None) is None


def test_build_bundle_internal_ref_edges_dedupes_in_order():
    schema = {
        "properties": {
            "a": {"$ref": "#/types/Money"},
            "b": {"$ref": "#/types/Money"},  # duplicate — recorded once
            "c": {"$ref": "../primitives/string"},  # not internal
        }
    }
    edges = build_bundle_internal_ref_edges(schema)
    assert edges == [
        {"relative_ref": "#/types/Money", "resolved_target": "Money", "status": "internal"}
    ]


# ===========================================================================
# parse_type_def_bundle — happy path
# ===========================================================================


def test_bundle_of_n_types_expands_with_refs_intact():
    """A bundle of N interlinked types yields N parsed types, refs captured (the AC)."""
    bundle = {
        "types": {
            "Order": {
                "type": "object",
                "properties": {"line": {"$ref": "#/types/Line"}},
            },
            "Line": {
                "type": "object",
                "properties": {"price": {"$ref": "../primitives/number"}},
            },
        }
    }
    types, warnings = parse_type_def_bundle(bundle)
    assert [t.name for t in types] == ["Order", "Line"]
    by_name = {t.name: t for t in types}
    assert by_name["Order"].pointer == "#/types/Order"
    # Inter-type ref captured as an internal edge for rewrite (#3463).
    assert by_name["Order"].internal_refs == [
        {"relative_ref": "#/types/Line", "resolved_target": "Line", "status": "internal"}
    ]
    # A registry-relative ref is left for the resolver — not an internal edge.
    assert by_name["Line"].internal_refs == []
    assert warnings == []


def test_bundle_accepts_defs_container_as_equivalent():
    types, _ = parse_type_def_bundle({"$defs": {"A": {"type": "string"}}})
    assert types[0].name == "A"
    assert types[0].pointer == "#/$defs/A"


def test_bundle_prefers_types_container_over_defs():
    bundle = {"types": {"A": {"type": "string"}}, "$defs": {"B": {"type": "string"}}}
    types, _ = parse_type_def_bundle(bundle)
    assert [t.name for t in types] == ["A"]


def test_bundle_per_type_validation_report():
    bundle = {"types": {"Good": {"type": "object"}, "Bad": {"type": "stringg"}}}
    types, _ = parse_type_def_bundle(bundle)
    by_name = {t.name: t for t in types}
    assert by_name["Good"].valid is True
    assert by_name["Bad"].valid is False
    assert by_name["Bad"].validation_errors


def test_bundle_dangling_inter_type_ref_warns():
    bundle = {"types": {"Order": {"properties": {"l": {"$ref": "#/types/Missing"}}}}}
    types, warnings = parse_type_def_bundle(bundle)
    assert len(types) == 1
    assert warnings and "Missing" in warnings[0]


def test_bundle_non_object_entry_is_skipped_with_warning():
    bundle = {"types": {"Good": {"type": "object"}, "Bad": "not-a-schema"}}
    types, warnings = parse_type_def_bundle(bundle)
    assert [t.name for t in types] == ["Good"]
    assert warnings and "Bad" in warnings[0]


# ===========================================================================
# parse_type_def_bundle — malformed bundle errors (clear messages)
# ===========================================================================


def test_bundle_not_a_mapping_raises():
    with pytest.raises(BundleError, match="top level"):
        parse_type_def_bundle(["not", "a", "mapping"])


def test_bundle_without_container_raises():
    with pytest.raises(BundleError, match="no 'types'"):
        parse_type_def_bundle({"meta": "x"}, source_label="b.json")


def test_bundle_with_only_unusable_entries_raises():
    with pytest.raises(BundleError, match="no usable type"):
        parse_type_def_bundle({"types": {"Bad": "x"}})


# ===========================================================================
# expand_zip_bundle — .zip archive of per-type files
# ===========================================================================


def _zip_bytes(members: dict) -> bytes:
    """Build an in-memory .zip from a ``{filename: text}`` mapping."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, text in members.items():
            zf.writestr(filename, text)
    return buf.getvalue()


def test_expand_zip_bundle_merges_members_into_types():
    raw = _zip_bytes(
        {
            "money.json": '{"type": "object", "properties": {"c": {"$ref": "#/types/currency"}}}',
            "currency.yaml": "type: string\n",
            "README.md": "ignored",  # non-JSON/YAML member is skipped
        }
    )
    doc = expand_zip_bundle(raw, source_label="bundle.zip")
    assert set(doc["types"]) == {"money", "currency"}
    # The merged document round-trips through the bundle parser with refs intact.
    types, warnings = parse_type_def_bundle(doc)
    assert {t.name for t in types} == {"money", "currency"}
    by_name = {t.name: t for t in types}
    assert by_name["money"].internal_refs[0]["resolved_target"] == "currency"
    assert warnings == []


def test_expand_zip_bundle_ignores_macosx_and_dotfiles():
    raw = _zip_bytes(
        {
            "types/order.json": '{"type": "object"}',
            "__MACOSX/types/._order.json": "junk",
            ".DS_Store": "junk",
        }
    )
    doc = expand_zip_bundle(raw)
    assert list(doc["types"]) == ["order"]


def test_expand_zip_bundle_rejects_bad_zip():
    with pytest.raises(BundleError, match="valid .zip"):
        expand_zip_bundle(b"not a zip file")


def test_expand_zip_bundle_rejects_duplicate_type_names():
    raw = _zip_bytes({"a/money.json": "{}", "b/money.json": "{}"})
    with pytest.raises(BundleError, match="more than once"):
        expand_zip_bundle(raw)


def test_expand_zip_bundle_rejects_non_mapping_member():
    raw = _zip_bytes({"money.json": "[1, 2, 3]"})
    with pytest.raises(BundleError, match="must be a JSON object"):
        expand_zip_bundle(raw)


def test_expand_zip_bundle_rejects_empty_archive():
    raw = _zip_bytes({"README.md": "no types here"})
    with pytest.raises(BundleError, match="no .json/.yaml"):
        expand_zip_bundle(raw)


def test_expand_zip_bundle_enforces_size_cap():
    raw = _zip_bytes({"big.json": "{}" + " " * 5000})
    with pytest.raises(BundleError, match="uncompressed limit"):
        expand_zip_bundle(raw, max_bytes=100)

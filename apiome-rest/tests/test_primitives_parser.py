"""Unit tests for the JSON Schema 2020-12 parser (#3461).

Covers :mod:`app.primitives_parser`: turning a document into discrete types
(``$defs`` bundle + single root), capturing intra-document ``#/$defs`` refs as
``internal`` edges for the rewrite stage (#3463), per-type draft 2020-12 validation,
and dangling-internal-ref warnings. Pure (no network/DB), so it asserts the parsed
types directly.
"""

from app.primitives_parser import (
    STATUS_INTERNAL,
    build_internal_ref_edges,
    derive_single_name,
    internal_ref_target,
    parse_json_schema_document,
)

# ===========================================================================
# internal_ref_target — which $refs are intra-document definitions refs
# ===========================================================================


def test_internal_ref_target_defs_and_definitions():
    assert internal_ref_target("#/$defs/Money") == "Money"
    assert internal_ref_target("#/definitions/Money") == "Money"
    # A pointer into a nested member resolves to the owning definition name.
    assert internal_ref_target("#/$defs/Money/properties/amount") == "Money"


def test_internal_ref_target_decodes_pointer_escapes():
    # %20 -> space, ~1 -> '/', ~0 -> '~' (RFC 6901 + percent-decoding).
    assert internal_ref_target("#/$defs/Postal%20Code") == "Postal Code"
    assert internal_ref_target("#/$defs/a~1b") == "a/b"
    assert internal_ref_target("#/$defs/a~0b") == "a~b"


def test_internal_ref_target_non_internal_refs_are_none():
    assert internal_ref_target("../primitives/string") is None  # registry-relative
    assert internal_ref_target("https://example.com/x") is None  # absolute
    assert internal_ref_target("#") is None  # bare root ref
    assert internal_ref_target("#/properties/x") is None  # not a definitions container
    assert internal_ref_target("#/$defs/") is None  # empty target segment


# ===========================================================================
# build_internal_ref_edges — capture for rewrite (#3463)
# ===========================================================================


def test_build_internal_ref_edges_captures_defs_refs_only():
    schema = {
        "type": "object",
        "properties": {
            "amount": {"$ref": "#/$defs/Money"},
            "currency": {"$ref": "../primitives/string"},  # registry, not internal
            "nested": {"items": {"$ref": "#/definitions/Code"}},
        },
    }
    edges = build_internal_ref_edges(schema)
    assert edges == [
        {"relative_ref": "#/$defs/Money", "resolved_target": "Money", "status": STATUS_INTERNAL},
        {"relative_ref": "#/definitions/Code", "resolved_target": "Code", "status": STATUS_INTERNAL},
    ]


def test_build_internal_ref_edges_dedupes_in_document_order():
    schema = {
        "anyOf": [{"$ref": "#/$defs/B"}, {"$ref": "#/$defs/A"}, {"$ref": "#/$defs/B"}],
    }
    edges = build_internal_ref_edges(schema)
    assert [e["resolved_target"] for e in edges] == ["B", "A"]


def test_build_internal_ref_edges_empty_when_no_internal_refs():
    assert build_internal_ref_edges({"type": "string"}) == []
    assert build_internal_ref_edges(True) == []  # boolean schema, no refs


# ===========================================================================
# parse_json_schema_document — $defs bundle
# ===========================================================================


def test_three_defs_yield_three_types_with_internal_refs_captured():
    """Acceptance criterion: a doc with 3 $defs yields 3 types with internal refs."""
    doc = {
        "$defs": {
            "Money": {
                "type": "object",
                "properties": {"currency": {"$ref": "#/$defs/Currency"}},
            },
            "Currency": {"type": "string"},
            "Invoice": {
                "type": "object",
                "properties": {"total": {"$ref": "#/$defs/Money"}},
            },
        }
    }
    types, warnings = parse_json_schema_document(doc)
    assert warnings == []
    assert len(types) == 3

    by_name = {t.name: t for t in types}
    assert by_name["Money"].pointer == "#/$defs/Money"
    assert by_name["Money"].internal_refs == [
        {"relative_ref": "#/$defs/Currency", "resolved_target": "Currency", "status": STATUS_INTERNAL}
    ]
    assert by_name["Invoice"].internal_refs[0]["resolved_target"] == "Money"
    assert by_name["Currency"].internal_refs == []
    # The fragment itself is retained for rewrite/persist.
    assert by_name["Currency"].schema == {"type": "string"}


def test_legacy_definitions_are_parsed():
    doc = {"definitions": {"A": {"type": "string"}, "B": {"$ref": "#/definitions/A"}}}
    types, warnings = parse_json_schema_document(doc)
    assert {t.name for t in types} == {"A", "B"}
    assert warnings == []
    b = next(t for t in types if t.name == "B")
    assert b.pointer == "#/definitions/B"
    assert b.internal_refs[0]["resolved_target"] == "A"


def test_dangling_internal_ref_warns():
    doc = {"$defs": {"Money": {"properties": {"c": {"$ref": "#/$defs/Missing"}}}}}
    types, warnings = parse_json_schema_document(doc)
    # The edge is still captured (the rewrite stage needs it), but a warning flags it.
    assert types[0].internal_refs[0]["resolved_target"] == "Missing"
    assert warnings and "Missing" in warnings[0] and "Money" in warnings[0]


# ===========================================================================
# parse_json_schema_document — per-type validation report
# ===========================================================================


def test_per_type_validation_report():
    doc = {"$defs": {"Good": {"type": "string"}, "Bad": {"type": "stringg"}}}
    types, _ = parse_json_schema_document(doc)
    by_name = {t.name: t for t in types}
    assert by_name["Good"].valid is True
    assert by_name["Good"].validation_errors == []
    assert by_name["Bad"].valid is False
    assert by_name["Bad"].validation_errors[0]["path"] == "type"


def test_candidate_dict_carries_report_and_refs():
    doc = {"$defs": {"Money": {"properties": {"c": {"$ref": "#/$defs/Money"}}}}}
    types, _ = parse_json_schema_document(doc)
    d = types[0].as_candidate_dict()
    assert d["name"] == "Money"
    assert d["pointer"] == "#/$defs/Money"
    assert d["ref_count"] == 1
    assert d["valid"] is True
    assert d["internal_refs"][0]["resolved_target"] == "Money"
    assert d["validation_errors"] == []


# ===========================================================================
# parse_json_schema_document — single-root document
# ===========================================================================


def test_single_root_document_is_one_type():
    doc = {"type": "object", "title": "Customer", "properties": {"id": {"type": "string"}}}
    types, warnings = parse_json_schema_document(doc)
    assert len(types) == 1
    assert types[0].name == "Customer"
    assert types[0].pointer == "#"
    assert types[0].internal_refs == []
    assert types[0].valid is True
    assert warnings == []


def test_single_root_name_falls_back_to_id_then_label():
    by_id = parse_json_schema_document({"$id": "https://x.dev/types/widget"})[0][0]
    assert by_id.name == "widget"
    by_label = parse_json_schema_document({"type": "object"}, source_label="a/b/thing.json")[0][0]
    assert by_label.name == "thing"
    fallback = parse_json_schema_document({"type": "object"})[0][0]
    assert fallback.name == "document"


def test_derive_single_name_prefers_title():
    assert derive_single_name({"title": "  Money  ", "$id": "x/y"}, None) == "Money"

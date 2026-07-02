"""Tests for the GraphQL SDL parse + build-schema service (MFI-10.1, #3770).

``graphql-core`` is a first-class Python dependency (no Node toolchain), so every test runs the
real parser/builder — there is no gated "real tool" tier as the AsyncAPI suite has. The suite
covers the three acceptance criteria — *valid SDL builds*, *invalid reports errors*, *multi-file
merges* — plus the merge semantics (field union, ``extend`` blocks, conflict detection), root
operation capture, the result-model surface, and the build-or-raise helpers.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from app.graphql_parser import (
    GraphQlDiagnostic,
    GraphQlParseError,
    GraphQlParseResult,
    GraphQlRootOperations,
    GraphQlSource,
    GraphQlSourceLocation,
    build_graphql_schema,
    build_schema_from_sources,
    parse_graphql,
    parse_graphql_sources,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "graphql"


# ===========================================================================
# Valid SDL builds
# ===========================================================================


def test_valid_single_document_builds_with_roots_and_types() -> None:
    result = parse_graphql(
        """
        type Query { hello: String, user(id: ID!): User }
        type Mutation { setName(name: String!): User }
        type User { id: ID!, name: String }
        """
    )
    assert result.ok is True
    assert result.errors == []
    assert result.root_operations.query == "Query"
    assert result.root_operations.mutation == "Mutation"
    assert result.root_operations.subscription is None
    # User-defined types are captured; built-in scalars / introspection types are not.
    assert "User" in result.type_names
    assert "String" not in result.type_names
    assert not any(n.startswith("__") for n in result.type_names)
    # The canonical SDL is re-printed from the built schema.
    assert "type User" in result.sdl


def test_subscription_root_is_captured() -> None:
    result = parse_graphql(
        "type Query { a: Int } type Subscription { ticks: Int }"
    )
    assert result.ok is True
    assert result.root_operations.subscription == "Subscription"


def test_custom_root_operation_type_names_are_captured() -> None:
    # GraphQL permits renaming the roots via a schema definition.
    result = parse_graphql(
        """
        schema { query: RootQuery, mutation: RootMutation }
        type RootQuery { a: String }
        type RootMutation { b: String }
        """
    )
    assert result.ok is True
    assert result.root_operations == GraphQlRootOperations(
        query="RootQuery", mutation="RootMutation", subscription=None
    )


def test_canonical_sdl_round_trips_into_an_identical_schema() -> None:
    result = parse_graphql(
        "type Query { post(id: ID!): Post } type Post { id: ID!, title: String! }"
    )
    assert result.ok is True
    # The canonical SDL re-parses, and re-printing it is a fixed point (deterministic output).
    reparsed = parse_graphql(result.sdl)
    assert reparsed.ok is True
    assert reparsed.sdl == result.sdl


def test_all_named_type_kinds_are_reported() -> None:
    result = parse_graphql(
        """
        type Query { node: Node }
        interface Node { id: ID! }
        type Thing implements Node { id: ID!, kind: Kind }
        enum Kind { A B }
        union Any = Thing
        input Filter { kind: Kind }
        scalar DateTime
        """
    )
    assert result.ok is True
    for name in ("Node", "Thing", "Kind", "Any", "Filter", "DateTime"):
        assert name in result.type_names


# ===========================================================================
# Invalid SDL reports errors (without raising)
# ===========================================================================


def test_unknown_type_reports_error_without_raising() -> None:
    result = parse_graphql("type Query { a: Missing }")
    assert result.ok is False
    assert result.sdl is None
    assert result.type_names == []
    assert result.root_operations == GraphQlRootOperations()
    assert any("Missing" in d.message for d in result.errors)


def test_syntax_error_is_reported_with_source_and_location() -> None:
    result = parse_graphql("type Query {", source_label="broken.graphql")
    assert result.ok is False
    assert len(result.errors) == 1
    err = result.errors[0]
    assert "Syntax Error" in err.message
    assert err.source == "broken.graphql"
    # graphql-core points at the position the parse failed.
    assert err.locations and isinstance(err.locations[0], GraphQlSourceLocation)
    assert err.locations[0].line == 1


def test_missing_query_root_reports_error() -> None:
    # A schema with no Query root is invalid per the GraphQL spec.
    result = parse_graphql("type Foo { a: String }")
    assert result.ok is False
    assert any("Query root" in d.message for d in result.errors)


def test_duplicate_field_in_one_document_reports_error() -> None:
    result = parse_graphql("type Query { a: String, a: Int }")
    assert result.ok is False
    assert any("a" in d.message for d in result.errors)


def test_invalid_interface_implementation_reports_error() -> None:
    # Thing claims to implement Node but omits the required `id` field.
    result = parse_graphql(
        """
        type Query { node: Node }
        interface Node { id: ID! }
        type Thing implements Node { name: String }
        """
    )
    assert result.ok is False
    assert result.errors


def test_empty_input_reports_error() -> None:
    assert parse_graphql("").ok is False
    assert parse_graphql_sources([]).ok is False
    assert any(
        "No GraphQL SDL" in d.message for d in parse_graphql_sources(["   \n  "]).errors
    )


# ===========================================================================
# Multi-file merge (graphql-tools semantics)
# ===========================================================================


def test_multi_file_distinct_types_and_extend_block_merge() -> None:
    result = parse_graphql_sources(
        [
            ("query.graphql", "type Query { a: String }"),
            ("ext.graphql", "extend type Query { b: Int }"),
            ("types.graphql", "type User { id: ID! }"),
        ]
    )
    assert result.ok is True
    assert "User" in result.type_names
    # The extend block's field is folded into the single Query type.
    assert "a: String" in result.sdl
    assert "b: Int" in result.sdl
    assert result.sdl.count("type Query {") == 1


def test_multi_file_same_type_fields_are_unioned() -> None:
    # graphql-tools mergeTypeDefs: the same type declared in two files has its fields unioned.
    result = parse_graphql_sources(
        [
            ("a", "type Query { ping: String }\ntype User { id: ID! }"),
            ("b", "type User { name: String }\ntype Query { pong: Int }"),
        ]
    )
    assert result.ok is True
    assert result.sdl.count("type User {") == 1
    assert "id: ID!" in result.sdl
    assert "name: String" in result.sdl
    # Both Query contributions survive the merge too.
    assert "ping: String" in result.sdl
    assert "pong: Int" in result.sdl


def test_multi_file_enum_values_and_union_members_are_unioned() -> None:
    result = parse_graphql_sources(
        [
            ("a", "type Query { a: Color } enum Color { RED } union Shape = Circle type Circle { r: Int }"),
            ("b", "enum Color { GREEN } union Shape = Square type Square { s: Int }"),
        ]
    )
    assert result.ok is True
    assert "RED" in result.sdl and "GREEN" in result.sdl
    assert "Circle" in result.sdl and "Square" in result.sdl


def test_conflicting_field_types_across_files_report_error() -> None:
    result = parse_graphql_sources(
        [
            ("a", "type Query { a: String }\ntype User { id: ID! }"),
            ("b", "type User { id: Int }"),
        ]
    )
    assert result.ok is False
    assert any("conflicting" in d.message.lower() for d in result.errors)
    assert any('"ID!"' in d.message and '"Int"' in d.message for d in result.errors)


def test_identical_redeclared_field_is_not_a_conflict() -> None:
    # Re-declaring a field with the *same* type across files is harmless and merges cleanly.
    result = parse_graphql_sources(
        [
            ("a", "type Query { a: String }\ntype User { id: ID! }"),
            ("b", "type User { id: ID! name: String }"),
        ]
    )
    assert result.ok is True
    assert result.sdl.count("type User {") == 1
    assert "name: String" in result.sdl


def test_syntax_error_in_one_file_attributes_that_file() -> None:
    result = parse_graphql_sources(
        [
            ("good.graphql", "type Query { a: String }"),
            ("bad.graphql", "type User { "),
        ]
    )
    assert result.ok is False
    assert any(d.source == "bad.graphql" for d in result.errors)


def test_same_name_different_kind_across_files_is_reported_not_merged() -> None:
    # One file's `Thing` is an object, another's is a scalar — a real conflict validate_sdl flags.
    result = parse_graphql_sources(
        [
            ("a", "type Query { a: Thing }\ntype Thing { id: ID! }"),
            ("b", "scalar Thing"),
        ]
    )
    assert result.ok is False
    assert result.errors


# ===========================================================================
# Fixtures: a realistic multi-file schema split
# ===========================================================================


def _fixture_sources(*names: str) -> List[GraphQlSource]:
    return [GraphQlSource(label=n, text=(_FIXTURES / n).read_text()) for n in names]


def test_fixture_multi_file_blog_schema_builds() -> None:
    result = parse_graphql_sources(
        _fixture_sources(
            "schema.query.graphql",
            "schema.types.graphql",
            "schema.mutation.graphql",
        )
    )
    assert result.ok is True
    assert result.root_operations.query == "Query"
    assert result.root_operations.mutation == "Mutation"
    for name in ("Post", "Author", "PostStatus", "CreatePostInput"):
        assert name in result.type_names
    # The `extend type Query { authors }` block from the mutation file is applied.
    assert "authors" in result.sdl


def test_fixture_invalid_unknown_type_reports_error() -> None:
    raw = (_FIXTURES / "invalid_unknown_type.graphql").read_text()
    result = parse_graphql(raw, source_label="invalid_unknown_type.graphql")
    assert result.ok is False
    assert any("Widget" in d.message for d in result.errors)


# ===========================================================================
# Source coercion
# ===========================================================================


def test_sources_accept_strings_pairs_and_models() -> None:
    result = parse_graphql_sources(
        [
            "type Query { a: String }",  # bare string
            ("two.graphql", "type A { x: Int }"),  # (label, text) pair
            GraphQlSource(label="three.graphql", text="type B { y: Int }"),  # model
        ]
    )
    assert result.ok is True
    assert {"A", "B"} <= set(result.type_names)


# ===========================================================================
# Build-or-raise helpers
# ===========================================================================


def test_build_graphql_schema_returns_live_schema() -> None:
    schema = build_graphql_schema("type Query { hello: String }")
    assert schema.query_type is not None
    assert schema.query_type.name == "Query"
    assert "hello" in schema.query_type.fields


def test_build_graphql_schema_raises_on_invalid_with_diagnostics() -> None:
    with pytest.raises(GraphQlParseError) as exc:
        build_graphql_schema("type Query { a: Missing }")
    assert "Missing" in str(exc.value)
    assert exc.value.diagnostics and exc.value.diagnostics[0].is_error


def test_build_schema_from_sources_merges_then_builds() -> None:
    schema = build_schema_from_sources(
        [
            ("a", "type Query { a: A }"),
            ("b", "type A { id: ID! }"),
        ]
    )
    assert "A" in schema.type_map
    assert schema.query_type.fields["a"].type.name == "A"


# ===========================================================================
# raise_if_invalid + result-model surface
# ===========================================================================


def test_raise_if_invalid_returns_self_when_valid() -> None:
    result = parse_graphql("type Query { a: String }")
    assert result.raise_if_invalid() is result


def test_raise_if_invalid_raises_with_first_error_message() -> None:
    result = parse_graphql("type Query { a: Missing }")
    with pytest.raises(GraphQlParseError) as exc:
        result.raise_if_invalid()
    assert "Missing" in str(exc.value)
    assert exc.value.diagnostics


def test_raise_if_invalid_includes_source_location_for_syntax_errors() -> None:
    # Two description strings back-to-back (a leftover/duplicate description not immediately
    # followed by a definition) is invalid SDL; the surfaced message must carry the line/column
    # so the offending token is findable in a large document.
    sdl = '"""old desc"""\n"Custom scalar for date/time"\nscalar DateTime\ntype Query { a: String }'
    result = parse_graphql(sdl)
    with pytest.raises(GraphQlParseError) as exc:
        result.raise_if_invalid()
    message = str(exc.value)
    assert "Unexpected String" in message
    assert "line 1" in message and "column" in message
    # The precise location is also preserved structurally on the diagnostics.
    assert exc.value.diagnostics[0].locations


def test_errors_property_filters_to_error_severity() -> None:
    result = GraphQlParseResult(
        ok=False,
        diagnostics=[
            GraphQlDiagnostic(severity="error", message="boom"),
            GraphQlDiagnostic(severity="info", message="fyi"),
        ],
    )
    assert [d.message for d in result.errors] == ["boom"]


def test_result_is_serializable_round_trip() -> None:
    result = parse_graphql("type Query { a: String }")
    dumped = result.model_dump()
    restored = GraphQlParseResult.model_validate(dumped)
    assert restored.ok is True
    assert restored.sdl == result.sdl
    assert restored.root_operations.query == "Query"


def test_diagnostic_is_error_flag() -> None:
    assert GraphQlDiagnostic(message="x").is_error is True
    assert GraphQlDiagnostic(severity="info", message="x").is_error is False

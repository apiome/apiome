"""Tests for the format lint capability matrix (CLX-2.4, #4854)."""

from __future__ import annotations

from app.format_lint_capabilities import (
    MODE_ADAPTED,
    MODE_NATIVE,
    MODE_UNSUPPORTED,
    RELATED_FORMAT_LINT_ISSUES,
    build_format_lint_capabilities,
    capability_for_format,
    expected_scanners_for_catalog_format,
    normalize_format_key,
)
from app.lint_evidence import NATIVE_SCANNER_ID


def test_matrix_covers_planned_formats_with_linked_issues():
    rows = {r.format: r for r in build_format_lint_capabilities()}
    for fmt, issues in (
        ("smithy", RELATED_FORMAT_LINT_ISSUES["smithy"]),
        ("raml", RELATED_FORMAT_LINT_ISSUES["raml"]),
        ("typespec", RELATED_FORMAT_LINT_ISSUES["typespec"]),
        ("avro", RELATED_FORMAT_LINT_ISSUES["avro"]),
        ("odata", RELATED_FORMAT_LINT_ISSUES["odata"]),
        ("apiblueprint", RELATED_FORMAT_LINT_ISSUES["apiblueprint"]),
        ("wsdl", RELATED_FORMAT_LINT_ISSUES["wsdl"]),
    ):
        assert fmt in rows
        row = rows[fmt]
        assert row.mode == MODE_UNSUPPORTED
        assert row.related_issues == issues
        assert all("github.com/apiome/apiome/issues/" in u for u in row.related_issues)


def test_every_row_has_valid_mode():
    for row in build_format_lint_capabilities():
        assert row.mode in (MODE_NATIVE, MODE_ADAPTED, MODE_UNSUPPORTED)
        assert row.format
        if row.mode == MODE_NATIVE:
            assert row.native_pack
        if row.mode == MODE_ADAPTED:
            assert row.adapted_scanners
        if row.mode == MODE_UNSUPPORTED and row.format in RELATED_FORMAT_LINT_ISSUES:
            assert row.related_issues


def test_native_formats_with_adapters():
    protobuf = capability_for_format("protobuf")
    assert protobuf.mode == MODE_NATIVE
    assert "buf.lint" in protobuf.adapted_scanners

    graphql = capability_for_format("graphql")
    assert graphql.mode == MODE_NATIVE
    assert "graphql.eslint" in graphql.adapted_scanners

    openapi = capability_for_format("openapi-3.1")
    assert openapi.mode == MODE_NATIVE
    assert openapi.native_pack == "openapi-schema-lint"
    assert any(s.startswith("spectral") or s.startswith("vacuum") or s.startswith("redocly")
               for s in openapi.adapted_scanners)


def test_normalize_aliases():
    assert normalize_format_key("api-blueprint") == "apiblueprint"
    assert normalize_format_key("grpc") == "protobuf"
    assert normalize_format_key("tsp") == "typespec"


def test_expected_scanners_include_adapters():
    scanners = expected_scanners_for_catalog_format("protobuf")
    assert scanners[0] == NATIVE_SCANNER_ID
    assert "buf.lint" in scanners

    gql = expected_scanners_for_catalog_format("graphql")
    assert "graphql.eslint" in gql

    bare = expected_scanners_for_catalog_format(None)
    assert bare == [NATIVE_SCANNER_ID]


def test_matrix_is_deterministic():
    a = [(r.format, r.mode) for r in build_format_lint_capabilities()]
    b = [(r.format, r.mode) for r in build_format_lint_capabilities()]
    assert a == b
    assert a == sorted(a, key=lambda t: t[0])

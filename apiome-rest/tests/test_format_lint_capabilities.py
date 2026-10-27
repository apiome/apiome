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


def test_every_planned_native_pack_has_shipped():
    # The planned-pack links (CLX-2.4) are gone once each format's pack ships; MFI-17.3 (#3810, Smithy)
    # was the last of them.
    assert RELATED_FORMAT_LINT_ISSUES == {}
    assert all(row.related_issues == () for row in build_format_lint_capabilities())


def test_smithy_has_a_native_pack_since_mfi_17_3():
    row = {r.format: r for r in build_format_lint_capabilities()}["smithy"]
    assert row.mode == MODE_NATIVE
    assert row.native_pack == "smithy"


def test_odata_has_a_native_pack_since_mfi_11_1():
    # MFI-11.1 (#3776) registered the `odata` pack (the OASIS CSDL schema rule); MFI-11.4 (#3779)
    # completed it (XML schema, reference and key rules), so no planned-pack issue is linked.
    row = {r.format: r for r in build_format_lint_capabilities()}["odata"]
    assert row.mode == MODE_NATIVE
    assert row.native_pack == "odata"
    assert row.related_issues == ()


def test_avro_has_a_native_pack_since_mfi_12_5():
    # MFI-12.5 (#3786) registered the `avro` pack, so no planned-pack issue is linked any more.
    row = {r.format: r for r in build_format_lint_capabilities()}["avro"]
    assert row.mode == MODE_NATIVE
    assert row.native_pack == "avro"
    assert row.related_issues == ()


def test_wsdl_has_a_native_pack_since_mfi_13_4():
    # MFI-13.4 (#3791) registered the WS-I pack under `wsdl`, so no planned-pack issue is linked.
    row = {r.format: r for r in build_format_lint_capabilities()}["wsdl"]
    assert row.mode == MODE_NATIVE
    assert row.native_pack == "wsdl"
    assert row.related_issues == ()


def test_typespec_has_a_native_pack_since_mfi_14_3():
    # MFI-14.3 (#3796) registered the `typespec` pack, so no planned-pack issue is linked any more.
    row = {r.format: r for r in build_format_lint_capabilities()}["typespec"]
    assert row.mode == MODE_NATIVE
    assert row.native_pack == "typespec"
    assert row.related_issues == ()


def test_raml_has_a_native_pack_since_mfi_15_3():
    # MFI-15.3 (#3801) registered the `raml` pack, so no planned-pack issue is linked any more.
    row = {r.format: r for r in build_format_lint_capabilities()}["raml"]
    assert row.mode == MODE_NATIVE
    assert row.native_pack == "raml"
    assert row.related_issues == ()


def test_apiblueprint_has_a_native_pack_since_mfi_16_3():
    # MFI-16.3 (#3806) registered the `apiblueprint` pack, so no planned-pack issue is linked any more.
    row = {r.format: r for r in build_format_lint_capabilities()}["apiblueprint"]
    assert row.mode == MODE_NATIVE
    assert row.native_pack == "apiblueprint"
    assert row.related_issues == ()


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

"""Tests for the Apache Thrift lint pack — MFI-19.3 (#3981)."""

from __future__ import annotations

from typing import List, Tuple

from app.format_lint_capabilities import MODE_NATIVE, capability_for_format
from app.lint_engine import get_rule_pack, lint_canonical_model
from app.thrift_normalizer import ThriftNormalizer
from app.thrift_parser import parse_thrift


def _thrift_findings(text: str) -> List[Tuple[str, str, str]]:
    """``(rule, severity, path)`` of every ``thrift.*`` finding for a document."""
    api = ThriftNormalizer().normalize(parse_thrift(text), include_raw=False)
    result = lint_canonical_model(api)
    return sorted((f.rule, f.severity, f.path) for f in result.findings if f.rule.startswith("thrift."))


def test_the_pack_is_registered_for_thrift():
    assert get_rule_pack("thrift") is not None


def test_a_clean_document_has_no_thrift_findings():
    assert _thrift_findings(
        "namespace java a.v1\nenum E { A = 1, B = 2 }\nstruct S { 1: optional E e }\n"
        "service X {\n  S get(1: string id) throws (1: S err)\n  oneway void fire(1: string id)\n}\n"
    ) == []


def test_namespace_declared():
    assert ("thrift.namespace-declared", "info", "namespace") in _thrift_findings("struct S { 1: i32 x }")


def test_field_no_required():
    assert _thrift_findings("namespace java a\nstruct S { 1: required i32 x }") == [
        ("thrift.field-no-required", "warning", "types.a.S.fields.a.S.x")
    ]


def test_unique_field_ids_in_structs_parameters_and_throws():
    findings = _thrift_findings(
        "namespace java a\nstruct S { 1: optional i32 x, 1: optional i32 y }\n"
        "service X {\n  void put(1: string a, 1: string b) throws (2: S e1, 2: S e2)\n}\n"
    )
    assert [(rule, severity, path) for rule, severity, path in findings] == [
        ("thrift.unique-field-ids", "error", "services.a.X.operations.a.X.put"),
        ("thrift.unique-field-ids", "error", "services.a.X.operations.a.X.put"),
        ("thrift.unique-field-ids", "error", "types.a.S"),
    ]


def test_enum_explicit_values():
    findings = _thrift_findings("namespace java a\nenum E { A, B = 5 }\n")
    assert findings == [("thrift.enum-explicit-values", "warning", "types.a.E.enum_values.a.E.A")]


def test_oneway_void():
    findings = _thrift_findings("namespace java a\nservice X {\n  oneway string bad()\n}\n")
    assert findings == [("thrift.oneway-void", "error", "services.a.X.operations.a.X.bad")]


def test_the_capability_matrix_reports_a_native_pack():
    row = capability_for_format("thrift")
    assert row.mode == MODE_NATIVE
    assert row.native_pack == "thrift"

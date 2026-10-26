"""Tests for the Apache Thrift breaking-change classifier — MFI-19.3 (#3981)."""

from __future__ import annotations

from typing import Dict, Tuple

from app.breaking_change import Severity, available_breaking_change_formats, classify_models
from app.thrift_normalizer import ThriftNormalizer
from app.thrift_parser import parse_thrift


def _api(body: str):
    """A one-struct Thrift API (namespace ``a``)."""
    return ThriftNormalizer().normalize(parse_thrift(f"namespace java a\n{body}\n"), include_raw=False)


def _grades(base: str, target: str) -> Dict[Tuple[str, str], Tuple[Severity, str]]:
    """``(kind, key)`` → ``(severity, rule_id)`` for the diff of two struct bodies."""
    result = classify_models(_api(base), _api(target))
    assert result.classifier == "thrift-field-id"
    return {(c.kind.value, c.key): (c.severity, c.rule_id) for c in result.classifications}


def test_the_classifier_is_registered_for_thrift():
    assert "thrift" in available_breaking_change_formats()


def test_a_rename_that_keeps_the_id_and_type_is_dangerous():
    grades = _grades("struct S {\n 1: optional string nick\n}", "struct S {\n 1: optional string nickname\n}")
    assert grades == {
        ("removed", "a.S.nick"): (Severity.DANGEROUS, "thrift.field-renamed"),
        ("added", "a.S.nickname"): (Severity.DANGEROUS, "thrift.field-renamed"),
    }


def test_a_rename_that_also_flips_requiredness_is_still_paired_by_id():
    grades = _grades("struct S {\n 1: optional string a\n}", "struct S {\n 1: required string b\n}")
    assert grades[("added", "a.S.b")] == (Severity.DANGEROUS, "thrift.field-renamed")


def test_an_id_reused_for_another_type_is_breaking():
    grades = _grades("struct S {\n 3: optional i32 age\n}", "struct S {\n 3: optional string label\n}")
    assert grades == {
        ("removed", "a.S.age"): (Severity.BREAKING, "thrift.field-id-reused"),
        ("added", "a.S.label"): (Severity.BREAKING, "thrift.field-id-reused"),
    }


def test_removals_depend_on_requiredness():
    grades = _grades(
        "struct S {\n 1: required string id,\n 2: optional string note,\n 3: string plain\n}",
        "struct S {\n 9: optional i32 other\n}",
    )
    assert grades[("removed", "a.S.id")] == (Severity.BREAKING, "thrift.required-field-removed")
    assert grades[("removed", "a.S.note")] == (Severity.DANGEROUS, "thrift.optional-field-removed")
    # A field with no requiredness keyword ("default") is optional on the wire.
    assert grades[("removed", "a.S.plain")] == (Severity.DANGEROUS, "thrift.optional-field-removed")
    assert grades[("added", "a.S.other")] == (Severity.SAFE, "thrift.optional-field-added")


def test_adding_a_required_field_is_breaking():
    grades = _grades(
        "struct S {\n 1: optional string a\n}",
        "struct S {\n 1: optional string a,\n 2: required i32 b\n}",
    )
    assert grades == {("added", "a.S.b"): (Severity.BREAKING, "thrift.required-field-added")}


def test_requiredness_flips():
    grades = _grades(
        "struct S {\n 1: optional string a,\n 2: required string b\n}",
        "struct S {\n 1: required string a,\n 2: optional string b\n}",
    )
    assert grades == {
        ("modified", "a.S.a"): (Severity.BREAKING, "thrift.made-required"),
        ("modified", "a.S.b"): (Severity.DANGEROUS, "thrift.made-optional"),
    }


def test_an_id_move_is_breaking():
    grades = _grades("struct S {\n 1: optional string a\n}", "struct S {\n 2: optional string a\n}")
    assert grades == {("modified", "a.S.a"): (Severity.BREAKING, "thrift.field-id-changed")}


def test_a_requiredness_flip_with_a_type_change_falls_back_to_the_baseline():
    grades = _grades("struct S {\n 1: optional string a\n}", "struct S {\n 1: required i32 a\n}")
    severity, rule_id = grades[("modified", "a.S.a")]
    assert severity is Severity.BREAKING
    assert not rule_id.startswith("thrift.")


def test_fields_of_different_structs_are_never_paired():
    grades = _grades(
        "struct A {\n 1: optional string x\n}\nstruct B {\n 2: optional string y\n}",
        "struct A {\n 2: optional string z\n}\nstruct B {\n 1: optional string w\n}",
    )
    assert grades[("removed", "a.A.x")] == (Severity.DANGEROUS, "thrift.optional-field-removed")
    assert grades[("added", "a.A.z")] == (Severity.SAFE, "thrift.optional-field-added")


def test_non_field_changes_use_the_baseline():
    result = classify_models(
        _api("struct S {\n 1: optional string a\n}\nservice X {\n string ping()\n}"),
        _api("struct S {\n 1: optional string a\n}"),
    )
    removed = [c for c in result.classifications if c.kind.value == "removed"]
    assert removed and all(c.severity is Severity.BREAKING and c.rule_id == "removed-entity" for c in removed)

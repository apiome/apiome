"""Tests for ASN.1 modules: complete normalization (tags, constraints, extensions, typedefs), lint and
breaking changes — MFI-21.5 (#3995)."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

import pytest

from app.asn1_breaking import RULE_IDS, Asn1BreakingChangeClassifier, grade_bounds
from app.asn1_emitter import Asn1Emitter
from app.asn1_import_source import Asn1ImportSource
from app.asn1_lint import Asn1RulePack, component_tag
from app.asn1_normalizer import resolved_tag
from app.asn1_parser import Asn1Tag, parse_asn1
from app.breaking_change import Severity, available_breaking_change_formats, classify_models
from app.canonical_model import TypeKind
from app.format_lint_capabilities import MODE_NATIVE, capability_for_format
from app.import_source import canonical_diff
from app.lint_engine import get_rule_pack, lint_canonical_model

_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLES = _ROOT / "apiome-ui" / "examples" / "asn1"
_VERSIONS = Path(__file__).parent / "fixtures" / "asn1_versions"


def _module(body: str, tags: str = "EXPLICIT") -> str:
    return f"M DEFINITIONS {tags} TAGS ::= BEGIN\n{body}\nEND\n"


def _api(text: str):
    adapter = Asn1ImportSource()
    return adapter.normalize(adapter.parse(text, source_label="t.asn1"), include_raw=False)


def _version(name: str):
    return _api((_VERSIONS / name).read_text(encoding="utf-8"))


def _types(api) -> Dict[str, object]:
    return {t.name: t for t in api.types}


def _fields(api, name: str) -> Dict[str, object]:
    return {f.name: f for f in _types(api)[name].fields}


def _findings(text: str, *, include_marker: bool = False) -> List[Tuple[str, str, str]]:
    result = lint_canonical_model(_api(text))
    return sorted(
        (f.rule, f.severity, f.path)
        for f in result.findings
        if f.rule.startswith("asn1.") and (include_marker or f.rule != "asn1.extension-marker")
    )


def _rules(text: str) -> set:
    return {rule for rule, _, _ in _findings(text)}


def _grades(base, target) -> Dict[Tuple[str, str], Tuple[Severity, str]]:
    result = classify_models(base, target)
    assert result.classifier == "asn1-encoding"
    return {(c.kind.value, c.key): (c.severity, c.rule_id) for c in result.classifications}


# --- parsing ---------------------------------------------------------------------------------


def test_tags_constraints_extensions_and_imports_are_read() -> None:
    doc = parse_asn1(
        "M DEFINITIONS AUTOMATIC TAGS ::= BEGIN\n"
        "IMPORTS Name FROM Other {1 2 3};\n"
        "A ::= SEQUENCE { a INTEGER (0..9), b [APPLICATION 3] IMPLICIT OCTET STRING (SIZE (4)), ...,"
        " c BOOLEAN OPTIONAL, [[ d INTEGER ]] }\n"
        "F ::= ENUMERATED { x, y, ..., z }\n"
        "END\n"
    )
    module = doc.module
    assert module.imports == (("Other", ("Name",)),)
    a = next(t for t in module.types if t.name == "A")
    assert a.extensible is True
    by_name = {m.name: m for m in a.members}
    assert by_name["a"].value_range == (0, 9)
    assert by_name["b"].tag == Asn1Tag(tag_class="APPLICATION", number=3, kind="IMPLICIT")
    assert by_name["b"].size == (4, 4)
    # Components after `...`, an `[[ … ]]` group included, are extension additions.
    assert [m.name for m in a.members if m.extension] == ["c", "d"]
    f = next(t for t in module.types if t.name == "F")
    assert [(v.name, v.extension) for v in f.enum_values] == [("x", False), ("y", False), ("z", True)]


# --- normalization ---------------------------------------------------------------------------


def test_scalar_list_and_reference_typedefs_import_as_aliases() -> None:
    api = _api((_EXAMPLES / "07-scalar-alias-typedefs.asn1").read_text(encoding="utf-8"))
    types = _types(api)
    host = types["HostName"]
    assert host.kind is TypeKind.ALIAS and host.aliased.name == "string"
    assert (host.constraints.min_length, host.constraints.max_length) == (1, 255)
    assert host.extras["asn1_type"] == "IA5String"
    assert types["SchemaVersion"].extras["asn1_named_numbers"] == {"initial": 0, "extended": 1}
    hosts = types["HostList"]
    assert hosts.kind is TypeKind.ALIAS and hosts.aliased.item.name == host.key
    ref = _types(_api(_module("A ::= SEQUENCE { a INTEGER }\nB ::= A")))["B"]
    assert ref.kind is TypeKind.ALIAS and ref.aliased.name == "M.A"


def test_components_keep_tags_ranges_defaults_and_declared_types() -> None:
    fields = _fields(_api((_EXAMPLES / "05-stress-grammar.asn1").read_text(encoding="utf-8")), "Envelope")
    ttl = fields["ttlSeconds"]
    assert (ttl.constraints.minimum, ttl.constraints.maximum, ttl.default) == (0, 86400, 3600)
    assert ttl.extras["asn1_tag"] == {"class": "CONTEXT", "number": 8, "kind": "EXPLICIT"}
    assert fields["contentType"].extras["asn1_type"] == "OBJECT IDENTIFIER"
    assert fields["flags"].extras["asn1_type"] == "BIT STRING"
    endpoint = _types(_api((_EXAMPLES / "05-stress-grammar.asn1").read_text(encoding="utf-8")))["Endpoint"]
    assert endpoint.extras["asn1_kind"] == "SET"


def test_a_tag_resolves_to_the_module_default_and_is_explicit_on_a_choice() -> None:
    tag = Asn1Tag(tag_class="CONTEXT", number=0)
    assert resolved_tag(tag, module_tags="EXPLICIT", choice=False)["kind"] == "EXPLICIT"
    assert resolved_tag(tag, module_tags="AUTOMATIC", choice=False)["kind"] == "IMPLICIT"
    assert resolved_tag(tag, module_tags="IMPLICIT", choice=True)["kind"] == "EXPLICIT"
    assert resolved_tag(None, module_tags="EXPLICIT", choice=False) is None


def test_extension_additions_and_extensibility_are_recorded() -> None:
    api = _version("subscriber.v1.asn1")
    subscriber = _types(api)["Subscriber"]
    assert subscriber.extras["asn1_extensible"] is True
    assert _fields(api, "Subscriber")["roaming"].extras["asn1_extension"] is True
    assert "asn1_extension" not in _fields(api, "Subscriber")["identity"].extras
    assert _types(api)["ServiceClass"].extras["asn1_extensible"] is True


def test_an_inline_constructed_component_becomes_a_named_type() -> None:
    api = _api(_module("G ::= SEQUENCE { inner SEQUENCE { z INTEGER }, pick CHOICE { a INTEGER, b BOOLEAN } }"))
    types = _types(api)
    assert types["GInner"].kind is TypeKind.RECORD
    assert types["GPick"].kind is TypeKind.UNION
    assert _fields(api, "G")["inner"].type.name == "M.GInner"


def test_choice_alternatives_keep_their_declared_built_in() -> None:
    api = _api((_EXAMPLES / "06-x509-certificate-shape.asn1").read_text(encoding="utf-8"))
    alternatives = _types(api)["Time"].extras["asn1_choice_members"]
    assert [a["asn1_type"] for a in alternatives] == ["UTCTime", "GeneralizedTime"]


def test_imports_are_kept() -> None:
    api = _api((_EXAMPLES / "04-imports-reuse.asn1").read_text(encoding="utf-8"))
    assert api.extras.get("asn1_imports")


# --- the emitter writes it back ----------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        _EXAMPLES / "05-stress-grammar.asn1",
        _EXAMPLES / "06-x509-certificate-shape.asn1",
        _EXAMPLES / "07-scalar-alias-typedefs.asn1",
        _VERSIONS / "subscriber.v1.asn1",
        _VERSIONS / "subscriber.v2-compatible.asn1",
        _VERSIONS / "subscriber.v3-breaking.asn1",
    ],
    ids=lambda p: p.name,
)
def test_tags_extensions_sets_and_built_ins_round_trip(path: Path) -> None:
    api = _api(path.read_text(encoding="utf-8"))
    again = _api(Asn1Emitter().emit(api).files[0].content)
    assert canonical_diff(api, again).entries == []


def test_the_written_module_keeps_tags_markers_and_string_types() -> None:
    text = Asn1Emitter().emit(_version("subscriber.v1.asn1")).files[0].content
    assert "Location ::= SET {" in text
    assert "imsi [0] IMPLICIT OCTET STRING (SIZE (3..8))" in text
    assert "msisdn [1] IMPLICIT NumericString (SIZE (1..15))" in text
    assert "ServiceClass ::= ENUMERATED { basic(0), premium(1), ... }" in text
    assert "    ...,\n    roaming [5] IMPLICIT BOOLEAN OPTIONAL" in text


# --- lint ------------------------------------------------------------------------------------


def test_the_pack_is_registered_and_native() -> None:
    assert get_rule_pack("asn1") is Asn1RulePack
    assert capability_for_format("asn1").mode == MODE_NATIVE
    ids = [rule.rule_id for rule in Asn1RulePack().rules()]
    assert len(ids) == len(set(ids)) == 8


@pytest.mark.parametrize("path", sorted(_EXAMPLES.glob("*.asn1")), ids=lambda p: p.name)
def test_the_corpus_raises_no_errors_or_warnings(path: Path) -> None:
    findings = _findings(path.read_text(encoding="utf-8"))
    assert [f for f in findings if f[1] != "info"] == []


def test_the_version_fixtures_raise_no_errors_or_warnings() -> None:
    for name in ("subscriber.v1.asn1", "subscriber.v2-compatible.asn1", "subscriber.v3-breaking.asn1"):
        findings = _findings((_VERSIONS / name).read_text(encoding="utf-8"))
        assert [f for f in findings if f[1] != "info"] == [], name


def test_unresolved_references_are_errors_but_imports_are_not() -> None:
    text = (
        "M DEFINITIONS AUTOMATIC TAGS ::= BEGIN\nIMPORTS Name FROM Other;\nA ::= SEQUENCE { a Name, b Missing }\nEND\n"
    )
    assert _findings(text) == [("asn1.type-resolves", "error", "M.A.b")]


def test_choice_alternatives_must_have_distinct_tags() -> None:
    findings = _findings(_module("C ::= CHOICE { a INTEGER, b INTEGER, c [0] BOOLEAN, d [0] UTF8String }"))
    assert ("asn1.choice-tags-distinct", "error", "M.C.b") in findings
    assert ("asn1.choice-tags-distinct", "error", "M.C.d") in findings


def test_automatic_tagging_makes_untagged_alternatives_distinct() -> None:
    assert "asn1.choice-tags-distinct" not in _rules(_module("C ::= CHOICE { a INTEGER, b INTEGER }", "AUTOMATIC"))


def test_set_components_must_have_distinct_tags() -> None:
    findings = _findings(_module("S ::= SET { a INTEGER, b INTEGER }"))
    assert findings == [("asn1.set-tags-distinct", "error", "M.S.b")]


def test_an_optional_component_must_not_share_a_tag_with_what_follows() -> None:
    text = _module("Q ::= SEQUENCE { a INTEGER OPTIONAL, b BOOLEAN OPTIONAL, c INTEGER, d INTEGER }")
    assert _findings(text) == [("asn1.sequence-tags-unambiguous", "error", "M.Q.a")]
    assert "asn1.sequence-tags-unambiguous" not in _rules(_module("Q ::= SEQUENCE { a INTEGER, b INTEGER }"))


def test_component_tags_follow_declared_built_ins_and_referenced_types() -> None:
    api = _api(_module("R ::= SEQUENCE { a IA5String, b R2 }\nR2 ::= SET { x INTEGER }"))
    from app.asn1_lint import _Module

    module = _Module(api)
    fields = _fields(api, "R")
    assert component_tag(module, fields["a"]) == ("UNIVERSAL", 22)
    assert component_tag(module, fields["b"]) == ("UNIVERSAL", 17)


def test_defaults_must_be_in_range_and_name_declared_items() -> None:
    text = _module(
        "E ::= ENUMERATED { low, high }\nD ::= SEQUENCE { n [0] INTEGER (1..10) DEFAULT 20, e [1] E DEFAULT medium }"
    )
    findings = _findings(text)
    assert ("asn1.default-valid", "warning", "M.D.n") in findings
    assert ("asn1.default-valid", "warning", "M.D.e") in findings


def test_any_and_legacy_strings_are_noted() -> None:
    findings = _findings(_module("L ::= SEQUENCE { a [0] ANY, b [1] TeletexString }"))
    assert ("asn1.any-deprecated", "warning", "M.L.a") in findings
    assert ("asn1.legacy-string-type", "info", "M.L.b") in findings


def test_a_type_without_an_extension_marker_is_noted() -> None:
    findings = _findings(
        _module("A ::= SEQUENCE { a INTEGER }\nB ::= SEQUENCE { b INTEGER, ... }"), include_marker=True
    )
    assert [f for f in findings if f[0] == "asn1.extension-marker"] == [("asn1.extension-marker", "info", "M.A")]


# --- breaking changes --------------------------------------------------------------------------


def test_the_classifier_is_registered() -> None:
    assert "asn1" in available_breaking_change_formats()
    assert Asn1BreakingChangeClassifier.classifier_id == "asn1-encoding"
    assert len(RULE_IDS) == len(set(RULE_IDS)) == 27


def test_the_compatible_version_grades_safe() -> None:
    grades = _grades(_version("subscriber.v1.asn1"), _version("subscriber.v2-compatible.asn1"))
    p = "Subscriber-Provisioning"
    assert grades == {
        ("modified", f"{p}.ServiceClass"): (Severity.SAFE, "asn1.enum-item-added-as-extension"),
        ("modified", f"{p}.Location.cellId"): (Severity.SAFE, "asn1.set-component-moved"),
        ("modified", f"{p}.Location.lac"): (Severity.SAFE, "asn1.set-component-moved"),
        ("added", f"{p}.Subscriber.lastSeen"): (Severity.SAFE, "asn1.component-added-as-extension"),
    }


def test_the_breaking_version_grades_each_change() -> None:
    grades = _grades(_version("subscriber.v1.asn1"), _version("subscriber.v3-breaking.asn1"))
    p = "Subscriber-Provisioning"
    expected = {
        ("modified", f"{p}.Identity"): (Severity.BREAKING, "asn1.alternative-removed"),
        ("modified", f"{p}.ServiceClass"): (Severity.BREAKING, "asn1.extension-marker-removed"),
        ("modified", f"{p}.Subscriber.displayName"): (Severity.BREAKING, "asn1.tag-changed"),
        ("modified", f"{p}.Subscriber.maxSessions"): (Severity.BREAKING, "asn1.default-changed"),
        ("modified", f"{p}.Subscriber.serviceClass"): (Severity.BREAKING, "asn1.component-reordered"),
        ("modified", f"{p}.Subscriber.location"): (Severity.SAFE, "asn1.component-shifted"),
        ("added", f"{p}.Subscriber.tenant"): (Severity.BREAKING, "asn1.component-added-required"),
    }
    for key, grade in expected.items():
        assert grades[key] == grade, key


def _two(before: str, after: str, tags: str = "EXPLICIT"):
    return _api(_module(before, tags)), _api(_module(after, tags))


@pytest.mark.parametrize(
    "before,after,key,expected",
    [
        (
            "A ::= SEQUENCE { a INTEGER }",
            "A ::= SEQUENCE { a INTEGER, b BOOLEAN OPTIONAL }",
            ("added", "M.A.b"),
            (Severity.DANGEROUS, "asn1.component-added-optional"),
        ),
        (
            "A ::= SEQUENCE { a INTEGER, b BOOLEAN }",
            "A ::= SEQUENCE { a INTEGER }",
            ("removed", "M.A.b"),
            (Severity.BREAKING, "asn1.component-removed"),
        ),
        (
            "A ::= SEQUENCE { a IA5String }",
            "A ::= SEQUENCE { a UTF8String }",
            ("modified", "M.A.a"),
            (Severity.BREAKING, "asn1.component-type-changed"),
        ),
        (
            "A ::= SEQUENCE { a INTEGER }",
            "A ::= SEQUENCE { a INTEGER OPTIONAL }",
            ("modified", "M.A.a"),
            (Severity.DANGEROUS, "asn1.component-made-optional"),
        ),
        (
            "A ::= SEQUENCE { a INTEGER OPTIONAL }",
            "A ::= SEQUENCE { a INTEGER }",
            ("modified", "M.A.a"),
            (Severity.BREAKING, "asn1.component-made-required"),
        ),
        (
            "A ::= SEQUENCE { a INTEGER (0..9) }",
            "A ::= SEQUENCE { a INTEGER (0..99) }",
            ("modified", "M.A.a"),
            (Severity.DANGEROUS, "asn1.constraint-widened"),
        ),
        (
            "A ::= SEQUENCE { a OCTET STRING (SIZE (1..8)) }",
            "A ::= SEQUENCE { a OCTET STRING (SIZE (1..4)) }",
            ("modified", "M.A.a"),
            (Severity.BREAKING, "asn1.constraint-narrowed"),
        ),
        (
            "A ::= SEQUENCE { a INTEGER, ..., b BOOLEAN OPTIONAL }",
            "A ::= SEQUENCE { a INTEGER, b BOOLEAN OPTIONAL, ... }",
            ("modified", "M.A.b"),
            (Severity.BREAKING, "asn1.extension-moved"),
        ),
        (
            "E ::= ENUMERATED { a, b }",
            "E ::= ENUMERATED { a, b, c }",
            ("modified", "M.E"),
            (Severity.DANGEROUS, "asn1.enum-item-added"),
        ),
        (
            "E ::= ENUMERATED { a(0), b(1) }",
            "E ::= ENUMERATED { a(0), b(2) }",
            ("modified", "M.E"),
            (Severity.BREAKING, "asn1.enum-item-renumbered"),
        ),
        (
            "C ::= CHOICE { a [0] INTEGER, ... }",
            "C ::= CHOICE { a [0] INTEGER, ..., b [1] BOOLEAN }",
            ("modified", "M.C"),
            (Severity.SAFE, "asn1.alternative-added-as-extension"),
        ),
        (
            "C ::= CHOICE { a [0] INTEGER }",
            "C ::= CHOICE { a [0] INTEGER, b [1] BOOLEAN }",
            ("modified", "M.C"),
            (Severity.DANGEROUS, "asn1.alternative-added"),
        ),
        (
            "C ::= CHOICE { a [0] INTEGER, b [1] BOOLEAN }",
            "C ::= CHOICE { a [0] INTEGER, b [1] UTF8String }",
            ("modified", "M.C"),
            (Severity.BREAKING, "asn1.alternative-type-changed"),
        ),
        (
            "A ::= SEQUENCE { a INTEGER }",
            "A ::= SEQUENCE { a INTEGER, ... }",
            ("modified", "M.A"),
            (Severity.DANGEROUS, "asn1.extension-marker-added"),
        ),
        (
            "A ::= SEQUENCE { a INTEGER }",
            "A ::= SET { a INTEGER }",
            ("modified", "M.A"),
            (Severity.BREAKING, "asn1.kind-changed"),
        ),
        (
            "A ::= SEQUENCE { a INTEGER }\nB ::= INTEGER\nV ::= A",
            "A ::= SEQUENCE { a INTEGER }\nB ::= INTEGER\nV ::= B",
            ("modified", "M.V"),
            (Severity.BREAKING, "asn1.alias-target-changed"),
        ),
        (
            "C ::= CHOICE { a [0] OCTET STRING (SIZE (1..8)) }",
            "C ::= CHOICE { a [0] OCTET STRING (SIZE (1..4)) }",
            ("modified", "M.C"),
            (Severity.BREAKING, "asn1.constraint-narrowed"),
        ),
        (
            "N ::= INTEGER (0..255)",
            "N ::= INTEGER (0..127)",
            ("modified", "M.N"),
            (Severity.BREAKING, "asn1.constraint-narrowed"),
        ),
    ],
)
def test_changes(before: str, after: str, key, expected) -> None:
    assert _grades(*_two(before, after))[key] == expected


def test_grade_bounds() -> None:
    assert grade_bounds("x", {"minimum": 0, "maximum": 9}, {"minimum": 0, "maximum": 9}) is None
    assert grade_bounds("x", {"maximum": 9}, None)[1] == "asn1.constraint-widened"
    assert grade_bounds("x", None, {"max_length": 9})[1] == "asn1.constraint-narrowed"

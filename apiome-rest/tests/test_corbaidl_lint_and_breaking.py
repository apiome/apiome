"""Tests for CORBA / OMG IDL interfaces: inheritance, attributes, oneway, lint and breaking changes —
MFI-21.4 (#3994)."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

import pytest

from app.breaking_change import Severity, available_breaking_change_formats, classify_models
from app.canonical_model import MessageRole, OperationKind
from app.corbaidl_breaking import RULE_IDS, CorbaIdlBreakingChangeClassifier, grade_signature, operation_signatures
from app.corbaidl_emitter import CorbaIdlEmitter
from app.corbaidl_import_source import CorbaIdlImportSource
from app.corbaidl_lint import CorbaIdlRulePack, referenced_names
from app.corbaidl_normalizer import attribute_operations, inherited_members
from app.corbaidl_parser import parse_corbaidl
from app.format_lint_capabilities import MODE_NATIVE, capability_for_format
from app.import_source import canonical_diff
from app.lint_engine import get_rule_pack, lint_canonical_model

_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLES = _ROOT / "apiome-ui" / "examples" / "corba-idl"
_VERSIONS = Path(__file__).parent / "fixtures" / "corbaidl_versions"


def _idl(body: str) -> str:
    """A module ``M`` around ``body``."""
    return f"module M {{\n{body}\n}};\n"


def _api(text: str):
    adapter = CorbaIdlImportSource()
    return adapter.normalize(adapter.parse(text, source_label="t.idl"), include_raw=False)


def _version(name: str):
    return _api((_VERSIONS / name).read_text(encoding="utf-8"))


def _operations(api) -> Dict[str, object]:
    return {op.key: op for service in api.services for op in service.operations}


def _findings(text: str) -> List[Tuple[str, str, str]]:
    result = lint_canonical_model(_api(text))
    return sorted((f.rule, f.severity, f.path) for f in result.findings if f.rule.startswith("corbaidl."))


def _rules(text: str) -> set:
    return {rule for rule, _, _ in _findings(text)}


def _grades(base, target) -> Dict[Tuple[str, str], Tuple[Severity, str]]:
    """``(kind, key)`` → ``(severity, rule_id)`` for the diff of two models."""
    result = classify_models(base, target)
    assert result.classifier == "corbaidl-giop"
    return {(c.kind.value, c.key): (c.severity, c.rule_id) for c in result.classifications}


_EXC = "exception Failed { string why; };"


# --- parsing ---------------------------------------------------------------------------------


def test_inheritance_attributes_and_oneway_are_read() -> None:
    doc = parse_corbaidl(
        _idl(
            "interface Base { void ping(); };\n"
            "interface Named;\n"
            "abstract interface X : Base, ::M::Other {\n"
            "  readonly attribute string name, alias;\n"
            "  attribute long size;\n"
            "  oneway void tick(in long n);\n"
            "};"
        )
    )
    by_name = {i.name: i for i in doc.interfaces}
    # A forward declaration is not an interface of its own.
    assert set(by_name) == {"Base", "X"}
    x = by_name["X"]
    assert x.bases == ("Base", "Other")
    assert [(a.name, a.type_expr, a.readonly) for a in x.attributes] == [
        ("name", "string", True),
        ("alias", "string", True),
        ("size", "long", False),
    ]
    (tick,) = x.operations
    assert (tick.name, tick.oneway, tick.return_type) == ("tick", True, "void")


def test_an_inheriting_interface_is_no_longer_dropped() -> None:
    doc = parse_corbaidl(_idl("interface A { void a(); };\ninterface B : A { void b(); };"))
    assert [i.name for i in doc.interfaces] == ["A", "B"]


# --- normalization ---------------------------------------------------------------------------


def test_oneway_is_one_way_with_no_response() -> None:
    operations = _operations(_api((_EXAMPLES / "05-trading-stress.idl").read_text(encoding="utf-8")))
    heartbeat = operations["Trading.MarketData.heartbeat"]
    assert heartbeat.kind is OperationKind.ONE_WAY
    assert [m.role for m in heartbeat.messages] == [MessageRole.REQUEST]


def test_attributes_become_their_giop_accessors() -> None:
    api = _api(_idl("interface X { readonly attribute string id; attribute long size; };"))
    operations = _operations(api)
    assert set(operations) == {"M.X._get_id", "M.X._get_size", "M.X._set_size"}
    getter = next(m for m in operations["M.X._get_size"].messages if m.role is MessageRole.RESPONSE)
    assert getter.payload.name == "i32"
    setter = operations["M.X._set_size"]
    assert [m.role for m in setter.messages] == [MessageRole.REQUEST]
    assert attribute_operations("id", True) == ["_get_id"]


def test_inherited_operations_are_flattened_into_the_derived_interface() -> None:
    api = _version("brokerage.v1.idl")
    account = next(s for s in api.services if s.name == "Account")
    names = {op.name for op in account.operations}
    assert {"audit", "_get_auditId", "place", "cancel", "heartbeat", "_get_nickname", "_set_nickname"} == names
    assert account.extras["corbaidl_bases"] == ["Auditable"]
    assert account.extras["corbaidl_inherited"] == {"audit": "Auditable", "_get_auditId": "Auditable"}


def test_a_diamond_is_inherited_once_and_a_cycle_ends() -> None:
    entries = {
        "Top": {"operations": [{"name": "t"}]},
        "L": {"operations": [{"name": "l"}], "bases": ["Top"]},
        "R": {"operations": [{"name": "r"}], "bases": ["Top"]},
        "D": {"operations": [], "bases": ["L", "R"]},
        "C1": {"operations": [{"name": "c1"}], "bases": ["C2"]},
        "C2": {"operations": [{"name": "c2"}], "bases": ["C1"]},
    }
    assert inherited_members("D", entries) == [("l", "L"), ("t", "Top"), ("r", "R")]
    assert inherited_members("C1", entries) == [("c2", "C2")]


def test_an_overloaded_operation_does_not_break_normalization() -> None:
    api = _api(_idl("interface X { void a(in long n); void a(in string s); };"))
    assert [op.name for op in api.services[0].operations] == ["a"]


def test_interfaces_are_recorded_as_declared() -> None:
    api = _version("brokerage.v1.idl")
    entries = {e["name"]: e for e in api.extras["corbaidl_interfaces"]}
    assert entries["Account"]["bases"] == ["Auditable"]
    assert entries["Account"]["attributes"] == [{"name": "nickname", "type": "string"}]
    assert entries["Auditable"]["attributes"] == [{"name": "auditId", "type": "string", "readonly": True}]
    heartbeat = next(op for op in entries["Account"]["operations"] if op["name"] == "heartbeat")
    assert heartbeat["oneway"] is True


# --- the emitter writes it back ----------------------------------------------------------------


@pytest.mark.parametrize("name", ["brokerage.v1.idl", "brokerage.v2-compatible.idl", "brokerage.v3-breaking.idl"])
def test_the_version_fixtures_round_trip(name: str) -> None:
    api = _version(name)
    text = CorbaIdlEmitter().emit(api).files[0].content
    again = _api(text)
    assert canonical_diff(api, again).entries == []


def test_bases_attributes_and_oneway_are_written() -> None:
    text = CorbaIdlEmitter().emit(_version("brokerage.v1.idl")).files[0].content
    assert "interface Account : Auditable {" in text
    assert "readonly attribute string auditId;" in text
    assert "attribute string nickname;" in text
    assert "oneway void heartbeat(in long seq);" in text


# --- lint ------------------------------------------------------------------------------------


def test_the_pack_is_registered_and_native() -> None:
    assert get_rule_pack("corbaidl") is CorbaIdlRulePack
    assert capability_for_format("corbaidl").mode == MODE_NATIVE
    ids = [rule.rule_id for rule in CorbaIdlRulePack().rules()]
    assert len(ids) == len(set(ids)) == 11


@pytest.mark.parametrize("path", sorted(_EXAMPLES.glob("*.idl")), ids=lambda p: p.name)
def test_the_corpus_raises_no_errors_or_warnings(path: Path) -> None:
    findings = _findings(path.read_text(encoding="utf-8"))
    assert [f for f in findings if f[1] != "info"] == []


def test_the_version_fixtures_lint_clean() -> None:
    for name in ("brokerage.v1.idl", "brokerage.v2-compatible.idl", "brokerage.v3-breaking.idl"):
        assert _findings((_VERSIONS / name).read_text(encoding="utf-8")) == [], name


def test_referenced_names_skip_base_types_and_bounds() -> None:
    assert referenced_names("sequence<Account, 10>") == ["Account"]
    assert referenced_names("unsigned long long") == []
    assert referenced_names("sequence<sequence<double>>") == []
    assert referenced_names("string<40>") == []


def test_undeclared_types_are_errors() -> None:
    findings = _findings(_idl("struct S { Missing m; };\ninterface X { Ghost get(in Phantom p); };"))
    assert ("corbaidl.type-resolves", "error", "M.S.m") in findings
    assert ("corbaidl.type-resolves", "error", "M.X.get#return") in findings
    assert ("corbaidl.type-resolves", "error", "M.X.get#param.p") in findings


def test_an_interface_is_a_valid_type() -> None:
    assert "corbaidl.type-resolves" not in _rules(_idl("interface Y { void y(); };\ninterface X { Y next(); };"))


def test_raises_must_name_exceptions() -> None:
    findings = _findings(_idl("struct S { long n; };\ninterface X { void a() raises (S, Nope); };"))
    assert ("corbaidl.raises-declared", "error", "M.X.a#raises.S") in findings
    assert ("corbaidl.raises-declared", "error", "M.X.a#raises.Nope") in findings


def test_an_exception_may_not_be_a_type() -> None:
    findings = _findings(_idl(f"{_EXC}\ninterface X {{ Failed get(); }};"))
    assert ("corbaidl.exception-as-type", "error", "M.X.get#return") in findings


def test_oneway_operations_must_be_void_in_only_and_raise_nothing() -> None:
    findings = _findings(_idl(f"{_EXC}\ninterface X {{ oneway long a(out long n) raises (Failed); }};"))
    ((rule, severity, path),) = [f for f in findings if f[0] == "corbaidl.oneway-signature"]
    assert (severity, path) == ("error", "M.X.a")


def test_operation_names_must_not_collide_by_case_or_with_inherited_ones() -> None:
    text = _idl(
        "interface Base { void ping(); };\ninterface X : Base { void Ping(); attribute long size; void _get_size(); };"
    )
    paths = {path for rule, _, path in _findings(text) if rule == "corbaidl.operation-names-unique"}
    assert paths == {"M.X._get_size", "M.X.ping"}


def test_member_and_parameter_names_must_not_collide_by_case() -> None:
    findings = _findings(_idl("struct S { long id; string ID; };\ninterface X { void a(in long n, in long N); };"))
    assert ("corbaidl.member-names-unique", "error", "M.S.ID") in findings
    assert ("corbaidl.member-names-unique", "error", "M.X.a#param.N") in findings


def test_inheritance_cycles_and_undeclared_bases() -> None:
    findings = _findings(
        _idl("interface A : B { void a(); };\ninterface B : A { void b(); };\ninterface C : Elsewhere { void c(); };")
    )
    assert ("corbaidl.inheritance-acyclic", "error", "M.A") in findings
    assert ("corbaidl.inheritance-acyclic", "error", "M.B") in findings
    assert ("corbaidl.base-interface-declared", "warning", "M.C") in findings


def test_keywords_are_not_identifiers() -> None:
    findings = _findings(_idl("struct Short { long Sequence; };\ninterface X { void attribute(in long string); };"))
    paths = {path for rule, _, path in findings if rule == "corbaidl.identifier-not-keyword"}
    assert paths == {"M.Short", "M.Short.Sequence", "M.X.attribute", "M.X.attribute#param.string"}


def test_any_and_object_are_noted() -> None:
    findings = _findings(_idl("interface X { any a(in Object o); };"))
    assert ("corbaidl.any-typed", "info", "M.X.a#return") in findings
    assert ("corbaidl.object-reference-typed", "info", "M.X.a#param.o") in findings


# --- breaking changes --------------------------------------------------------------------------


def test_the_classifier_is_registered() -> None:
    assert "corbaidl" in available_breaking_change_formats()
    assert CorbaIdlBreakingChangeClassifier.classifier_id == "corbaidl-giop"
    assert len(RULE_IDS) == len(set(RULE_IDS)) == 23


def test_the_compatible_version_grades_safe() -> None:
    grades = _grades(_version("brokerage.v1.idl"), _version("brokerage.v2-compatible.idl"))
    assert grades and all(severity is Severity.SAFE for severity, _ in grades.values())
    assert grades[("added", "Brokerage.Quotes")] == (Severity.SAFE, "added-entity")
    assert grades[("added", "Brokerage.Account.openOrders")] == (Severity.SAFE, "added-entity")


def test_the_breaking_version_grades_each_change() -> None:
    grades = _grades(_version("brokerage.v1.idl"), _version("brokerage.v3-breaking.idl"))
    expected = {
        ("modified", "Brokerage.Account"): (Severity.BREAKING, "corbaidl.base-removed"),
        ("removed", "Brokerage.Account.audit"): (Severity.BREAKING, "removed-entity"),
        ("modified", "Brokerage.Account.heartbeat"): (Severity.BREAKING, "corbaidl.oneway-changed"),
        ("added", "Brokerage.Account.cancel#error.Rejected"): (Severity.DANGEROUS, "corbaidl.raises-added"),
        ("modified", "Brokerage.Account.cancel#request"): (Severity.BREAKING, "corbaidl.parameter-type-changed"),
        ("modified", "Brokerage.Account.place#request"): (Severity.BREAKING, "corbaidl.parameter-direction-changed"),
        ("modified", "Brokerage.Side"): (Severity.BREAKING, "corbaidl.enumerator-inserted"),
        ("added", "Brokerage.Order.account"): (Severity.BREAKING, "corbaidl.member-added"),
        ("modified", "Brokerage.Order.quantity"): (Severity.BREAKING, "corbaidl.member-reordered"),
        ("modified", "Brokerage.Order.side"): (Severity.BREAKING, "corbaidl.member-reordered"),
        ("modified", "Brokerage.Order.limitPrice"): (Severity.SAFE, "corbaidl.member-shifted"),
        ("modified", "Brokerage.Order.symbol"): (Severity.BREAKING, "corbaidl.bound-narrowed"),
    }
    for key, grade in expected.items():
        assert grades[key] == grade, key


def _two(before: str, after: str):
    """Two models of ``before`` / ``after`` (each with an interface, so it detects as IDL)."""
    anchor = "\ninterface Anchor { void anchor(); };"
    return _api(_idl(before + anchor)), _api(_idl(after + anchor))


@pytest.mark.parametrize(
    "before,after,key,expected",
    [
        (
            "enum E { A, B };",
            "enum E { A, B, C };",
            ("modified", "M.E"),
            (Severity.DANGEROUS, "corbaidl.enumerator-appended"),
        ),
        (
            "enum E { A, B };",
            "enum E { B, A };",
            ("modified", "M.E"),
            (Severity.BREAKING, "corbaidl.enumerator-reordered"),
        ),
        ("enum E { A, B };", "enum E { A };", ("modified", "M.E"), (Severity.BREAKING, "corbaidl.enumerator-removed")),
        (
            "struct S { string<5> s; };",
            "struct S { string<9> s; };",
            ("modified", "M.S.s"),
            (Severity.DANGEROUS, "corbaidl.bound-widened"),
        ),
        (
            "struct S { long n; };",
            "struct S { double n; };",
            ("modified", "M.S.n"),
            (Severity.BREAKING, "corbaidl.member-type-changed"),
        ),
        (
            "struct S { long n; long m; };",
            "struct S { long n; };",
            ("removed", "M.S.m"),
            (Severity.BREAKING, "corbaidl.member-removed"),
        ),
        (
            "struct S { long n; };",
            "exception S { long n; };",
            ("modified", "M.S"),
            (Severity.BREAKING, "corbaidl.kind-changed"),
        ),
        (
            f"{_EXC} interface X {{ void a() raises (Failed); }};",
            f"{_EXC} interface X {{ void a(); }};",
            ("removed", "M.X.a#error.Failed"),
            (Severity.SAFE, "corbaidl.raises-removed"),
        ),
        (
            "interface X { long a(in long n, in long m); };",
            "interface X { long a(in long n, in long m, in long k); };",
            ("modified", "M.X.a#request"),
            (Severity.BREAKING, "corbaidl.parameter-added"),
        ),
        (
            "interface X { long a(in long n); };",
            "interface X { string a(in long n); };",
            ("modified", "M.X.a#response"),
            (Severity.BREAKING, "corbaidl.return-type-changed"),
        ),
        (
            "interface A { void a(); }; interface X { void x(); };",
            "interface A { void a(); }; interface X : A { void x(); };",
            ("modified", "M.X"),
            (Severity.SAFE, "corbaidl.base-added"),
        ),
    ],
)
def test_changes(before: str, after: str, key, expected) -> None:
    assert _grades(*_two(before, after))[key] == expected


def test_a_renamed_parameter_of_a_multi_parameter_operation_is_safe() -> None:
    base, target = _two(
        "interface X { void a(in long n, in long m); };", "interface X { void a(in long n, in long k); };"
    )
    assert _grades(base, target)[("modified", "M.X.a#request")] == (Severity.SAFE, "corbaidl.parameter-renamed")


def test_signatures_include_accessors_and_inherited_operations() -> None:
    signatures = operation_signatures(_version("brokerage.v1.idl"))
    assert signatures["Brokerage.Account.audit"]["parameters"] == [
        {"name": "note", "type": "string", "direction": "in"}
    ]
    assert signatures["Brokerage.Account._set_nickname"]["return_type"] == "void"


def test_grade_signature_reports_raises_by_name() -> None:
    before = {"name": "a", "return_type": "void", "parameters": [], "raises": ["X"]}
    after = {"name": "a", "return_type": "void", "parameters": [], "raises": ["Y"]}
    rules = {rule for _, rule, _ in grade_signature(before, after)}
    assert rules == {"corbaidl.raises-added", "corbaidl.raises-removed"}

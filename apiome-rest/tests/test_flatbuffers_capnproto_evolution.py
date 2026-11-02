"""FlatBuffers and Cap'n Proto breaking changes and lint — MFI-19.4 (#3982).

Both formats identify a field by number: a FlatBuffers table field by its id (``(id: N)`` or its
position, a union taking two; a removed field is kept as ``(deprecated)``), a Cap'n Proto member by
its ``@N`` ordinal. The classifiers pair the two sides of a diff by that number and apply each
format's evolution rules; the lint packs catch what each compiler refuses. Every case below goes
through the real readers and :func:`app.breaking_change.classify_models`.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import pytest

from app.breaking_change import classify_models, get_breaking_change_classifier
from app.canonical_model import CanonicalApi
from app.capnproto_breaking import CapnProtoBreakingChangeClassifier
from app.capnproto_import_source import CapnpImportSource
from app.capnproto_parser import parse_capnproto
from app.flatbuffers_breaking import FlatBuffersBreakingChangeClassifier
from app.flatbuffers_import_source import FlatBuffersImportSource
from app.lint_engine import lint_canonical_model

_FBS = FlatBuffersImportSource()
_CAPNP = CapnpImportSource()

FBS = (
    "namespace Game;\n\n"
    "enum Color : byte { Red = 0, Green = 1 }\n\n"
    "union Equipment { Weapon }\n\n"
    "struct Vec3 { x: float; y: float; }\n\n"
    "table Weapon { damage: short; }\n\n"
    "table Monster {\n  pos: Vec3;\n  hp: short = 100;\n  name: string;\n}\n\n"
    "root_type Monster;\n"
)

CAPNP = (
    "@0xbf5147cbbecf40c1;\n\n"
    "struct Person {\n  name @0 :Text;\n  email @1 :Text;\n}\n\n"
    "enum Kind {\n  a @0;\n  b @1;\n}\n\n"
    "interface Book {\n"
    "  get @0 (id :UInt32) -> (person :Person);\n"
    "  list @1 () -> (people :List(Person));\n"
    "}\n"
)


def _fbs(text: str) -> CanonicalApi:
    return _FBS.normalize(_FBS.parse(text), include_raw=False)


def _capnp(text: str) -> CanonicalApi:
    return _CAPNP.normalize(_CAPNP.parse(text), include_raw=False)


def _grades(base: CanonicalApi, target: CanonicalApi) -> Dict[str, Tuple[str, str]]:
    """``{change key: (severity, rule id)}`` of a diff."""
    result = classify_models(base, target)
    return {c.key: (c.severity.value, c.rule_id) for c in result.classifications}


def _rules(base: CanonicalApi, target: CanonicalApi) -> List[Tuple[str, str]]:
    return sorted(set(_grades(base, target).values()))


# --- registration ------------------------------------------------------------------------------


def test_the_classifiers_are_registered() -> None:
    assert get_breaking_change_classifier("flatbuffers") is FlatBuffersBreakingChangeClassifier
    assert get_breaking_change_classifier("capnproto") is CapnProtoBreakingChangeClassifier


# --- FlatBuffers -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "edit, expected",
    [
        pytest.param(("name: string", "title: string"), {("dangerous", "fbs.field-renamed")}, id="rename"),
        pytest.param(("name: string", "name_id: int"), {("breaking", "fbs.field-id-reused")}, id="reuse"),
        pytest.param(
            ("name: string", "name: string (deprecated)"), {("safe", "fbs.field-deprecated")}, id="deprecate"
        ),
        pytest.param(("  name: string;\n", ""), {("breaking", "fbs.field-removed")}, id="remove"),
        pytest.param(("name: string;", "name: string;\n  mana: int;"), {("safe", "fbs.field-added")}, id="append"),
        pytest.param(("= 100", "= 50"), {("dangerous", "fbs.default-changed")}, id="default"),
        pytest.param(("y: float; }", "y: float; z: float; }"), {("breaking", "fbs.struct-changed")}, id="struct"),
        pytest.param(("Green = 1", "Green = 2"), {("breaking", "fbs.enum-value-changed")}, id="enum-renumbered"),
        pytest.param((", Green = 1", ""), {("breaking", "fbs.enum-value-removed")}, id="enum-value-removed"),
    ],
)
def test_flatbuffers_evolution_rules(edit: Tuple[str, str], expected: set) -> None:
    assert set(_rules(_fbs(FBS), _fbs(FBS.replace(*edit)))) == expected


def test_inserting_a_field_moves_the_later_ids() -> None:
    grades = _grades(_fbs(FBS), _fbs(FBS.replace("hp: short = 100;", "mana: int;\n  hp: short = 100;")))
    assert grades["Game.Monster.mana"] == ("safe", "fbs.field-added")
    assert grades["Game.Monster.hp"] == ("breaking", "fbs.field-id-changed")
    assert grades["Game.Monster.name"] == ("breaking", "fbs.field-id-changed")


def test_explicit_ids_keep_a_field_where_it_was() -> None:
    base = FBS.replace("pos: Vec3;", "pos: Vec3 (id: 0);").replace("hp: short = 100;", "hp: short = 100 (id: 1);")
    base = base.replace("name: string;", "name: string (id: 2);")
    moved = base.replace("  hp: short = 100 (id: 1);\n", "").replace(
        "name: string (id: 2);", "name: string (id: 2);\n  hp: short = 100 (id: 1);"
    )
    assert _rules(_fbs(base), _fbs(moved)) in ([], [("safe", "fbs.field-id-unchanged")])


def test_a_union_member_removed_or_reordered_is_breaking() -> None:
    base = FBS.replace("union Equipment { Weapon }", "union Equipment { Weapon, Shield }")
    base = base.replace("table Weapon", "table Shield { armor: short; }\n\ntable Weapon")
    grades = _grades(_fbs(base), _fbs(base.replace("{ Weapon, Shield }", "{ Shield, Weapon }")))
    assert grades["Game.Equipment"] == ("breaking", "fbs.union-member-removed")
    appended = base.replace("{ Weapon, Shield }", "{ Weapon, Shield, Weapon2 }").replace(
        "table Weapon {", "table Weapon2 { x: short; }\n\ntable Weapon {"
    )
    assert _grades(_fbs(base), _fbs(appended)).get("Game.Equipment", ("", ""))[1] != "fbs.union-member-removed"


# --- Cap'n Proto -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "edit, expected",
    [
        pytest.param(("email @1", "mail @1"), {("safe", "capnp.field-renamed")}, id="rename"),
        pytest.param(("email @1 :Text", "age @1 :UInt8"), {("breaking", "capnp.ordinal-reused")}, id="reuse"),
        pytest.param(("  email @1 :Text;\n", ""), {("breaking", "capnp.field-removed")}, id="remove"),
        pytest.param(
            ("email @1 :Text;", "email @1 :Text;\n  age @2 :UInt8;"), {("safe", "capnp.field-added")}, id="add"
        ),
        pytest.param(("b @1", "b @2"), {("breaking", "capnp.enum-value-changed")}, id="enum-renumbered"),
        pytest.param(("  b @1;\n", ""), {("breaking", "capnp.enum-value-removed")}, id="enum-value-removed"),
    ],
)
def test_capnproto_evolution_rules(edit: Tuple[str, str], expected: set) -> None:
    assert set(_rules(_capnp(CAPNP), _capnp(CAPNP.replace(*edit)))) == expected


def test_a_renamed_method_and_its_messages_are_safe() -> None:
    grades = _grades(_capnp(CAPNP), _capnp(CAPNP.replace("get @0", "fetch @0")))
    assert set(grades.values()) == {("safe", "capnp.method-renamed")}
    assert {"Book.get", "Book.fetch", "Book.get#request", "Book.fetch#response"} <= set(grades)


def test_a_method_removed_is_breaking_and_one_added_is_safe() -> None:
    removed = _grades(_capnp(CAPNP), _capnp(CAPNP.replace("  list @1 () -> (people :List(Person));\n", "")))
    assert removed["Book.list"] == ("breaking", "capnp.method-removed")
    with_count = CAPNP.replace(
        "  list @1 () -> (people :List(Person));\n",
        "  list @1 () -> (people :List(Person));\n  count @2 () -> (n :UInt32);\n",
    )
    added = _grades(_capnp(CAPNP), _capnp(with_count))
    assert added.get("Book.count") == ("safe", "capnp.method-added")


def test_a_method_reusing_an_ordinal_with_another_signature_is_breaking() -> None:
    grades = _grades(_capnp(CAPNP), _capnp(CAPNP.replace("get @0 (id :UInt32)", "find @0 (query :Text)")))
    assert grades["Book.get"] == ("breaking", "capnp.ordinal-reused")


def test_a_method_moved_to_another_ordinal_is_breaking() -> None:
    swapped = CAPNP.replace("get @0", "get @9").replace("list @1", "list @0").replace("get @9", "get @1")
    grades = _grades(_capnp(CAPNP), _capnp(swapped))
    assert grades["Book.get"] == ("breaking", "capnp.ordinal-changed")


def test_a_method_returning_a_parenthesized_type_is_parsed() -> None:
    # Before MFI-19.4 the reader stopped at the first `)` and dropped `list` entirely.
    document = parse_capnproto(CAPNP)
    methods = {m.name: m for m in document.interfaces[0].methods}
    assert set(methods) == {"get", "list"}
    assert methods["list"].results[0].type_expr == "List(Person)"


# --- lint --------------------------------------------------------------------------------------


def _findings(api: CanonicalApi, prefix: str) -> List[str]:
    rules = (finding.as_dict()["rule"] for finding in lint_canonical_model(api).findings)
    return sorted(rule for rule in rules if rule.startswith(prefix))


def test_a_clean_flatbuffers_schema_has_no_findings() -> None:
    assert _findings(_fbs(FBS), "flatbuffers.") == []


@pytest.mark.parametrize(
    "edit, rule",
    [
        pytest.param(("namespace Game;\n", ""), "flatbuffers.namespace-declared", id="namespace"),
        pytest.param(("root_type Monster;\n", ""), "flatbuffers.root-type-declared", id="root-type"),
        pytest.param(
            ("hp: short = 100;\n  name: string;", "hp: short = 100 (id: 1);\n  name: string (id: 1);"),
            "flatbuffers.unique-field-ids",
            id="duplicate-ids",
        ),
        pytest.param(("pos: Vec3;", "pos: Vec3 (id: 0);"), "flatbuffers.explicit-ids-all-or-none", id="mixed-ids"),
    ],
)
def test_flatbuffers_lint_rules(edit: Tuple[str, str], rule: str) -> None:
    assert rule in _findings(_fbs(FBS.replace(*edit)), "flatbuffers.")


def test_a_clean_capnproto_schema_has_no_findings() -> None:
    assert _findings(_capnp(CAPNP), "capnproto.") == []


@pytest.mark.parametrize(
    "edit, rule",
    [
        pytest.param(("@0xbf5147cbbecf40c1;\n", ""), "capnproto.file-id-declared", id="file-id"),
        pytest.param(("email @1", "email @0"), "capnproto.unique-ordinals", id="duplicate-field"),
        pytest.param(("email @1", "email @2"), "capnproto.contiguous-ordinals", id="field-gap"),
        pytest.param(("b @1", "b @3"), "capnproto.contiguous-ordinals", id="enum-gap"),
        pytest.param(("list @1", "list @0"), "capnproto.unique-ordinals", id="duplicate-method"),
    ],
)
def test_capnproto_lint_rules(edit: Tuple[str, str], rule: str) -> None:
    assert rule in _findings(_capnp(CAPNP.replace(*edit)), "capnproto.")


def test_a_duplicate_is_not_also_reported_as_a_gap() -> None:
    findings = _findings(_capnp(CAPNP.replace("email @1", "email @0")), "capnproto.")
    assert "capnproto.contiguous-ordinals" not in findings

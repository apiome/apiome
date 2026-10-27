"""Tests for the Avro lint pack — MFI-12.5 (#3786).

Covers :mod:`app.avro_hygiene` (defaults, unions, optional-union hygiene, aliases, docs) on both
Avro surfaces, the normalizer extras and the ``avro`` rules in :mod:`app.avro_lint`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from app.avro_hygiene import MAX_REPORTED_ISSUES, check_avro_document
from app.avro_import_source import AvroImportSource
from app.lint_engine import lint_canonical_model

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_CORPUS = sorted((_EXAMPLES / "avro").glob("*.avsc")) + sorted((_EXAMPLES / "avro-idl").glob("*.avdl"))


def _record(*fields: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
    """A record ``com.acme.Account`` with the given fields."""
    schema: Dict[str, Any] = {"type": "record", "name": "Account", "namespace": "com.acme", "fields": list(fields)}
    schema.update(extra)
    return schema


def _issues(schema: Any, *, text: Optional[str] = None) -> List[Dict[str, str]]:
    """Parse a schema (dict → ``.avsc`` JSON, or IDL ``text``) and run the hygiene checks."""
    adapter = AvroImportSource()
    document = adapter.parse(text if text is not None else json.dumps(schema))
    issues, _ = check_avro_document(document)
    return [issue.as_dict() for issue in issues]


def _rules(schema: Any) -> List[str]:
    return [issue["rule"] for issue in _issues(schema)]


@pytest.mark.parametrize("path", _CORPUS, ids=lambda p: p.name)
def test_the_corpus_is_clean(path: Path):
    document = AvroImportSource().parse(path.read_text(encoding="utf-8"), source_label=path.name)
    assert check_avro_document(document) == ([], 0)


# ===========================================================================
# Defaults
# ===========================================================================


@pytest.mark.parametrize(
    ("field_type", "default"),
    [
        ("null", None),
        ("boolean", False),
        ("int", 2147483647),
        ("long", -(2**63)),
        ("float", 1),
        ("double", 1.5),
        ("string", "x"),
        ("bytes", "ÿ"),
        (["null", "string"], None),
        (["string", "null"], "x"),
        ({"type": "array", "items": "int"}, [1, 2]),
        ({"type": "map", "values": "long"}, {"a": 1}),
        ({"type": "enum", "name": "Tier", "symbols": ["GOLD", "SILVER"]}, "GOLD"),
        ({"type": "fixed", "name": "Pin", "size": 4}, "1234"),
        ({"type": "string", "logicalType": "uuid"}, "00000000-0000-0000-0000-000000000000"),
        (
            {
                "type": "record",
                "name": "Money",
                "fields": [{"name": "amount", "type": "long"}, {"name": "cur", "type": "string", "default": "EUR"}],
            },
            {"amount": 1},
        ),
    ],
)
def test_valid_defaults_are_accepted(field_type: Any, default: Any):
    assert _rules(_record({"name": "value", "type": field_type, "default": default})) == []


@pytest.mark.parametrize(
    ("field_type", "default", "fragment"),
    [
        ("long", "zero", "not a valid `long` value"),
        ("int", 2**31, "not a valid `int` value"),
        ("boolean", 0, "not a valid `boolean` value"),
        ("int", True, "not a valid `int` value"),
        ("string", None, "not a valid `string` value"),
        (["string", "null"], None, "a union's default must match its first branch"),
        ({"type": "array", "items": "int"}, ["a"], "not a valid `array` value"),
        ({"type": "enum", "name": "Tier", "symbols": ["GOLD"]}, "BRONZE", "not a valid `Tier` value"),
        ({"type": "fixed", "name": "Pin", "size": 4}, "12", "not a valid `Pin` value"),
        (
            {"type": "record", "name": "Money", "fields": [{"name": "amount", "type": "long"}]},
            {},
            "not a valid `Money` value",
        ),
    ],
)
def test_invalid_defaults_are_reported(field_type: Any, default: Any, fragment: str):
    (issue,) = _issues(_record({"name": "value", "type": field_type, "default": default}))
    assert issue["rule"] == "avro.invalid-default"
    assert issue["path"] == "/com.acme.Account/fields/value/default"
    assert fragment in issue["message"]


def test_defaults_of_named_references_resolve_through_the_namespace():
    tier = {"type": "enum", "name": "Tier", "symbols": ["GOLD"]}
    schema = _record(
        {"name": "tier", "type": tier, "default": "GOLD"}, {"name": "previous", "type": "Tier", "default": "LEAD"}
    )
    (issue,) = _issues(schema)
    assert issue["path"] == "/com.acme.Account/fields/previous/default"


def test_an_unknown_reference_is_not_judged():
    assert _rules(_record({"name": "x", "type": "com.other.Thing", "default": 1})) == []


def test_an_enum_default_must_be_a_symbol():
    schema = _record({"name": "tier", "type": {"type": "enum", "name": "Tier", "symbols": ["GOLD"], "default": "LEAD"}})
    (issue,) = _issues(schema)
    assert issue == {
        "rule": "avro.invalid-default",
        "path": "/com.acme.Tier/default",
        "message": 'enum `com.acme.Tier` has default `"LEAD"`, which is not one of its symbols.',
    }


# ===========================================================================
# Unions and optional-union hygiene
# ===========================================================================


def test_nested_and_repeated_union_branches_are_reported():
    schema = _record(
        {"name": "a", "type": ["null", ["int", "long"]], "default": None},
        {"name": "b", "type": ["null", "string", {"type": "string", "logicalType": "uuid"}], "default": None},
        {"name": "c", "type": {"type": "array", "items": ["int", "int"]}},
    )
    issues = _issues(schema)
    assert [(i["rule"], i["path"]) for i in issues] == [
        ("avro.invalid-union", "/com.acme.Account/fields/a"),
        ("avro.invalid-union", "/com.acme.Account/fields/b"),
        ("avro.invalid-union", "/com.acme.Account/fields/c"),
    ]


def test_distinct_named_branches_are_fine():
    a = {"type": "record", "name": "A", "fields": []}
    b = {"type": "record", "name": "B", "fields": []}
    assert _rules(_record({"name": "x", "type": ["null", a, b], "default": None})) == []


def test_optional_union_hygiene():
    schema = _record(
        {"name": "late", "type": ["string", "null"]},
        {"name": "bare", "type": ["null", "string"]},
        {"name": "good", "type": ["null", "string"], "default": None},
        {"name": "valued", "type": ["string", "null"], "default": "x"},
        {"name": "wide", "type": ["string", "int", "null"]},
    )
    issues = _issues(schema)
    assert [(i["rule"], i["path"]) for i in issues] == [
        ("avro.optional-union-null-first", "/com.acme.Account/fields/late"),
        ("avro.optional-union-missing-default", "/com.acme.Account/fields/bare"),
    ]
    assert '["null", "string"]' in issues[0]["message"]


# ===========================================================================
# Aliases
# ===========================================================================


def test_field_aliases():
    schema = _record(
        {"name": "id", "type": "string", "aliases": ["account-id", "id", "owner"]},
        {"name": "owner", "type": "string"},
        {"name": "holder", "type": "string", "aliases": ["legacy"]},
        {"name": "payee", "type": "string", "aliases": ["legacy"]},
    )
    issues = _issues(schema)
    assert [(i["rule"], i["path"]) for i in issues] == [
        ("avro.invalid-alias", "/com.acme.Account/fields/id/aliases"),
        ("avro.redundant-alias", "/com.acme.Account/fields/id/aliases"),
        ("avro.alias-conflict", "/com.acme.Account/fields/id/aliases"),
        ("avro.alias-conflict", "/com.acme.Account/fields/payee/aliases"),
    ]


def test_type_aliases():
    other = {"type": "record", "name": "Ledger", "fields": [], "aliases": ["Book"]}
    schema = _record(
        {"name": "ledger", "type": other},
        aliases=["Ledger", "com.acme.Account", "Book", "Legacy", "bad name", "old.ns.Account"],
    )
    issues = _issues(schema)
    by_rule = [(i["rule"], i["message"]) for i in issues]
    assert (
        "avro.alias-conflict",
        "alias `Ledger` of `com.acme.Account` is also the name or an alias of `com.acme.Ledger`.",
    ) in by_rule
    assert ("avro.redundant-alias", "alias `com.acme.Account` repeats the name of `com.acme.Account`.") in by_rule
    assert any(rule == "avro.alias-conflict" and "`Book`" in message for rule, message in by_rule)
    assert any(rule == "avro.invalid-alias" and '`"bad name"`' in message for rule, message in by_rule)
    assert len(issues) == 4


def test_aliases_must_be_a_list():
    (issue,) = _issues(_record({"name": "id", "type": "string", "aliases": "old"}))
    assert issue["rule"] == "avro.invalid-alias"


# ===========================================================================
# Docs
# ===========================================================================


def test_ignored_docs():
    schema = _record(
        {"name": "id", "type": {"type": "string", "doc": "lost"}},
        {"name": "n", "type": "int", "doc": 7},
        {"name": "tags", "type": {"type": "array", "items": {"type": "string", "doc": "lost too"}}},
        doc=["not", "a", "string"],
    )
    issues = _issues(schema)
    assert {i["rule"] for i in issues} == {"avro.doc-ignored"}
    assert [i["path"] for i in issues] == [
        "/com.acme.Account/doc",
        "/com.acme.Account/fields/id/doc",
        "/com.acme.Account/fields/n/doc",
        "/com.acme.Account/fields/tags/doc",
    ]


# ===========================================================================
# IDL
# ===========================================================================


def test_idl_fields_and_message_parameters_are_checked():
    text = """
    @namespace("com.acme")
    protocol Bank {
      record Account {
        union { string, null } nickname;
        union { null, string } memo;
      }
      Account open(string owner, union { null, int } limit, long start = "x");
    }
    """
    issues = _issues(None, text=text)
    assert [(i["rule"], i["path"]) for i in issues] == [
        ("avro.optional-union-null-first", "/com.acme.Account/fields/nickname"),
        ("avro.optional-union-missing-default", "/com.acme.Account/fields/memo"),
        ("avro.optional-union-missing-default", "/messages/open/request/limit"),
        ("avro.invalid-default", "/messages/open/request/start/default"),
    ]


# ===========================================================================
# Normalizer extras and lint rules
# ===========================================================================


def _lint(schema: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    adapter = AvroImportSource()
    model = adapter.normalize(adapter.parse(json.dumps(schema)))
    findings: Dict[str, List[Dict[str, Any]]] = {}
    for finding in lint_canonical_model(model).findings:
        payload = finding.as_dict()
        findings.setdefault(payload["rule"], []).append(payload)
    return findings


def test_a_clean_schema_adds_no_extras_or_findings():
    schema = _record({"name": "id", "type": "string", "doc": "Id."}, doc="An account.")
    adapter = AvroImportSource()
    model = adapter.normalize(adapter.parse(json.dumps(schema)))
    assert "avro_lint_issues" not in model.extras
    assert not [rule for rule in _lint(schema) if rule.startswith("avro.")]


def test_each_rule_reports_with_its_severity():
    schema = _record(
        {"name": "balance", "type": "long", "default": "zero"},
        {"name": "ref", "type": ["null", "string", "string"], "default": None},
        {"name": "id", "type": "string", "aliases": ["bad-alias", "id", "owner"]},
        {"name": "owner", "type": "string"},
        {"name": "late", "type": ["string", "null"]},
        {"name": "bare", "type": ["null", "string"]},
        {"name": "note", "type": {"type": "string", "doc": "lost"}},
    )
    findings = _lint(schema)
    severities = {rule: {f["severity"] for f in items} for rule, items in findings.items() if rule.startswith("avro.")}
    assert severities == {
        "avro.invalid-default": {"error"},
        "avro.invalid-union": {"error"},
        "avro.invalid-alias": {"error"},
        "avro.alias-conflict": {"error"},
        "avro.optional-union-null-first": {"warning"},
        "avro.optional-union-missing-default": {"warning"},
        "avro.doc-ignored": {"warning"},
        "avro.redundant-alias": {"info"},
    }
    assert findings["avro.invalid-default"][0]["path"] == "avro:/com.acme.Account/fields/balance/default"


def test_issues_are_capped_and_the_rest_counted():
    fields = [{"name": f"f{i}", "type": "long", "default": "x"} for i in range(MAX_REPORTED_ISSUES + 3)]
    schema = _record(*fields)
    adapter = AvroImportSource()
    model = adapter.normalize(adapter.parse(json.dumps(schema)))
    assert len(model.extras["avro_lint_issues"]) == MAX_REPORTED_ISSUES
    assert model.extras["avro_lint_issue_count"] == MAX_REPORTED_ISSUES + 3
    messages = [f["message"] for f in _lint(schema)["avro.invalid-default"]]
    assert "3 more Avro hygiene issue(s) not listed." in messages

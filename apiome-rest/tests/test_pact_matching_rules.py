"""Pact matching rules as JSON Schema constraints — PFX-2.2 (#6926)."""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from app.pact_matching_rules import (
    MATCHER_MAPPINGS,
    MAX_RULE_LOCATIONS,
    NOT_MAPPED_REASONS,
    UNVERIFIED_REASONS,
    MatchingRule,
    evaluate_rule,
    json_type,
    parse_matching_rules,
    parse_path,
    rule_constraint,
    schema_types,
    select_path,
)
from app.pact_oas_schema import REQUEST, RESPONSE, ProviderSchemas

SITE = "/paths/~1things/get/responses/200/content/application~1json/schema"


def _schemas(schema: Dict[str, Any], **components: Any) -> ProviderSchemas:
    """A provider document whose one response body has the given schema."""
    return ProviderSchemas(
        {
            "openapi": "3.0.3",
            "paths": {
                "/things": {
                    "get": {
                        "responses": {"200": {"content": {"application/json": {"schema": schema}}}}
                    }
                }
            },
            "components": {"schemas": components},
        }
    )


def _outcome(
    matcher: Dict[str, Any],
    schema: Dict[str, Any],
    example: Any,
    *,
    path: str = "$",
    direction: str = RESPONSE,
    site: Optional[str] = SITE,
    **components: Any,
):
    (rule,) = parse_matching_rules({"body": {path: {"matchers": [matcher]}}}, "/r")
    return evaluate_rule(
        rule,
        direction=direction,
        schemas=_schemas(schema, **components),
        site=site,
        example=example,
    )


# =============================================================================================
# Reading rules
# =============================================================================================


def test_pact_2_rules_are_filed_by_their_key() -> None:
    rules = parse_matching_rules(
        {
            "$.body.items[*].id": {"match": "type"},
            "$.body": {"match": "type"},
            "$.headers.X-Trace": {"regex": "[a-z]+"},
            "$.headers['Content-Type']": {"match": "regex", "regex": "json"},
            "$.query.limit": {"match": "regex", "regex": "\\d+"},
            "$.path": {"match": "regex", "regex": "/a/\\d+"},
            "$.method": {"match": "equality"},
        },
        "/interactions/0/request/matchingRules",
    )

    assert [(rule.category, rule.path, rule.kind) for rule in rules] == [
        ("body", "$", "type"),
        ("body", "$.items[*].id", "type"),
        ("header", "X-Trace", "regex"),
        ("header", "Content-Type", "regex"),
        ("unknown", "$.method", "equality"),
        ("path", "", "regex"),
        ("query", "limit", "regex"),
    ]
    assert rules[1].pointer == "/interactions/0/request/matchingRules/$.body.items[*].id"


def test_pact_3_and_4_rules_are_filed_by_category() -> None:
    rules = parse_matching_rules(
        {
            "body": {"$.id": {"matchers": [{"match": "integer"}], "combine": "AND"}},
            "header": {"X-Trace": {"matchers": [{"match": "regex", "regex": "a"}]}},
            "query": {"q": {"matchers": [{"match": "include", "value": "a"}]}},
            "path": {"matchers": [{"match": "regex", "regex": "/a"}]},
            "status": {"matchers": [{"match": "statusCode", "status": "success"}]},
            "metadata": {"contentType": {"matchers": [{"match": "type"}]}},
        },
        "/m",
    )

    assert [(rule.category, rule.path, rule.kind, rule.pointer) for rule in rules] == [
        ("body", "$.id", "integer", "/m/body/$.id/matchers/0"),
        ("header", "X-Trace", "regex", "/m/header/X-Trace/matchers/0"),
        ("unknown", "metadata", "unknown", "/m/metadata"),
        ("path", "", "regex", "/m/path/matchers/0"),
        ("query", "q", "include", "/m/query/q/matchers/0"),
        ("status", "", "statuscode", "/m/status/matchers/0"),
    ]


def test_several_matchers_on_one_path_keep_their_combination() -> None:
    rules = parse_matching_rules(
        {"body": {"$.a": {"combine": "OR", "matchers": [{"match": "integer"}, {"match": "null"}]}}},
        "/m",
    )

    assert [(rule.kind, rule.combine, rule.siblings) for rule in rules] == [
        ("integer", "OR", 2),
        ("null", "OR", 2),
    ]


@pytest.mark.parametrize(
    "matcher, kind",
    [
        ({"match": "Type"}, "type"),
        ({"regex": "a"}, "regex"),
        ({"min": 2}, "type"),
        ({"match": "min", "min": 2}, "type"),
        ({"match": "notEmpty"}, "notempty"),
        ({}, "unknown"),
    ],
)
def test_matcher_is_named_even_when_match_is_implied(matcher: Dict[str, Any], kind: str) -> None:
    (rule,) = parse_matching_rules({"$.body.a": matcher}, "/m")
    assert rule.kind == kind


def test_a_rule_that_is_no_matcher_is_still_accounted_for() -> None:
    (rule,) = parse_matching_rules({"body": {"$.a": "type"}}, "/m")
    assert (rule.kind, rule.pointer) == ("unknown", "/m/body/$.a")
    assert parse_matching_rules(None, "/m") == []
    assert parse_matching_rules({}, "/m") == []


@pytest.mark.parametrize(
    "expression, steps",
    [
        ("$", []),
        ("$.a.b", ["a", "b"]),
        ("$.items[*].id", ["items", None, "id"]),
        ("$[0]['a b'][\"c\"]", [0, "a b", "c"]),
        ("$.a.*", ["a", None]),
        ("$['it\\'s']", ["it's"]),
        ("a.b", None),
        ("$.a[?(@.b)]", None),
        ("$..a", None),
    ],
)
def test_parse_path(expression: str, steps: Any) -> None:
    assert parse_path(expression) == steps


def test_select_path_returns_concrete_locations_in_order() -> None:
    body = {"items": [{"id": 1}, {"id": 2, "x": 0}], "meta": {"b": 1, "a": 2}}

    assert select_path(body, ["items", None, "id"]) == [
        (("items", 0, "id"), 1),
        (("items", 1, "id"), 2),
    ]
    assert select_path(body, ["meta", None]) == [(("meta", "a"), 2), (("meta", "b"), 1)]
    assert select_path(body, ["items", 5]) == []
    assert select_path(body, ["missing"]) == []
    assert select_path(body, []) == [((), body)]
    assert len(select_path(list(range(1000)), [None])) == MAX_RULE_LOCATIONS


# =============================================================================================
# The mapping table
# =============================================================================================


@pytest.mark.parametrize(
    "kind, matcher, example, direction, constraint",
    [
        ("type", {}, "a", RESPONSE, {"type": "string"}),
        ("type", {}, 5, RESPONSE, {"type": "number"}),
        ("type", {}, 5, REQUEST, {"type": "integer"}),
        ("type", {}, 5.5, REQUEST, {"type": "number"}),
        ("type", {}, True, RESPONSE, {"type": "boolean"}),
        ("type", {}, None, RESPONSE, {"type": "null"}),
        ("type", {}, {"a": 1}, RESPONSE, {"type": "object"}),
        (
            "type",
            {"min": 2, "max": 9},
            [1, 2],
            RESPONSE,
            {"type": "array", "minItems": 2, "maxItems": 9},
        ),
        ("type", {"min": 2}, "not an array", RESPONSE, {"type": "string"}),
        ("equality", {}, {"a": [1]}, RESPONSE, {"const": {"a": [1]}}),
        ("regex", {"regex": "^a+$"}, "aa", RESPONSE, {"type": "string", "pattern": "^a+$"}),
        ("include", {"value": "a.b"}, "xa.by", RESPONSE, {"type": "string", "pattern": "a\\.b"}),
        ("integer", {}, 1, RESPONSE, {"type": "integer"}),
        ("number", {}, 1, RESPONSE, {"type": "number"}),
        ("boolean", {}, True, RESPONSE, {"type": "boolean"}),
        ("null", {}, None, RESPONSE, {"type": "null"}),
        ("notempty", {}, "a", RESPONSE, {"type": "string", "minLength": 1}),
        ("notempty", {}, [1], RESPONSE, {"type": "array", "minItems": 1}),
        ("notempty", {}, {"a": 1}, RESPONSE, {"type": "object", "minProperties": 1}),
        ("notempty", {}, 3, REQUEST, {"type": "integer"}),
    ],
)
def test_mapped_matchers(
    kind: str, matcher: Any, example: Any, direction: str, constraint: Any
) -> None:
    assert rule_constraint(kind, matcher, example, direction) == constraint


@pytest.mark.parametrize(
    "kind",
    [
        "decimal",
        "date",
        "time",
        "timestamp",
        "datetime",
        "semver",
        "values",
        "eachkey",
        "eachvalue",
        "arraycontains",
        "contenttype",
        "statuscode",
        "unknown",
        "soundslike",
    ],
)
def test_matchers_without_a_lossless_mapping(kind: str) -> None:
    assert rule_constraint(kind, {"regex": "x", "value": "x"}, "x", RESPONSE) is None


def test_regex_and_include_need_their_operand() -> None:
    assert rule_constraint("regex", {}, "a", RESPONSE) is None
    assert rule_constraint("include", {"value": 3}, "a", RESPONSE) is None


def test_mapping_table_agrees_with_the_implementation() -> None:
    documented = {}
    for mapping in MATCHER_MAPPINGS:
        for name in mapping.matcher.split(" / "):
            documented[name.lower()] = mapping.constraint is not None
    assert len(documented) == 21

    samples = {"array": [1], "string": "a"}
    for name, mapped in documented.items():
        constraint = rule_constraint(
            name, {"regex": "a", "value": "a"}, samples["string"], RESPONSE
        )
        assert (constraint is not None) is mapped, name


@pytest.mark.parametrize(
    "value, name",
    [
        (None, "null"),
        (True, "boolean"),
        (1, "integer"),
        (1.5, "number"),
        ("a", "string"),
        ([], "array"),
        ({}, "object"),
    ],
)
def test_json_type(value: Any, name: str) -> None:
    assert json_type(value) == name


def test_schema_types() -> None:
    assert schema_types({"type": "string"}) == {"string"}
    assert schema_types({"type": ["string", "null"]}) == {"string", "null"}
    assert schema_types({"const": 3}) == {"integer"}
    assert schema_types({"enum": ["a", None]}) == {"string", "null"}
    assert schema_types({}) is None
    assert schema_types(True) is None


# =============================================================================================
# What the provider's schema proves
# =============================================================================================


def test_response_type_rule_is_proven_by_the_same_type() -> None:
    schema = {"type": "object", "properties": {"n": {"type": "integer"}, "s": {"type": "string"}}}

    assert _outcome({"match": "type"}, schema, {"n": 1}, path="$.n").status == "verified"
    # Pact's number type accepts a fraction; an integer provider never sends one.
    assert _outcome({"match": "type"}, schema, {"s": "a"}, path="$.s").status == "verified"


@pytest.mark.parametrize(
    "schema, reason",
    [
        ({"type": "string", "nullable": True}, "provider-nullable"),
        ({"type": ["string", "integer"]}, "provider-broader"),
        ({"description": "anything"}, "provider-type-undeclared"),
        ({"oneOf": [{"type": "string"}, {"type": "integer"}]}, "composition"),
        ({"allOf": [{"type": "string"}]}, "composition"),
    ],
)
def test_response_type_rule_the_schema_does_not_prove(schema: Any, reason: str) -> None:
    outcome = _outcome(
        {"match": "type"}, {"type": "object", "properties": {"s": schema}}, {"s": "a"}, path="$.s"
    )

    assert (outcome.status, outcome.reason) == ("unverified", reason)
    assert outcome.constraint == {"type": "string"}
    assert outcome.locations == 1
    if reason != "composition":
        assert outcome.oas_pointer == f"{SITE}/properties/s"


def test_response_regex_is_proven_only_by_the_same_pattern() -> None:
    matcher = {"match": "regex", "regex": "^a+$"}

    assert _outcome(matcher, {"type": "string", "pattern": "^a+$"}, "aa").status == "verified"
    assert (
        _outcome(matcher, {"type": "string", "pattern": "^a*$"}, "aa").reason
        == "pattern-not-guaranteed"
    )
    # A provider enum is not evaluated against the pact's expression (it is tenant input).
    assert (
        _outcome(matcher, {"type": "string", "enum": ["a", "aa"]}, "aa").reason
        == "pattern-not-guaranteed"
    )


def test_response_equality_needs_a_fixed_value() -> None:
    matcher = {"match": "equality"}

    assert _outcome(matcher, {"const": "USD"}, "USD").status == "verified"
    assert _outcome(matcher, {"enum": ["USD"]}, "USD").status == "verified"
    assert _outcome(matcher, {"enum": ["USD", "EUR"]}, "USD").reason == "value-not-guaranteed"
    assert _outcome(matcher, {"type": "string"}, "USD").reason == "value-not-guaranteed"
    assert _outcome(matcher, {"const": 1}, True).reason == "value-not-guaranteed"


def test_response_bounds_need_the_provider_to_promise_them() -> None:
    items = {"type": "array", "items": {"type": "integer"}}

    assert (
        _outcome({"match": "type", "min": 1}, {**items, "minItems": 2}, [1, 2]).status == "verified"
    )
    assert (
        _outcome({"match": "type", "min": 3}, {**items, "minItems": 2}, [1, 2, 3]).reason
        == "bounds-not-guaranteed"
    )
    assert _outcome({"match": "type", "max": 3}, {**items, "maxItems": 3}, [1]).status == "verified"
    assert _outcome({"match": "type", "max": 3}, items, [1]).reason == "bounds-not-guaranteed"
    assert (
        _outcome({"match": "notEmpty"}, {"type": "string", "minLength": 1}, "a").status
        == "verified"
    )
    assert (
        _outcome({"match": "notEmpty"}, {"type": "string"}, "a").reason == "bounds-not-guaranteed"
    )


def test_request_rule_is_proven_when_the_provider_is_not_narrower() -> None:
    def request(matcher: Any, schema: Any, example: Any):
        return _outcome(matcher, schema, example, direction=REQUEST)

    assert request({"match": "type"}, {"type": "string"}, "a").status == "verified"
    assert request({"match": "type"}, {}, "a").status == "verified"
    assert request({"match": "type"}, {"type": "number"}, 5).status == "verified"
    assert request({"match": "type"}, {"type": "string", "minLength": 0}, "a").status == "verified"
    assert (
        request({"match": "equality"}, {"type": "string", "enum": ["a"]}, "a").status == "verified"
    )
    assert (
        request(
            {"match": "regex", "regex": "^a$"}, {"type": "string", "pattern": "^a$"}, "a"
        ).status
        == "verified"
    )
    assert (
        request({"match": "notEmpty"}, {"type": "string", "minLength": 1}, "a").status == "verified"
    )
    bounded = {"type": "array", "minItems": 1, "maxItems": 9, "items": {"type": "integer"}}
    assert request({"match": "type", "min": 1, "max": 5}, bounded, [1]).status == "verified"
    # Where the provider says nothing about a value, it accepts whatever the consumer sends ...
    assert request({"match": "type"}, {"type": "array"}, [1]).status == "verified"
    # ... but promises nothing about what it returns.
    assert _outcome({"match": "type"}, {"type": "array"}, [1]).reason == "path-not-declared"
    assert (
        request({"match": "type"}, {"type": "object", "minProperties": 1}, {"a": 1}).status
        == "verified"
    )


@pytest.mark.parametrize(
    "matcher, schema, example",
    [
        ({"match": "type"}, {"type": "string", "enum": ["a", "b"]}, "a"),
        ({"match": "type"}, {"type": "string", "maxLength": 3}, "a"),
        ({"match": "type"}, {"type": "string", "pattern": "^a$"}, "a"),
        ({"match": "type"}, {"type": "integer", "minimum": 1}, 5),
        ({"match": "number"}, {"type": "integer"}, 5),
        ({"match": "regex", "regex": "^a$"}, {"type": "string", "pattern": "^a+$"}, "a"),
        ({"match": "type"}, {"type": "array", "minItems": 1}, [1]),
        ({"match": "type", "min": 1}, {"type": "array", "maxItems": 5}, [1]),
        ({"match": "type"}, {"type": "array", "uniqueItems": True}, [1]),
        ({"match": "notEmpty"}, {"type": "string", "minLength": 2}, "ab"),
    ],
)
def test_request_rule_the_provider_is_narrower_than(
    matcher: Any, schema: Any, example: Any
) -> None:
    outcome = _outcome(matcher, schema, example, direction=REQUEST)
    assert (outcome.status, outcome.reason) == ("unverified", "provider-narrower")


def test_type_rule_cascades_until_a_more_specific_rule() -> None:
    schema = {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "note": {"type": "string", "nullable": True},
            "lines": {"type": "array", "items": {"$ref": "#/components/schemas/Line"}},
        },
    }
    line = {"type": "object", "properties": {"sku": {"type": "string"}, "qty": {"type": "integer"}}}
    body = {"id": 1, "note": "n", "lines": [{"sku": "a", "qty": 1}, {"sku": "b", "qty": 2}]}
    schemas = _schemas(schema, Line=line)
    (rule,) = parse_matching_rules({"$.body": {"match": "type"}}, "/m")

    cascade = evaluate_rule(rule, direction=RESPONSE, schemas=schemas, site=SITE, example=body)
    assert (cascade.status, cascade.reason, cascade.locations) == (
        "unverified",
        "provider-nullable",
        1,
    )
    assert cascade.oas_pointer == f"{SITE}/properties/note"

    # A rule on $.note takes that value out of the cascade.
    handed_over = evaluate_rule(
        rule, direction=RESPONSE, schemas=schemas, site=SITE, example=body, other_paths=[["note"]]
    )
    assert handed_over.status == "verified"


def test_rule_through_references_and_all_of_is_located() -> None:
    schema = {
        "allOf": [
            {"$ref": "#/components/schemas/Base"},
            {"type": "object", "properties": {"b": {"type": "string"}}},
        ]
    }
    base = {"type": "object", "properties": {"a": {"$ref": "#/components/schemas/Id"}}}

    outcome = _outcome(
        {"match": "integer"}, schema, {"a": 1}, path="$.a", Base=base, Id={"type": "string"}
    )

    assert (outcome.status, outcome.reason) == ("unverified", "provider-broader")
    assert outcome.oas_pointer == "/components/schemas/Id"
    assert (
        _outcome({"match": "type"}, schema, {"b": "x"}, path="$.b", Base=base, Id={}).status
        == "verified"
    )


def test_rule_outcomes_that_need_no_schema() -> None:
    assert (
        _outcome({"match": "type"}, {"type": "object"}, {"a": 1}, path="$.b").reason
        == "path-not-in-example"
    )
    assert (
        _outcome({"match": "type"}, {"type": "object"}, {"a": 1}, path="$.a").reason
        == "path-not-declared"
    )
    assert (
        _outcome({"match": "type"}, {}, {"a": 1}, path="$.a", site=None).reason
        == "no-provider-schema"
    )
    assert _outcome({"match": "type"}, {}, 1, path="$..a").reason == "path-not-understood"
    not_mapped = _outcome({"match": "decimal"}, {"type": "number"}, 1.5)
    assert (not_mapped.status, not_mapped.reason) == ("not-mapped", "no-lossless-mapping")
    assert _outcome({"match": "decimal"}, {}, 1.5, site=None).status == "not-mapped"


def test_or_combined_status_and_unknown_rules_are_not_mapped() -> None:
    schemas = _schemas({"type": "string"})

    def run(rule: MatchingRule):
        return evaluate_rule(rule, direction=RESPONSE, schemas=schemas, site=SITE, example="a")

    assert run(MatchingRule("body", "$", "type", {}, "/p", "OR", 2)).reason == "combined-with-or"
    assert run(MatchingRule("body", "$", "type", {}, "/p", "OR", 1)).status == "verified"
    assert run(MatchingRule("status", "", "statuscode", {}, "/p")).reason == "no-lossless-mapping"
    assert run(MatchingRule("unknown", "x", "type", {}, "/p")).reason == "unknown-location"


def test_every_reason_the_engine_gives_is_documented() -> None:
    assert set(UNVERIFIED_REASONS) >= {
        "no-provider-schema",
        "path-not-in-example",
        "path-not-declared",
        "composition",
        "provider-narrower",
        "provider-nullable",
        "provider-broader",
        "provider-type-undeclared",
        "pattern-not-guaranteed",
        "value-not-guaranteed",
        "bounds-not-guaranteed",
        "budget-exhausted",
    }
    assert set(NOT_MAPPED_REASONS) == {
        "no-lossless-mapping",
        "combined-with-or",
        "path-not-understood",
        "unknown-location",
    }


def test_rule_work_is_bounded_per_rule_and_per_comparison() -> None:
    schema = {"type": "array", "items": {"type": "array", "items": {"type": "integer"}}}
    schemas = _schemas(schema)
    body = [[1] * 500 for _ in range(500)]
    (rule,) = parse_matching_rules({"$.body": {"match": "type"}}, "/m")

    budget = [1_000]
    outcome = evaluate_rule(
        rule, direction=RESPONSE, schemas=schemas, site=SITE, example=body, budget=budget
    )
    # 250,000 values below the rule, of which one rule looks at no more than its own ceiling.
    assert outcome.status == "verified"
    assert 1_000 - budget[0] == MAX_RULE_LOCATIONS + 1

    spent = evaluate_rule(
        rule, direction=RESPONSE, schemas=schemas, site=SITE, example=body, budget=[0]
    )
    assert (spent.status, spent.reason) == ("unverified", "budget-exhausted")
    # A rule with no mapping stays "not mapped" whatever the budget.
    (unmapped,) = parse_matching_rules({"$.body": {"match": "decimal"}}, "/m")
    assert (
        evaluate_rule(
            unmapped, direction=RESPONSE, schemas=schemas, site=SITE, example=body, budget=[0]
        ).status
        == "not-mapped"
    )

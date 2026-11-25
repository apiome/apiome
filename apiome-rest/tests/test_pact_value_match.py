"""Unit tests for the verifier's matching engine — PFX-3.2 (#6932).

:mod:`app.pact_value_match` decides whether a live response satisfies a pact's example under its
matching rules. Covered here:

* with no rule a value must be equal, extra response fields are ignored, missing ones are not;
* each matcher the engine applies, passing and failing (table-driven);
* rule resolution — the most specific path wins, type matchers cascade, ``AND`` / ``OR`` combine;
* headers — presence, equality, ``Content-Type`` parameters, header rules;
* **nothing passes silently**: a rule that cannot be applied is a mismatch naming the rule;
* every mismatch names the field (JSONPath and JSON Pointer), the rule and where the pact declares it.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

from app.contract_suite import PactMatchingRuleEntry, PactResponseExpectation
from app.pact_value_match import (
    MAX_MISMATCHES,
    PART_BODY,
    PART_HEADER,
    RULE_EQUALITY,
    RULE_PRESENCE,
    Mismatch,
    date_format_pattern,
    match_body,
    match_headers,
    match_response,
    mismatch_rule,
)


def _rule(
    path: str, matcher: Dict[str, Any], *, category: str = "body", combine: str = "AND", n: int = 0
) -> PactMatchingRuleEntry:
    """A matching rule as the PFX-3.1 compiler files it."""
    return PactMatchingRuleEntry(
        category=category,
        path=path,
        match=str(matcher.get("match", "type")).lower(),
        matcher=matcher,
        combine=combine,
        pointer=f"/interactions/0/response/matchingRules/{category}/{path}/matchers/{n}",
    )


def _expect(
    body: Any, rules: Optional[List[PactMatchingRuleEntry]] = None, *, media_type: Optional[str] = "application/json"
) -> PactResponseExpectation:
    """An expected response with a body."""
    return PactResponseExpectation(
        status=200, has_body=True, body=body, media_type=media_type, matching_rules=rules or []
    )


def _body(expected: Any, actual: Any, rules: Optional[List[PactMatchingRuleEntry]] = None) -> List[Mismatch]:
    """Compare a JSON body."""
    return match_body(_expect(expected, rules), json.dumps(actual).encode(), "application/json")


# ---------------------------------------------------------------------------
# No rules: equality, with the response allowed to say more
# ---------------------------------------------------------------------------


def test_an_identical_body_matches() -> None:
    assert _body({"id": 1, "tags": ["a", "b"]}, {"id": 1, "tags": ["a", "b"]}) == []


def test_extra_response_fields_are_ignored() -> None:
    assert _body({"id": 1}, {"id": 1, "added": True, "more": {"x": 1}}) == []


def test_a_missing_field_is_a_presence_mismatch_naming_its_pointer() -> None:
    (mismatch,) = _body({"id": 1, "customer": {"name": "Ada"}}, {"id": 1, "customer": {}})
    assert (mismatch.part, mismatch.rule, mismatch.rule_pointer) == (PART_BODY, RULE_PRESENCE, None)
    assert mismatch.path == "$.customer.name"
    assert mismatch.pointer == "/customer/name"
    assert mismatch.actual is None


def test_a_different_value_is_an_equality_mismatch_with_both_values() -> None:
    (mismatch,) = _body({"status": "open"}, {"status": "void"})
    assert mismatch.rule == RULE_EQUALITY
    assert (mismatch.expected, mismatch.actual) == ('"open"', '"void"')
    assert mismatch.message == '$.status: expected "open", got "void" (rule: equality)'
    assert mismatch_rule(mismatch.message) == "equality"


def test_an_array_without_a_rule_must_have_the_same_length() -> None:
    (mismatch,) = _body({"items": [1, 2]}, {"items": [1, 2, 3]})
    assert mismatch.pointer == "/items"
    assert "expected 2 item(s), got 3" in mismatch.message


def test_true_is_not_one_and_an_integer_equals_its_decimal() -> None:
    assert _body({"n": 1}, {"n": 1.0}) == []
    assert [m.pointer for m in _body({"flag": True}, {"flag": 1})] == ["/flag"]


def test_a_wrong_container_type_is_reported_once() -> None:
    (mismatch,) = _body({"lines": [{"sku": "A"}]}, {"lines": {"sku": "A"}})
    assert "expected an array, got object" in mismatch.message


# ---------------------------------------------------------------------------
# Matchers
# ---------------------------------------------------------------------------

_MATCHERS = [
    ({"match": "type"}, "x", "y", True),
    ({"match": "type"}, "x", 5, False),
    ({"match": "type"}, 1, 2.5, True),
    ({"match": "type"}, None, None, True),
    ({"match": "type"}, None, "x", False),
    ({"match": "equality"}, "x", "x", True),
    ({"match": "equality"}, "x", "y", False),
    ({"match": "regex", "regex": "^[A-Z]{3}$"}, "EUR", "USD", True),
    ({"match": "regex", "regex": "^[A-Z]{3}$"}, "EUR", "usd", False),
    ({"match": "regex", "regex": "^\\d+$"}, "1", 42, True),
    ({"match": "regex", "regex": "^\\d+$"}, "1", {"a": 1}, False),
    ({"match": "include", "value": "cat"}, "a cat", "concatenate", True),
    ({"match": "include", "value": "cat"}, "a cat", "dog", False),
    ({"match": "integer"}, 1, 7, True),
    ({"match": "integer"}, 1, 7.5, False),
    ({"match": "integer"}, 1, "7", False),
    ({"match": "integer"}, 1, True, False),
    ({"match": "decimal"}, 1.5, 2.25, True),
    ({"match": "decimal"}, 1.5, 2, False),
    ({"match": "number"}, 1, 2.25, True),
    ({"match": "number"}, 1, "2", False),
    ({"match": "boolean"}, True, False, True),
    ({"match": "boolean"}, True, "false", False),
    ({"match": "null"}, None, None, True),
    ({"match": "null"}, None, 0, False),
    ({"match": "notEmpty"}, "x", "y", True),
    ({"match": "notEmpty"}, "x", "", False),
    ({"match": "notEmpty"}, [1], [], False),
    ({"match": "semver"}, "1.0.0", "2.3.4-rc.1+build", True),
    ({"match": "semver"}, "1.0.0", "v2", False),
    ({"match": "date", "format": "yyyy-MM-dd"}, "2026-01-02", "2027-12-31", True),
    ({"match": "date", "format": "yyyy-MM-dd"}, "2026-01-02", "31/12/2027", False),
    ({"match": "date"}, "2026-01-02", "2027-12-31", True),
    ({"match": "time", "format": "HH:mm:ss"}, "10:00:00", "23:59:59", True),
    ({"match": "time", "format": "HH:mm:ss"}, "10:00:00", "noon", False),
    ({"match": "timestamp", "format": "yyyy-MM-dd'T'HH:mm:ss.SSSXXX"}, "", "2026-11-25T10:00:00.123Z", True),
    ({"match": "timestamp", "format": "yyyy-MM-dd'T'HH:mm:ss.SSSXXX"}, "", "2026-11-25T10:00:00+01:00", False),
    ({"match": "datetime", "format": "yyyy-MM-dd'T'HH:mm:ssXXX"}, "", "2026-11-25T10:00:00+01:00", True),
    ({"match": "datetime", "format": "yyyy-MM-dd'T'HH:mm:ssXXX"}, "", 20261125, False),
]


@pytest.mark.parametrize("matcher, example, actual, matches", _MATCHERS)
def test_each_scalar_matcher(matcher: Dict[str, Any], example: Any, actual: Any, matches: bool) -> None:
    found = _body({"v": example}, {"v": actual}, [_rule("$.v", matcher)])
    assert (found == []) is matches, found
    if not matches:
        assert found[0].rule == matcher["match"].lower()
        assert found[0].pointer == "/v"
        assert found[0].rule_pointer == "/interactions/0/response/matchingRules/body/$.v/matchers/0"


def test_min_and_max_bound_the_array_the_rule_is_on() -> None:
    example = {"items": [{"id": 1}]}
    low = _body(example, {"items": []}, [_rule("$.items", {"match": "type", "min": 1})])
    assert [m.message for m in low] == ["$.items: expected at least 1 item(s), got 0 (rule: type)"]
    high = _body(example, {"items": [{"id": 1}, {"id": 2}, {"id": 3}]}, [_rule("$.items", {"match": "type", "max": 2})])
    assert [m.message for m in high] == ["$.items: expected at most 2 item(s), got 3 (rule: type)"]


def test_a_type_rule_cascades_to_every_item_and_field_beneath_it() -> None:
    rules = [_rule("$.items", {"match": "type", "min": 1})]
    example = {"items": [{"id": 1, "name": "a"}]}
    assert _body(example, {"items": [{"id": 9, "name": "z"}, {"id": 10, "name": "y", "extra": 1}]}, rules) == []
    (mismatch,) = _body(example, {"items": [{"id": 9, "name": "z"}, {"id": "ten", "name": "y"}]}, rules)
    assert (mismatch.pointer, mismatch.path, mismatch.rule) == ("/items/1/id", "$.items[1].id", "type")


def test_a_non_cascading_rule_applies_only_where_it_is_declared() -> None:
    # A regex on $.meta says nothing about $.meta.code, which stays under equality.
    rules = [_rule("$.other", {"match": "regex", "regex": "x"})]
    (mismatch,) = _body({"meta": {"code": "A"}, "other": "x"}, {"meta": {"code": "B"}, "other": "x"}, rules)
    assert (mismatch.pointer, mismatch.rule) == ("/meta/code", RULE_EQUALITY)


def test_the_most_specific_path_wins() -> None:
    rules = [
        _rule("$.items[*].id", {"match": "type"}),
        _rule("$.items[0].id", {"match": "equality"}),
        _rule("$.items", {"match": "type"}),
    ]
    found = _body({"items": [{"id": 1}]}, {"items": [{"id": 2}, {"id": 3}]}, rules)
    assert [(m.pointer, m.rule) for m in found] == [("/items/0/id", "equality")]


def test_a_wildcard_field_rule_reaches_every_field() -> None:
    rules = [_rule("$.entry.*", {"match": "type"})]
    assert _body({"entry": {"a": 1, "b": "x"}}, {"entry": {"a": 5, "b": "y"}}, rules) == []
    (mismatch,) = _body({"entry": {"a": 1, "b": "x"}}, {"entry": {"a": "5", "b": "y"}}, rules)
    assert mismatch.pointer == "/entry/a"


def test_and_needs_every_matcher_and_or_needs_one() -> None:
    both = [
        _rule("$.v", {"match": "regex", "regex": "^a"}, n=0),
        _rule("$.v", {"match": "regex", "regex": "z$"}, n=1),
    ]
    assert [m.rule for m in _body({"v": "az"}, {"v": "ab"}, both)] == ["regex"]
    either = [rule.model_copy(update={"combine": "OR"}) for rule in both]
    assert _body({"v": "az"}, {"v": "ab"}, either) == []
    assert len(_body({"v": "az"}, {"v": "b"}, either)) == 2


def test_values_ignores_keys_and_matches_values() -> None:
    rules = [_rule("$.prices", {"match": "values"}), _rule("$.prices.*", {"match": "type"})]
    assert _body({"prices": {"eur": 1.0}}, {"prices": {"usd": 2.5, "gbp": 3}}, rules) == []
    (mismatch,) = _body({"prices": {"eur": 1.0}}, {"prices": {"usd": "free"}}, rules)
    assert mismatch.pointer == "/prices/usd"


def test_each_key_and_each_value_apply_their_nested_rules() -> None:
    keys = [_rule("$.by_code", {"match": "eachKey", "rules": [{"match": "regex", "regex": "^[A-Z]{2}$"}]})]
    assert _body({"by_code": {"DE": 1}}, {"by_code": {"FR": 1, "IT": 1}}, keys) == []
    (bad_key,) = _body({"by_code": {"DE": 1}}, {"by_code": {"France": 1}}, keys)
    assert (bad_key.pointer, bad_key.rule) == ("/by_code/France", "eachkey")

    values = [_rule("$.tags", {"match": "eachValue", "rules": [{"match": "type"}]})]
    assert _body({"tags": {"a": "x"}}, {"tags": {"b": "y", "c": "z"}}, values) == []
    (bad_value,) = _body({"tags": {"a": "x"}}, {"tags": {"b": 1}}, values)
    assert (bad_value.pointer, bad_value.rule) == ("/tags/b", "type")


def test_each_value_with_no_example_has_no_type_to_compare() -> None:
    values = [_rule("$.tags", {"match": "eachValue", "rules": [{"match": "type"}]})]
    assert _body({"tags": {}}, {"tags": {"b": 1, "c": "z"}}, values) == []
    strict = [_rule("$.tags", {"match": "eachValue", "rules": [{"match": "integer"}]})]
    assert [m.pointer for m in _body({"tags": {}}, {"tags": {"b": 1, "c": "z"}}, strict)] == ["/tags/c"]


def test_array_contains_needs_one_item_per_variant() -> None:
    rule = _rule(
        "$.actions",
        {
            "match": "arrayContains",
            "variants": [
                {
                    "index": 0,
                    "rules": {"$.href": {"combine": "AND", "matchers": [{"match": "regex", "regex": "^/a/"}]}},
                },
                {"index": 1, "rules": {}},
            ],
        },
    )
    example = {"actions": [{"name": "edit", "href": "/a/1"}, {"name": "delete"}]}
    ok = {"actions": [{"name": "delete"}, {"name": "other"}, {"name": "edit", "href": "/a/77"}]}
    assert _body(example, ok, [rule]) == []
    (mismatch,) = _body(example, {"actions": [{"name": "edit", "href": "/a/2"}]}, [rule])
    assert mismatch.rule == "arraycontains"
    assert "no item matches variant 1" in mismatch.message


# ---------------------------------------------------------------------------
# Nothing passes silently
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "matcher, fragment",
    [
        ({"match": "contentType", "value": "image/png"}, "cannot be applied"),
        ({"match": "telepathy"}, "is not one this verifier applies"),
        ({"match": "regex", "regex": "("}, "does not compile"),
        ({"match": "regex"}, "states no regex"),
        ({"match": "date", "format": "QQQ yyyy"}, "pattern letter this verifier does not read"),
        ({"match": "eachValue", "rules": []}, "lists no matchers"),
        ({"match": "arrayContains", "variants": []}, "lists no variants"),
    ],
)
def test_a_rule_that_cannot_be_applied_fails_and_names_itself(matcher: Dict[str, Any], fragment: str) -> None:
    actual: Any = [1] if matcher["match"] == "arrayContains" else {"a": 1} if matcher["match"] == "eachValue" else "x"
    example: Any = [1] if matcher["match"] == "arrayContains" else {"a": 1} if matcher["match"] == "eachValue" else "x"
    (mismatch,) = _body({"v": example}, {"v": actual}, [_rule("$.v", matcher)])
    assert mismatch.rule == matcher["match"].lower()
    assert fragment in mismatch.message
    assert mismatch.rule_pointer is not None


def test_a_runaway_regex_is_stopped_and_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.pact_value_match as engine

    def never_finishes(pattern: str, subject: str, timeout: float) -> None:
        assert timeout > 0
        raise TimeoutError

    monkeypatch.setattr(engine.regex, "search", never_finishes)
    rules = [_rule("$.v", {"match": "regex", "regex": "^(a+)+$"})]
    (mismatch,) = _body({"v": "aa"}, {"v": "a" * 40 + "!"}, rules)
    assert "did not finish" in mismatch.message
    assert mismatch.rule == "regex"


def test_an_overlong_regex_or_value_is_refused_rather_than_run() -> None:
    long_pattern = [_rule("$.v", {"match": "regex", "regex": "a" * 3000})]
    assert "longer than" in _body({"v": "a"}, {"v": "a"}, long_pattern)[0].message
    long_value = [_rule("$.v", {"match": "regex", "regex": "a"})]
    assert "longer than" in _body({"v": "a"}, {"v": "a" * 200_001}, long_value)[0].message


def test_a_rule_path_that_is_not_a_jsonpath_is_reported() -> None:
    (mismatch,) = _body({"v": 1}, {"v": 1}, [_rule("body.v", {"match": "type"})])
    assert "is not a JSONPath" in mismatch.message


def test_an_undecodable_expected_body_cannot_be_compared() -> None:
    expectation = PactResponseExpectation(status=200, has_body=True, body=None, media_type="application/json")
    (mismatch,) = match_body(expectation, b'{"a":1}', "application/json")
    assert "cannot be decoded" in mismatch.message


def test_mismatches_are_capped() -> None:
    example = {str(n): n for n in range(MAX_MISMATCHES + 20)}
    actual = {key: -1 for key in example}
    assert len(_body(example, actual)) == MAX_MISMATCHES


# ---------------------------------------------------------------------------
# Bodies that are not what was expected
# ---------------------------------------------------------------------------


def test_no_expected_body_accepts_any_body() -> None:
    assert match_body(PactResponseExpectation(status=204), b"anything at all", None) == []


def test_a_json_expectation_refuses_a_non_json_or_empty_response() -> None:
    (not_json,) = match_body(_expect({"a": 1}), b"<html>oops</html>", "text/html")
    assert "not JSON (Content-Type: text/html)" in not_json.message
    (empty,) = match_body(_expect({"a": 1}), b"", None)
    assert empty.rule == RULE_PRESENCE


def test_a_text_body_is_compared_as_text_or_by_a_rule_on_the_whole_body() -> None:
    plain = _expect("hello world", media_type="text/plain")
    assert match_body(plain, b"hello world", "text/plain") == []
    assert [m.rule for m in match_body(plain, b"goodbye", "text/plain")] == [RULE_EQUALITY]
    ruled = _expect("hello world", [_rule("$", {"match": "regex", "regex": "^hello"})], media_type="text/plain")
    assert match_body(ruled, b"hello there", "text/plain") == []


def test_a_field_rule_on_a_text_body_cannot_be_applied() -> None:
    expectation = _expect("<a>1</a>", [_rule("$.a", {"match": "type"})], media_type="application/xml")
    found = match_body(expectation, b"<a>1</a>", "application/xml")
    assert [m.rule for m in found] == ["type"]
    assert "not JSON" in found[0].message


# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------


def test_recorded_headers_must_be_present_whatever_their_case() -> None:
    assert match_headers({"X-Request-Id": "abc"}, [], {"x-request-id": "abc", "server": "nginx"}) == []
    (mismatch,) = match_headers({"X-Request-Id": "abc"}, [], {"server": "nginx"})
    assert (mismatch.part, mismatch.path, mismatch.rule) == (PART_HEADER, "X-Request-Id", RULE_PRESENCE)


def test_a_content_type_may_add_parameters_but_not_change_recorded_ones() -> None:
    assert (
        match_headers({"Content-Type": "application/json"}, [], {"content-type": "application/json; charset=utf-8"})
        == []
    )
    assert (
        match_headers(
            {"Content-Type": "application/json; charset=utf-8"}, [], {"content-type": "application/json;charset=UTF-8"}
        )
        == []
    )
    assert (
        len(
            match_headers({"Content-Type": "application/json; charset=utf-8"}, [], {"content-type": "application/json"})
        )
        == 1
    )
    assert len(match_headers({"Content-Type": "application/json"}, [], {"content-type": "text/plain"})) == 1


def test_spacing_after_commas_is_not_a_difference() -> None:
    assert match_headers({"Vary": "Accept, Origin"}, [], {"vary": "Accept,Origin"}) == []
    assert len(match_headers({"Vary": "Accept, Origin"}, [], {"vary": "Accept"})) == 1


def test_a_header_rule_replaces_equality() -> None:
    rules = [_rule("Location", {"match": "regex", "regex": "^/invoices/\\d+$"}, category="header")]
    assert match_headers({"Location": "/invoices/1"}, rules, {"location": "/invoices/9001"}) == []
    (mismatch,) = match_headers({"Location": "/invoices/1"}, rules, {"location": "/orders/1"})
    assert (mismatch.rule, mismatch.path) == ("regex", "Location")
    assert mismatch_rule(mismatch.message) == "regex"


def test_a_number_rule_reads_a_header_as_a_number() -> None:
    rules = [_rule("X-Count", {"match": "integer"}, category="header")]
    assert match_headers({"X-Count": "1"}, rules, {"x-count": "250"}) == []
    assert len(match_headers({"X-Count": "1"}, rules, {"x-count": "many"})) == 1


def test_match_response_reports_headers_then_body() -> None:
    expectation = PactResponseExpectation(
        status=200,
        headers={"Content-Type": "application/json"},
        has_body=True,
        body={"id": 1},
        media_type="application/json",
    )
    found = match_response(expectation, headers={"Content-Type": "text/plain"}, content=b'{"id": 2}')
    assert [m.part for m in found] == [PART_HEADER, PART_BODY]


# ---------------------------------------------------------------------------
# Date formats
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fmt, value",
    [
        ("yyyy-MM-dd", "2026-11-25"),
        ("dd/MM/yy", "25/11/26"),
        ("yyyy-MM-dd'T'HH:mm:ss'Z'", "2026-11-25T10:00:00Z"),
        ("yyyy-MM-dd'T'HH:mm:ss.SSSZ", "2026-11-25T10:00:00.000+0100"),
        ("EEE, dd MMM yyyy HH:mm:ss z", "Wed, 25 Nov 2026 10:00:00 GMT"),
        ("h:mm a", "9:05 PM"),
        ("yyyy-MM-dd'T'HH:mm:ssXXX", "2026-11-25T10:00:00-07:00"),
        ("HH 'o''clock'", "10 o'clock"),
    ],
)
def test_date_formats_translate_to_a_shape(fmt: str, value: str) -> None:
    import re

    pattern = date_format_pattern(fmt)
    assert pattern is not None
    assert re.match(pattern, value), (pattern, value)
    assert not re.match(pattern, value + "!")


def test_an_unreadable_date_format_is_none() -> None:
    assert date_format_pattern("yyyy 'unterminated") is None
    assert date_format_pattern("GGGG") is None


def test_mismatch_rule_reads_only_a_trailing_rule() -> None:
    assert mismatch_rule("$.a: bad (rule: mintype)") == "mintype"
    assert mismatch_rule("no rule here") is None
    assert mismatch_rule(None) is None

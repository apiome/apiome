"""Cache trace evaluation — UXE-3.1 (private-suite#2473).

Pure tests over :func:`app.slate_cache.evaluate_trace`, which answers acceptance criterion 2:
"rule trace explains eligibility, key, TTL, bypass, and winning rule for a test request."

Each of those five clauses is asserted individually, so a trace that answers four of them is a
failure rather than a partial pass.

Determinism gets its own class. It is asserted as a property over shuffled inputs rather than
on one example, because the failure mode being guarded — a verdict that depends on the order
rows came back from Postgres — would pass any single-example test.
"""

from __future__ import annotations

import itertools
import random
from datetime import datetime, timedelta, timezone

import pytest

from app.slate_cache import (
    TraceRequest,
    evaluate_trace,
    matches_route,
    normalize_rule,
    rules_digest,
)

NOW = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)


def rule(**overrides):
    """A matching, cacheable rule; each test states only the field it is about."""
    base = {
        "id": "rule-1",
        "ordinal": 0,
        "enabled": True,
        "label": "Docs HTML",
        "matcher_kind": "prefix",
        "matcher_value": "/docs",
        "matcher_methods": ["GET"],
        "matcher_hosts": [],
        "eligibility": "cacheable",
        "browser_ttl_seconds": 30,
        "edge_ttl_seconds": 60,
        "stale_while_revalidate_seconds": 90,
        "stale_if_error_seconds": 120,
        "cache_key_base": "host-url",
        "vary_query_mode": "none",
        "vary_query_keys": [],
        "vary_headers": [],
        "vary_cookies": [],
        "bypass_conditions": [],
        "expires_at": None,
    }
    base.update(overrides)
    return base


def request(**overrides) -> TraceRequest:
    """A GET for /docs/intro on docs.example.com."""
    base = {"method": "GET", "host": "docs.example.com", "path": "/docs/intro"}
    base.update(overrides)
    return TraceRequest(**base)


def trace(rules=None, preset="standard", req=None, now=NOW):
    """Run a trace with the suite's defaults."""
    return evaluate_trace(
        request=req or request(),
        preset_key=preset,
        rules=rules if rules is not None else [rule()],
        now=now,
    )


class TestTraceAnswersEveryClause:
    """Criterion 2, clause by clause."""

    def test_eligibility_is_reported_with_a_reason(self) -> None:
        verdict = trace()
        assert verdict.eligibility == "cacheable"
        assert "Docs HTML" in verdict.eligibility_reason

    def test_cache_key_is_rendered_and_broken_into_components(self) -> None:
        verdict = trace()
        assert verdict.cache_key == "docs.example.com|/docs/intro"
        sources = [c["source"] for c in verdict.cache_key_components]
        assert sources == ["host", "path"]
        for component in verdict.cache_key_components:
            assert component["contributed_because"], "every key component states why it is there"

    def test_every_ttl_is_reported_with_its_source(self) -> None:
        verdict = trace()
        assert verdict.browser_ttl_seconds == 30
        assert verdict.edge_ttl_seconds == 60
        assert verdict.stale_while_revalidate_seconds == 90
        assert verdict.stale_if_error_seconds == 120
        assert "Docs HTML" in verdict.ttl_source

    def test_bypass_is_reported_even_when_it_did_not_fire(self) -> None:
        verdict = trace()
        assert verdict.bypassed is False
        assert verdict.bypass_reason is None

    def test_the_winning_rule_is_named(self) -> None:
        verdict = trace()
        assert verdict.winning_rule_id == "rule-1"
        assert verdict.winning_rule_label == "Docs HTML"


class TestWinnerSelection:
    """Precedence, and the reasons losing rules give."""

    def test_the_lowest_matching_ordinal_wins(self) -> None:
        verdict = trace(
            [
                rule(id="late", ordinal=10, label="Late", edge_ttl_seconds=999),
                rule(id="early", ordinal=1, label="Early", edge_ttl_seconds=5),
            ]
        )
        assert verdict.winning_rule_id == "early"
        assert verdict.edge_ttl_seconds == 5

    def test_every_rule_is_reported_not_only_the_winner(self) -> None:
        verdict = trace(
            [
                rule(id="a", ordinal=0, label="A"),
                rule(id="b", ordinal=1, label="B"),
                rule(id="c", ordinal=2, label="C"),
            ]
        )
        assert [c["rule_id"] for c in verdict.considered] == ["a", "b", "c"]
        for entry in verdict.considered:
            assert entry["reason"], f"{entry['rule_id']} lost without saying why"

    def test_rules_after_the_winner_are_marked_not_reached(self) -> None:
        verdict = trace([rule(id="a", ordinal=0), rule(id="b", ordinal=1)])
        outcomes = {c["rule_id"]: c["outcome"] for c in verdict.considered}
        assert outcomes == {"a": "matched", "b": "not-reached"}
        assert "already decided" in [c for c in verdict.considered if c["rule_id"] == "b"][0][
            "reason"
        ]

    def test_a_disabled_rule_is_considered_and_skipped_not_absent(self) -> None:
        """"Why did my rule not fire" is the question a trace exists to answer."""
        verdict = trace([rule(id="off", enabled=False)])
        entry = verdict.considered[0]
        assert entry["outcome"] == "skipped"
        assert entry["reason"] == "Disabled."

    def test_an_expired_rule_is_considered_and_skipped_with_its_expiry(self) -> None:
        expired = rule(id="old", expires_at=NOW - timedelta(days=1))
        verdict = trace([expired])
        entry = verdict.considered[0]
        assert entry["outcome"] == "skipped"
        assert "Expired at" in entry["reason"]

    def test_a_rule_expiring_later_still_applies(self) -> None:
        future = rule(id="live", expires_at=NOW + timedelta(days=1))
        assert trace([future]).winning_rule_id == "live"

    def test_a_non_matching_rule_says_what_did_not_match(self) -> None:
        verdict = trace([rule(id="other", matcher_value="/blog")])
        entry = verdict.considered[0]
        assert entry["outcome"] == "skipped"
        assert "/blog" in entry["reason"]
        assert "/docs/intro" in entry["reason"]

    def test_the_preset_decides_when_no_expert_rule_matches(self) -> None:
        """A preset deciding is an answer, not a missing winner."""
        verdict = trace([rule(matcher_value="/blog")], preset="aggressive")
        assert verdict.winning_rule_id is None
        assert "Aggressive" in verdict.winning_rule_label
        assert verdict.edge_ttl_seconds == 600

    def test_the_preset_decides_when_there_are_no_rules_at_all(self) -> None:
        verdict = trace([], preset="standard")
        assert verdict.winning_rule_id is None
        assert verdict.edge_ttl_seconds == 60
        assert verdict.considered == []


class TestMatching:
    """Matcher semantics, including the ones that silently widen if got wrong."""

    @pytest.mark.parametrize(
        ("kind", "value", "path", "expected"),
        [
            ("exact", "/docs/intro", "/docs/intro", True),
            ("exact", "/docs", "/docs/intro", False),
            ("prefix", "/docs", "/docs/intro", True),
            # Prefix is textual, not segment-aware, so /docs also selects /docsearch. That is
            # deliberate: purge-by-prefix uses the same comparison, and a rule whose scope
            # differed from the purge that targets it would make a trace misleading. Operators
            # who want the section only write "/docs/".
            ("prefix", "/docs", "/docsearch", True),
            ("prefix", "/docs/", "/docsearch", False),
            ("prefix", "/blog", "/docs/intro", False),
            ("glob", "/docs/*", "/docs/intro", True),
            ("glob", "/_next/static/**", "/_next/static/a/b.js", True),
            ("glob", "/docs/*", "/blog/intro", False),
            ("regex", r"^/docs/", "/docs/intro", True),
            ("regex", r"^/blog/", "/docs/intro", False),
        ],
    )
    def test_matcher_kinds(self, kind, value, path, expected) -> None:
        candidate = normalize_rule(rule(matcher_kind=kind, matcher_value=value))
        assert matches_route(candidate, request(path=path).normalized()) is expected

    def test_a_method_outside_the_matcher_does_not_match(self) -> None:
        candidate = normalize_rule(rule(matcher_methods=["GET"]))
        assert matches_route(candidate, request(method="POST").normalized()) is False

    def test_an_empty_host_list_matches_every_host(self) -> None:
        candidate = normalize_rule(rule(matcher_hosts=[]))
        assert matches_route(candidate, request(host="other.example.com").normalized()) is True

    def test_a_host_scoped_rule_does_not_match_another_host(self) -> None:
        candidate = normalize_rule(rule(matcher_hosts=["docs.example.com"]))
        assert matches_route(candidate, request(host="www.example.com").normalized()) is False

    def test_an_uncompilable_regex_matches_nothing_rather_than_raising(self) -> None:
        """The write already refused it; a trace over historical data must still render."""
        candidate = normalize_rule(rule(matcher_kind="regex", matcher_value="([unclosed"))
        assert matches_route(candidate, request().normalized()) is False


class TestCacheKey:
    """The key is what answers "why is this cached separately for every reader"."""

    def test_url_no_query_base_omits_host_and_query(self) -> None:
        verdict = trace(
            [rule(cache_key_base="url-no-query", vary_query_mode="all")],
            req=request(query={"page": "2"}),
        )
        assert verdict.cache_key == "/docs/intro"

    def test_vary_all_puts_every_query_parameter_in_the_key(self) -> None:
        verdict = trace(
            [rule(vary_query_mode="all")],
            req=request(query={"page": "2", "utm_source": "x"}),
        )
        assert "page=2" in verdict.cache_key
        assert "utm_source=x" in verdict.cache_key

    def test_an_allowlist_admits_only_the_named_parameters(self) -> None:
        verdict = trace(
            [rule(vary_query_mode="allowlist", vary_query_keys=["page"])],
            req=request(query={"page": "2", "utm_source": "x"}),
        )
        assert "page=2" in verdict.cache_key
        assert "utm_source" not in verdict.cache_key

    def test_a_denylist_excludes_only_the_named_parameters(self) -> None:
        verdict = trace(
            [rule(vary_query_mode="denylist", vary_query_keys=["utm_source"])],
            req=request(query={"page": "2", "utm_source": "x"}),
        )
        assert "page=2" in verdict.cache_key
        assert "utm_source" not in verdict.cache_key

    def test_query_order_does_not_change_the_key(self) -> None:
        """Otherwise two identical requests would occupy two cache entries."""
        a = trace([rule(vary_query_mode="all")], req=request(query={"a": "1", "b": "2"}))
        b = trace([rule(vary_query_mode="all")], req=request(query={"b": "2", "a": "1"}))
        assert a.cache_key == b.cache_key

    def test_a_varied_header_enters_the_key_with_its_value(self) -> None:
        verdict = trace(
            [rule(vary_headers=["Accept-Language"])],
            req=request(headers={"Accept-Language": "en"}),
        )
        assert "accept-language:en" in verdict.cache_key

    def test_a_missing_varied_header_still_contributes_an_empty_component(self) -> None:
        """Absence is a variant too; collapsing it would merge two distinct responses."""
        verdict = trace([rule(vary_headers=["Accept-Language"])])
        names = [c["name"] for c in verdict.cache_key_components]
        assert "accept-language" in names


class TestBypass:
    """Bypass overrides everything the rule otherwise said."""

    def test_a_present_cookie_condition_bypasses(self) -> None:
        verdict = trace(
            [rule(bypass_conditions=[{"kind": "cookie", "name": "preview"}])],
            req=request(cookies={"preview": "1"}),
        )
        assert verdict.bypassed is True
        assert "cookie preview is present" in verdict.bypass_reason

    def test_an_absent_cookie_condition_does_not_bypass(self) -> None:
        verdict = trace([rule(bypass_conditions=[{"kind": "cookie", "name": "preview"}])])
        assert verdict.bypassed is False

    def test_an_equals_condition_only_fires_on_the_value(self) -> None:
        conditions = [{"kind": "query", "name": "mode", "equals": "debug"}]
        assert trace([rule(bypass_conditions=conditions)], req=request(query={"mode": "debug"})).bypassed
        assert not trace(
            [rule(bypass_conditions=conditions)], req=request(query={"mode": "normal"})
        ).bypassed

    def test_a_header_condition_is_matched_case_insensitively(self) -> None:
        verdict = trace(
            [rule(bypass_conditions=[{"kind": "header", "name": "X-Debug"}])],
            req=request(headers={"x-debug": "1"}),
        )
        assert verdict.bypassed is True

    def test_a_method_condition_fires_on_the_method(self) -> None:
        verdict = trace(
            [
                rule(
                    matcher_methods=["GET", "POST"],
                    bypass_conditions=[{"kind": "method", "equals": "POST"}],
                )
            ],
            req=request(method="POST"),
        )
        assert verdict.bypassed is True

    def test_a_bypass_zeroes_every_ttl_and_forces_no_store(self) -> None:
        """A bypassed response that still reported a TTL would be reporting a lie."""
        verdict = trace(
            [rule(bypass_conditions=[{"kind": "cookie", "name": "preview"}])],
            req=request(cookies={"preview": "1"}),
        )
        assert verdict.eligibility == "no-store"
        assert verdict.browser_ttl_seconds == 0
        assert verdict.edge_ttl_seconds == 0
        assert verdict.stale_while_revalidate_seconds == 0
        assert verdict.stale_if_error_seconds == 0
        assert "bypass condition" in verdict.eligibility_reason

    def test_a_malformed_bypass_condition_is_ignored_rather_than_raising(self) -> None:
        verdict = trace([rule(bypass_conditions=["not-a-condition", {"kind": "nonsense"}])])
        assert verdict.bypassed is False


class TestDeterminism:
    """The property the whole feature rests on."""

    def test_the_verdict_does_not_depend_on_input_order(self) -> None:
        rules = [
            rule(id=f"r{i}", ordinal=i, label=f"R{i}", matcher_value=f"/docs/{i}")
            for i in range(6)
        ] + [rule(id="win", ordinal=99, label="Catch all", matcher_value="/docs")]
        baseline = trace(rules)
        rng = random.Random(20260719)
        for _ in range(200):
            shuffled = rules[:]
            rng.shuffle(shuffled)
            verdict = trace(shuffled)
            assert verdict.winning_rule_id == baseline.winning_rule_id
            assert verdict.cache_key == baseline.cache_key
            assert verdict.edge_ttl_seconds == baseline.edge_ttl_seconds
            assert verdict.eligibility == baseline.eligibility
            assert verdict.rules_digest == baseline.rules_digest

    def test_repeated_evaluation_is_identical(self) -> None:
        assert trace() == trace()

    def test_the_digest_is_stable_across_key_reordering(self) -> None:
        a = rules_digest([rule()])
        reordered = dict(reversed(list(rule().items())))
        assert rules_digest([reordered]) == a

    def test_the_digest_changes_when_a_ttl_changes(self) -> None:
        """A digest that survived a policy change could not certify anything."""
        assert rules_digest([rule()]) != rules_digest([rule(edge_ttl_seconds=61)])

    def test_the_digest_ignores_a_rename(self) -> None:
        """Renaming a rule must not invalidate the traces that already explained it."""
        assert rules_digest([rule()]) == rules_digest([rule(label="Renamed")])

    def test_the_digest_ignores_disabled_rules(self) -> None:
        assert rules_digest([rule()]) == rules_digest([rule(), rule(id="x", ordinal=7, enabled=False)])

    def test_the_digest_matches_the_column_constraint(self) -> None:
        """V187 CHECKs rules_digest against exactly this shape."""
        import re

        assert re.fullmatch(r"sha256:[0-9a-f]{64}", rules_digest([rule()]))

    def test_the_empty_ruleset_has_a_digest_too(self) -> None:
        assert rules_digest([]).startswith("sha256:")


class TestTraceWarnings:
    """The trace surfaces the same vocabulary the write path refuses on."""

    def test_a_costly_winning_rule_carries_its_warning(self) -> None:
        verdict = trace([rule(vary_query_mode="all")])
        assert "vary-query-all" in [w["code"] for w in verdict.warnings]

    def test_a_stored_rule_that_became_unsafe_is_reported_not_raised(self) -> None:
        """An operator debugging a leak needs the verdict; a trace is a read."""
        verdict = trace([rule(vary_cookies=["session"])])
        codes = [w["code"] for w in verdict.warnings]
        assert "identity-in-cache-key" in codes
        assert verdict.winning_rule_id == "rule-1", "the trace still renders a verdict"

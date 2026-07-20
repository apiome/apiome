"""Policy simulation and determinism digests — UXE-3.2 (private-suite#2474).

Pure tests over :func:`app.slate_security.simulate_request`, which answers the acceptance
criterion that makes "every block can be investigated" true: a simulation reports the deciding
rule **and every rule that lost, with the reason it lost**.

Three properties get disproportionate attention, because each fails quietly and each fails during
an incident:

* **Nothing is omitted.** A rule that did not fire is reported as considered-and-skipped with a
  sentence. "Why did my rule not fire" is the question the surface exists to answer, and a rule
  that is simply absent from the answer reads as a rule that does not exist.
* **A simulate-mode rule reports ``would-block`` and never ``blocked``.** That is the honesty
  boundary of a staged rollout, and it is asserted as a property over the whole verdict rather
  than on one example: an event stream that recorded a simulated denial as a real one would tell
  an operator they were protected when they were not.
* **Same inputs, same output.** ``now`` is a parameter, so a verdict is reproducible from its
  recorded inputs — and :class:`TestPurity` proves the parameter is load-bearing by moving it and
  watching an expiry-dependent verdict change.
"""

from __future__ import annotations

import random
import re
from datetime import datetime, timedelta, timezone

import pytest

from app.slate_security import (
    EVENT_ACTIONS,
    MANAGED_GROUPS,
    MANAGED_RULESETS,
    SimulationRequest,
    body_digest,
    rules_digest,
    simulate_request,
)

NOW = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)


def rule(**overrides):
    """A matching, enforcing rule; each test states only the field it is about."""
    base = {
        "id": "rule-1",
        "ordinal": 0,
        "enabled": True,
        "label": "API keys guard",
        "matcher_kind": "prefix",
        "matcher_value": "/docs/api/",
        "matcher_methods": [],
        "matcher_hosts": [],
        "conditions": [],
        "action": "block",
        "rate_requests": None,
        "rate_window_seconds": None,
        "rollout_mode": "enforce",
        "rollout_percent": 100,
        "previous_rollout_percent": 50,
        "simulated_at": NOW - timedelta(days=1),
        "expires_at": None,
        "acknowledged_warnings": [],
        "author_actor_key": "actor-author",
        "approvals": [],
    }
    base.update(overrides)
    return base


def request(**overrides) -> SimulationRequest:
    """A GET for /docs/api/keys on docs.example.com, classified human, no burst."""
    base = {"method": "GET", "host": "docs.example.com", "path": "/docs/api/keys"}
    base.update(overrides)
    return SimulationRequest(**base)


def exception(**overrides):
    """A scoped, live carve-out for the rule under test."""
    base = {
        "id": "exc-1",
        "subject_kind": "rule",
        "subject_ref": "rule-1",
        "matcher_kind": "prefix",
        "matcher_value": "/docs/api/",
        "expires_at": NOW + timedelta(days=7),
        "reason": "Partner integration reads the key reference.",
    }
    base.update(overrides)
    return base


def sim(rules=None, *, policy=None, groups=(), exceptions=(), req=None, now=NOW):
    """Run a simulation with the suite's defaults."""
    return simulate_request(
        request=req or request(),
        policy=policy,
        managed_groups=groups,
        rules=[] if rules is None else rules,
        exceptions=exceptions,
        now=now,
    )


def entries(verdict, kind=None):
    """The considered entries, optionally of one kind, in evaluation order."""
    return [e for e in verdict.considered if kind is None or e["kind"] == kind]


class TestTheHonestyBoundary:
    """Nothing here blocks anything, and no argument exists with which to claim otherwise."""

    def test_a_verdict_never_claims_enforcement_observation_or_mitigation(self) -> None:
        verdict = sim([rule()])
        assert verdict.enforced is False
        assert verdict.observed is False
        assert verdict.mitigated is False

    def test_the_basis_is_always_policy_simulation(self) -> None:
        assert sim([rule()]).basis == "policy-simulation"

    def test_no_policy_field_can_make_the_verdict_claim_an_edge(self) -> None:
        """The corresponding V188 CHECKs are backstops; this is the mechanism."""
        verdict = sim(
            [rule()],
            policy={"edge_attached": True, "edge_provider": "some-cdn"},
        )
        assert verdict.enforced is False
        assert verdict.observed is False
        assert verdict.mitigated is False
        assert verdict.basis == "policy-simulation"

    @pytest.mark.parametrize("mode", ["simulate", "enforce"])
    def test_the_reported_action_is_always_from_the_declared_vocabulary(self, mode) -> None:
        verdict = sim([rule(rollout_mode=mode)])
        assert verdict.action in EVENT_ACTIONS
        for entry in verdict.considered:
            assert entry["action"] is None or entry["action"] in EVENT_ACTIONS


class TestSimulateModeNeverReportsARealDenial:
    """The single most important claim in the evaluator."""

    @pytest.mark.parametrize("action", ["block", "challenge", "rate-limit"])
    def test_a_simulate_mode_denial_reports_would_block(self, action) -> None:
        verdict = sim([rule(action=action, rollout_mode="simulate")])
        assert verdict.action == "would-block"
        assert verdict.rollout_mode == "simulate"

    @pytest.mark.parametrize("action", ["block", "challenge", "rate-limit"])
    def test_nothing_in_the_verdict_says_blocked_while_the_rule_is_simulating(self, action) -> None:
        """Asserted over the whole structure, not only the headline action."""
        verdict = sim([rule(action=action, rollout_mode="simulate")])
        assert verdict.action != "blocked"
        assert [e["action"] for e in entries(verdict, "rule")] == ["would-block"]

    def test_the_sentence_says_it_acted_on_nothing(self) -> None:
        verdict = sim([rule(rollout_mode="simulate")])
        assert "acts on nothing" in verdict.action_reason
        assert "would have done" in verdict.action_reason

    def test_an_enforcing_rule_reports_the_real_outcome(self) -> None:
        """The other direction: simulate must not swallow an enforcing decision."""
        assert sim([rule(action="block", rollout_mode="enforce")]).action == "blocked"

    @pytest.mark.parametrize(
        ("action", "expected"),
        [
            ("allow", "allowed"),
            ("log", "logged"),
            ("challenge", "challenged"),
            ("rate-limit", "rate-limited"),
            ("block", "blocked"),
        ],
    )
    def test_each_enforcing_action_maps_to_its_own_outcome(self, action, expected) -> None:
        verdict = sim([rule(action=action, rollout_mode="enforce")])
        assert entries(verdict, "rule")[0]["action"] == expected

    def test_a_simulating_allow_or_log_rule_is_not_reported_as_would_block(self) -> None:
        """`would-block` names a denial that did not happen, not any simulated rule."""
        for action in ("allow", "log"):
            verdict = sim([rule(action=action, rollout_mode="simulate")])
            assert entries(verdict, "rule")[0]["action"] != "would-block"


class TestEveryRuleIsAccountedFor:
    """A rule missing from the answer reads as a rule that does not exist."""

    def test_the_deciding_rule_is_named(self) -> None:
        verdict = sim([rule()])
        assert verdict.winning_rule_kind == "rule"
        assert verdict.winning_rule_ref == "rule-1"
        assert verdict.winning_rule_label == "API keys guard"
        assert verdict.action_reason

    def test_every_rule_appears_with_an_outcome_and_a_sentence(self) -> None:
        verdict = sim(
            [
                rule(id="a", ordinal=0, label="A", matcher_value="/blog/"),
                rule(id="b", ordinal=1, label="B"),
                rule(id="c", ordinal=2, label="C"),
            ]
        )
        rule_entries = entries(verdict, "rule")
        assert [e["ref"] for e in rule_entries] == ["a", "b", "c"]
        for entry in rule_entries:
            assert entry["outcome"] in ("matched", "skipped", "not-reached")
            assert entry["reason"], f"{entry['ref']} lost without saying why"

    def test_rules_are_evaluated_in_precedence_order_not_input_order(self) -> None:
        verdict = sim(
            [
                rule(id="late", ordinal=10, label="Late", action="block"),
                rule(id="early", ordinal=1, label="Early", action="challenge"),
            ]
        )
        assert verdict.winning_rule_ref == "early"
        assert verdict.action == "challenged"

    def test_rules_after_the_decision_are_marked_not_reached_and_name_the_decider(self) -> None:
        verdict = sim([rule(id="a", ordinal=0, label="A"), rule(id="b", ordinal=1, label="B")])
        outcomes = {e["ref"]: e["outcome"] for e in entries(verdict, "rule")}
        assert outcomes == {"a": "matched", "b": "not-reached"}
        later = [e for e in entries(verdict, "rule") if e["ref"] == "b"][0]
        assert "already decided" in later["reason"]
        assert '"A"' in later["reason"]

    def test_a_disabled_rule_is_considered_and_skipped_not_absent(self) -> None:
        """"Why did my rule not fire" is the question a simulation exists to answer."""
        verdict = sim([rule(id="off", enabled=False)])
        entry = entries(verdict, "rule")[0]
        assert entry["ref"] == "off"
        assert entry["outcome"] == "skipped"
        assert entry["reason"] == "Disabled."

    def test_a_rule_at_zero_rollout_is_skipped_and_says_it_reaches_no_traffic(self) -> None:
        verdict = sim([rule(rollout_percent=0)])
        entry = entries(verdict, "rule")[0]
        assert entry["outcome"] == "skipped"
        assert "0% rollout" in entry["reason"]

    def test_a_partial_rollout_states_that_the_request_is_treated_as_in_scope(self) -> None:
        """Sampling would make the same inputs produce different answers."""
        verdict = sim([rule(rollout_percent=5)])
        assert "treated as in scope" in verdict.action_reason

    def test_an_expired_rule_is_skipped_with_its_expiry(self) -> None:
        verdict = sim([rule(expires_at=NOW - timedelta(days=1))])
        entry = entries(verdict, "rule")[0]
        assert entry["outcome"] == "skipped"
        assert "Expired at" in entry["reason"]

    def test_a_rule_expiring_later_still_decides(self) -> None:
        assert sim([rule(expires_at=NOW + timedelta(days=1))]).winning_rule_ref == "rule-1"

    def test_a_non_matching_rule_names_both_the_matcher_and_the_request(self) -> None:
        verdict = sim([rule(matcher_value="/blog/")])
        entry = entries(verdict, "rule")[0]
        assert entry["outcome"] == "skipped"
        assert "/blog/" in entry["reason"]
        assert "/docs/api/keys" in entry["reason"]
        assert "GET" in entry["reason"]

    def test_a_logging_rule_matches_and_steps_aside(self) -> None:
        """Otherwise "log first, then enforce" would quietly shadow the rules behind it."""
        verdict = sim(
            [
                rule(id="watch", ordinal=0, label="Watch", action="log"),
                rule(id="act", ordinal=1, label="Act", action="challenge"),
            ]
        )
        outcomes = {e["ref"]: e["outcome"] for e in entries(verdict, "rule")}
        assert outcomes == {"watch": "matched", "act": "matched"}
        assert verdict.winning_rule_ref == "act"
        assert verdict.action == "challenged"

    def test_an_allow_rule_is_an_early_exit(self) -> None:
        """That is what lets a carve-out be expressed as a rule rather than a special case."""
        verdict = sim(
            [
                rule(id="permit", ordinal=0, label="Permit", action="allow"),
                rule(id="deny", ordinal=1, label="Deny", action="block"),
            ]
        )
        assert verdict.action == "allowed"
        assert verdict.winning_rule_ref == "permit"
        assert [e["outcome"] for e in entries(verdict, "rule")] == ["matched", "not-reached"]

    def test_nothing_matching_at_all_is_an_answer_rather_than_a_missing_winner(self) -> None:
        verdict = sim([rule(matcher_value="/blog/")])
        assert verdict.winning_rule_kind == "default"
        assert verdict.winning_rule_ref is None
        assert verdict.action == "allowed"
        assert "leaves it alone" in verdict.action_reason


class TestConditions:
    """V188 stores conditions as a list precisely so a simulation can name the one that failed."""

    def test_a_met_condition_lets_the_rule_decide(self) -> None:
        verdict = sim(
            [rule(conditions=[{"kind": "country", "equals": "FR"}])],
            req=request(country="fr"),
        )
        assert verdict.winning_rule_ref == "rule-1"

    @pytest.mark.parametrize(
        ("condition", "fragment"),
        [
            ({"kind": "country", "equals": "FR"}, "country is"),
            ({"kind": "asn", "equals": "AS64500"}, "ASN is"),
            ({"kind": "bot-class", "equals": "automated"}, "bot class is"),
            ({"kind": "header", "name": "X-Partner"}, "header X-Partner is absent"),
            ({"kind": "query", "name": "token"}, "query parameter token is absent"),
        ],
    )
    def test_an_unmet_condition_is_named_rather_than_reported_as_no_match(
        self, condition, fragment
    ) -> None:
        verdict = sim([rule(conditions=[condition])])
        entry = entries(verdict, "rule")[0]
        assert entry["outcome"] == "skipped"
        assert "Matched the route but not the condition" in entry["reason"]
        assert fragment in entry["reason"]

    def test_an_unrecognized_condition_narrows_the_rule_rather_than_widening_it(self) -> None:
        """An unknown predicate on a blocking rule must not be read as satisfied."""
        verdict = sim([rule(conditions=[{"kind": "phase-of-moon", "equals": "waxing"}])])
        entry = entries(verdict, "rule")[0]
        assert entry["outcome"] == "skipped"
        assert "not one this evaluator understands" in entry["reason"]

    def test_a_malformed_condition_entry_is_reported_rather_than_raising(self) -> None:
        verdict = sim([rule(conditions=["not-a-condition"])])
        assert entries(verdict, "rule")[0]["outcome"] == "skipped"
        assert "malformed condition" in entries(verdict, "rule")[0]["reason"]

    def test_a_header_condition_is_matched_case_insensitively(self) -> None:
        verdict = sim(
            [rule(conditions=[{"kind": "header", "name": "X-Partner", "equals": "acme"}])],
            req=request(headers={"x-partner": "acme"}),
        )
        assert verdict.winning_rule_ref == "rule-1"


class TestManagedGroups:
    """A group acts only when the request declares its signal — the simulation is not a detector."""

    def test_a_tripped_group_decides_and_explains_itself(self) -> None:
        verdict = sim(req=request(signals=("sql-injection",)))
        assert verdict.winning_rule_kind == "managed-group"
        assert verdict.winning_rule_ref == "sql-injection"
        assert verdict.action == "blocked"
        assert "block mode" in verdict.action_reason

    def test_every_group_in_the_tier_is_reported_even_when_it_did_nothing(self) -> None:
        verdict = sim()
        reported = [e["ref"] for e in entries(verdict, "managed-group")]
        assert reported == list(MANAGED_RULESETS["core"].groups)
        for entry in entries(verdict, "managed-group"):
            assert entry["reason"], f"{entry['ref']} was silent about why it did nothing"

    def test_a_group_that_the_request_does_not_trip_says_so(self) -> None:
        entry = [e for e in entries(verdict=sim(), kind="managed-group") if e["ref"] == "xss"][0]
        assert entry["outcome"] == "skipped"
        assert "does not trip" in entry["reason"]

    def test_a_group_logging_under_the_core_tier_does_not_decide(self) -> None:
        """Core runs cross-site scripting in log mode, so a tripped request still falls through."""
        verdict = sim(req=request(signals=("xss",)))
        xss = [e for e in entries(verdict, "managed-group") if e["ref"] == "xss"][0]
        assert xss["outcome"] == "matched"
        assert xss["action"] == "logged"
        assert verdict.winning_rule_kind != "managed-group"

    def test_the_strict_tier_makes_the_same_request_a_block(self) -> None:
        verdict = sim(policy={"managed_ruleset": "strict"}, req=request(signals=("xss",)))
        assert verdict.winning_rule_ref == "xss"
        assert verdict.action == "blocked"

    def test_the_off_tier_evaluates_no_group_at_all(self) -> None:
        verdict = sim(
            policy={"managed_ruleset": "off", "managed_off_reason": "INC-4821"},
            req=request(signals=("sql-injection",)),
        )
        assert entries(verdict, "managed-group") == []
        assert verdict.action == "allowed"

    def test_a_lane_override_stands_a_group_down_and_records_the_reason(self) -> None:
        verdict = sim(
            groups=[{"group_id": "sql-injection", "mode": "off", "reason": "search reflects SQL"}],
            req=request(signals=("sql-injection",)),
        )
        entry = [e for e in entries(verdict, "managed-group") if e["ref"] == "sql-injection"][0]
        assert entry["outcome"] == "skipped"
        assert "search reflects SQL" in entry["reason"]
        assert verdict.winning_rule_ref != "sql-injection"

    def test_an_override_for_a_group_the_tier_does_not_run_is_ignored(self) -> None:
        """The tier decides what runs; the override table only records deviations within it."""
        verdict = sim(
            policy={"managed_ruleset": "off", "managed_off_reason": "INC-4821"},
            groups=[{"group_id": "sql-injection", "mode": "block"}],
            req=request(signals=("sql-injection",)),
        )
        assert entries(verdict, "managed-group") == []
        assert verdict.action == "allowed"

    def test_groups_behind_a_decision_are_recorded_as_not_reached(self) -> None:
        verdict = sim(req=request(signals=("sql-injection", "protocol-anomaly")))
        after = [
            e
            for e in entries(verdict, "managed-group")
            if e["ref"] == "protocol-anomaly"
        ][0]
        assert after["outcome"] == "not-reached"
        assert "already decided" in after["reason"]

    def test_a_custom_rule_pre_empting_the_waf_still_lists_every_group(self) -> None:
        """"Why did the WAF not catch this" is answered by seeing the allow rule that stopped it."""
        verdict = sim(
            [rule(id="permit", label="Partner allow", action="allow")],
            req=request(signals=("sql-injection",)),
        )
        group_entries = entries(verdict, "managed-group")
        assert [e["ref"] for e in group_entries] == list(MANAGED_RULESETS["core"].groups)
        for entry in group_entries:
            assert entry["outcome"] == "not-reached"
            assert "Partner allow" in entry["reason"]

    def test_a_group_reports_its_catalog_title_not_its_id(self) -> None:
        entry = entries(sim(), "managed-group")[0]
        assert entry["label"] == MANAGED_GROUPS[entry["ref"]].title


class TestBotAndRatePresets:
    """The presets are the last things consulted, and they say what they did."""

    def test_a_human_request_is_not_acted_on_by_the_default_preset(self) -> None:
        entry = [e for e in entries(sim(), "bot-preset")][0]
        assert entry["outcome"] == "skipped"
        assert "human" in entry["reason"]

    def test_the_balanced_preset_challenges_definite_automation(self) -> None:
        verdict = sim(req=request(bot_class="automated"))
        assert verdict.winning_rule_kind == "bot-preset"
        assert verdict.action == "challenged"

    def test_the_balanced_preset_leaves_a_verified_crawler_alone(self) -> None:
        """A documentation site out of the search index is damaged as surely as one offline."""
        verdict = sim(req=request(bot_class="verified-bot"))
        assert verdict.action != "challenged"
        entry = entries(verdict, "bot-preset")[0]
        assert entry["action"] == "allowed"

    def test_the_aggressive_preset_challenges_the_likely_automated_class(self) -> None:
        verdict = sim(
            policy={"bot_preset": "aggressive"}, req=request(bot_class="likely-automated")
        )
        assert verdict.action == "challenged"

    def test_the_balanced_preset_does_not(self) -> None:
        verdict = sim(req=request(bot_class="likely-automated"))
        assert verdict.action != "challenged"

    def test_classification_off_is_reported_rather_than_omitted(self) -> None:
        verdict = sim(policy={"bot_preset": "off"}, req=request(bot_class="automated"))
        entry = entries(verdict, "bot-preset")[0]
        assert entry["outcome"] == "skipped"
        assert "off on this lane" in entry["reason"]

    def test_a_budget_that_is_not_exceeded_reports_the_numbers_anyway(self) -> None:
        entry = entries(sim(req=request(burst_requests=10)), "rate-preset")[0]
        assert entry["outcome"] == "skipped"
        assert "10 requests against a budget of 300" in entry["reason"]

    def test_an_exceeded_budget_decides_and_states_both_numbers(self) -> None:
        verdict = sim(req=request(burst_requests=500))
        assert verdict.winning_rule_kind == "rate-preset"
        assert verdict.action == "rate-limited"
        assert "500" in verdict.action_reason
        assert "300" in verdict.action_reason

    def test_the_generous_preset_reports_without_acting(self) -> None:
        verdict = sim(policy={"rate_preset": "generous"}, req=request(burst_requests=1000))
        entry = entries(verdict, "rate-preset")[0]
        assert entry["outcome"] == "matched"
        assert entry["action"] == "logged"
        assert verdict.winning_rule_kind == "default"

    def test_rate_limiting_off_is_reported_rather_than_omitted(self) -> None:
        verdict = sim(policy={"rate_preset": "off"}, req=request(burst_requests=10_000))
        entry = entries(verdict, "rate-preset")[0]
        assert entry["outcome"] == "skipped"
        assert "off on this lane" in entry["reason"]

    def test_an_unknown_preset_key_falls_back_to_the_safe_default(self) -> None:
        """A policy row from a future version must not make the surface unrenderable."""
        verdict = sim(policy={"bot_preset": "turbo", "rate_preset": "turbo"})
        assert entries(verdict, "bot-preset")[0]["ref"] == "balanced"
        assert entries(verdict, "rate-preset")[0]["ref"] == "standard"


class TestExceptions:
    """A carve-out suppresses a decision, and an expired one does not."""

    def test_a_live_exception_suppresses_the_rule_and_names_itself(self) -> None:
        verdict = sim([rule()], exceptions=[exception()])
        entry = entries(verdict, "rule")[0]
        assert entry["outcome"] == "skipped"
        assert "Suppressed by exception exc-1" in entry["reason"]
        assert "Partner integration" in entry["reason"]
        assert verdict.winning_rule_kind != "rule"

    def test_an_expired_exception_does_not_carve_anything_out(self) -> None:
        verdict = sim([rule()], exceptions=[exception(expires_at=NOW - timedelta(seconds=1))])
        assert verdict.winning_rule_ref == "rule-1"
        assert verdict.action == "blocked"

    def test_an_exception_expiring_exactly_now_has_lapsed(self) -> None:
        verdict = sim([rule()], exceptions=[exception(expires_at=NOW)])
        assert verdict.winning_rule_ref == "rule-1"

    def test_an_exception_outside_the_requests_route_does_not_apply(self) -> None:
        verdict = sim([rule()], exceptions=[exception(matcher_value="/blog/")])
        assert verdict.winning_rule_ref == "rule-1"

    def test_an_exception_for_another_subject_does_not_apply(self) -> None:
        verdict = sim([rule()], exceptions=[exception(subject_ref="some-other-rule")])
        assert verdict.winning_rule_ref == "rule-1"

    def test_a_policy_scoped_exception_covers_every_subject(self) -> None:
        verdict = sim(
            exceptions=[exception(subject_kind="policy", subject_ref="", matcher_value="/docs/")],
            req=request(signals=("sql-injection",)),
        )
        entry = [e for e in entries(verdict, "managed-group") if e["ref"] == "sql-injection"][0]
        assert entry["outcome"] == "skipped"
        assert "Suppressed by exception" in entry["reason"]
        assert verdict.action == "allowed"

    def test_an_exception_carves_out_a_managed_group_by_reference(self) -> None:
        verdict = sim(
            exceptions=[
                exception(
                    subject_kind="managed-group",
                    subject_ref="sql-injection",
                    matcher_value="/docs/",
                )
            ],
            req=request(signals=("sql-injection",)),
        )
        assert verdict.action == "allowed"

    def test_the_exception_reported_is_stable_when_several_apply(self) -> None:
        many = [exception(id=f"exc-{i}") for i in (3, 1, 2)]
        first = sim([rule()], exceptions=many)
        second = sim([rule()], exceptions=list(reversed(many)))
        assert entries(first, "rule")[0]["reason"] == entries(second, "rule")[0]["reason"]
        assert "exc-1" in entries(first, "rule")[0]["reason"]


class TestVerdictWarnings:
    """The simulation surfaces the same vocabulary the write path refuses on."""

    def test_a_costly_winning_rule_carries_its_warning(self) -> None:
        verdict = sim([rule(action="challenge", matcher_value="/guide", matcher_methods=["GET"])],
                      req=request(path="/guide/start"))
        codes = [w["code"] for w in verdict.warnings]
        assert "broad-matcher" in codes
        for warning in verdict.warnings:
            assert warning["message"], f"{warning['code']} reached the operator as a bare code"

    def test_a_stored_rule_that_became_unsafe_is_reported_not_raised(self) -> None:
        """An operator investigating a block needs the verdict; a simulation is a read."""
        verdict = sim([rule(action="block", rollout_mode="enforce", approvals=[])])
        codes = [w["code"] for w in verdict.warnings]
        assert "enforce-without-approval" in codes
        assert verdict.winning_rule_ref == "rule-1", "the simulation still renders a verdict"

    def test_a_verdict_decided_by_a_preset_carries_no_rule_warnings(self) -> None:
        assert sim(req=request(bot_class="automated")).warnings == []


class TestDeterminism:
    """Same inputs, same output. The property the recorded evidence rests on."""

    def test_simulating_twice_gives_an_identical_verdict(self) -> None:
        assert sim([rule()]) == sim([rule()])

    def test_the_verdict_does_not_depend_on_rule_input_order(self) -> None:
        rules = [
            rule(id=f"r{i}", ordinal=i, label=f"R{i}", matcher_value=f"/docs/api/{i}/")
            for i in range(6)
        ] + [rule(id="win", ordinal=99, label="Catch all", matcher_value="/docs/api/")]
        baseline = sim(rules)
        rng = random.Random(20260719)
        for _ in range(100):
            shuffled = rules[:]
            rng.shuffle(shuffled)
            assert sim(shuffled) == baseline

    def test_the_verdict_does_not_depend_on_group_override_order(self) -> None:
        overrides = [
            {"group_id": "sql-injection", "mode": "log"},
            {"group_id": "xss", "mode": "block"},
        ]
        assert sim(groups=overrides, req=request(signals=("xss",))) == sim(
            groups=list(reversed(overrides)), req=request(signals=("xss",))
        )

    def test_the_request_is_normalized_the_way_http_defines_case(self) -> None:
        loud = request(method="get", host="Docs.Example.COM", country="fr", bot_class="Automated")
        assert sim(req=loud) == sim(
            req=request(
                method="GET", host="docs.example.com", country="FR", bot_class="automated"
            )
        )

    def test_normalizing_a_request_leaves_the_original_untouched(self) -> None:
        original = request(method="get")
        original.normalized()
        assert original.method == "get"

    def test_the_verdict_carries_the_digest_of_the_ruleset_that_produced_it(self) -> None:
        rules = [rule()]
        assert sim(rules).rules_digest == rules_digest(rules)


class TestRulesDigest:
    """The receipt: a simulation that has drifted from the lane is explained by its digest."""

    def test_the_digest_matches_the_column_constraint(self) -> None:
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", rules_digest([rule()]))

    def test_the_empty_ruleset_has_a_digest_too(self) -> None:
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", rules_digest([]))

    def test_the_digest_is_stable_across_a_rename(self) -> None:
        """Renaming a rule must not invalidate the evidence that already explained it."""
        assert rules_digest([rule()]) == rules_digest([rule(label="Renamed during the incident")])

    def test_the_digest_is_stable_across_input_order(self) -> None:
        a = rule(id="a", ordinal=0, matcher_value="/docs/api/a/")
        b = rule(id="b", ordinal=1, matcher_value="/docs/api/b/")
        assert rules_digest([a, b]) == rules_digest([b, a])

    def test_the_digest_is_stable_across_key_reordering(self) -> None:
        reordered = dict(reversed(list(rule().items())))
        assert rules_digest([reordered]) == rules_digest([rule()])

    def test_the_digest_ignores_disabled_rules(self) -> None:
        """A disabled rule changes nothing about what the policy does."""
        assert rules_digest([rule()]) == rules_digest(
            [rule(), rule(id="x", ordinal=7, enabled=False)]
        )

    def test_the_digest_ignores_who_authored_and_approved_the_rules(self) -> None:
        assert rules_digest([rule()]) == rules_digest(
            [rule(author_actor_key="somebody-else", approvals=[{"approver_actor_key": "x"}])]
        )

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("ordinal", 9),
            ("matcher_kind", "glob"),
            ("matcher_value", "/docs/other/"),
            ("matcher_methods", ["GET"]),
            ("matcher_hosts", ["docs.example.com"]),
            ("conditions", [{"kind": "country", "equals": "FR"}]),
            ("action", "challenge"),
            ("rate_requests", 600),
            ("rate_window_seconds", 60),
            ("rollout_mode", "simulate"),
            ("rollout_percent", 25),
            ("expires_at", NOW),
        ],
    )
    def test_the_digest_changes_when_a_decisive_field_changes(self, field, value) -> None:
        assert rules_digest([rule()]) != rules_digest([rule(**{field: value})])

    def test_disabling_a_rule_changes_the_digest_of_a_ruleset_it_was_in(self) -> None:
        """Ignoring disabled rules must not mean ignoring the act of disabling one."""
        assert rules_digest([rule()]) != rules_digest([rule(enabled=False)])

    def test_a_single_rule_ruleset_agrees_with_nothing_about_its_body_digest(self) -> None:
        """The two digests answer different questions and must not be interchangeable."""
        assert rules_digest([rule()]) != body_digest(rule())

    def test_the_digest_is_repeatable(self) -> None:
        assert rules_digest([rule()]) == rules_digest([rule()])


class TestPurity:
    """``now`` is a parameter. These tests are what prove there is no clock behind it."""

    def test_moving_now_past_a_rule_expiry_changes_the_verdict(self) -> None:
        candidate = rule(expires_at=NOW + timedelta(hours=1))
        before = sim([candidate], now=NOW)
        after = sim([candidate], now=NOW + timedelta(hours=2))
        assert before.action == "blocked"
        assert before.winning_rule_ref == "rule-1"
        assert after.winning_rule_ref is None
        assert after.action == "allowed"
        assert "Expired at" in entries(after, "rule")[0]["reason"]

    def test_moving_now_past_an_exception_expiry_changes_the_verdict(self) -> None:
        carve_out = exception(expires_at=NOW + timedelta(hours=1))
        before = sim([rule()], exceptions=[carve_out], now=NOW)
        after = sim([rule()], exceptions=[carve_out], now=NOW + timedelta(hours=2))
        assert before.winning_rule_ref != "rule-1", "the carve-out held"
        assert after.winning_rule_ref == "rule-1", "the carve-out lapsed"

    def test_the_same_now_always_gives_the_same_verdict(self) -> None:
        candidate = rule(expires_at=NOW + timedelta(hours=1))
        assert sim([candidate], now=NOW) == sim([candidate], now=NOW)

    def test_a_verdict_from_the_distant_future_still_renders(self) -> None:
        """Nothing consults the wall clock, so an arbitrary `now` is simply another input."""
        verdict = sim([rule()], now=NOW + timedelta(days=3650))
        assert verdict.winning_rule_ref == "rule-1"

    def test_an_iso_string_expiry_is_read_the_same_as_a_datetime(self) -> None:
        iso = (NOW - timedelta(days=1)).isoformat().replace("+00:00", "Z")
        assert sim([rule(expires_at=iso)]).winning_rule_ref is None

    def test_an_unreadable_expiry_leaves_protection_on(self) -> None:
        """The failure mode of a bad timestamp must be a rule that stays, not one that vanishes."""
        assert sim([rule(expires_at="whenever")]).winning_rule_ref == "rule-1"

    def test_a_naive_now_does_not_raise_against_an_aware_expiry(self) -> None:
        naive = datetime(2026, 7, 19, 12, 0, 0)
        assert sim([rule(expires_at=NOW + timedelta(days=1))], now=naive).winning_rule_ref == "rule-1"

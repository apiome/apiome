"""Invocation simulation and determinism digests — UXE-3.3 (private-suite#2475).

Pure tests over :func:`app.slate_functions.simulate_invocation`, which answers the acceptance
criterion that makes "every decision can be investigated" true: a simulation reports the function
that won, the variant it selected, **and every function and variant that lost, with the reason it
lost**.

Four properties get disproportionate attention, because each fails quietly and each fails during
an incident:

* **Nothing is omitted.** A function that did not run is reported as considered-and-skipped with a
  sentence. "Why did my function not run" is the question the surface exists to answer, and a
  function simply absent from the answer reads as one that does not exist.
* **A denial is an outcome, not a refusal.** A function with no capability grant is configured
  legally and simply cannot do the thing, so it surfaces as ``capability-denied`` in the
  considered list. Refusing the write instead would either refuse ordinary functions or hide the
  denial that will actually happen in production.
* **Nothing ran.** ``executed``, ``observed`` and ``enforced`` are asserted as properties over
  every verdict the suite produces, not on one example: a row claiming an execution would be
  evidence of an isolation guarantee that was never tested.
* **Same inputs, same output.** ``now`` is a mandatory keyword parameter, so a recorded simulation
  can be re-checked later rather than merely believed — and :class:`TestPurity` proves the
  parameter is load-bearing by moving it and watching a grant-dependent verdict change.
"""

from __future__ import annotations

import random
import re
from datetime import datetime, timedelta, timezone

import pytest

from app.slate_functions import (
    CACHE_KEY_EFFECTS,
    INVOCATION_OUTCOMES,
    InvocationRequest,
    body_digest,
    functions_digest,
    simulate_invocation,
)

NOW = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)


def function(**overrides):
    """A matching, enforcing, fully-gated function; each test states only its own field."""
    base = {
        "id": "fn-1",
        "tenant_id": "tenant-1",
        "environment_id": "env-1",
        "ordinal": 0,
        "enabled": True,
        "label": "Geo banner",
        "matcher_kind": "prefix",
        "matcher_value": "/docs/guide/",
        "matcher_methods": [],
        "matcher_hosts": [],
        "runtime": "js-isolate",
        "active_version_id": "ver-1",
        "rollout_mode": "enforce",
        "rollout_percent": 100,
        "previous_rollout_percent": 50,
        "region": None,
        "residency_class": None,
        "cpu_ms_limit": None,
        "memory_mb_limit": None,
        "wall_ms_limit": None,
        "env_var_names": [],
        "declared_destinations": [],
        "acknowledged_warnings": [],
        "simulated_at": NOW - timedelta(days=1),
        "author_actor_key": "actor-author",
    }
    base.update(overrides)
    # The baseline carries a genuine second-person approval of whatever the overrides produced,
    # so a verdict's warning list is empty unless the test asked for a problem. Computed after
    # the update because the digest covers the decisive fields the override may have changed.
    if "approvals" not in overrides:
        base["approvals"] = [
            {"approver_actor_key": "actor-reviewer", "digest": body_digest(base)}
        ]
    return base


def approved(body):
    """Attach a valid second-person approval of exactly this body, after every override."""
    return dict(
        body,
        approvals=[{"approver_actor_key": "actor-reviewer", "digest": body_digest(body)}],
    )


def policy(**overrides):
    """A lane with functions enabled, the shipped ceilings and no runtime attached."""
    base = {
        "functions_enabled": True,
        "policy_version": 3,
        "edge_attached": False,
        "default_region": "eu-central",
        "default_residency_class": "in-region-only",
        "default_cpu_ms_limit": 50,
        "default_memory_mb_limit": 128,
        "default_wall_ms_limit": 5000,
        "residency_waiver_reason": None,
    }
    base.update(overrides)
    return base


def variant(**overrides):
    """A safe, coarse, non-personal variant of the function under test."""
    base = {
        "id": "var-1",
        "function_id": "fn-1",
        "ordinal": 0,
        "enabled": True,
        "label": "German banner",
        "audience_kind": "geo",
        "audience_matcher": [{"kind": "country", "equals": "DE"}],
        "fallback_variant": "default",
        "cache_key_effect": "vary-on-dimension",
        "vary_dimension": "country",
        "analytics_dimension": "country",
        "privacy_class": "non-personal",
        "consent_basis": "not-required",
    }
    base.update(overrides)
    return base


def capability(**overrides):
    """A live grant of the smallest capability."""
    base = {
        "id": "cap-1",
        "function_id": "fn-1",
        "capability": "geo-read",
        "reason": "The banner varies by country.",
        "expires_at": None,
    }
    base.update(overrides)
    return base


def egress(**overrides):
    """A live exact-host allowlist entry."""
    base = {
        "id": "egr-1",
        "function_id": "fn-1",
        "destination_kind": "exact-host",
        "destination": "api.example.com",
        "scheme": "https",
        "reason": "The banner reads the pricing feed.",
        "expires_at": None,
    }
    base.update(overrides)
    return base


def request(**overrides) -> InvocationRequest:
    """A GET for /docs/guide/intro from Germany, asking for nothing."""
    base = {
        "method": "GET",
        "host": "docs.example.com",
        "path": "/docs/guide/intro",
        "country": "DE",
    }
    base.update(overrides)
    return InvocationRequest(**base)


def sim(
    functions=None,
    *,
    variants=(),
    capabilities=(),
    egress_rules=(),
    pol=None,
    req=None,
    now=NOW,
):
    """Run a simulation with the suite's defaults."""
    return simulate_invocation(
        request=req or request(),
        policy=policy() if pol is None else pol,
        functions=[function()] if functions is None else functions,
        variants=variants,
        capabilities=capabilities,
        egress_rules=egress_rules,
        now=now,
    )


def entries(verdict, kind=None):
    """The considered entries, optionally of one kind, in evaluation order."""
    return [e for e in verdict.considered if kind is None or e["kind"] == kind]


class TestTheHonestyBoundary:
    """Nothing here runs anything, and no argument exists with which to claim otherwise."""

    def test_a_verdict_never_claims_execution_observation_or_enforcement(self) -> None:
        verdict = sim()
        assert verdict.executed is False
        assert verdict.observed is False
        assert verdict.enforced is False

    def test_the_basis_is_always_policy_simulation(self) -> None:
        assert sim().basis == "policy-simulation"

    def test_an_enforcing_function_at_full_rollout_still_only_would_run(self) -> None:
        assert sim().outcome == "would-run"

    def test_no_verdict_this_module_can_produce_reports_ran(self) -> None:
        """`ran` exists in the enum for a runtime tier that does not exist yet."""
        bodies = [
            [function()],
            [function(rollout_mode="simulate", rollout_percent=5)],
            [function(enabled=False)],
            [],
        ]
        for functions in bodies:
            assert sim(functions).outcome != "ran"

    def test_the_winning_sentence_says_nothing_executed(self) -> None:
        assert "no runtime tier is attached" in sim().outcome_reason.lower()

    def test_the_verdict_carries_no_resource_measurement(self) -> None:
        """A simulation consumed no CPU; reporting a zero would be a measurement."""
        verdict = sim()
        assert set(verdict.limits) == {"cpu_ms", "memory_mb", "wall_ms"}
        assert not hasattr(verdict, "cpu_ms")


class TestEveryDecisionCanBeInvestigated:
    """The considered list is what makes that claim true rather than asserted."""

    def test_every_function_appears_with_an_outcome_and_a_sentence(self) -> None:
        functions = [
            function(id="fn-1", ordinal=0, matcher_value="/nope/"),
            function(id="fn-2", ordinal=1, enabled=False),
            function(id="fn-3", ordinal=2),
            function(id="fn-4", ordinal=3),
        ]
        verdict = sim(functions)
        reported = entries(verdict, "function")
        assert [e["ref"] for e in reported] == ["fn-1", "fn-2", "fn-3", "fn-4"]
        for entry in reported:
            assert entry["outcome"] in INVOCATION_OUTCOMES
            assert len(entry["reason"]) > 20

    def test_every_variant_of_the_winning_function_appears(self) -> None:
        variants = [
            variant(id="var-1", ordinal=0, audience_matcher=[{"kind": "country", "equals": "FR"}]),
            variant(id="var-2", ordinal=1),
            variant(id="var-3", ordinal=2),
        ]
        verdict = sim(variants=variants)
        assert [e["ref"] for e in entries(verdict, "variant")] == ["var-1", "var-2", "var-3"]

    def test_a_variant_of_a_function_that_did_not_run_is_not_reported(self) -> None:
        """It explains nothing about this request, so listing it would be noise."""
        verdict = sim(variants=[variant(id="other", function_id="fn-9")])
        assert entries(verdict, "variant") == []

    def test_functions_are_evaluated_in_precedence_order_whatever_order_they_arrive(
        self,
    ) -> None:
        shuffled = [
            function(id="fn-c", ordinal=2),
            function(id="fn-a", ordinal=0),
            function(id="fn-b", ordinal=1),
        ]
        verdict = sim(shuffled)
        assert [e["ordinal"] for e in entries(verdict, "function")] == [0, 1, 2]
        assert verdict.function_ref == "fn-a"

    def test_a_function_behind_the_winner_says_who_claimed_the_request(self) -> None:
        verdict = sim([function(id="fn-a", ordinal=0), function(id="fn-b", ordinal=1)])
        loser = entries(verdict, "function")[1]
        assert loser["outcome"] == "skipped"
        assert "Geo banner" in loser["reason"]

    @pytest.mark.parametrize(
        "override,fragment",
        [
            ({"enabled": False}, "disabled"),
            ({"active_version_id": None}, "no active version"),
            ({"rollout_percent": 0}, "0% rollout"),
            ({"matcher_value": "/elsewhere/"}, "does not match"),
        ],
    )
    def test_a_skipped_function_names_the_specific_reason(self, override, fragment) -> None:
        verdict = sim([function(**override)])
        entry = entries(verdict, "function")[0]
        assert entry["outcome"] == "skipped"
        assert fragment in entry["reason"].lower()

    def test_a_lane_with_functions_turned_off_says_so_rather_than_blaming_the_matcher(
        self,
    ) -> None:
        verdict = sim(pol=policy(functions_enabled=False))
        assert "not enabled on this lane" in entries(verdict, "function")[0]["reason"]

    def test_a_request_no_function_claims_is_a_complete_verdict(self) -> None:
        verdict = sim([function(matcher_value="/elsewhere/")])
        assert verdict.outcome == "skipped"
        assert verdict.function_ref is None
        assert verdict.cache_key_effect == "none"
        assert verdict.privacy_class == "non-personal"
        assert verdict.executed is False


class TestDenialsAreOutcomesNotRefusals:
    """Deny-by-default is a runtime answer: the function is configured perfectly legally."""

    def test_a_capability_with_no_grant_is_denied_rather_than_refused(self) -> None:
        verdict = sim(req=request(requested_capabilities=("geo-read",)))
        assert verdict.outcome == "capability-denied"
        assert verdict.capabilities_denied == ["geo-read"]
        assert verdict.capabilities_granted == []

    def test_the_denial_appears_on_the_winning_functions_considered_entry(self) -> None:
        verdict = sim(req=request(requested_capabilities=("secret-read",)))
        entry = entries(verdict, "function")[0]
        assert entry["outcome"] == "capability-denied"
        assert entry["reason"] == verdict.denial_reason

    def test_a_live_grant_allows_the_capability(self) -> None:
        verdict = sim(
            capabilities=[capability()], req=request(requested_capabilities=("geo-read",))
        )
        assert verdict.outcome == "would-run"
        assert verdict.capabilities_granted == ["geo-read"]

    def test_a_lapsed_grant_denies_exactly_as_an_absent_one_does(self) -> None:
        verdict = sim(
            capabilities=[capability(expires_at=NOW - timedelta(days=1))],
            req=request(requested_capabilities=("geo-read",)),
        )
        assert verdict.outcome == "capability-denied"
        assert verdict.capabilities_denied == ["geo-read"]

    def test_a_grant_belonging_to_another_function_does_not_help(self) -> None:
        verdict = sim(
            capabilities=[capability(function_id="fn-9")],
            req=request(requested_capabilities=("geo-read",)),
        )
        assert verdict.outcome == "capability-denied"

    def test_an_unallowlisted_destination_is_denied_rather_than_refused(self) -> None:
        verdict = sim(
            capabilities=[capability(capability="fetch-egress")],
            req=request(
                requested_capabilities=("fetch-egress",),
                requested_destinations=("collector.example.net",),
            ),
        )
        assert verdict.outcome == "egress-denied"
        assert verdict.egress_denied == ["collector.example.net"]

    def test_an_allowlisted_destination_is_reachable(self) -> None:
        verdict = sim(
            capabilities=[capability(capability="fetch-egress")],
            egress_rules=[egress()],
            req=request(
                requested_capabilities=("fetch-egress",),
                requested_destinations=("api.example.com",),
            ),
        )
        assert verdict.outcome == "would-run"
        assert verdict.egress_allowed == ["api.example.com"]
        assert verdict.egress_denied == []

    def test_a_capability_denial_is_reported_before_an_egress_one(self) -> None:
        """A handler denied its fetch capability never reaches the destination check."""
        verdict = sim(
            req=request(
                requested_capabilities=("fetch-egress",),
                requested_destinations=("collector.example.net",),
            )
        )
        assert verdict.outcome == "capability-denied"
        assert verdict.egress_denied == ["collector.example.net"]

    def test_an_estimate_above_a_ceiling_is_limit_exceeded(self) -> None:
        verdict = sim(req=request(estimated_cpu_ms=500))
        assert verdict.outcome == "limit-exceeded"
        assert "CPU ceiling of 50ms" in verdict.denial_reason

    @pytest.mark.parametrize(
        "field,phrase",
        [
            ("estimated_cpu_ms", "CPU ceiling"),
            ("estimated_memory_mb", "memory ceiling"),
            ("estimated_wall_ms", "wall-clock ceiling"),
        ],
    )
    def test_each_ceiling_is_named_separately(self, field, phrase) -> None:
        verdict = sim(req=request(**{field: 999999}))
        assert verdict.outcome == "limit-exceeded"
        assert phrase in verdict.denial_reason

    def test_an_absent_estimate_is_not_treated_as_zero_usage(self) -> None:
        """A simulation that invented a measurement would be the worst thing here."""
        assert sim(req=request()).outcome == "would-run"

    def test_an_estimate_at_the_ceiling_is_not_exceeded(self) -> None:
        assert sim(req=request(estimated_cpu_ms=50)).outcome == "would-run"

    def test_a_denial_reason_is_present_only_when_something_was_denied(self) -> None:
        assert sim().denial_reason is None
        assert sim(req=request(requested_capabilities=("kv-write",))).denial_reason


class TestVariantSelection:
    """Audience rule, fallback, cache-key effect, analytics and privacy, reported together."""

    def test_the_first_matching_variant_wins(self) -> None:
        variants = [
            variant(id="var-1", ordinal=0, audience_matcher=[{"kind": "country", "equals": "FR"}]),
            variant(id="var-2", ordinal=1),
            variant(id="var-3", ordinal=2),
        ]
        verdict = sim(variants=variants)
        assert verdict.variant_ref == "var-2"
        assert verdict.variant_label == "German banner"

    def test_a_variant_that_lost_names_the_predicate_it_failed(self) -> None:
        verdict = sim(
            variants=[
                variant(audience_matcher=[{"kind": "country", "equals": "FR"}])
            ]
        )
        entry = entries(verdict, "variant")[0]
        assert entry["outcome"] == "skipped"
        assert "country is DE, not FR" in entry["reason"]

    def test_an_unmatched_reader_still_learns_the_fallback(self) -> None:
        verdict = sim(
            variants=[variant(audience_matcher=[{"kind": "country", "equals": "FR"}])]
        )
        assert verdict.variant_ref is None
        assert verdict.fallback_variant == "default"

    def test_the_fallback_is_reported_even_when_a_variant_matched(self) -> None:
        """"And everybody else?" is answered whether or not this reader matched."""
        verdict = sim(variants=[variant()])
        assert verdict.variant_ref == "var-1"
        assert verdict.fallback_variant == "default"

    def test_a_disabled_variant_says_what_the_reader_gets_instead(self) -> None:
        verdict = sim(variants=[variant(enabled=False)])
        entry = entries(verdict, "variant")[0]
        assert entry["outcome"] == "skipped"
        assert "default" in entry["reason"]

    def test_a_variant_behind_the_selected_one_says_who_won(self) -> None:
        verdict = sim(variants=[variant(id="var-1", ordinal=0), variant(id="var-2", ordinal=1)])
        loser = entries(verdict, "variant")[1]
        assert loser["outcome"] == "skipped"
        assert "already" in loser["reason"]

    def test_an_empty_audience_matcher_is_a_catch_all(self) -> None:
        verdict = sim(variants=[variant(audience_matcher=[])])
        assert verdict.variant_ref == "var-1"

    @pytest.mark.parametrize(
        "kind,field,value",
        [
            ("country", "country", "DE"),
            ("language", "language", "de"),
            ("device", "device", "mobile"),
            ("cohort", "cohort", "beta"),
            ("experiment", "experiment", "exp-7"),
        ],
    )
    def test_every_audience_predicate_kind_is_evaluated(self, kind, field, value) -> None:
        matched = sim(
            variants=[
                variant(
                    audience_kind=kind,
                    audience_matcher=[{"kind": kind, "equals": value}],
                    cache_key_effect="bypass-cache",
                )
            ],
            req=request(**{field: value}),
        )
        assert matched.variant_ref == "var-1"
        missed = sim(
            variants=[
                variant(
                    audience_kind=kind,
                    audience_matcher=[{"kind": kind, "equals": value}],
                    cache_key_effect="bypass-cache",
                )
            ],
            req=request(**{field: "something-else"}),
        )
        assert missed.variant_ref is None

    def test_an_in_predicate_matches_any_of_its_options(self) -> None:
        verdict = sim(
            variants=[variant(audience_matcher=[{"kind": "country", "in": ["FR", "DE"]}])]
        )
        assert verdict.variant_ref == "var-1"

    def test_an_unknown_predicate_kind_narrows_rather_than_widens(self) -> None:
        """An unknown condition on a personalizing variant must not let everybody in."""
        verdict = sim(variants=[variant(audience_matcher=[{"kind": "phase-of-moon"}])])
        assert verdict.variant_ref is None
        assert "not one this evaluator understands" in entries(verdict, "variant")[0]["reason"]

    def test_a_malformed_predicate_narrows_too(self) -> None:
        verdict = sim(variants=[variant(audience_matcher=["not-a-mapping"])])
        assert verdict.variant_ref is None

    def test_a_predicate_with_no_comparison_narrows_too(self) -> None:
        verdict = sim(variants=[variant(audience_matcher=[{"kind": "country"}])])
        assert verdict.variant_ref is None

    def test_the_verdict_reports_cache_privacy_and_analytics_together(self) -> None:
        """§29.5 requires them shown together; a verdict missing one is a type error."""
        verdict = sim(
            variants=[
                variant(
                    cache_key_effect="bypass-cache",
                    privacy_class="pseudonymous",
                    consent_basis="explicit-consent",
                    analytics_dimension="cohort-a",
                )
            ]
        )
        assert verdict.cache_key_effect == "bypass-cache"
        assert verdict.privacy_class == "pseudonymous"
        assert verdict.consent_basis == "explicit-consent"
        assert verdict.analytics_dimension == "cohort-a"

    def test_the_resolved_cache_key_effect_is_always_a_known_value(self) -> None:
        assert sim().cache_key_effect in CACHE_KEY_EFFECTS
        assert sim(variants=[variant()]).cache_key_effect in CACHE_KEY_EFFECTS

    def test_the_matching_sentence_quotes_the_whole_personalization_decision(self) -> None:
        entry = entries(sim(variants=[variant()]), "variant")[0]
        for fragment in ("geo", "country", "non-personal", "not-required", "vary-on-dimension"):
            assert fragment in entry["reason"]


class TestResolvedSettings:
    """A verdict states where and within what a function would have run."""

    def test_an_inheriting_function_reports_the_lane_defaults(self) -> None:
        verdict = sim()
        assert verdict.region == "eu-central"
        assert verdict.residency_class == "in-region-only"
        assert verdict.limits == {"cpu_ms": 50, "memory_mb": 128, "wall_ms": 5000}

    def test_a_pinned_function_reports_its_own_values(self) -> None:
        verdict = sim([approved(function(region="us-east", cpu_ms_limit=20))])
        assert verdict.region == "us-east"
        assert verdict.limits["cpu_ms"] == 20

    def test_the_verdict_names_the_version_that_would_have_run(self) -> None:
        assert sim().version_ref == "ver-1"

    def test_the_verdict_names_the_runtime_and_the_rollout(self) -> None:
        verdict = sim()
        assert verdict.runtime == "js-isolate"
        assert verdict.rollout_mode == "enforce"
        assert verdict.rollout_percent == 100

    def test_a_simulate_mode_function_says_its_result_would_be_discarded(self) -> None:
        verdict = sim([function(rollout_mode="simulate", rollout_percent=5)])
        assert verdict.outcome == "would-run"
        assert "discard" in verdict.outcome_reason


class TestWarningsSurfaceRatherThanRaise:
    """A stored function can drift into unsafe; a simulation is a read and must still render."""

    def test_the_baseline_verdict_carries_no_warnings_at_all(self) -> None:
        """Proves the fixture is clean, so every warning a test sees was caused by its override."""
        assert sim().warnings == []

    def test_a_broad_stored_function_warns_without_raising(self) -> None:
        verdict = sim([approved(function(matcher_value="/"))])
        assert "broad-matcher" in {w["code"] for w in verdict.warnings}

    def test_a_stored_function_that_became_refusable_reports_the_refusal_as_a_warning(
        self,
    ) -> None:
        verdict = sim([function(approvals=[])])
        codes = {w["code"] for w in verdict.warnings}
        assert "enforce-without-approval" in codes
        assert verdict.outcome == "would-run"

    def test_a_variant_that_became_refusable_reports_it_too(self) -> None:
        verdict = sim(
            variants=[variant(privacy_class="pseudonymous", cache_key_effect="none")]
        )
        assert "variant-identity-cache-key" in {w["code"] for w in verdict.warnings}

    def test_an_egress_denial_is_not_also_reported_as_a_refusal(self) -> None:
        """One problem, one report: two would read as two problems."""
        verdict = sim(
            [approved(function(declared_destinations=["collector.example.net"]))],
            capabilities=[capability(capability="fetch-egress")],
            req=request(
                requested_capabilities=("fetch-egress",),
                requested_destinations=("collector.example.net",),
            ),
        )
        assert verdict.outcome == "egress-denied"
        assert "egress-unapproved" not in {w["code"] for w in verdict.warnings}

    def test_every_warning_carries_a_code_message_and_field(self) -> None:
        verdict = sim([approved(function(matcher_value="/"))])
        for warning in verdict.warnings:
            assert set(warning) == {"code", "message", "field"}
            assert warning["message"].strip()


class TestPurity:
    """No database, no clock. `now` is mandatory, and it decides what is live."""

    def test_now_is_keyword_only_and_mandatory(self) -> None:
        with pytest.raises(TypeError):
            simulate_invocation(
                request=request(), policy=policy(), functions=[function()]
            )

    def test_the_same_grant_flips_the_verdict_on_the_instant_it_is_judged_against(
        self,
    ) -> None:
        grant = capability(expires_at=NOW + timedelta(days=1))
        req = request(requested_capabilities=("geo-read",))
        assert sim(capabilities=[grant], req=req, now=NOW).outcome == "would-run"
        assert (
            sim(capabilities=[grant], req=req, now=NOW + timedelta(days=2)).outcome
            == "capability-denied"
        )

    def test_evaluation_does_not_consult_the_wall_clock(self) -> None:
        past = datetime(2000, 1, 1, tzinfo=timezone.utc)
        grant = capability(expires_at=past + timedelta(days=1))
        verdict = sim(
            capabilities=[grant],
            req=request(requested_capabilities=("geo-read",)),
            now=past,
        )
        assert verdict.outcome == "would-run"

    def test_the_same_inputs_produce_the_same_verdict_every_time(self) -> None:
        functions = [function(id=f"fn-{i}", ordinal=i) for i in range(5)]
        variants = [variant(id=f"var-{i}", ordinal=i) for i in range(3)]
        first = sim(functions, variants=variants)
        for _ in range(5):
            again = sim(functions, variants=variants)
            assert again.outcome == first.outcome
            assert again.function_ref == first.function_ref
            assert again.variant_ref == first.variant_ref
            assert again.considered == first.considered

    def test_input_order_does_not_change_the_answer(self) -> None:
        functions = [function(id=f"fn-{i}", ordinal=i) for i in range(6)]
        baseline = sim(list(functions))
        shuffled = list(functions)
        random.Random(2475).shuffle(shuffled)
        assert sim(shuffled).considered == baseline.considered

    def test_rollout_is_applied_deterministically_rather_than_sampled(self) -> None:
        """Sampling would make the same inputs produce different answers."""
        outcomes = {sim([function(rollout_percent=1)]).outcome for _ in range(20)}
        assert outcomes == {"would-run"}

    def test_a_naive_now_does_not_raise_against_an_aware_expiry(self) -> None:
        verdict = sim(
            capabilities=[capability(expires_at=NOW + timedelta(days=1))],
            req=request(requested_capabilities=("geo-read",)),
            now=datetime(2026, 7, 19, 12, 0, 0),
        )
        assert verdict.outcome == "would-run"

    def test_a_lane_that_was_never_configured_still_renders(self) -> None:
        verdict = simulate_invocation(
            request=request(), policy=None, functions=[function()], now=NOW
        )
        assert verdict.outcome == "skipped"
        assert "not enabled on this lane" in entries(verdict, "function")[0]["reason"]


class TestDigests:
    """The determinism receipt: a verdict either reproduces or is explained by having drifted."""

    def test_the_digest_matches_the_column_constraint(self) -> None:
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", functions_digest([function()]))
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", body_digest(function()))

    def test_the_verdict_carries_the_digest_of_the_set_that_produced_it(self) -> None:
        functions = [function(id="fn-1", ordinal=0), function(id="fn-2", ordinal=1)]
        assert sim(functions).functions_digest == functions_digest(functions)

    def test_the_digest_ignores_order(self) -> None:
        a = function(id="fn-a", ordinal=0)
        b = function(id="fn-b", ordinal=1)
        assert functions_digest([a, b]) == functions_digest([b, a])

    def test_the_digest_ignores_a_rename(self) -> None:
        assert functions_digest([function()]) == functions_digest(
            [function(label="Renamed")]
        )

    def test_a_disabled_function_does_not_contribute(self) -> None:
        """An unrelated toggle must not appear to invalidate every recorded simulation."""
        assert functions_digest([function(), function(id="off", ordinal=9, enabled=False)]) == (
            functions_digest([function()])
        )

    def test_a_decisive_change_moves_the_digest(self) -> None:
        assert functions_digest([function()]) != functions_digest(
            [function(matcher_value="/other/")]
        )

    def test_an_empty_lane_still_has_a_digest(self) -> None:
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", functions_digest([]))

    def test_the_digest_is_repeatable(self) -> None:
        assert functions_digest([function()]) == functions_digest([function()])

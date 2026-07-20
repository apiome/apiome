"""Function catalogs, refusal vocabulary and safety evaluation — UXE-3.3 (private-suite#2475).

Pure tests over :mod:`app.slate_functions`: no TestClient, no database, no clock. ``now`` is a
parameter everywhere it matters, and :class:`TestPurity` asserts that it actually is one.

The suite is weighted toward the four claims §29.5 makes:

* **No arbitrary function reads tenant secrets or crosses a project boundary.** V189 makes the
  first half a schema impossibility; the second half is a refusal with no acknowledgement path,
  and it is pinned in both directions here.
* **Egress and runtime capabilities are deny-by-default.** The catalog is asserted to explain what
  each grant costs, because a capability nobody can review is one that gets granted by default in
  practice however the schema is written.
* **Personalization states its cache and privacy effects together.** The combinations that are
  contradictions rather than configurations are asserted to be refusals, not warnings.
* **A refusal has no acknowledgement path.** The asymmetry between
  :data:`app.slate_functions._HARD_REFUSALS` and :data:`app.slate_functions._WARNING_SENTENCES` is
  the whole design, so acknowledging a refusal is asserted not to let the write through, and
  acknowledging a warning is asserted not to be needed for it to.

Simulation and digests live in ``tests/test_slate_functions_simulate.py``.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import get_args

import pytest

from app.slate_functions import (
    CACHE_KEY_EFFECT_CATALOG,
    CACHE_KEY_EFFECTS,
    CAPABILITIES,
    CAPABILITY_CATALOG,
    CHANGE_KINDS,
    CONSENT_BASES,
    EGRESS_DESTINATION_KINDS,
    EGRESS_SCHEMES,
    INVOCATION_OUTCOMES,
    MATCHER_KINDS,
    PRIVACY_CLASSES,
    RESIDENCY_CLASS_CATALOG,
    RESIDENCY_CLASSES,
    ROLLOUT_MODES,
    RUNTIME_CATALOG,
    RUNTIMES,
    SECRET_SCOPES,
    SOURCE_ORIGINS,
    FunctionRefusal,
    FunctionRefusalReason,
    FunctionWarning,
    InvocationRequest,
    SlateFunctionRefusedError,
    body_digest,
    covers_everything,
    evaluate_approval_safety,
    evaluate_capability_safety,
    evaluate_egress_safety,
    evaluate_function_safety,
    evaluate_policy_safety,
    evaluate_variant_safety,
    matches_route,
    normalize_capability,
    normalize_egress_rule,
    normalize_function,
    normalize_policy,
    normalize_secret_ref,
    normalize_variant,
)
from app.slate_functions import (
    _BROAD_MATCHER_MAX_SEGMENTS,
    _HARD_REFUSALS,
    _HIGH_CARDINALITY_DIMENSIONS,
    _IDENTITY_DIMENSION_TOKENS,
    _LIMIT_NEAR_CEILING_RATIO,
    _MAX_CAPABILITY_WINDOW_DAYS,
    _REFUSAL_SENTENCES,
    _WARNING_SENTENCES,
)

NOW = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)


def function(**overrides):
    """A narrowly-scoped, simulate-mode function; each test states only the field it is about.

    The baseline deliberately does not enforce and pins two path segments, so any refusal or
    warning a test observes was caused by the override it made, not by the fixture.
    """
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
        "rollout_mode": "simulate",
        "rollout_percent": 10,
        "previous_rollout_percent": None,
        "region": None,
        "residency_class": None,
        "cpu_ms_limit": None,
        "memory_mb_limit": None,
        "wall_ms_limit": None,
        "env_var_names": [],
        "declared_destinations": [],
        "acknowledged_warnings": [],
        "simulated_at": None,
        "author_actor_key": "actor-author",
        "approvals": [],
    }
    base.update(overrides)
    return base


def policy(**overrides):
    """A lane policy with functions enabled and the shipped ceilings."""
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
    """A safe, coarse, non-personal variant with a fallback and an analytics dimension."""
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
    """A grant of the smallest capability, with a reason and no expiry requirement."""
    base = {
        "id": "cap-1",
        "function_id": "fn-1",
        "capability": "geo-read",
        "reason": "The banner varies by country.",
        "expires_at": None,
        "granted_at": NOW - timedelta(days=1),
        "granted_by_actor_key": "actor-granter",
    }
    base.update(overrides)
    return base


def egress(**overrides):
    """An exact-host allowlist entry with a reason."""
    base = {
        "id": "egr-1",
        "function_id": "fn-1",
        "destination_kind": "exact-host",
        "destination": "api.example.com",
        "scheme": "https",
        "port": None,
        "methods": ["GET"],
        "reason": "The banner reads the pricing feed.",
        "expires_at": None,
    }
    base.update(overrides)
    return base


def approved(candidate, approver="actor-reviewer"):
    """Attach a valid second-person approval of exactly this body."""
    return dict(
        candidate,
        approvals=[{"approver_actor_key": approver, "digest": body_digest(candidate)}],
    )


def enforcing(**overrides):
    """A function that has passed every gate before the one under test."""
    return function(
        rollout_mode="enforce",
        rollout_percent=100,
        previous_rollout_percent=50,
        simulated_at=NOW - timedelta(days=1),
        **overrides,
    )


# Every hard refusal, paired with a body that provokes it from this module. Each callable takes
# an ``ack`` list which is threaded into the body, so the same table drives both "the refusal
# fires" and "acknowledging it changes nothing".
def _trigger_secret_cross_project(ack):
    evaluate_function_safety(
        function(acknowledged_warnings=ack),
        policy=policy(),
        secret_refs=[
            {
                "secret_name": "stripe-key",
                "alias": "STRIPE",
                "scope": "environment",
                "owner_environment_id": "env-other",
            }
        ],
        now=NOW,
    )


def _trigger_egress_unapproved(ack):
    evaluate_function_safety(
        function(
            declared_destinations=["https://collector.example.net/ingest"],
            acknowledged_warnings=ack,
        ),
        policy=policy(),
        egress_rules=[egress()],
        now=NOW,
    )


def _trigger_capability_without_reason(ack):
    evaluate_capability_safety(capability(reason="   "), now=NOW)
    del ack


def _trigger_capability_unbounded(ack):
    evaluate_capability_safety(
        capability(capability="secret-read", expires_at=None), now=NOW
    )
    del ack


def _trigger_enforce_without_version(ack):
    evaluate_function_safety(
        enforcing(active_version_id=None, acknowledged_warnings=ack),
        policy=policy(),
        now=NOW,
    )


def _trigger_enforce_without_simulation(ack):
    evaluate_function_safety(
        function(
            rollout_mode="enforce",
            rollout_percent=100,
            simulated_at=None,
            acknowledged_warnings=ack,
        ),
        policy=policy(),
        now=NOW,
    )


def _trigger_enforce_without_approval(ack):
    evaluate_function_safety(
        enforcing(approvals=[], acknowledged_warnings=ack), policy=policy(), now=NOW
    )


def _trigger_approval_self(ack):
    body = enforcing(acknowledged_warnings=ack)
    evaluate_function_safety(
        approved(body, approver="actor-author"), policy=policy(), now=NOW
    )


def _trigger_approval_stale(ack):
    body = enforcing(acknowledged_warnings=ack)
    stale = approved(body)
    # Re-edit a decisive field after the approval was recorded.
    evaluate_function_safety(
        dict(stale, matcher_value="/docs/guide/v2/"), policy=policy(), now=NOW
    )


def _trigger_limit_exceeds_ceiling(ack):
    evaluate_function_safety(
        function(cpu_ms_limit=500, acknowledged_warnings=ack), policy=policy(), now=NOW
    )


def _trigger_matcher_invalid(ack):
    evaluate_function_safety(
        function(matcher_kind="regex", matcher_value="([unclosed", acknowledged_warnings=ack),
        policy=policy(),
        now=NOW,
    )


def _trigger_ordinal_conflict(ack):
    evaluate_function_safety(
        function(id="mine", ordinal=5, acknowledged_warnings=ack),
        siblings=[function(id="theirs", ordinal=5)],
        policy=policy(),
        now=NOW,
    )


def _trigger_variant_without_fallback(ack):
    evaluate_variant_safety(variant(fallback_variant="", acknowledged_warnings=ack))


def _trigger_variant_identity_cache_key(ack):
    evaluate_variant_safety(
        variant(vary_dimension="sessionId", analytics_dimension="sessionId",
                acknowledged_warnings=ack)
    )


def _trigger_variant_personal_without_basis(ack):
    evaluate_variant_safety(
        variant(
            privacy_class="personal",
            consent_basis="not-required",
            cache_key_effect="bypass-cache",
            acknowledged_warnings=ack,
        )
    )


def _trigger_residency_violation(ack):
    evaluate_policy_safety(
        policy(
            default_residency_class="unrestricted",
            residency_waiver_reason="",
            acknowledged_warnings=ack,
        )
    )


#: (reason, trigger) for every hard refusal this module can raise from a body. The one omission
#: is ``policy-version-conflict``, which is a store-level concurrency check with no pure trigger;
#: :meth:`TestRefusalVocabulary.test_every_declared_reason_has_a_sentence` still covers it.
REFUSAL_TRIGGERS = [
    ("secret-cross-project", _trigger_secret_cross_project),
    ("egress-unapproved", _trigger_egress_unapproved),
    ("capability-without-reason", _trigger_capability_without_reason),
    ("capability-unbounded", _trigger_capability_unbounded),
    ("enforce-without-version", _trigger_enforce_without_version),
    ("enforce-without-simulation", _trigger_enforce_without_simulation),
    ("enforce-without-approval", _trigger_enforce_without_approval),
    ("approval-self", _trigger_approval_self),
    ("approval-stale", _trigger_approval_stale),
    ("limit-exceeds-ceiling", _trigger_limit_exceeds_ceiling),
    ("matcher-invalid", _trigger_matcher_invalid),
    ("ordinal-conflict", _trigger_ordinal_conflict),
    ("variant-without-fallback", _trigger_variant_without_fallback),
    ("variant-identity-cache-key", _trigger_variant_identity_cache_key),
    ("variant-personal-without-basis", _trigger_variant_personal_without_basis),
    ("residency-violation", _trigger_residency_violation),
]


class TestEnumerations:
    """The vocabularies V189 CHECKs, pinned so a widened enum is a visible diff."""

    def test_matcher_kinds_match_the_cache_and_security_surfaces(self) -> None:
        """An operator who learned `glob` on two other screens must not relearn it here."""
        assert MATCHER_KINDS == ("exact", "prefix", "glob", "regex")

    def test_runtimes_are_ordered_by_how_narrow_the_sandbox_is(self) -> None:
        assert RUNTIMES == ("js-isolate", "wasm")

    def test_a_function_is_either_recording_or_acting(self) -> None:
        assert ROLLOUT_MODES == ("simulate", "enforce")

    def test_residency_classes_are_ordered_most_restrictive_first(self) -> None:
        assert RESIDENCY_CLASSES == ("in-region-only", "region-pinned", "unrestricted")

    def test_capabilities_are_ordered_safest_first(self) -> None:
        assert CAPABILITIES == (
            "geo-read",
            "env-read",
            "kv-read",
            "kv-write",
            "crypto-subtle",
            "fetch-egress",
            "cookie-write",
            "secret-read",
        )

    def test_cache_key_effects_are_ordered_safest_first(self) -> None:
        assert CACHE_KEY_EFFECTS == ("none", "vary-on-dimension", "bypass-cache")

    def test_privacy_classes_are_ordered_least_personal_first(self) -> None:
        assert PRIVACY_CLASSES == ("non-personal", "pseudonymous", "personal")

    def test_consent_bases_are_ordered_by_how_defensible_they_are(self) -> None:
        assert CONSENT_BASES == ("not-required", "explicit-consent", "legitimate-interest")

    def test_secret_scopes_are_narrowest_first(self) -> None:
        assert SECRET_SCOPES == ("function", "environment")

    def test_there_is_no_wildcard_egress_destination_kind(self) -> None:
        """An egress allowlist with a wildcard is a denylist wearing a costume."""
        assert EGRESS_DESTINATION_KINDS == ("exact-host", "host-suffix")
        assert "any" not in EGRESS_DESTINATION_KINDS

    def test_egress_schemes_put_https_first(self) -> None:
        assert EGRESS_SCHEMES == ("https", "http")

    def test_would_run_is_a_first_class_outcome_and_ran_exists_but_is_unreachable(self) -> None:
        """Without would-run, a simulated execution would have to be recorded as a real one."""
        assert INVOCATION_OUTCOMES == (
            "skipped",
            "would-run",
            "ran",
            "refused",
            "capability-denied",
            "egress-denied",
            "limit-exceeded",
            "error",
        )

    def test_source_origins_and_change_kinds_match_the_migration(self) -> None:
        assert SOURCE_ORIGINS == ("upload", "build", "import")
        assert CHANGE_KINDS == (
            "created",
            "updated",
            "disabled",
            "deleted",
            "reverted",
            "rollout-changed",
            "version-added",
        )

    def test_catalog_ids_agree_with_their_enumerations(self) -> None:
        assert tuple(CAPABILITY_CATALOG) == CAPABILITIES
        assert tuple(RUNTIME_CATALOG) == RUNTIMES
        assert tuple(RESIDENCY_CLASS_CATALOG) == RESIDENCY_CLASSES
        assert tuple(CACHE_KEY_EFFECT_CATALOG) == CACHE_KEY_EFFECTS


class TestCapabilityCatalog:
    """Deny-by-default only helps if granting is a decision somebody can actually review."""

    @pytest.mark.parametrize("key", CAPABILITIES)
    def test_every_capability_explains_itself_in_prose(self, key) -> None:
        entry = CAPABILITY_CATALOG[key]
        assert entry.id == key
        assert entry.title.strip()
        assert len(entry.description.strip()) > 40, f"{key} does not say what it permits"
        assert len(entry.expected_impact.strip()) > 60, f"{key} states no expected impact"

    @pytest.mark.parametrize("key", CAPABILITIES)
    def test_every_capability_names_what_it_is_wrong_for(self, key) -> None:
        entry = CAPABILITY_CATALOG[key]
        assert entry.unsafe_if, f"{key} names nothing it is a poor fit for"
        for sentence in entry.unsafe_if:
            assert len(sentence.strip()) > 20

    @pytest.mark.parametrize("key", CAPABILITIES)
    def test_a_capabilitys_impact_is_not_a_restatement_of_its_description(self, key) -> None:
        entry = CAPABILITY_CATALOG[key]
        assert entry.expected_impact != entry.description
        assert entry.expected_impact != entry.title

    def test_no_two_capabilities_share_boilerplate_prose(self) -> None:
        impacts = [c.expected_impact for c in CAPABILITY_CATALOG.values()]
        descriptions = [c.description for c in CAPABILITY_CATALOG.values()]
        assert len(set(impacts)) == len(impacts), "two capabilities share an impact sentence"
        assert len(set(descriptions)) == len(descriptions), "two share a description"

    @pytest.mark.parametrize("key", CAPABILITIES)
    def test_every_capability_declares_a_privacy_reach(self, key) -> None:
        assert CAPABILITY_CATALOG[key].privacy_reach in ("none", "coarse", "identifying")

    def test_the_capabilities_that_lapse_are_the_ones_whose_uses_are_temporary(self) -> None:
        """A permanent grant of any of these is a standing privilege nobody re-decided."""
        expiring = {k for k, v in CAPABILITY_CATALOG.items() if v.requires_expiry}
        assert expiring == {"kv-write", "fetch-egress", "cookie-write", "secret-read"}

    def test_reading_geography_does_not_have_to_be_renewed_weekly(self) -> None:
        """The expiry exists for the incident grant, not for the function that legitimately reads."""
        assert CAPABILITY_CATALOG["geo-read"].requires_expiry is False
        assert CAPABILITY_CATALOG["kv-read"].requires_expiry is False

    def test_the_secret_capability_names_the_exfiltration_pair(self) -> None:
        """secret-read plus fetch-egress is one request away from a credential leaving the lane."""
        joined = " ".join(CAPABILITY_CATALOG["secret-read"].unsafe_if).lower()
        assert "egress" in joined


class TestRuntimeCatalog:
    """A runtime is a blast radius, so it has to say how large."""

    @pytest.mark.parametrize("key", RUNTIMES)
    def test_every_runtime_states_intent_impact_sandbox_and_what_it_is_wrong_for(
        self, key
    ) -> None:
        entry = RUNTIME_CATALOG[key]
        assert entry.key == key
        assert entry.label.strip()
        assert entry.intent.strip()
        assert len(entry.expected_impact.strip()) > 60
        assert len(entry.sandbox.strip()) > 40
        assert entry.unsafe_if

    def test_the_narrower_runtime_is_the_column_default(self) -> None:
        """V189 defaults slate_functions.runtime to js-isolate; normalization must agree."""
        assert normalize_function({})["runtime"] == "js-isolate"
        assert RUNTIMES[0] == "js-isolate"

    def test_the_wider_runtime_says_its_imports_are_the_attack_surface(self) -> None:
        assert "import" in RUNTIME_CATALOG["wasm"].sandbox.lower()


class TestResidencyCatalog:
    """§29.6 asks the UX to state what a residency option does not cover, so it is required."""

    @pytest.mark.parametrize("key", RESIDENCY_CLASSES)
    def test_every_class_states_impact_and_what_it_does_not_cover(self, key) -> None:
        entry = RESIDENCY_CLASS_CATALOG[key]
        assert entry.key == key
        assert len(entry.expected_impact.strip()) > 60
        assert len(entry.does_not_cover.strip()) > 30, f"{key} claims to cover everything"
        assert entry.unsafe_if

    def test_the_default_class_is_the_most_restrictive_one(self) -> None:
        """A residency promise that has to be opted into is one nobody made."""
        assert normalize_policy(None)["default_residency_class"] == "in-region-only"
        assert RESIDENCY_CLASSES[0] == "in-region-only"

    def test_only_the_unrestricted_class_needs_a_stated_reason(self) -> None:
        needing = {k for k, v in RESIDENCY_CLASS_CATALOG.items() if v.requires_waiver_reason}
        assert needing == {"unrestricted"}

    def test_only_the_unrestricted_class_forbids_personal_data(self) -> None:
        forbidding = {k for k, v in RESIDENCY_CLASS_CATALOG.items() if not v.permits_personal}
        assert forbidding == {"unrestricted"}


class TestCacheKeyEffectCatalog:
    """The effect on a shared cache key is the field §29.5 refuses to let drift."""

    @pytest.mark.parametrize("key", CACHE_KEY_EFFECTS)
    def test_every_effect_explains_what_it_does_to_the_cache(self, key) -> None:
        entry = CACHE_KEY_EFFECT_CATALOG[key]
        assert entry.key == key
        assert len(entry.expected_impact.strip()) > 60
        assert entry.unsafe_if

    def test_leaving_the_key_alone_is_declared_unsafe_for_personal_output(self) -> None:
        assert CACHE_KEY_EFFECT_CATALOG["none"].safe_for_personal is False

    def test_only_varying_fragments_the_cache(self) -> None:
        fragmenting = {k for k, v in CACHE_KEY_EFFECT_CATALOG.items() if v.fragments_cache}
        assert fragmenting == {"vary-on-dimension"}

    def test_the_column_default_is_the_effect_that_changes_nothing(self) -> None:
        assert normalize_variant({})["cache_key_effect"] == "none"


class TestRefusalVocabulary:
    """The codes are ours to test against; the sentences are the operator's only explanation."""

    def test_every_declared_reason_has_a_sentence(self) -> None:
        declared = set(get_args(FunctionRefusalReason))
        assert declared == set(_REFUSAL_SENTENCES)

    def test_the_seventeen_refusals_are_exactly_the_declared_ones(self) -> None:
        assert len(_REFUSAL_SENTENCES) == 17
        assert set(_HARD_REFUSALS) == set(_REFUSAL_SENTENCES)

    def test_every_refusal_is_hard(self) -> None:
        """A future reason has to decide which side it is on rather than defaulting to one."""
        for reason in _REFUSAL_SENTENCES:
            assert reason in _HARD_REFUSALS

    def test_no_refusal_is_also_a_warning(self) -> None:
        assert not set(_REFUSAL_SENTENCES) & set(_WARNING_SENTENCES)

    def test_an_unknown_reason_still_produces_a_sentence(self) -> None:
        assert FunctionRefusal.of("not-a-real-code").sentence.strip()

    @pytest.mark.parametrize("reason", sorted(_REFUSAL_SENTENCES))
    def test_sentences_say_what_to_do_rather_than_only_what_failed(self, reason) -> None:
        sentence = _REFUSAL_SENTENCES[reason]
        assert len(sentence.split(".")) >= 3, f"{reason} is not two or three clauses"
        assert len(sentence) > 80

    def test_the_error_carries_both_the_code_and_the_sentence(self) -> None:
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            _trigger_matcher_invalid([])
        assert excinfo.value.code == "matcher-invalid"
        assert excinfo.value.refusal.sentence == _REFUSAL_SENTENCES["matcher-invalid"]
        assert str(excinfo.value) == _REFUSAL_SENTENCES["matcher-invalid"]


class TestWarningVocabulary:
    """The acknowledgeable half: a cost, never a boundary crossing."""

    def test_every_warning_has_a_sentence(self) -> None:
        for code, sentence in _WARNING_SENTENCES.items():
            assert sentence.strip(), code

    def test_the_six_acknowledgeable_warnings_are_the_contract_ones(self) -> None:
        assert set(_WARNING_SENTENCES) == {
            "broad-matcher",
            "cache-fragmenting",
            "rollout-jump",
            "variant-without-analytics",
            "limit-near-ceiling",
            "function-shadowed",
        }

    def test_an_unknown_warning_code_still_produces_a_sentence(self) -> None:
        assert FunctionWarning.of("not-a-real-code").message.strip()

    def test_a_warning_carries_the_field_it_attaches_to(self) -> None:
        assert FunctionWarning.of("broad-matcher", field="matcher_value").field == (
            "matcher_value"
        )


class TestHardRefusalsHaveNoAcknowledgementPath:
    """Criterion: the server is the authority on what is unsafe, not a checkbox."""

    @pytest.mark.parametrize("reason,trigger", REFUSAL_TRIGGERS)
    def test_the_refusal_fires(self, reason, trigger) -> None:
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            trigger([])
        assert excinfo.value.code == reason

    @pytest.mark.parametrize("reason,trigger", REFUSAL_TRIGGERS)
    def test_acknowledging_it_does_not_let_the_write_through(self, reason, trigger) -> None:
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            trigger([reason])
        assert excinfo.value.code == reason

    @pytest.mark.parametrize("reason,trigger", REFUSAL_TRIGGERS)
    def test_acknowledging_every_reason_at_once_still_does_not(self, reason, trigger) -> None:
        everything = sorted(set(_REFUSAL_SENTENCES) | set(_WARNING_SENTENCES))
        with pytest.raises(SlateFunctionRefusedError):
            trigger(everything)

    def test_the_trigger_table_covers_every_refusal_except_the_store_owned_one(self) -> None:
        covered = {reason for reason, _ in REFUSAL_TRIGGERS}
        assert set(_REFUSAL_SENTENCES) - covered == {"policy-version-conflict"}


class TestSecretsCannotCrossABoundary:
    """§29.5's first flat prohibition, and the half a schema cannot express."""

    def test_a_reference_inside_the_functions_own_environment_is_allowed(self) -> None:
        refs = [
            {
                "secret_name": "feed-token",
                "alias": "FEED",
                "scope": "environment",
                "owner_environment_id": "env-1",
                "owner_tenant_id": "tenant-1",
            }
        ]
        assert evaluate_function_safety(
            function(), policy=policy(), secret_refs=refs, now=NOW
        ) == []

    def test_a_reference_owned_by_another_environment_is_refused(self) -> None:
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            evaluate_function_safety(
                function(),
                policy=policy(),
                secret_refs=[{"secret_name": "k", "owner_environment_id": "env-2"}],
                now=NOW,
            )
        assert excinfo.value.code == "secret-cross-project"

    def test_a_reference_owned_by_another_tenant_is_refused(self) -> None:
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            evaluate_function_safety(
                function(),
                policy=policy(),
                secret_refs=[{"secret_name": "k", "owner_tenant_id": "tenant-2"}],
                now=NOW,
            )
        assert excinfo.value.code == "secret-cross-project"

    def test_a_function_scoped_reference_belonging_to_another_function_is_refused(self) -> None:
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            evaluate_function_safety(
                function(),
                policy=policy(),
                secret_refs=[
                    {"secret_name": "k", "scope": "function", "owner_function_id": "fn-9"}
                ],
                now=NOW,
            )
        assert excinfo.value.code == "secret-cross-project"

    def test_an_environment_scoped_reference_is_not_pinned_to_one_function(self) -> None:
        """That is what the scope means; pinning it would make the enum pointless."""
        assert evaluate_function_safety(
            function(),
            policy=policy(),
            secret_refs=[
                {"secret_name": "k", "scope": "environment", "owner_function_id": "fn-9"}
            ],
            now=NOW,
        ) == []

    def test_an_absent_owner_means_the_functions_own_boundary(self) -> None:
        """The ordinary case must not require a caller to restate what it already knows."""
        assert evaluate_function_safety(
            function(), policy=policy(), secret_refs=[{"secret_name": "k"}], now=NOW
        ) == []

    def test_a_secret_reference_has_no_field_able_to_hold_a_value(self) -> None:
        """The strongest claim this module makes about secrets is a structural absence."""
        normalized = normalize_secret_ref(
            {"secret_name": "k", "value": "hunter2", "secret": "hunter2"}
        )
        assert "hunter2" not in repr(normalized)
        assert set(normalized) == {
            "id",
            "function_id",
            "secret_name",
            "alias",
            "scope",
            "owner_tenant_id",
            "owner_environment_id",
            "owner_function_id",
        }


class TestEgressIsDenyByDefault:
    """§29.5's second flat prohibition, split between a write refusal and a runtime denial."""

    def test_a_function_declaring_nothing_is_allowed_with_no_allowlist_at_all(self) -> None:
        """Deny-by-default is the absence of a grant, not a reason to refuse the function."""
        assert evaluate_function_safety(function(), policy=policy(), now=NOW) == []

    def test_a_declared_destination_with_an_allowlist_entry_is_allowed(self) -> None:
        assert (
            evaluate_function_safety(
                function(declared_destinations=["https://api.example.com/v1/prices"]),
                policy=policy(),
                egress_rules=[egress()],
                now=NOW,
            )
            == []
        )

    def test_a_declared_destination_with_no_entry_is_refused(self) -> None:
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            evaluate_function_safety(
                function(declared_destinations=["evil.example.net"]),
                policy=policy(),
                egress_rules=[egress()],
                now=NOW,
            )
        assert excinfo.value.code == "egress-unapproved"

    def test_an_expired_entry_approves_nothing(self) -> None:
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            evaluate_function_safety(
                function(declared_destinations=["api.example.com"]),
                policy=policy(),
                egress_rules=[egress(expires_at=NOW - timedelta(days=1))],
                now=NOW,
            )
        assert excinfo.value.code == "egress-unapproved"

    def test_a_host_suffix_entry_requires_a_dot_so_a_lookalike_is_not_covered(self) -> None:
        rules = [egress(destination_kind="host-suffix", destination="example.com")]
        assert (
            evaluate_function_safety(
                function(declared_destinations=["api.example.com", "example.com"]),
                policy=policy(),
                egress_rules=rules,
                now=NOW,
            )
            == []
        )
        with pytest.raises(SlateFunctionRefusedError):
            evaluate_function_safety(
                function(declared_destinations=["evilexample.com"]),
                policy=policy(),
                egress_rules=rules,
                now=NOW,
            )

    def test_an_exact_host_entry_does_not_cover_a_subdomain(self) -> None:
        with pytest.raises(SlateFunctionRefusedError):
            evaluate_function_safety(
                function(declared_destinations=["inner.api.example.com"]),
                policy=policy(),
                egress_rules=[egress()],
                now=NOW,
            )

    def test_an_egress_rule_with_no_reason_is_refused(self) -> None:
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            evaluate_egress_safety(egress(reason=""), now=NOW)
        assert excinfo.value.code == "capability-without-reason"

    def test_an_egress_rule_may_be_permanent_because_a_dependency_is(self) -> None:
        """Forcing this to lapse would produce quarterly outages and gain nothing."""
        assert evaluate_egress_safety(egress(expires_at=None), now=NOW) == []

    def test_evaluating_a_rule_against_the_destination_it_is_meant_to_cover(self) -> None:
        assert (
            evaluate_egress_safety(
                egress(), destinations=["https://api.example.com/x"], now=NOW
            )
            == []
        )
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            evaluate_egress_safety(egress(), destinations=["other.example.net"], now=NOW)
        assert excinfo.value.code == "egress-unapproved"

    @pytest.mark.parametrize(
        "declared",
        [
            "API.EXAMPLE.COM",
            "https://api.example.com",
            "https://api.example.com:8443/path",
            "api.example.com/path",
        ],
    )
    def test_a_destination_is_compared_by_host_however_it_was_written(self, declared) -> None:
        assert (
            evaluate_function_safety(
                function(declared_destinations=[declared]),
                policy=policy(),
                egress_rules=[egress()],
                now=NOW,
            )
            == []
        )


class TestCapabilitySafety:
    """A grant that cannot say why it exists or when it ends is not reviewable."""

    def test_a_grant_with_a_reason_and_no_required_expiry_is_allowed(self) -> None:
        assert evaluate_capability_safety(capability(), now=NOW) == []

    @pytest.mark.parametrize("reason", ["", "   ", "\n"])
    def test_a_blank_reason_is_not_a_reason(self, reason) -> None:
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            evaluate_capability_safety(capability(reason=reason), now=NOW)
        assert excinfo.value.code == "capability-without-reason"

    @pytest.mark.parametrize(
        "key", sorted(k for k, v in CAPABILITY_CATALOG.items() if v.requires_expiry)
    )
    def test_a_privileged_grant_with_no_expiry_is_refused(self, key) -> None:
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            evaluate_capability_safety(
                capability(capability=key, expires_at=None), now=NOW
            )
        assert excinfo.value.code == "capability-unbounded"

    @pytest.mark.parametrize(
        "key", sorted(k for k, v in CAPABILITY_CATALOG.items() if not v.requires_expiry)
    )
    def test_an_ordinary_grant_may_be_permanent(self, key) -> None:
        assert evaluate_capability_safety(
            capability(capability=key, expires_at=None), now=NOW
        ) == []

    def test_a_grant_outliving_the_review_window_is_refused(self) -> None:
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            evaluate_capability_safety(
                capability(
                    capability="secret-read",
                    expires_at=NOW + timedelta(days=_MAX_CAPABILITY_WINDOW_DAYS + 1),
                ),
                now=NOW,
            )
        assert excinfo.value.code == "capability-unbounded"

    def test_a_grant_expiring_exactly_at_the_limit_is_allowed(self) -> None:
        assert (
            evaluate_capability_safety(
                capability(
                    capability="secret-read",
                    expires_at=NOW + timedelta(days=_MAX_CAPABILITY_WINDOW_DAYS),
                ),
                now=NOW,
            )
            == []
        )

    def test_the_capability_window_is_one_review_cycle(self) -> None:
        assert _MAX_CAPABILITY_WINDOW_DAYS == 90

    def test_an_iso_string_expiry_is_accepted_the_same_as_a_datetime(self) -> None:
        assert (
            evaluate_capability_safety(
                capability(
                    capability="secret-read",
                    expires_at=(NOW + timedelta(days=7)).isoformat(),
                ),
                now=NOW,
            )
            == []
        )

    def test_an_unparseable_expiry_reads_as_no_expiry_and_is_refused(self) -> None:
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            evaluate_capability_safety(
                capability(capability="secret-read", expires_at="whenever"), now=NOW
            )
        assert excinfo.value.code == "capability-unbounded"

    def test_a_capability_outside_the_catalog_is_not_forced_to_expire(self) -> None:
        """An unknown capability has no policy attached, so only the reason check applies."""
        assert evaluate_capability_safety(
            capability(capability="future-thing", expires_at=None), now=NOW
        ) == []


class TestStagedRollout:
    """A rollout is only a guarantee if the stages cannot be skipped."""

    def test_a_simulate_mode_function_needs_no_version_simulation_or_approval(self) -> None:
        assert evaluate_function_safety(function(), policy=policy(), now=NOW) == []

    def test_an_enforcing_function_with_no_active_version_is_refused(self) -> None:
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            evaluate_function_safety(
                enforcing(active_version_id=None), policy=policy(), now=NOW
            )
        assert excinfo.value.code == "enforce-without-version"

    def test_an_enforcing_function_that_never_simulated_is_refused(self) -> None:
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            evaluate_function_safety(
                function(rollout_mode="enforce", rollout_percent=100, simulated_at=None),
                policy=policy(),
                now=NOW,
            )
        assert excinfo.value.code == "enforce-without-simulation"

    def test_a_function_at_zero_percent_is_not_yet_enforcing(self) -> None:
        """Nothing is reached, so none of the enforcement gates apply yet."""
        assert (
            evaluate_function_safety(
                function(rollout_mode="enforce", rollout_percent=0, active_version_id=None),
                policy=policy(),
                now=NOW,
            )
            == []
        )

    def test_an_enforcing_function_with_a_distinct_approval_of_this_body_is_allowed(
        self,
    ) -> None:
        assert (
            evaluate_function_safety(approved(enforcing()), policy=policy(), now=NOW) == []
        )

    def test_re_editing_a_decisive_field_invalidates_the_approval(self) -> None:
        body = approved(enforcing())
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            evaluate_function_safety(
                dict(body, rollout_percent=100, matcher_value="/docs/"),
                policy=policy(),
                now=NOW,
            )
        assert excinfo.value.code == "approval-stale"

    def test_renaming_a_function_does_not_invalidate_its_approval(self) -> None:
        body = approved(enforcing())
        assert (
            evaluate_function_safety(
                dict(body, label="Geo banner (renamed)"), policy=policy(), now=NOW
            )
            == []
        )

    def test_the_gates_run_in_the_order_the_operator_can_act_on(self) -> None:
        """Missing version reported before missing simulation: you cannot simulate no code."""
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            evaluate_function_safety(
                function(rollout_mode="enforce", rollout_percent=100,
                         active_version_id=None, simulated_at=None),
                policy=policy(),
                now=NOW,
            )
        assert excinfo.value.code == "enforce-without-version"


class TestLimitsAndResidency:
    """A function may tighten a lane ceiling and cannot raise one."""

    @pytest.mark.parametrize(
        "field,value",
        [("cpu_ms_limit", 51), ("memory_mb_limit", 129), ("wall_ms_limit", 5001)],
    )
    def test_a_limit_above_the_lane_ceiling_is_refused(self, field, value) -> None:
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            evaluate_function_safety(
                function(**{field: value}), policy=policy(), now=NOW
            )
        assert excinfo.value.code == "limit-exceeds-ceiling"

    def test_a_limit_at_the_ceiling_is_allowed_and_does_not_warn(self) -> None:
        """Sitting exactly at the ceiling is the inherited default, not a risk."""
        assert (
            evaluate_function_safety(
                function(cpu_ms_limit=50, memory_mb_limit=128, wall_ms_limit=5000),
                policy=policy(),
                now=NOW,
            )
            == []
        )

    def test_a_tightened_limit_is_allowed(self) -> None:
        assert evaluate_function_safety(
            function(cpu_ms_limit=10), policy=policy(), now=NOW
        ) == []

    def test_inheriting_means_following_a_later_policy_change(self) -> None:
        """NULL is inherit, which is different from pinning today's lane value."""
        assert normalize_function(function())["cpu_ms_limit"] is None
        assert (
            evaluate_function_safety(
                function(), policy=policy(default_cpu_ms_limit=10), now=NOW
            )
            == []
        )

    def test_a_function_may_be_stricter_than_its_lane(self) -> None:
        assert (
            evaluate_function_safety(
                function(residency_class="in-region-only"),
                policy=policy(default_residency_class="unrestricted"),
                now=NOW,
            )
            == []
        )

    def test_a_function_may_not_be_looser_than_its_lane(self) -> None:
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            evaluate_function_safety(
                function(residency_class="unrestricted"),
                policy=policy(default_residency_class="in-region-only"),
                now=NOW,
            )
        assert excinfo.value.code == "residency-violation"

    def test_matching_the_lane_exactly_is_allowed(self) -> None:
        assert (
            evaluate_function_safety(
                function(residency_class="region-pinned"),
                policy=policy(default_residency_class="region-pinned"),
                now=NOW,
            )
            == []
        )


class TestPolicySafety:
    """A residency promise ends quietly, so ending it has to be explained."""

    def test_loosening_residency_without_a_reason_is_refused(self) -> None:
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            evaluate_policy_safety(
                policy(default_residency_class="unrestricted", residency_waiver_reason=None)
            )
        assert excinfo.value.code == "residency-violation"

    @pytest.mark.parametrize("reason", ["", "   "])
    def test_a_blank_reason_is_not_a_reason(self, reason) -> None:
        with pytest.raises(SlateFunctionRefusedError):
            evaluate_policy_safety(
                policy(default_residency_class="unrestricted", residency_waiver_reason=reason)
            )

    def test_loosening_it_with_a_reason_is_allowed(self) -> None:
        assert (
            evaluate_policy_safety(
                policy(
                    default_residency_class="unrestricted",
                    residency_waiver_reason="Latency in APAC; reviewed 2026-07-01.",
                )
            )
            == []
        )

    def test_the_restrictive_classes_need_no_waiver(self) -> None:
        assert evaluate_policy_safety(policy()) == []
        assert evaluate_policy_safety(policy(default_residency_class="region-pinned")) == []

    def test_a_policy_level_problem_does_not_refuse_a_function_edit(self) -> None:
        """An operator narrowing a matcher must not be blocked by somebody else's waiver."""
        assert (
            evaluate_function_safety(
                function(),
                policy=policy(
                    default_residency_class="unrestricted", residency_waiver_reason=None
                ),
                now=NOW,
            )
            == []
        )

    def test_a_lane_that_was_never_configured_reads_as_the_shipped_defaults(self) -> None:
        resolved = normalize_policy(None)
        assert resolved["functions_enabled"] is False
        assert resolved["default_residency_class"] == "in-region-only"
        assert resolved["default_cpu_ms_limit"] == 50


class TestEdgeIsNeverClaimed:
    """There is no runtime, and no argument here can pretend otherwise."""

    def test_edge_attachment_defaults_to_false(self) -> None:
        assert normalize_policy(None)["edge_attached"] is False
        assert normalize_policy({})["edge_attached"] is False

    def test_edge_attachment_is_never_inferred_from_a_provider_name(self) -> None:
        resolved = normalize_policy({"edge_provider": "some-runtime"})
        assert resolved["edge_attached"] is False
        assert resolved["edge_provider"] == "some-runtime"


class TestVariantSafety:
    """§29.5: audience rule, fallback, cache-key effect, analytics and privacy, or none of them."""

    def test_a_coarse_non_personal_variant_with_a_fallback_is_allowed(self) -> None:
        assert evaluate_variant_safety(variant()) == []

    @pytest.mark.parametrize("fallback", ["", "   ", None])
    def test_a_variant_with_no_fallback_is_refused(self, fallback) -> None:
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            evaluate_variant_safety(variant(fallback_variant=fallback))
        assert excinfo.value.code == "variant-without-fallback"

    @pytest.mark.parametrize(
        "dimension",
        ["cookie", "sessionId", "session_id", "Session ID", "userId", "auth", "jwt", "apiKey"],
    )
    def test_varying_a_shared_key_on_an_identity_credential_is_refused(
        self, dimension
    ) -> None:
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            evaluate_variant_safety(
                variant(vary_dimension=dimension, analytics_dimension=dimension)
            )
        assert excinfo.value.code == "variant-identity-cache-key"

    def test_bypassing_the_cache_on_an_identity_dimension_is_allowed(self) -> None:
        """Nothing is stored, so nothing can be served to the wrong reader."""
        assert (
            evaluate_variant_safety(
                variant(
                    cache_key_effect="bypass-cache",
                    vary_dimension="sessionId",
                    analytics_dimension="sessionId",
                )
            )
            == []
        )

    def test_personalizing_without_touching_the_cache_key_is_refused(self) -> None:
        """The §29.3 defect: a shared entry that differs per reader."""
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            evaluate_variant_safety(
                variant(privacy_class="pseudonymous", cache_key_effect="none")
            )
        assert excinfo.value.code == "variant-identity-cache-key"

    def test_a_non_personal_variant_may_leave_the_key_alone(self) -> None:
        assert evaluate_variant_safety(variant(cache_key_effect="none")) == []

    def test_personal_data_with_no_consent_basis_is_refused(self) -> None:
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            evaluate_variant_safety(
                variant(
                    privacy_class="personal",
                    consent_basis="not-required",
                    cache_key_effect="bypass-cache",
                )
            )
        assert excinfo.value.code == "variant-personal-without-basis"

    @pytest.mark.parametrize("basis", ["explicit-consent", "legitimate-interest"])
    def test_personal_data_with_a_stated_basis_is_allowed(self, basis) -> None:
        assert (
            evaluate_variant_safety(
                variant(
                    privacy_class="personal",
                    consent_basis=basis,
                    cache_key_effect="bypass-cache",
                )
            )
            == []
        )

    def test_personal_data_in_an_unrestricted_region_is_refused(self) -> None:
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            evaluate_variant_safety(
                variant(
                    privacy_class="personal",
                    consent_basis="explicit-consent",
                    cache_key_effect="bypass-cache",
                ),
                policy=policy(
                    default_residency_class="unrestricted",
                    residency_waiver_reason="Latency.",
                ),
            )
        assert excinfo.value.code == "residency-violation"

    def test_a_pseudonymous_variant_may_run_unrestricted(self) -> None:
        """The refusal is scoped to personal data, not to personalization as such."""
        assert (
            evaluate_variant_safety(
                variant(privacy_class="pseudonymous", cache_key_effect="bypass-cache"),
                policy=policy(
                    default_residency_class="unrestricted",
                    residency_waiver_reason="Latency.",
                ),
            )
            == []
        )

    def test_a_function_pinning_a_stricter_region_rescues_a_personal_variant(self) -> None:
        assert (
            evaluate_variant_safety(
                variant(
                    privacy_class="personal",
                    consent_basis="explicit-consent",
                    cache_key_effect="bypass-cache",
                ),
                function=function(residency_class="in-region-only"),
                policy=policy(
                    default_residency_class="unrestricted",
                    residency_waiver_reason="Latency.",
                ),
            )
            == []
        )

    def test_a_variant_edit_is_not_refused_for_the_functions_matcher(self) -> None:
        """The split evaluators exist so an unrelated problem does not block this write."""
        assert (
            evaluate_variant_safety(
                variant(), function=function(matcher_kind="regex", matcher_value="([bad")
            )
            == []
        )


class TestWarningsAreAcknowledgeable:
    """Costs, not boundary crossings: each returns rather than raises."""

    def test_a_broad_matcher_warns(self) -> None:
        codes = [
            w.code
            for w in evaluate_function_safety(
                function(matcher_value="/"), policy=policy(), now=NOW
            )
        ]
        assert "broad-matcher" in codes

    def test_a_narrow_matcher_does_not_warn(self) -> None:
        assert evaluate_function_safety(function(), policy=policy(), now=NOW) == []

    def test_the_broad_matcher_threshold_is_the_first_path_segment(self) -> None:
        assert _BROAD_MATCHER_MAX_SEGMENTS == 1
        one_segment = evaluate_function_safety(
            function(matcher_value="/docs/"), policy=policy(), now=NOW
        )
        assert [w.code for w in one_segment] == ["broad-matcher"]

    def test_a_rollout_jumping_straight_to_everything_warns(self) -> None:
        codes = [
            w.code
            for w in evaluate_function_safety(
                function(rollout_percent=100, previous_rollout_percent=0),
                policy=policy(),
                now=NOW,
            )
        ]
        assert "rollout-jump" in codes

    def test_a_staged_rollout_does_not_warn(self) -> None:
        codes = [
            w.code
            for w in evaluate_function_safety(
                function(rollout_percent=100, previous_rollout_percent=50),
                policy=policy(),
                now=NOW,
            )
        ]
        assert "rollout-jump" not in codes

    def test_a_limit_close_to_the_ceiling_warns(self) -> None:
        codes = [
            w.code
            for w in evaluate_function_safety(
                function(cpu_ms_limit=48), policy=policy(), now=NOW
            )
        ]
        assert "limit-near-ceiling" in codes

    def test_a_limit_with_headroom_does_not_warn(self) -> None:
        codes = [
            w.code
            for w in evaluate_function_safety(
                function(cpu_ms_limit=20), policy=policy(), now=NOW
            )
        ]
        assert "limit-near-ceiling" not in codes

    def test_the_headroom_ratio_is_stated_rather_than_measured(self) -> None:
        assert _LIMIT_NEAR_CEILING_RATIO == 0.9

    def test_a_shadowed_function_warns(self) -> None:
        codes = [
            w.code
            for w in evaluate_function_safety(
                function(id="mine", ordinal=5, matcher_value="/docs/guide/api/"),
                siblings=[function(id="theirs", ordinal=1, matcher_value="/docs/guide/")],
                policy=policy(),
                now=NOW,
            )
        ]
        assert "function-shadowed" in codes

    def test_a_lower_precedence_function_does_not_shadow_a_higher_one(self) -> None:
        codes = [
            w.code
            for w in evaluate_function_safety(
                function(id="mine", ordinal=1, matcher_value="/docs/guide/api/"),
                siblings=[function(id="theirs", ordinal=5, matcher_value="/docs/guide/")],
                policy=policy(),
                now=NOW,
            )
        ]
        assert "function-shadowed" not in codes

    def test_a_disabled_function_shadows_nothing(self) -> None:
        codes = [
            w.code
            for w in evaluate_function_safety(
                function(id="mine", ordinal=5, matcher_value="/docs/guide/api/"),
                siblings=[
                    function(
                        id="theirs", ordinal=1, matcher_value="/docs/guide/", enabled=False
                    )
                ],
                policy=policy(),
                now=NOW,
            )
        ]
        assert "function-shadowed" not in codes

    def test_shadowing_is_not_guessed_across_regexes(self) -> None:
        """A warning an operator cannot act on is worse than no warning."""
        codes = [
            w.code
            for w in evaluate_function_safety(
                function(id="mine", ordinal=5, matcher_kind="regex", matcher_value="^/docs/g"),
                siblings=[
                    function(
                        id="theirs", ordinal=1, matcher_kind="regex", matcher_value="^/docs/"
                    )
                ],
                policy=policy(),
                now=NOW,
            )
        ]
        assert "function-shadowed" not in codes

    def test_a_high_cardinality_vary_dimension_warns(self) -> None:
        codes = [
            w.code
            for w in evaluate_variant_safety(
                variant(
                    audience_kind="cohort",
                    vary_dimension="cohort",
                    analytics_dimension="cohort",
                )
            )
        ]
        assert "cache-fragmenting" in codes

    def test_a_coarse_vary_dimension_does_not_warn(self) -> None:
        assert evaluate_variant_safety(variant()) == []

    def test_the_high_cardinality_list_is_names_rather_than_a_measurement(self) -> None:
        assert "cohort" in _HIGH_CARDINALITY_DIMENSIONS
        assert "country" not in _HIGH_CARDINALITY_DIMENSIONS

    def test_a_variant_with_no_analytics_dimension_warns(self) -> None:
        codes = [
            w.code
            for w in evaluate_variant_safety(
                variant(analytics_dimension="", vary_dimension="country")
            )
        ]
        assert "variant-without-analytics" in codes

    @pytest.mark.parametrize("code", sorted(_WARNING_SENTENCES))
    def test_every_warning_code_is_acknowledgeable_rather_than_blocking(self, code) -> None:
        assert code not in _HARD_REFUSALS

    def test_acknowledging_a_warning_does_not_change_the_write_outcome(self) -> None:
        """The caller decides what to do with an acknowledgement; this module does not."""
        plain = evaluate_function_safety(
            function(matcher_value="/"), policy=policy(), now=NOW
        )
        acked = evaluate_function_safety(
            function(matcher_value="/", acknowledged_warnings=["broad-matcher"]),
            policy=policy(),
            now=NOW,
        )
        assert [w.code for w in plain] == [w.code for w in acked]

    def test_warnings_never_raise_however_many_accumulate(self) -> None:
        warnings = evaluate_function_safety(
            function(
                id="mine",
                ordinal=5,
                matcher_value="/",
                rollout_percent=100,
                previous_rollout_percent=0,
                cpu_ms_limit=48,
            ),
            siblings=[function(id="theirs", ordinal=1, matcher_value="/")],
            policy=policy(),
            now=NOW,
        )
        assert {w.code for w in warnings} >= {
            "broad-matcher",
            "rollout-jump",
            "limit-near-ceiling",
            "function-shadowed",
        }


class TestIdentityDimensionDetection:
    """Erring towards yes is deliberate: a false negative is a reader-keyed shared cache."""

    def test_the_token_list_is_a_stated_list_rather_than_a_heuristic(self) -> None:
        assert "cookie" in _IDENTITY_DIMENSION_TOKENS
        assert "session" in _IDENTITY_DIMENSION_TOKENS
        assert "country" not in _IDENTITY_DIMENSION_TOKENS

    @pytest.mark.parametrize(
        "dimension", ["country", "language", "device-class", "release", "locale"]
    )
    def test_a_coarse_dimension_is_not_treated_as_an_identity(self, dimension) -> None:
        assert (
            evaluate_variant_safety(
                variant(vary_dimension=dimension, analytics_dimension=dimension)
            )
            == []
        )


class TestMatching:
    """Route matching is the same on the cache, security and function surfaces, on purpose."""

    @pytest.mark.parametrize(
        "kind,value,path,expected",
        [
            ("exact", "/docs/guide", "/docs/guide", True),
            ("exact", "/docs/guide", "/docs/guide/", False),
            ("prefix", "/docs", "/docsearch", True),
            ("prefix", "/docs/", "/docsearch", False),
            ("glob", "/docs/*/api", "/docs/v1/api", True),
            # fnmatch's `*` crosses separators, exactly as it does on the cache and security
            # surfaces. Pinned rather than fixed: three surfaces agreeing is worth more than one
            # of them being segment-aware, and an operator who wants one segment writes a regex.
            ("glob", "/docs/*/api", "/docs/v1/v2/api", True),
            ("regex", r"^/docs/v\d+/", "/docs/v2/x", True),
            ("regex", r"^/docs/v\d+/", "/docs/vx/x", False),
        ],
    )
    def test_matcher_kinds(self, kind, value, path, expected) -> None:
        fn = normalize_function(function(matcher_kind=kind, matcher_value=value))
        assert matches_route(fn, InvocationRequest(path=path).normalized()) is expected

    def test_an_empty_method_list_means_every_method(self) -> None:
        fn = normalize_function(function(matcher_methods=[]))
        for method in ("GET", "POST", "DELETE"):
            assert matches_route(
                fn, InvocationRequest(method=method, path="/docs/guide/x").normalized()
            )

    def test_a_method_scope_narrows_the_matcher(self) -> None:
        fn = normalize_function(function(matcher_methods=["post"]))
        assert matches_route(fn, InvocationRequest(method="POST", path="/docs/guide/x").normalized())
        assert not matches_route(
            fn, InvocationRequest(method="GET", path="/docs/guide/x").normalized()
        )

    def test_a_host_scope_narrows_the_matcher(self) -> None:
        fn = normalize_function(function(matcher_hosts=["Docs.Example.COM"]))
        assert matches_route(
            fn, InvocationRequest(host="docs.example.com", path="/docs/guide/x").normalized()
        )
        assert not matches_route(
            fn, InvocationRequest(host="other.example.com", path="/docs/guide/x").normalized()
        )

    def test_an_uncompilable_regex_matches_nothing_rather_than_raising(self) -> None:
        """The write already refused it; a simulation over stored policy must still render."""
        fn = normalize_function(function(matcher_kind="regex", matcher_value="([bad"))
        assert matches_route(fn, InvocationRequest(path="/anything").normalized()) is False

    @pytest.mark.parametrize(
        "kind,value",
        [
            ("prefix", "/"),
            ("prefix", ""),
            ("glob", "*"),
            ("glob", "/**"),
            ("regex", ".*"),
            ("regex", ""),
        ],
    )
    def test_covers_everything_errs_towards_saying_yes(self, kind, value) -> None:
        assert covers_everything(
            normalize_function(function(matcher_kind=kind, matcher_value=value))
        )

    def test_an_exact_matcher_never_covers_everything(self) -> None:
        assert not covers_everything(
            normalize_function(function(matcher_kind="exact", matcher_value="/"))
        )


class TestNormalization:
    """Normalizing once is what makes two spellings of one function hash the same."""

    def test_methods_and_hosts_are_case_folded_because_http_is(self) -> None:
        normalized = normalize_function(
            function(matcher_methods=["get", "Post"], matcher_hosts=["Docs.EXAMPLE.com"])
        )
        assert normalized["matcher_methods"] == ["GET", "POST"]
        assert normalized["matcher_hosts"] == ["docs.example.com"]

    def test_missing_fields_take_their_column_defaults(self) -> None:
        normalized = normalize_function({})
        assert normalized["runtime"] == "js-isolate"
        assert normalized["rollout_mode"] == "simulate"
        assert normalized["rollout_percent"] == 0
        assert normalized["matcher_kind"] == "prefix"

    def test_an_absent_matcher_defaults_to_root(self) -> None:
        assert normalize_function({})["matcher_value"] == "/"

    def test_an_explicitly_empty_matcher_is_preserved_rather_than_widened(self) -> None:
        """Coercing "" to "/" would turn a half-filled form into a lane-wide function."""
        assert normalize_function({"matcher_value": ""})["matcher_value"] == ""
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            evaluate_function_safety(function(matcher_value=""), policy=policy(), now=NOW)
        assert excinfo.value.code == "matcher-invalid"

    def test_null_overrides_are_kept_as_inherit(self) -> None:
        normalized = normalize_function({})
        assert normalized["region"] is None
        assert normalized["residency_class"] is None
        assert normalized["cpu_ms_limit"] is None

    def test_a_variant_keeps_a_missing_fallback_as_empty_rather_than_inventing_one(self) -> None:
        assert normalize_variant({})["fallback_variant"] == ""

    def test_a_variant_vary_dimension_falls_back_to_its_analytics_dimension(self) -> None:
        assert normalize_variant({"analytics_dimension": "country"})["vary_dimension"] == (
            "country"
        )

    def test_a_capability_keeps_a_missing_expiry_as_none(self) -> None:
        assert normalize_capability({})["expires_at"] is None

    def test_an_egress_destination_is_case_folded_because_dns_is(self) -> None:
        assert normalize_egress_rule({"destination": "API.Example.COM"})["destination"] == (
            "api.example.com"
        )

    @pytest.mark.parametrize(
        "normalizer,body",
        [
            (normalize_function, {"id": "x", "matcher_methods": ["get"]}),
            (normalize_variant, {"id": "x", "analytics_dimension": "country"}),
            (normalize_capability, {"capability": "geo-read", "reason": "why"}),
            (normalize_egress_rule, {"destination": "API.example.com"}),
            (normalize_secret_ref, {"secret_name": "k"}),
        ],
    )
    def test_normalizing_is_idempotent(self, normalizer, body) -> None:
        once = normalizer(body)
        assert normalizer(once) == once


class TestApprovalSafety:
    """Dual control compares immutable keys, so offboarding cannot weaken a recorded approval."""

    DIGEST = "sha256:" + "a" * 64

    def test_no_approvals_at_all_is_refused_as_missing(self) -> None:
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            evaluate_approval_safety(
                author_actor_key="actor-author", approvals=[], digest=self.DIGEST
            )
        assert excinfo.value.code == "enforce-without-approval"

    def test_only_the_authors_own_approval_is_refused_as_self_approval(self) -> None:
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            evaluate_approval_safety(
                author_actor_key="actor-author",
                approvals=[
                    {"approver_actor_key": "actor-author", "digest": self.DIGEST}
                ],
                digest=self.DIGEST,
            )
        assert excinfo.value.code == "approval-self"

    def test_a_distinct_approval_of_a_different_body_is_refused_as_stale(self) -> None:
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            evaluate_approval_safety(
                author_actor_key="actor-author",
                approvals=[
                    {"approver_actor_key": "actor-reviewer", "digest": "sha256:" + "b" * 64}
                ],
                digest=self.DIGEST,
            )
        assert excinfo.value.code == "approval-stale"

    def test_the_authors_own_approval_cannot_satisfy_the_digest_check(self) -> None:
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            evaluate_approval_safety(
                author_actor_key="actor-author",
                approvals=[
                    {"approver_actor_key": "actor-author", "digest": self.DIGEST},
                    {"approver_actor_key": "actor-reviewer", "digest": "sha256:" + "c" * 64},
                ],
                digest=self.DIGEST,
            )
        assert excinfo.value.code == "approval-stale"

    def test_a_distinct_approval_of_this_body_passes_silently(self) -> None:
        assert (
            evaluate_approval_safety(
                author_actor_key="actor-author",
                approvals=[
                    {"approver_actor_key": "actor-reviewer", "digest": self.DIGEST}
                ],
                digest=self.DIGEST,
            )
            is None
        )


class TestOrdinalConflict:
    """Two functions at one precedence would make a simulation unreproducible."""

    def test_two_functions_at_the_same_precedence_are_refused(self) -> None:
        with pytest.raises(SlateFunctionRefusedError) as excinfo:
            evaluate_function_safety(
                function(id="mine", ordinal=5),
                siblings=[function(id="theirs", ordinal=5)],
                policy=policy(),
                now=NOW,
            )
        assert excinfo.value.code == "ordinal-conflict"

    def test_a_function_does_not_conflict_with_itself(self) -> None:
        assert (
            evaluate_function_safety(
                function(id="fn-1", ordinal=5),
                siblings=[function(id="fn-1", ordinal=5)],
                policy=policy(),
                now=NOW,
            )
            == []
        )

    def test_distinct_precedences_are_allowed(self) -> None:
        assert (
            evaluate_function_safety(
                function(id="mine", ordinal=5),
                siblings=[function(id="theirs", ordinal=6)],
                policy=policy(),
                now=NOW,
            )
            == []
        )


class TestPurity:
    """No database, no clock. `now` is a parameter, and it is load-bearing."""

    def test_the_same_grant_flips_verdict_on_the_instant_it_is_judged_against(self) -> None:
        grant = capability(
            capability="secret-read", expires_at=NOW + timedelta(days=30)
        )
        assert evaluate_capability_safety(grant, now=NOW) == []
        with pytest.raises(SlateFunctionRefusedError):
            evaluate_capability_safety(grant, now=NOW - timedelta(days=70))

    def test_evaluation_does_not_consult_the_wall_clock(self) -> None:
        """A grant far in the real past is still judged against the injected instant."""
        past = datetime(2000, 1, 1, tzinfo=timezone.utc)
        grant = capability(capability="secret-read", expires_at=past + timedelta(days=1))
        assert evaluate_capability_safety(grant, now=past) == []

    def test_function_safety_evaluation_is_repeatable(self) -> None:
        body = function(matcher_value="/")
        first = evaluate_function_safety(body, policy=policy(), now=NOW)
        second = evaluate_function_safety(body, policy=policy(), now=NOW)
        assert [w.code for w in first] == [w.code for w in second]

    def test_a_naive_expiry_is_compared_without_raising(self) -> None:
        grant = capability(
            capability="secret-read", expires_at=datetime(2026, 7, 26, 12, 0, 0)
        )
        assert evaluate_capability_safety(grant, now=NOW) == []

    def test_an_aware_expiry_is_comparable_with_a_naive_now(self) -> None:
        naive_now = datetime(2026, 7, 19, 12, 0, 0)
        grant = capability(capability="secret-read", expires_at=NOW + timedelta(days=7))
        assert evaluate_capability_safety(grant, now=naive_now) == []

    def test_no_evaluator_imports_a_database_session(self) -> None:
        import app.slate_functions as module

        source = module.__file__
        with open(source, "r", encoding="utf-8") as handle:
            text = handle.read()
        assert "sqlalchemy" not in text.lower()
        assert "from app.database" not in text
        assert "datetime.now(" not in text
        assert "datetime.utcnow(" not in text


class TestBodyDigest:
    """An approval names a body, not a row id, so re-editing invalidates it."""

    def test_the_digest_matches_the_column_constraint(self) -> None:
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", body_digest(function()))

    def test_the_digest_is_stable_across_a_rename(self) -> None:
        assert body_digest(function()) == body_digest(function(label="Something else"))

    def test_the_digest_is_stable_across_key_reordering(self) -> None:
        body = function()
        reordered = {k: body[k] for k in reversed(list(body))}
        assert body_digest(body) == body_digest(reordered)

    def test_the_digest_ignores_who_wrote_it_and_who_approved_it(self) -> None:
        assert body_digest(function()) == body_digest(
            function(author_actor_key="somebody-else", approvals=[{"x": 1}])
        )

    def test_the_digest_ignores_the_acknowledgements(self) -> None:
        assert body_digest(function()) == body_digest(
            function(acknowledged_warnings=["broad-matcher"])
        )

    @pytest.mark.parametrize(
        "field,value",
        [
            ("ordinal", 9),
            ("enabled", False),
            ("matcher_kind", "glob"),
            ("matcher_value", "/other/"),
            ("matcher_methods", ["POST"]),
            ("matcher_hosts", ["other.example.com"]),
            ("runtime", "wasm"),
            ("active_version_id", "ver-2"),
            ("rollout_mode", "enforce"),
            ("rollout_percent", 100),
            ("region", "us-east"),
            ("residency_class", "region-pinned"),
            ("cpu_ms_limit", 25),
            ("memory_mb_limit", 64),
            ("wall_ms_limit", 1000),
            ("env_var_names", ["FEATURE_X"]),
            ("declared_destinations", ["api.example.com"]),
        ],
    )
    def test_the_digest_changes_when_a_decisive_field_changes(self, field, value) -> None:
        assert body_digest(function()) != body_digest(function(**{field: value}))

    def test_the_digest_is_repeatable(self) -> None:
        assert body_digest(function()) == body_digest(function())

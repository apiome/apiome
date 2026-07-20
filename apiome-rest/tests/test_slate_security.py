"""Security catalogs, refusal vocabulary and safety evaluation — UXE-3.2 (private-suite#2474).

Pure tests over :mod:`app.slate_security`: no TestClient, no database, no clock. ``now`` is a
parameter everywhere it matters, and :class:`TestPurity` asserts that it actually is one.

The suite is weighted toward the two claims the feature rests on:

* **Criterion 2, managed presets have safe defaults and explain expected impact.** Every catalog
  entry is asserted to carry prose, and the *defaults* are asserted to be the cautious option —
  a documentation lane must not ship on the tier whose own ``unsafe_if`` says it blocks readers
  for searching. A preset that cannot say what it will break is asserted to be a test failure
  rather than a code-review comment.
* **Criterion 3, a lockout has no acknowledgement path.** The asymmetry between
  :data:`app.slate_security._HARD_REFUSALS` and :data:`app.slate_security._WARNING_SENTENCES` is
  the whole design, so it is pinned in both directions: acknowledging a refusal is asserted not
  to let the write through, and acknowledging a warning is asserted not to be needed for it to.

Simulation and digests live in ``tests/test_slate_security_simulate.py``.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import get_args

import pytest

from app.slate_security import (
    BOT_PRESET_IDS,
    BOT_PRESETS,
    EVENT_ACTIONS,
    GROUP_MODES,
    MANAGED_GROUP_IDS,
    MANAGED_GROUPS,
    MANAGED_RULESET_IDS,
    MANAGED_RULESETS,
    MATCHER_KINDS,
    RATE_PRESET_IDS,
    RATE_PRESETS,
    ROLLOUT_MODES,
    RULE_ACTIONS,
    SecurityRefusal,
    SecurityRefusalReason,
    SecurityWarning,
    SlateSecurityRefusedError,
    body_digest,
    covers_everything,
    evaluate_approval_safety,
    evaluate_exception_safety,
    evaluate_policy_safety,
    evaluate_security_safety,
    matches_route,
    normalize_exception,
    normalize_policy,
    normalize_rule,
)
from app.slate_security import (
    _HARD_REFUSALS,
    _MAX_EXCEPTION_WINDOW_DAYS,
    _RATE_FLOOR_REQUESTS_PER_MINUTE,
    _REFUSAL_SENTENCES,
    _WARNING_SENTENCES,
)

NOW = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)


def rule(**overrides):
    """A narrowly-scoped logging rule; each test states only the field it is about.

    The baseline deliberately does not act — ``log`` is the one action that can neither lock a
    reader out nor cost search visibility — so any refusal or warning a test observes was caused
    by the override it made, not by the fixture.
    """
    base = {
        "id": "rule-1",
        "ordinal": 0,
        "enabled": True,
        "label": "Scraper watch",
        "matcher_kind": "prefix",
        "matcher_value": "/docs/api/",
        "matcher_methods": [],
        "matcher_hosts": [],
        "conditions": [],
        "action": "log",
        "rate_requests": None,
        "rate_window_seconds": None,
        "rollout_mode": "simulate",
        "rollout_percent": 10,
        "previous_rollout_percent": None,
        "simulated_at": None,
        "expires_at": None,
        "acknowledged_warnings": [],
        "author_actor_key": "actor-author",
        "approvals": [],
    }
    base.update(overrides)
    return base


def approved(candidate, approver="actor-reviewer"):
    """Attach a valid second-person approval of exactly this body."""
    return dict(candidate, approvals=[{"approver_actor_key": approver, "digest": body_digest(candidate)}])


def exception(**overrides):
    """A scoped, expiring carve-out."""
    base = {
        "id": "exc-1",
        "subject_kind": "managed-group",
        "subject_ref": "sql-injection",
        "matcher_kind": "prefix",
        "matcher_value": "/docs/search",
        "expires_at": NOW + timedelta(days=7),
        "reason": "Reader queries quote SQL on the SQL guide.",
    }
    base.update(overrides)
    return base


# Every hard refusal, paired with a body that provokes it from this module. Each callable takes
# an ``ack`` list which is threaded into the body, so the same table drives both "the refusal
# fires" and "acknowledging it changes nothing".
def _trigger_blocks_entire_site(ack):
    evaluate_security_safety(
        rule(action="block", matcher_kind="prefix", matcher_value="/", acknowledged_warnings=ack)
    )


def _trigger_blocks_documentation_root(ack):
    evaluate_security_safety(
        rule(action="challenge", matcher_kind="exact", matcher_value="/", acknowledged_warnings=ack)
    )


def _trigger_enforce_without_simulation(ack):
    evaluate_security_safety(
        rule(
            action="challenge",
            rollout_mode="enforce",
            rollout_percent=100,
            simulated_at=None,
            acknowledged_warnings=ack,
        )
    )


def _trigger_enforce_without_approval(ack):
    evaluate_security_safety(
        rule(
            action="block",
            rollout_mode="enforce",
            rollout_percent=100,
            simulated_at=NOW - timedelta(days=1),
            approvals=[],
            acknowledged_warnings=ack,
        )
    )


def _trigger_rate_limit_below_floor(ack):
    evaluate_security_safety(
        rule(
            action="rate-limit",
            rate_requests=10,
            rate_window_seconds=60,
            acknowledged_warnings=ack,
        )
    )


def _trigger_matcher_invalid(ack):
    evaluate_security_safety(
        rule(matcher_kind="regex", matcher_value="([unclosed", acknowledged_warnings=ack)
    )


def _trigger_ordinal_conflict(ack):
    evaluate_security_safety(
        rule(id="mine", ordinal=5, acknowledged_warnings=ack),
        siblings=[rule(id="theirs", ordinal=5)],
    )


def _trigger_exception_unbounded(ack):
    evaluate_exception_safety(exception(expires_at=None, acknowledged_warnings=ack), now=NOW)


def _trigger_exception_outlives_limit(ack):
    evaluate_exception_safety(
        exception(
            expires_at=NOW + timedelta(days=_MAX_EXCEPTION_WINDOW_DAYS + 1),
            acknowledged_warnings=ack,
        ),
        now=NOW,
    )


def _trigger_managed_off_without_reason(ack):
    evaluate_policy_safety(
        {"managed_ruleset": "off", "managed_off_reason": "", "acknowledged_warnings": ack}
    )


def _trigger_approval_self(ack):
    body = rule(action="block", rollout_mode="enforce", rollout_percent=100,
                simulated_at=NOW - timedelta(days=1), acknowledged_warnings=ack)
    evaluate_security_safety(approved(body, approver="actor-author"))


def _trigger_approval_stale(ack):
    body = rule(action="block", rollout_mode="enforce", rollout_percent=100,
                simulated_at=NOW - timedelta(days=1), acknowledged_warnings=ack)
    stale = approved(body)
    # Re-edit a decisive field after the approval was recorded.
    evaluate_security_safety(dict(stale, matcher_value="/docs/api/v2/"))


#: (reason, trigger) for every hard refusal this module can raise from a body. The one omission
#: is ``policy-version-conflict``, which is a store-level concurrency check with no pure trigger;
#: :meth:`TestRefusalVocabulary.test_every_declared_reason_has_a_sentence` still covers it.
REFUSAL_TRIGGERS = [
    ("blocks-entire-site", _trigger_blocks_entire_site),
    ("blocks-documentation-root", _trigger_blocks_documentation_root),
    ("enforce-without-simulation", _trigger_enforce_without_simulation),
    ("enforce-without-approval", _trigger_enforce_without_approval),
    ("rate-limit-below-floor", _trigger_rate_limit_below_floor),
    ("matcher-invalid", _trigger_matcher_invalid),
    ("ordinal-conflict", _trigger_ordinal_conflict),
    ("exception-unbounded", _trigger_exception_unbounded),
    ("exception-outlives-limit", _trigger_exception_outlives_limit),
    ("managed-off-without-reason", _trigger_managed_off_without_reason),
    ("approval-self", _trigger_approval_self),
    ("approval-stale", _trigger_approval_stale),
]


class TestEnumerations:
    """The vocabularies V188 CHECKs, pinned so a widened enum is a visible diff."""

    def test_matcher_kinds_match_the_cache_surface(self) -> None:
        """An operator who learned `glob` on the cache screen must not have to relearn it."""
        assert MATCHER_KINDS == ("exact", "prefix", "glob", "regex")

    def test_rule_actions_are_the_five_v188_allows(self) -> None:
        assert RULE_ACTIONS == ("allow", "log", "challenge", "rate-limit", "block")

    def test_a_rule_is_either_recording_or_acting(self) -> None:
        assert ROLLOUT_MODES == ("simulate", "enforce")

    def test_group_modes_include_off_so_a_group_can_be_stood_down(self) -> None:
        assert GROUP_MODES == ("off", "log", "challenge", "block")

    def test_would_block_is_a_first_class_event_action(self) -> None:
        """Without it, a simulated denial would have to be recorded as a real one."""
        assert "would-block" in EVENT_ACTIONS
        assert "blocked" in EVENT_ACTIONS

    def test_catalog_ids_agree_with_their_tables(self) -> None:
        assert tuple(MANAGED_RULESETS) == MANAGED_RULESET_IDS
        assert tuple(BOT_PRESETS) == BOT_PRESET_IDS
        assert tuple(RATE_PRESETS) == RATE_PRESET_IDS
        assert tuple(MANAGED_GROUPS) == MANAGED_GROUP_IDS


class TestManagedGroupCatalog:
    """Criterion 2: a group that cannot say what it will break is a group nobody can enable."""

    def test_every_roadmap_group_is_present(self) -> None:
        assert set(MANAGED_GROUP_IDS) >= {
            "sql-injection",
            "xss",
            "path-traversal",
            "remote-code-execution",
            "scanner-detection",
            "protocol-anomaly",
        }

    @pytest.mark.parametrize("group_id", MANAGED_GROUP_IDS)
    def test_every_group_explains_itself_in_prose(self, group_id) -> None:
        group = MANAGED_GROUPS[group_id]
        assert group.id == group_id
        assert group.title.strip()
        assert len(group.description.strip()) > 40, f"{group_id} does not say what it detects"
        assert len(group.expected_impact.strip()) > 40, f"{group_id} states no expected impact"

    @pytest.mark.parametrize("group_id", MANAGED_GROUP_IDS)
    def test_every_group_ships_in_a_declared_mode_and_states_its_risk(self, group_id) -> None:
        group = MANAGED_GROUPS[group_id]
        assert group.default_mode in GROUP_MODES
        assert group.false_positive_risk in ("low", "medium", "high")

    def test_a_group_that_overlaps_legitimate_automation_ships_logging(self) -> None:
        """Scanner signatures also describe uptime monitors and link checkers."""
        assert MANAGED_GROUPS["scanner-detection"].default_mode == "log"

    def test_no_two_groups_share_boilerplate_prose(self) -> None:
        """Criterion 2 is only met if each entry says something about *itself*."""
        impacts = [g.expected_impact for g in MANAGED_GROUPS.values()]
        descriptions = [g.description for g in MANAGED_GROUPS.values()]
        assert len(set(impacts)) == len(impacts), "two groups share an expected-impact sentence"
        assert len(set(descriptions)) == len(descriptions), "two groups share a description"

    @pytest.mark.parametrize("group_id", MANAGED_GROUP_IDS)
    def test_a_groups_impact_is_not_a_restatement_of_its_detection(self, group_id) -> None:
        group = MANAGED_GROUPS[group_id]
        assert group.expected_impact != group.description
        assert group.expected_impact != group.title


class TestManagedRulesetCatalog:
    """The tier is a set of values, not an adjective the request path interprets."""

    @pytest.mark.parametrize("key", MANAGED_RULESET_IDS)
    def test_every_tier_states_intent_impact_and_what_it_is_wrong_for(self, key) -> None:
        tier = MANAGED_RULESETS[key]
        assert tier.key == key
        assert tier.label.strip()
        assert tier.intent.strip()
        assert len(tier.expected_impact.strip()) > 60, f"{key} states no expected impact"
        assert tier.unsafe_if, f"{key} names nothing it is a poor fit for"
        for sentence in tier.unsafe_if:
            assert len(sentence.strip()) > 20

    @pytest.mark.parametrize("key", MANAGED_RULESET_IDS)
    def test_a_tier_only_enables_groups_that_exist_and_names_a_mode_for_each(self, key) -> None:
        tier = MANAGED_RULESETS[key]
        for group_id in tier.groups:
            assert group_id in MANAGED_GROUPS, f"{key} enables unknown group {group_id}"
            assert tier.group_modes.get(group_id) in GROUP_MODES
        assert set(tier.group_modes) <= set(tier.groups), f"{key} sets a mode for a group it omits"

    def test_the_default_tier_is_core_not_strict(self) -> None:
        """A lane that has never been configured must not ship on the tier that blocks readers."""
        assert normalize_policy(None)["managed_ruleset"] == "core"

    def test_the_default_tier_runs_every_risky_group_below_block(self) -> None:
        """The safe-defaults claim, stated as a property rather than as a table row."""
        core = MANAGED_RULESETS["core"]
        for group_id, mode in core.group_modes.items():
            if MANAGED_GROUPS[group_id].false_positive_risk in ("medium", "high"):
                assert mode != "block", f"core blocks on {group_id}, whose false positives are real"

    def test_strict_is_the_aggressive_option_and_says_so(self) -> None:
        strict = MANAGED_RULESETS["strict"]
        assert set(strict.group_modes.values()) == {"block"}
        assert "false positive" in strict.expected_impact.lower()

    def test_only_turning_the_waf_off_requires_a_stated_reason(self) -> None:
        for key, tier in MANAGED_RULESETS.items():
            assert tier.requires_reason == (key == "off"), key

    def test_the_off_tier_enables_nothing(self) -> None:
        assert MANAGED_RULESETS["off"].groups == ()
        assert dict(MANAGED_RULESETS["off"].group_modes) == {}


class TestBotPresetCatalog:
    """Search indexing is the thing a bot preset can quietly destroy."""

    @pytest.mark.parametrize("key", BOT_PRESET_IDS)
    def test_every_preset_explains_its_impact_and_names_what_it_is_wrong_for(self, key) -> None:
        preset = BOT_PRESETS[key]
        assert preset.key == key
        assert preset.label.strip()
        assert preset.intent.strip()
        assert len(preset.expected_impact.strip()) > 60, f"{key} states no expected impact"
        assert preset.unsafe_if, f"{key} names nothing it is a poor fit for"

    @pytest.mark.parametrize("key", BOT_PRESET_IDS)
    def test_every_preset_states_a_disposition_for_all_three_classes(self, key) -> None:
        preset = BOT_PRESETS[key]
        assert preset.verified_bots.strip()
        assert preset.likely_automated.strip()
        assert preset.automated.strip()

    @pytest.mark.parametrize("key", BOT_PRESET_IDS)
    def test_no_preset_ever_challenges_a_verified_crawler(self, key) -> None:
        """A crawler cannot solve a challenge, and a docs site out of the index is damaged."""
        assert "Challenged" not in BOT_PRESETS[key].verified_bots

    def test_the_default_preset_is_balanced_not_aggressive(self) -> None:
        assert normalize_policy(None)["bot_preset"] == "balanced"

    def test_the_default_preset_does_not_act_on_the_misclassified_class(self) -> None:
        """Likely-automated is where real readers behind corporate proxies land."""
        assert "Challenged" not in BOT_PRESETS["balanced"].likely_automated
        assert "Challenged" in BOT_PRESETS["aggressive"].likely_automated

    def test_monitor_acts_on_nothing_at_all(self) -> None:
        preset = BOT_PRESETS["monitor"]
        assert "Challenged" not in (
            preset.verified_bots + preset.likely_automated + preset.automated
        )


class TestRatePresetCatalog:
    """A budget is a number over a window, so it can be compared against the floor."""

    @pytest.mark.parametrize("key", RATE_PRESET_IDS)
    def test_every_preset_explains_what_the_budget_means_for_a_reader(self, key) -> None:
        preset = RATE_PRESETS[key]
        assert preset.key == key
        assert preset.intent.strip()
        assert len(preset.expected_impact.strip()) > 60, f"{key} states no expected impact"
        assert preset.unsafe_if, f"{key} names nothing it is a poor fit for"
        assert preset.action in RULE_ACTIONS

    @pytest.mark.parametrize("key", RATE_PRESET_IDS)
    def test_no_shipped_budget_is_below_the_floor_it_refuses_custom_rules_for(self, key) -> None:
        """A preset the server would refuse as a custom rule would be a double standard."""
        preset = RATE_PRESETS[key]
        if preset.requests == 0:
            assert preset.window_seconds == 0
            return
        per_minute = preset.requests * 60.0 / preset.window_seconds
        assert per_minute >= _RATE_FLOOR_REQUESTS_PER_MINUTE, f"{key} is tighter than the floor"

    def test_the_default_budget_is_standard_not_strict(self) -> None:
        assert normalize_policy(None)["rate_preset"] == "standard"

    def test_the_budgets_are_pinned(self) -> None:
        """The golden table: a silent change to a budget becomes a test diff."""
        assert [(p.requests, p.window_seconds, p.action) for p in RATE_PRESETS.values()] == [
            (0, 0, "allow"),
            (600, 60, "log"),
            (300, 60, "challenge"),
            (120, 60, "challenge"),
        ]

    def test_the_gentlest_acting_preset_only_reports(self) -> None:
        assert RATE_PRESETS["generous"].action == "log"


class TestRefusalVocabulary:
    """Every reason must be reachable and must reach the operator as words, not a code."""

    def test_every_declared_reason_has_a_sentence(self) -> None:
        for reason in get_args(SecurityRefusalReason):
            refusal = SecurityRefusal.of(reason)
            assert refusal.reason == reason
            assert len(refusal.sentence.strip()) > 40, f"{reason} has no operator-facing sentence"

    def test_the_thirteen_refusals_are_exactly_the_declared_ones(self) -> None:
        assert set(get_args(SecurityRefusalReason)) == set(_REFUSAL_SENTENCES)
        assert len(_REFUSAL_SENTENCES) == 13

    def test_every_refusal_is_hard(self) -> None:
        """The set is spelled out so a future reason has to decide which side it is on."""
        assert set(_HARD_REFUSALS) == set(_REFUSAL_SENTENCES)

    def test_no_refusal_is_also_a_warning(self) -> None:
        assert set(_HARD_REFUSALS).isdisjoint(_WARNING_SENTENCES)

    def test_an_unknown_reason_still_produces_a_sentence(self) -> None:
        """A refusal that reached the operator as a bare code would be a dead end."""
        assert SecurityRefusal.of("not-a-reason").sentence

    def test_sentences_say_what_to_do_rather_than_only_what_failed(self) -> None:
        assert "Scope the matcher" in SecurityRefusal.of("blocks-entire-site").sentence
        assert "Simulate first" in SecurityRefusal.of("enforce-without-simulation").sentence
        assert "route scope and an end date" in SecurityRefusal.of("exception-unbounded").sentence

    def test_every_warning_has_a_sentence(self) -> None:
        for code in _WARNING_SENTENCES:
            warning = SecurityWarning.of(code)
            assert warning.code == code
            assert len(warning.message.strip()) > 40, f"{code} has no operator-facing sentence"

    def test_the_five_acknowledgeable_warnings_are_the_contract_ones(self) -> None:
        assert set(_WARNING_SENTENCES) == {
            "broad-matcher",
            "challenge-on-crawlable-route",
            "rule-shadowed",
            "rollout-jump",
            "expiry-missing",
        }

    def test_an_unknown_warning_code_still_produces_a_sentence(self) -> None:
        assert SecurityWarning.of("not-a-code").message

    def test_the_error_carries_both_the_code_and_the_sentence(self) -> None:
        with pytest.raises(SlateSecurityRefusedError) as excinfo:
            evaluate_security_safety(rule(action="block", matcher_value="/"))
        assert excinfo.value.code == "blocks-entire-site"
        assert excinfo.value.refusal.sentence == _REFUSAL_SENTENCES["blocks-entire-site"]
        assert str(excinfo.value) == _REFUSAL_SENTENCES["blocks-entire-site"]


class TestHardRefusalsHaveNoAcknowledgementPath:
    """The asymmetry that is the whole design, asserted refusal by refusal."""

    @pytest.mark.parametrize(("reason", "trigger"), REFUSAL_TRIGGERS, ids=[r for r, _ in REFUSAL_TRIGGERS])
    def test_the_refusal_fires(self, reason, trigger) -> None:
        with pytest.raises(SlateSecurityRefusedError) as excinfo:
            trigger([])
        assert excinfo.value.code == reason

    @pytest.mark.parametrize(("reason", "trigger"), REFUSAL_TRIGGERS, ids=[r for r, _ in REFUSAL_TRIGGERS])
    def test_acknowledging_it_does_not_let_the_write_through(self, reason, trigger) -> None:
        """An "I accept the risk" checkbox over a lockout is a checkbox over an outage."""
        with pytest.raises(SlateSecurityRefusedError) as excinfo:
            trigger([reason])
        assert excinfo.value.code == reason

    def test_acknowledging_every_reason_at_once_still_does_not(self) -> None:
        for reason, trigger in REFUSAL_TRIGGERS:
            with pytest.raises(SlateSecurityRefusedError) as excinfo:
                trigger(sorted(_HARD_REFUSALS))
            assert excinfo.value.code == reason

    def test_the_trigger_table_covers_every_refusal_except_the_store_owned_one(self) -> None:
        """Guards the sweep above against a refusal added without a case."""
        covered = {reason for reason, _ in REFUSAL_TRIGGERS}
        assert set(_HARD_REFUSALS) - covered == {"policy-version-conflict"}


class TestLockoutPrevention:
    """The point of the feature: no path here can produce a lane nobody can open."""

    @pytest.mark.parametrize(
        ("kind", "value"),
        [
            ("prefix", "/"),
            ("prefix", ""),
            ("glob", "*"),
            ("glob", "**"),
            ("glob", "/*"),
            ("glob", "/**"),
            ("regex", ".*"),
            ("regex", "^"),
        ],
    )
    def test_a_block_rule_matching_everything_is_refused(self, kind, value) -> None:
        with pytest.raises(SlateSecurityRefusedError) as excinfo:
            evaluate_security_safety(
                rule(action="block", matcher_kind=kind, matcher_value=value)
            )
        # An empty matcher never compiles, so it is caught one check earlier — but it is caught.
        assert excinfo.value.code in ("blocks-entire-site", "matcher-invalid")

    def test_covers_everything_errs_towards_saying_yes(self) -> None:
        """A false positive costs a narrowed matcher; a false negative costs the lane."""
        assert covers_everything(normalize_rule(rule(matcher_kind="prefix", matcher_value="/")))
        assert covers_everything(normalize_rule(rule(matcher_kind="regex", matcher_value=".*")))
        assert not covers_everything(
            normalize_rule(rule(matcher_kind="exact", matcher_value="/"))
        ), "an exact matcher selects one path by construction"
        assert not covers_everything(
            normalize_rule(rule(matcher_kind="prefix", matcher_value="/docs/"))
        )

    def test_host_scoping_does_not_make_a_total_matcher_safe(self) -> None:
        """A rule limited to one host still blocks every route on it, and lanes have one host."""
        with pytest.raises(SlateSecurityRefusedError) as excinfo:
            evaluate_security_safety(
                rule(action="block", matcher_value="/", matcher_hosts=["docs.example.com"])
            )
        assert excinfo.value.code == "blocks-entire-site"

    @pytest.mark.parametrize("root", ["/", "/docs", "/docs/", "/index.html"])
    @pytest.mark.parametrize("action", ["block", "challenge", "rate-limit"])
    def test_an_acting_rule_covering_the_documentation_root_is_refused(self, root, action) -> None:
        candidate = rule(
            action=action,
            matcher_kind="exact",
            matcher_value=root,
            rate_requests=600,
            rate_window_seconds=60,
        )
        with pytest.raises(SlateSecurityRefusedError) as excinfo:
            evaluate_security_safety(candidate)
        assert excinfo.value.code == "blocks-documentation-root"

    def test_a_site_wide_challenge_is_refused_even_though_it_is_not_a_block(self) -> None:
        """`blocks-entire-site` is scoped to `block`; the root refusal is what catches this."""
        with pytest.raises(SlateSecurityRefusedError) as excinfo:
            evaluate_security_safety(rule(action="challenge", matcher_value="/"))
        assert excinfo.value.code == "blocks-documentation-root"

    def test_a_logging_rule_over_the_root_is_allowed(self) -> None:
        """Over-refusing would push operators towards disabling the check entirely."""
        assert evaluate_security_safety(rule(action="log", matcher_value="/")) == []

    def test_an_acting_prefix_at_or_above_the_docs_root_is_refused(self) -> None:
        """`/docs` and `/docs/` are entry points, so a section-wide challenge is a lockout."""
        for value in ("/docs", "/docs/"):
            with pytest.raises(SlateSecurityRefusedError) as excinfo:
                evaluate_security_safety(rule(action="challenge", matcher_value=value))
            assert excinfo.value.code == "blocks-documentation-root"

    def test_an_acting_rule_below_the_docs_root_is_allowed(self) -> None:
        """The refusal must stop at the entry point, or no rule could ever act on docs routes."""
        codes = [
            w.code
            for w in evaluate_security_safety(rule(action="challenge", matcher_value="/docs/api/"))
        ]
        assert "blocks-documentation-root" not in codes

    def test_a_rule_scoped_to_a_method_no_reader_uses_does_not_hit_the_root_refusal(self) -> None:
        """A crawler and a reader open the root with GET; a POST-only rule cannot lock them out."""
        assert evaluate_security_safety(
            rule(
                action="challenge",
                matcher_methods=["POST"],
                matcher_value="/docs/api/",
                expires_at=NOW + timedelta(days=7),
            )
        ) == []

    @pytest.mark.parametrize("action", ["block", "challenge", "rate-limit"])
    def test_an_enforcing_rule_that_never_simulated_is_refused(self, action) -> None:
        candidate = rule(
            action=action,
            rollout_mode="enforce",
            rollout_percent=5,
            simulated_at=None,
            rate_requests=600,
            rate_window_seconds=60,
        )
        with pytest.raises(SlateSecurityRefusedError) as excinfo:
            evaluate_security_safety(candidate)
        assert excinfo.value.code == "enforce-without-simulation"

    def test_a_rule_at_zero_percent_is_not_yet_enforcing(self) -> None:
        """Enforce at 0% reaches no traffic, so the simulation gate has nothing to guard yet."""
        assert evaluate_security_safety(
            rule(action="challenge", rollout_mode="enforce", rollout_percent=0)
        ) is not None

    def test_a_simulate_mode_rule_needs_no_prior_simulation(self) -> None:
        """Simulate is the cheap, always-available step; reaching enforce is the deliberate one."""
        codes = [
            w.code
            for w in evaluate_security_safety(
                rule(action="challenge", rollout_mode="simulate", rollout_percent=100)
            )
        ]
        assert "enforce-without-simulation" not in codes

    def test_an_enforcing_block_with_no_approval_is_refused(self) -> None:
        with pytest.raises(SlateSecurityRefusedError) as excinfo:
            evaluate_security_safety(
                rule(
                    action="block",
                    rollout_mode="enforce",
                    rollout_percent=100,
                    simulated_at=NOW - timedelta(days=1),
                    approvals=[],
                )
            )
        assert excinfo.value.code == "enforce-without-approval"

    def test_an_enforcing_block_approved_by_its_author_is_refused(self) -> None:
        """Dual control with one person is a record, not a review."""
        body = rule(
            action="block",
            rollout_mode="enforce",
            rollout_percent=100,
            simulated_at=NOW - timedelta(days=1),
        )
        with pytest.raises(SlateSecurityRefusedError) as excinfo:
            evaluate_security_safety(approved(body, approver="actor-author"))
        assert excinfo.value.code == "approval-self"

    def test_an_enforcing_block_with_a_distinct_approval_of_this_body_is_allowed(self) -> None:
        body = rule(
            action="block",
            rollout_mode="enforce",
            rollout_percent=100,
            previous_rollout_percent=50,
            simulated_at=NOW - timedelta(days=1),
            expires_at=NOW + timedelta(days=7),
        )
        assert evaluate_security_safety(approved(body)) == []

    def test_re_editing_a_decisive_field_invalidates_the_approval(self) -> None:
        """An approval names what was reviewed, not just which rule it was about."""
        body = rule(
            action="block",
            rollout_mode="enforce",
            rollout_percent=100,
            simulated_at=NOW - timedelta(days=1),
        )
        with pytest.raises(SlateSecurityRefusedError) as excinfo:
            evaluate_security_safety(dict(approved(body), matcher_value="/docs/api/v2/"))
        assert excinfo.value.code == "approval-stale"

    def test_renaming_a_rule_does_not_invalidate_its_approval(self) -> None:
        """The label is not a decisive field, so a rename is not a re-edit."""
        body = rule(
            action="block",
            rollout_mode="enforce",
            rollout_percent=100,
            previous_rollout_percent=50,
            simulated_at=NOW - timedelta(days=1),
            expires_at=NOW + timedelta(days=7),
        )
        renamed = dict(approved(body), label="Renamed after review")
        assert evaluate_security_safety(renamed) == []

    def test_an_enforcing_non_block_rule_needs_no_approval(self) -> None:
        """Blocking is the one change where a second pair of eyes is worth the delay."""
        assert evaluate_security_safety(
            rule(
                action="challenge",
                matcher_methods=["POST"],
                rollout_mode="enforce",
                rollout_percent=100,
                previous_rollout_percent=50,
                simulated_at=NOW - timedelta(days=1),
                expires_at=NOW + timedelta(days=7),
            )
        ) == []


class TestRateFloor:
    """A budget below what reading costs challenges readers rather than automation."""

    @pytest.mark.parametrize(
        ("requests", "window"),
        [
            (10, 60),
            (59, 60),
            (1, 1000),
            # A punishing budget hidden behind a long window: 100/hour is 1.6 a minute.
            (100, 3600),
        ],
    )
    def test_a_budget_below_the_floor_is_refused(self, requests, window) -> None:
        with pytest.raises(SlateSecurityRefusedError) as excinfo:
            evaluate_security_safety(
                rule(action="rate-limit", rate_requests=requests, rate_window_seconds=window)
            )
        assert excinfo.value.code == "rate-limit-below-floor"

    @pytest.mark.parametrize(("requests", "window"), [(None, 60), (600, None), (0, 60), (600, 0)])
    def test_a_rate_rule_with_no_budget_at_all_is_refused(self, requests, window) -> None:
        """Treating a missing budget as unlimited would slip past the one check that noticed."""
        with pytest.raises(SlateSecurityRefusedError) as excinfo:
            evaluate_security_safety(
                rule(action="rate-limit", rate_requests=requests, rate_window_seconds=window)
            )
        assert excinfo.value.code == "rate-limit-below-floor"

    @pytest.mark.parametrize(("requests", "window"), [(60, 60), (600, 60), (10, 10), (3600, 3600)])
    def test_a_budget_at_or_above_the_floor_is_allowed(self, requests, window) -> None:
        codes = [
            w.code
            for w in evaluate_security_safety(
                rule(action="rate-limit", rate_requests=requests, rate_window_seconds=window)
            )
        ]
        assert "rate-limit-below-floor" not in codes

    def test_the_floor_is_normalized_per_minute_so_the_window_is_not_a_loophole(self) -> None:
        """The same rate expressed over ten seconds and over an hour is judged identically."""
        for window in (10, 60, 600, 3600):
            requests = int(_RATE_FLOOR_REQUESTS_PER_MINUTE * window / 60)
            assert (
                evaluate_security_safety(
                    rule(
                        action="rate-limit",
                        rate_requests=requests,
                        rate_window_seconds=window,
                    )
                )
                is not None
            )
            with pytest.raises(SlateSecurityRefusedError):
                evaluate_security_safety(
                    rule(
                        action="rate-limit",
                        rate_requests=requests - 1,
                        rate_window_seconds=window,
                    )
                )


class TestExceptionSafety:
    """An exception is a hole; keeping it scoped and dated is what stops it becoming policy."""

    def test_a_scoped_expiring_exception_is_allowed(self) -> None:
        assert evaluate_exception_safety(exception(), now=NOW) == []

    @pytest.mark.parametrize("value", ["/", "*", "**", ".*"])
    def test_an_exception_covering_every_route_is_refused(self, value) -> None:
        kind = "regex" if value == ".*" else ("glob" if "*" in value else "prefix")
        with pytest.raises(SlateSecurityRefusedError) as excinfo:
            evaluate_exception_safety(
                exception(matcher_kind=kind, matcher_value=value), now=NOW
            )
        assert excinfo.value.code == "exception-unbounded"

    def test_an_exception_with_no_expiry_is_refused(self) -> None:
        with pytest.raises(SlateSecurityRefusedError) as excinfo:
            evaluate_exception_safety(exception(expires_at=None), now=NOW)
        assert excinfo.value.code == "exception-unbounded"

    def test_an_exception_with_an_unparseable_expiry_is_refused_as_unbounded(self) -> None:
        """An expiry nobody can read is an expiry that will not happen."""
        with pytest.raises(SlateSecurityRefusedError) as excinfo:
            evaluate_exception_safety(exception(expires_at="whenever"), now=NOW)
        assert excinfo.value.code == "exception-unbounded"

    def test_an_exception_outliving_the_carve_out_window_is_refused(self) -> None:
        with pytest.raises(SlateSecurityRefusedError) as excinfo:
            evaluate_exception_safety(
                exception(expires_at=NOW + timedelta(days=_MAX_EXCEPTION_WINDOW_DAYS + 1)),
                now=NOW,
            )
        assert excinfo.value.code == "exception-outlives-limit"

    def test_an_exception_expiring_exactly_at_the_limit_is_allowed(self) -> None:
        assert (
            evaluate_exception_safety(
                exception(expires_at=NOW + timedelta(days=_MAX_EXCEPTION_WINDOW_DAYS)), now=NOW
            )
            == []
        )

    def test_the_carve_out_window_is_one_review_cycle(self) -> None:
        assert _MAX_EXCEPTION_WINDOW_DAYS == 90

    def test_an_uncompilable_exception_matcher_is_refused(self) -> None:
        with pytest.raises(SlateSecurityRefusedError) as excinfo:
            evaluate_exception_safety(
                exception(matcher_kind="regex", matcher_value="([unclosed"), now=NOW
            )
        assert excinfo.value.code == "matcher-invalid"

    def test_an_iso_string_expiry_is_accepted_the_same_as_a_datetime(self) -> None:
        iso = (NOW + timedelta(days=7)).isoformat().replace("+00:00", "Z")
        assert evaluate_exception_safety(exception(expires_at=iso), now=NOW) == []


class TestPolicySafety:
    """A policy-level problem must not refuse an unrelated rule edit."""

    def test_turning_the_managed_ruleset_off_without_a_reason_is_refused(self) -> None:
        with pytest.raises(SlateSecurityRefusedError) as excinfo:
            evaluate_policy_safety({"managed_ruleset": "off"})
        assert excinfo.value.code == "managed-off-without-reason"

    @pytest.mark.parametrize("reason", ["", "   ", None])
    def test_a_blank_reason_is_not_a_reason(self, reason) -> None:
        with pytest.raises(SlateSecurityRefusedError):
            evaluate_policy_safety({"managed_ruleset": "off", "managed_off_reason": reason})

    def test_turning_it_off_with_a_reason_is_allowed(self) -> None:
        assert (
            evaluate_policy_safety(
                {"managed_ruleset": "off", "managed_off_reason": "INC-4821 triage"}
            )
            == []
        )

    def test_a_policy_level_problem_does_not_refuse_a_rule_edit(self) -> None:
        """An operator narrowing a matcher must not be blocked by somebody else's change."""
        broken = {"managed_ruleset": "off", "managed_off_reason": ""}
        assert evaluate_security_safety(rule(), policy=broken) == []

    def test_a_lane_that_was_never_configured_reads_as_the_shipped_defaults(self) -> None:
        assert evaluate_policy_safety({}) == []
        assert normalize_policy(None)["challenge_mode"] == "managed"


class TestEdgeIsNeverClaimed:
    """The honesty boundary: there is no delivery tier, and nothing here may imply one."""

    def test_edge_attachment_defaults_to_false(self) -> None:
        assert normalize_policy(None)["edge_attached"] is False
        assert normalize_policy({})["edge_attached"] is False

    def test_edge_attachment_is_never_inferred_from_a_provider_name(self) -> None:
        resolved = normalize_policy({"edge_provider": "some-cdn"})
        assert resolved["edge_attached"] is False


class TestWarningsAreAcknowledgeable:
    """Costly, not dangerous — so these warn, and the write proceeds either way."""

    def test_a_broad_acting_matcher_warns(self) -> None:
        warnings = evaluate_security_safety(
            rule(action="challenge", matcher_methods=["POST"], matcher_value="/docs")
        )
        codes = [w.code for w in warnings]
        assert "broad-matcher" in codes
        assert warnings[codes.index("broad-matcher")].field == "matcher_value"

    def test_a_broad_matcher_on_a_logging_rule_does_not_warn(self) -> None:
        """A rule that observes cannot catch a route by accident in a way anybody notices."""
        assert "broad-matcher" not in [
            w.code for w in evaluate_security_safety(rule(action="log", matcher_value="/docs"))
        ]

    def test_a_challenge_on_a_crawlable_route_warns(self) -> None:
        warnings = evaluate_security_safety(rule(action="challenge", matcher_methods=["GET"]))
        codes = [w.code for w in warnings]
        assert "challenge-on-crawlable-route" in codes
        assert warnings[codes.index("challenge-on-crawlable-route")].field == "action"

    def test_a_challenge_on_a_method_no_crawler_issues_does_not_warn(self) -> None:
        assert "challenge-on-crawlable-route" not in [
            w.code
            for w in evaluate_security_safety(
                rule(action="challenge", matcher_methods=["POST"])
            )
        ]

    def test_the_crawlable_warning_is_silent_when_challenges_are_off(self) -> None:
        """A challenge that cannot happen cannot cost search visibility; the warning is noise."""
        assert "challenge-on-crawlable-route" not in [
            w.code
            for w in evaluate_security_safety(
                rule(action="challenge"), policy={"challenge_mode": "off"}
            )
        ]

    def test_a_shadowed_rule_warns(self) -> None:
        outer = rule(id="outer", ordinal=0, action="block", matcher_value="/docs/api/")
        inner = rule(id="inner", ordinal=5, action="log", matcher_value="/docs/api/keys")
        warnings = evaluate_security_safety(inner, siblings=[outer, inner])
        codes = [w.code for w in warnings]
        assert "rule-shadowed" in codes
        assert warnings[codes.index("rule-shadowed")].field == "ordinal"

    def test_a_lower_precedence_rule_does_not_shadow_a_higher_one(self) -> None:
        outer = rule(id="outer", ordinal=9, action="block", matcher_value="/docs/api/")
        inner = rule(id="inner", ordinal=1, action="log", matcher_value="/docs/api/keys")
        assert "rule-shadowed" not in [
            w.code for w in evaluate_security_safety(inner, siblings=[outer, inner])
        ]

    def test_a_logging_rule_shadows_nothing_because_it_steps_aside(self) -> None:
        outer = rule(id="outer", ordinal=0, action="log", matcher_value="/docs/api/")
        inner = rule(id="inner", ordinal=5, action="log", matcher_value="/docs/api/keys")
        assert "rule-shadowed" not in [
            w.code for w in evaluate_security_safety(inner, siblings=[outer, inner])
        ]

    def test_a_disabled_rule_shadows_nothing(self) -> None:
        outer = rule(id="outer", ordinal=0, action="block", enabled=False, matcher_value="/docs/api/")
        inner = rule(id="inner", ordinal=5, action="log", matcher_value="/docs/api/keys")
        assert "rule-shadowed" not in [
            w.code for w in evaluate_security_safety(inner, siblings=[outer, inner])
        ]

    def test_shadowing_is_not_guessed_across_regexes(self) -> None:
        """A warning an operator cannot act on is worse than silence."""
        outer = rule(id="outer", ordinal=0, action="block", matcher_kind="regex",
                     matcher_value="^/docs/api/")
        inner = rule(id="inner", ordinal=5, action="log", matcher_value="/docs/api/keys")
        assert "rule-shadowed" not in [
            w.code for w in evaluate_security_safety(inner, siblings=[outer, inner])
        ]

    def test_a_rollout_jumping_straight_to_everything_warns(self) -> None:
        warnings = evaluate_security_safety(
            rule(
                action="challenge",
                matcher_methods=["POST"],
                rollout_percent=100,
                previous_rollout_percent=0,
            )
        )
        codes = [w.code for w in warnings]
        assert "rollout-jump" in codes
        assert warnings[codes.index("rollout-jump")].field == "rollout_percent"

    def test_a_staged_rollout_does_not_warn(self) -> None:
        assert "rollout-jump" not in [
            w.code
            for w in evaluate_security_safety(
                rule(
                    action="challenge",
                    matcher_methods=["POST"],
                    rollout_percent=100,
                    previous_rollout_percent=25,
                )
            )
        ]

    def test_an_acting_rule_with_no_expiry_warns(self) -> None:
        warnings = evaluate_security_safety(
            rule(action="challenge", matcher_methods=["POST"], expires_at=None)
        )
        codes = [w.code for w in warnings]
        assert "expiry-missing" in codes
        assert warnings[codes.index("expiry-missing")].field == "expires_at"

    def test_an_acting_rule_with_an_expiry_does_not_warn(self) -> None:
        assert "expiry-missing" not in [
            w.code
            for w in evaluate_security_safety(
                rule(
                    action="challenge",
                    matcher_methods=["POST"],
                    expires_at=NOW + timedelta(days=7),
                )
            )
        ]

    @pytest.mark.parametrize("code", sorted(_WARNING_SENTENCES))
    def test_every_warning_code_is_acknowledgeable_rather_than_blocking(self, code) -> None:
        """The other half of the asymmetry: none of these has a refusal to escalate to."""
        assert code not in _HARD_REFUSALS

    def test_acknowledging_a_warning_does_not_change_the_write_outcome(self) -> None:
        """The caller decides whether an acknowledgement is on file; this module still reports."""
        body = rule(action="challenge", matcher_methods=["GET"], matcher_value="/guide")
        without = evaluate_security_safety(body)
        with_ack = evaluate_security_safety(
            dict(body, acknowledged_warnings=sorted(_WARNING_SENTENCES))
        )
        assert [w.code for w in without] == [w.code for w in with_ack]
        assert without, "the fixture was meant to produce warnings"

    def test_warnings_never_raise_however_many_accumulate(self) -> None:
        warnings = evaluate_security_safety(
            rule(
                id="inner",
                ordinal=5,
                action="challenge",
                matcher_value="/guide",
                rollout_percent=100,
                previous_rollout_percent=0,
                expires_at=None,
            ),
            siblings=[rule(id="outer", ordinal=0, action="block", matcher_value="/guide")],
        )
        codes = {w.code for w in warnings}
        assert codes == {
            "broad-matcher",
            "challenge-on-crawlable-route",
            "rollout-jump",
            "expiry-missing",
            "rule-shadowed",
        }
        for warning in warnings:
            assert len(warning.message) > 40, f"{warning.code} has no sentence"


class TestMatching:
    """Matcher semantics, including the ones that silently widen if got wrong."""

    @pytest.mark.parametrize(
        ("kind", "value", "path", "expected"),
        [
            ("exact", "/docs/intro", "/docs/intro", True),
            ("exact", "/docs", "/docs/intro", False),
            ("prefix", "/docs", "/docs/intro", True),
            # Textual, not segment-aware — identical to the cache surface on purpose. A matcher
            # that meant different things on the two screens would eventually be copied across.
            ("prefix", "/docs", "/docsearch", True),
            ("prefix", "/docs/", "/docsearch", False),
            ("glob", "/docs/*", "/docs/intro", True),
            ("glob", "/docs/**", "/docs/a/b", True),
            ("glob", "/docs/*", "/blog/intro", False),
            ("regex", r"^/docs/", "/docs/intro", True),
            ("regex", r"^/blog/", "/docs/intro", False),
        ],
    )
    def test_matcher_kinds(self, kind, value, path, expected) -> None:
        from app.slate_security import SimulationRequest

        candidate = normalize_rule(rule(matcher_kind=kind, matcher_value=value))
        probe = SimulationRequest(path=path).normalized()
        assert matches_route(candidate, probe) is expected

    def test_an_empty_method_list_means_every_method(self) -> None:
        """A rule protecting GET and forgetting POST would be a hole shaped like a typo."""
        from app.slate_security import SimulationRequest

        candidate = normalize_rule(rule(matcher_methods=[], matcher_value="/docs/api/"))
        for method in ("GET", "POST", "DELETE", "PATCH"):
            probe = SimulationRequest(method=method, path="/docs/api/keys").normalized()
            assert matches_route(candidate, probe) is True

    def test_an_uncompilable_regex_matches_nothing_rather_than_raising(self) -> None:
        """The write already refused it; a simulation over stored policy must still render."""
        from app.slate_security import SimulationRequest

        candidate = normalize_rule(rule(matcher_kind="regex", matcher_value="([unclosed"))
        assert matches_route(candidate, SimulationRequest(path="/docs").normalized()) is False


class TestNormalization:
    """Normalization is what makes two spellings of one rule hash alike."""

    def test_methods_and_hosts_are_case_folded_because_http_is(self) -> None:
        normalized = normalize_rule(
            {"matcher_methods": ["get", "Post"], "matcher_hosts": ["Docs.Example.COM"]}
        )
        assert normalized["matcher_methods"] == ["GET", "POST"]
        assert normalized["matcher_hosts"] == ["docs.example.com"]

    def test_missing_fields_take_their_column_defaults(self) -> None:
        normalized = normalize_rule({})
        assert normalized["action"] == "log"
        assert normalized["rollout_mode"] == "simulate"
        assert normalized["rollout_percent"] == 0
        assert normalized["enabled"] is True
        assert normalized["matcher_kind"] == "prefix"

    def test_an_absent_matcher_defaults_to_root(self) -> None:
        assert normalize_rule({})["matcher_value"] == "/"

    def test_an_explicitly_empty_matcher_is_preserved_rather_than_widened(self) -> None:
        """Coercing "" to "/" would turn a half-filled form into a site-wide rule."""
        assert normalize_rule({"matcher_value": ""})["matcher_value"] == ""
        with pytest.raises(SlateSecurityRefusedError) as excinfo:
            evaluate_security_safety(rule(matcher_value=""))
        assert excinfo.value.code == "matcher-invalid"

    def test_an_exception_keeps_a_missing_expiry_as_none(self) -> None:
        """So the refusal can fire rather than an expiry being invented."""
        assert normalize_exception({"matcher_value": "/docs"})["expires_at"] is None

    def test_an_exception_applies_to_every_method_and_host_in_its_scope(self) -> None:
        normalized = normalize_exception({"matcher_value": "/docs"})
        assert normalized["matcher_methods"] == []
        assert normalized["matcher_hosts"] == []

    def test_normalizing_is_idempotent(self) -> None:
        once = normalize_rule(rule())
        assert normalize_rule(once) == once


class TestApprovalSafety:
    """Two failures, distinguished on purpose, because they need different actions."""

    DIGEST = "sha256:" + "a" * 64

    def test_no_approvals_at_all_is_refused_as_missing(self) -> None:
        with pytest.raises(SlateSecurityRefusedError) as excinfo:
            evaluate_approval_safety(
                author_actor_key="actor-author", approvals=[], digest=self.DIGEST
            )
        assert excinfo.value.code == "enforce-without-approval"

    def test_only_the_authors_own_approval_is_refused_as_self_approval(self) -> None:
        with pytest.raises(SlateSecurityRefusedError) as excinfo:
            evaluate_approval_safety(
                author_actor_key="actor-author",
                approvals=[{"approver_actor_key": "actor-author", "digest": self.DIGEST}],
                digest=self.DIGEST,
            )
        assert excinfo.value.code == "approval-self"

    def test_a_distinct_approval_of_a_different_body_is_refused_as_stale(self) -> None:
        with pytest.raises(SlateSecurityRefusedError) as excinfo:
            evaluate_approval_safety(
                author_actor_key="actor-author",
                approvals=[{"approver_actor_key": "actor-two", "digest": "sha256:" + "b" * 64}],
                digest=self.DIGEST,
            )
        assert excinfo.value.code == "approval-stale"

    def test_the_authors_own_approval_cannot_satisfy_the_digest_check(self) -> None:
        """Self-approval of the right body is still self-approval."""
        with pytest.raises(SlateSecurityRefusedError) as excinfo:
            evaluate_approval_safety(
                author_actor_key="actor-author",
                approvals=[
                    {"approver_actor_key": "actor-author", "digest": self.DIGEST},
                    {"approver_actor_key": "actor-two", "digest": "sha256:" + "b" * 64},
                ],
                digest=self.DIGEST,
            )
        assert excinfo.value.code == "approval-stale"

    def test_a_distinct_approval_of_this_body_passes_silently(self) -> None:
        """The function communicates only by raising, so a falsy return cannot mean approval."""
        assert (
            evaluate_approval_safety(
                author_actor_key="actor-author",
                approvals=[{"approver_actor_key": "actor-two", "digest": self.DIGEST}],
                digest=self.DIGEST,
            )
            is None
        )

    def test_an_absent_approver_key_is_treated_as_distinct_but_still_needs_the_digest(self) -> None:
        with pytest.raises(SlateSecurityRefusedError) as excinfo:
            evaluate_approval_safety(
                author_actor_key="actor-author",
                approvals=[{"digest": "sha256:" + "b" * 64}],
                digest=self.DIGEST,
            )
        assert excinfo.value.code == "approval-stale"


class TestOrdinalConflict:
    """A total order, or which rule blocked the caller depends on physical row order."""

    def test_two_rules_at_the_same_precedence_are_refused(self) -> None:
        with pytest.raises(SlateSecurityRefusedError) as excinfo:
            evaluate_security_safety(
                rule(id="mine", ordinal=5), siblings=[rule(id="theirs", ordinal=5)]
            )
        assert excinfo.value.code == "ordinal-conflict"

    def test_a_rule_does_not_conflict_with_itself(self) -> None:
        """Re-checking a stored rule against its own lane must not report a collision."""
        stored = rule(id="mine", ordinal=5)
        assert evaluate_security_safety(stored, siblings=[stored]) == []

    def test_distinct_precedences_are_allowed(self) -> None:
        assert evaluate_security_safety(
            rule(id="mine", ordinal=5), siblings=[rule(id="theirs", ordinal=6)]
        ) == []


class TestPurity:
    """``now`` is a parameter. These tests are what prove it is not a clock."""

    def test_the_same_exception_flips_verdict_on_the_instant_it_is_judged_against(self) -> None:
        candidate = exception(expires_at=NOW + timedelta(days=30))
        assert evaluate_exception_safety(candidate, now=NOW) == []
        # Judged from far enough in the past, the same expiry outlives the carve-out window.
        with pytest.raises(SlateSecurityRefusedError) as excinfo:
            evaluate_exception_safety(candidate, now=NOW - timedelta(days=70))
        assert excinfo.value.code == "exception-outlives-limit"

    def test_evaluation_does_not_consult_the_wall_clock(self) -> None:
        """A far-future `now` changes nothing, because nothing here reads the real time."""
        candidate = exception(expires_at=NOW + timedelta(days=1))
        assert evaluate_exception_safety(candidate, now=NOW) == []
        far_future = NOW + timedelta(days=3650)
        assert (
            evaluate_exception_safety(
                exception(expires_at=far_future + timedelta(days=1)), now=far_future
            )
            == []
        )

    def test_rule_safety_evaluation_is_repeatable(self) -> None:
        body = rule(action="challenge", matcher_value="/guide")
        assert evaluate_security_safety(body) == evaluate_security_safety(body)

    def test_a_naive_expiry_is_compared_without_raising(self) -> None:
        """A security check that failed on a timezone detail would fail unactionably."""
        naive = datetime(2026, 8, 1, 12, 0, 0)
        assert evaluate_exception_safety(exception(expires_at=naive), now=NOW) == []

    def test_an_aware_expiry_is_comparable_with_a_naive_now(self) -> None:
        naive_now = datetime(2026, 7, 19, 12, 0, 0)
        assert (
            evaluate_exception_safety(
                exception(expires_at=NOW + timedelta(days=7)), now=naive_now
            )
            == []
        )


class TestBodyDigest:
    """What an approval names, so approving one body and shipping another is detectable."""

    def test_the_digest_matches_the_column_constraint(self) -> None:
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", body_digest(rule()))

    def test_the_digest_is_stable_across_a_rename(self) -> None:
        """A rename is not a re-edit, so it must not invalidate an approval."""
        assert body_digest(rule()) == body_digest(rule(label="Renamed"))

    def test_the_digest_is_stable_across_key_reordering(self) -> None:
        reordered = dict(reversed(list(rule().items())))
        assert body_digest(reordered) == body_digest(rule())

    def test_the_digest_ignores_who_wrote_it_and_who_approved_it(self) -> None:
        """Otherwise recording the approval would invalidate the thing it approved."""
        assert body_digest(rule()) == body_digest(
            rule(author_actor_key="somebody-else", approvals=[{"approver_actor_key": "x"}])
        )

    def test_the_digest_ignores_the_acknowledgements(self) -> None:
        assert body_digest(rule()) == body_digest(rule(acknowledged_warnings=["broad-matcher"]))

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("ordinal", 9),
            ("enabled", False),
            ("matcher_kind", "glob"),
            ("matcher_value", "/docs/other/"),
            ("matcher_methods", ["GET"]),
            ("matcher_hosts", ["docs.example.com"]),
            ("conditions", [{"kind": "country", "equals": "FR"}]),
            ("action", "block"),
            ("rate_requests", 600),
            ("rate_window_seconds", 60),
            ("rollout_mode", "enforce"),
            ("rollout_percent", 100),
            ("expires_at", NOW),
        ],
    )
    def test_the_digest_changes_when_a_decisive_field_changes(self, field, value) -> None:
        """A digest that survived a change to what the rule does could not certify anything."""
        assert body_digest(rule()) != body_digest(rule(**{field: value}))

    def test_the_digest_is_repeatable(self) -> None:
        assert body_digest(rule()) == body_digest(rule())

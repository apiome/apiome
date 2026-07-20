"""Preset and cache-safety rules — UXE-3.1 (private-suite#2473).

Pure tests over :mod:`app.slate_cache`: no TestClient, no database, no clock.

The suite is weighted toward two acceptance criteria:

* **Criterion 1, presets are documented and deterministic.** The preset table is asserted
  field by field rather than "a preset exists", because a preset whose numbers can drift
  silently is not a documented default — it is a mood. A change to any TTL below shows up as a
  test diff, which is the point.
* **Criterion 4, unsafe identity/cookie variants.** The server is the authority; the UI renders
  what it says. So the boundary between "refuse outright" and "warn and let the operator
  proceed" is pinned here, in both directions.
"""

from __future__ import annotations

from typing import get_args

import pytest

from app.slate_cache import (
    PRESET_IDS,
    PRESETS,
    CacheRefusal,
    CacheRefusalReason,
    SlateCacheRefusedError,
    apply_preset,
    evaluate_cache_safety,
    normalize_rule,
)


def rule(**overrides):
    """Build a cacheable rule with safe defaults, so each test states only what it is about."""
    base = {
        "id": "rule-1",
        "ordinal": 0,
        "enabled": True,
        "label": "Test rule",
        "matcher_kind": "prefix",
        "matcher_value": "/",
        "matcher_methods": ["GET"],
        "matcher_hosts": [],
        "eligibility": "cacheable",
        "browser_ttl_seconds": 0,
        "edge_ttl_seconds": 60,
        "stale_while_revalidate_seconds": 0,
        "stale_if_error_seconds": 0,
        "cache_key_base": "host-url",
        "vary_query_mode": "none",
        "vary_query_keys": [],
        "vary_headers": [],
        "vary_cookies": [],
        "bypass_conditions": [],
    }
    base.update(overrides)
    return base


class TestPresetCatalog:
    """Criterion 1: the preset table is a set of literals, asserted as such."""

    def test_exactly_the_four_roadmap_presets_exist(self) -> None:
        assert tuple(PRESETS) == PRESET_IDS
        assert PRESET_IDS == ("standard", "aggressive", "bypass", "personalized")

    def test_every_preset_states_its_intent_and_rationale(self) -> None:
        for preset in PRESETS.values():
            assert preset.intent.strip()
            assert preset.rationale.strip()
            assert preset.rules, f"{preset.key} contributes no rules"

    @pytest.mark.parametrize(
        ("preset_key", "expected"),
        [
            # (eligibility, browser TTL, edge TTL, SWR, SIE) for the HTML rule of each preset.
            ("standard", ("cacheable", 0, 60, 60, 86_400)),
            ("aggressive", ("cacheable", 0, 600, 86_400, 604_800)),
            ("bypass", ("no-store", 0, 0, 0, 0)),
            ("personalized", ("private", 0, 0, 0, 0)),
        ],
    )
    def test_html_behaviour_per_preset_is_pinned(self, preset_key, expected) -> None:
        """The golden table. A silent TTL change becomes a visible diff here."""
        html = PRESETS[preset_key].rules[-1]
        assert (
            html.eligibility,
            html.browser_ttl_seconds,
            html.edge_ttl_seconds,
            html.stale_while_revalidate_seconds,
            html.stale_if_error_seconds,
        ) == expected

    @pytest.mark.parametrize("preset_key", ["standard", "aggressive", "personalized"])
    def test_immutable_assets_are_cached_for_a_year(self, preset_key) -> None:
        """A hashed bundle's URL changes when its bytes do, so a stale one is unreachable."""
        asset = PRESETS[preset_key].rules[0]
        assert asset.browser_ttl_seconds == 31_536_000
        assert asset.edge_ttl_seconds == 31_536_000

    def test_bypass_caches_nothing_at_all(self) -> None:
        """Including assets: bypass is a debugging mode, not a tuned policy."""
        assert len(PRESETS["bypass"].rules) == 1
        assert PRESETS["bypass"].rules[0].eligibility == "no-store"

    def test_only_bypass_requires_an_expiry(self) -> None:
        for key, preset in PRESETS.items():
            assert preset.requires_expiry == (key == "bypass"), key

    def test_personalized_html_is_never_shared(self) -> None:
        """The safeguard the roadmap names: identity-aware content gets no shared TTL."""
        html = PRESETS["personalized"].rules[-1]
        assert html.eligibility == "private"
        assert html.edge_ttl_seconds == 0

    def test_every_preset_names_what_it_forbids(self) -> None:
        for preset in PRESETS.values():
            assert preset.unsafe_if, f"{preset.key} names nothing it forbids"


class TestApplyPreset:
    """Determinism, stated as a property rather than asserted on one example."""

    @pytest.mark.parametrize("preset_key", PRESET_IDS)
    def test_applying_a_preset_twice_gives_the_same_rules(self, preset_key) -> None:
        assert apply_preset(preset_key) == apply_preset(preset_key)

    @pytest.mark.parametrize("preset_key", PRESET_IDS)
    def test_rules_are_returned_in_precedence_order(self, preset_key) -> None:
        ordinals = [r["ordinal"] for r in apply_preset(preset_key)]
        assert ordinals == sorted(ordinals)
        assert len(set(ordinals)) == len(ordinals), "two preset rules share a precedence"

    def test_an_override_replaces_only_the_named_field(self) -> None:
        resolved = apply_preset("standard", {"HTML documents": {"edge_ttl_seconds": 5}})
        html = resolved[-1]
        assert html["edge_ttl_seconds"] == 5
        assert html["stale_if_error_seconds"] == 86_400, "unrelated fields must survive"

    def test_an_override_for_a_rule_that_no_longer_exists_is_ignored(self) -> None:
        """A leftover override from a previous preset must not make the lane unreadable."""
        resolved = apply_preset("bypass", {"HTML documents": {"edge_ttl_seconds": 900}})
        assert all(r["edge_ttl_seconds"] == 0 for r in resolved)

    def test_the_resolved_rules_record_which_preset_produced_them(self) -> None:
        for row in apply_preset("aggressive"):
            assert row["derived_from_preset"] == "aggressive"

    def test_an_unknown_preset_is_refused_by_name(self) -> None:
        with pytest.raises(SlateCacheRefusedError) as excinfo:
            apply_preset("turbo")
        assert excinfo.value.code == "preset-unknown"


class TestRefusalVocabulary:
    """Every reason must be reachable and must carry a sentence, not a code."""

    def test_every_declared_reason_has_a_sentence(self) -> None:
        for reason in get_args(CacheRefusalReason):
            refusal = CacheRefusal.of(reason)
            assert refusal.reason == reason
            assert len(refusal.sentence) > 20, f"{reason} has no operator-facing sentence"

    def test_an_unknown_reason_still_produces_a_sentence(self) -> None:
        """A refusal that reached the operator as a bare code would be a dead end."""
        assert CacheRefusal.of("not-a-reason").sentence

    def test_sentences_explain_what_to_do_rather_than_only_what_failed(self) -> None:
        assert "Mark the route private" in CacheRefusal.of("identity-in-cache-key").sentence
        assert "Name a release" in CacheRefusal.of("purge-scope-unbounded").sentence


class TestUnsafeVariantsAreRefused:
    """Criterion 4, the blocking half. None of these has an acknowledgement path."""

    @pytest.mark.parametrize(
        "header", ["Authorization", "authorization", "Cookie", "Proxy-Authorization"]
    )
    def test_identity_header_in_a_shared_cache_key_is_refused(self, header) -> None:
        with pytest.raises(SlateCacheRefusedError) as excinfo:
            evaluate_cache_safety(rule(vary_headers=[header]))
        assert excinfo.value.code == "identity-in-cache-key"

    @pytest.mark.parametrize(
        "cookie", ["session", "SESSIONID", "sid", "auth_token", "jwt", "csrf", "remember_me"]
    )
    def test_identity_cookie_in_a_shared_cache_key_is_refused(self, cookie) -> None:
        with pytest.raises(SlateCacheRefusedError) as excinfo:
            evaluate_cache_safety(rule(vary_cookies=[cookie]))
        assert excinfo.value.code == "identity-in-cache-key"

    def test_identity_variation_plus_stale_delivery_is_refused(self) -> None:
        """Even when marked private: stale re-serves a stored response without revalidating."""
        with pytest.raises(SlateCacheRefusedError) as excinfo:
            evaluate_cache_safety(
                rule(
                    eligibility="private",
                    edge_ttl_seconds=0,
                    vary_cookies=["session"],
                    stale_if_error_seconds=300,
                )
            )
        assert excinfo.value.code == "stale-serves-identity"

    def test_private_with_an_edge_ttl_is_refused(self) -> None:
        with pytest.raises(SlateCacheRefusedError) as excinfo:
            evaluate_cache_safety(rule(eligibility="private", edge_ttl_seconds=60))
        assert excinfo.value.code == "private-served-from-edge"

    @pytest.mark.parametrize("field", ["edge_ttl_seconds", "browser_ttl_seconds"])
    def test_no_store_with_any_ttl_is_refused(self, field) -> None:
        candidate = rule(eligibility="no-store", edge_ttl_seconds=0, browser_ttl_seconds=0)
        candidate[field] = 30
        with pytest.raises(SlateCacheRefusedError) as excinfo:
            evaluate_cache_safety(candidate)
        assert excinfo.value.code == "no-store-with-ttl"

    def test_an_uncompilable_regex_matcher_is_refused(self) -> None:
        with pytest.raises(SlateCacheRefusedError) as excinfo:
            evaluate_cache_safety(rule(matcher_kind="regex", matcher_value="([unclosed"))
        assert excinfo.value.code == "matcher-invalid"

    def test_an_empty_matcher_is_refused(self) -> None:
        with pytest.raises(SlateCacheRefusedError) as excinfo:
            evaluate_cache_safety(rule(matcher_value=""))
        assert excinfo.value.code == "matcher-invalid"


class TestSafeVariantsAreAllowed:
    """The other direction. Over-refusing would push operators to disable the check."""

    def test_a_non_identity_cookie_on_a_private_route_is_allowed(self) -> None:
        warnings = evaluate_cache_safety(
            rule(eligibility="private", edge_ttl_seconds=0, vary_cookies=["theme"])
        )
        assert [w.code for w in warnings] == ["cookie-variation-high-cardinality"]

    def test_a_non_identity_header_in_a_shared_key_is_allowed(self) -> None:
        assert evaluate_cache_safety(rule(vary_headers=["Accept-Language"])) == []

    def test_a_plain_shared_rule_produces_no_warnings(self) -> None:
        assert evaluate_cache_safety(rule()) == []


class TestWarnings:
    """Costly, not dangerous — so these warn and can be acknowledged."""

    def test_varying_on_every_query_parameter_warns(self) -> None:
        warnings = evaluate_cache_safety(rule(vary_query_mode="all"))
        codes = [w.code for w in warnings]
        assert "vary-query-all" in codes
        assert warnings[codes.index("vary-query-all")].field == "vary_query_mode"

    def test_a_long_shared_html_ttl_warns(self) -> None:
        warnings = evaluate_cache_safety(rule(edge_ttl_seconds=7_200))
        assert "long-ttl-on-html" in [w.code for w in warnings]

    def test_a_long_ttl_on_a_fingerprinted_asset_does_not_warn(self) -> None:
        """The long-TTL warning must not fire on the case a year is correct for."""
        warnings = evaluate_cache_safety(
            rule(matcher_kind="glob", matcher_value="/_next/static/**", edge_ttl_seconds=31_536_000)
        )
        assert "long-ttl-on-html" not in [w.code for w in warnings]

    def test_a_fully_shadowed_rule_warns(self) -> None:
        outer = rule(id="outer", ordinal=0, matcher_value="/docs")
        inner = rule(id="inner", ordinal=5, matcher_value="/docs/api")
        warnings = evaluate_cache_safety(inner, siblings=[outer, inner])
        assert "rule-shadowed" in [w.code for w in warnings]

    def test_a_lower_precedence_rule_does_not_shadow_a_higher_one(self) -> None:
        outer = rule(id="outer", ordinal=9, matcher_value="/docs")
        inner = rule(id="inner", ordinal=1, matcher_value="/docs/api")
        warnings = evaluate_cache_safety(inner, siblings=[outer, inner])
        assert "rule-shadowed" not in [w.code for w in warnings]

    def test_shadowing_is_not_guessed_across_regexes(self) -> None:
        """Coverage that cannot be decided cheaply is not reported; a warning an operator
        cannot act on is worse than silence."""
        outer = rule(id="outer", ordinal=0, matcher_kind="regex", matcher_value="^/docs")
        inner = rule(id="inner", ordinal=5, matcher_value="/docs/api")
        warnings = evaluate_cache_safety(inner, siblings=[outer, inner])
        assert "rule-shadowed" not in [w.code for w in warnings]

    def test_every_warning_carries_a_sentence(self) -> None:
        warnings = evaluate_cache_safety(
            rule(vary_query_mode="all", vary_cookies=["theme"], edge_ttl_seconds=7_200)
        )
        assert len(warnings) == 3
        for warning in warnings:
            assert len(warning.message) > 20, f"{warning.code} has no sentence"


class TestNormalizeRule:
    """Normalization is what makes two spellings of one rule hash alike."""

    def test_header_names_and_methods_are_case_folded(self) -> None:
        normalized = normalize_rule(
            {"vary_headers": ["Accept-Language"], "matcher_methods": ["get"]}
        )
        assert normalized["vary_headers"] == ["accept-language"]
        assert normalized["matcher_methods"] == ["GET"]

    def test_cookie_names_keep_their_case_because_http_does(self) -> None:
        assert normalize_rule({"vary_cookies": ["SessionId"]})["vary_cookies"] == ["SessionId"]

    def test_missing_fields_take_their_column_defaults(self) -> None:
        normalized = normalize_rule({})
        assert normalized["eligibility"] == "cacheable"
        assert normalized["matcher_methods"] == ["GET", "HEAD"]
        assert normalized["enabled"] is True

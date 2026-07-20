"""Purge scope planning — UXE-3.1 (private-suite#2473).

Pure tests over :func:`app.slate_cache.plan_purge_scope`, which answers the first half of
acceptance criterion 3: "purge estimates scope and supports release/tag/prefix/host/URL". The
audit half is asserted in ``tests/test_slate_cache_routes.py``, where the writes happen.

Two properties get disproportionate attention, because both fail quietly and both fail during
an incident — the worst combination:

* **An estimate states its basis.** A bare number invites belief; a number plus the table that
  produced it invites checking.
* **A scope never widens by accident.** An empty or unbounded scope is refused rather than
  interpreted generously, and prefix comparison is textual in Python rather than handed to SQL
  ``LIKE``, where an unescaped ``_`` in a route silently matches any character.
"""

from __future__ import annotations

import pytest

from app.slate_cache import (
    PURGE_SCOPE_KINDS,
    SlateCacheRefusedError,
    plan_purge_scope,
)

ROUTES = [
    "/",
    "/docs/intro",
    "/docs/api",
    "/docs/api/auth",
    "/blog/hello",
    "/docs_internal/secret",
]


def plan(**overrides):
    """Plan a purge over the suite's route inventory."""
    base = {
        "scope_kind": "prefix",
        "scope_value": "/docs",
        "routes": ROUTES,
        "basis": "changed-pages",
    }
    base.update(overrides)
    return plan_purge_scope(**base)


class TestScopeKinds:
    """All five roadmap scopes, and nothing else."""

    def test_exactly_the_five_roadmap_scopes_are_supported(self) -> None:
        assert PURGE_SCOPE_KINDS == ("release", "tag", "prefix", "host", "url")

    @pytest.mark.parametrize(
        ("kind", "value"),
        [
            ("release", "r-4821"),
            ("tag", "nav"),
            ("prefix", "/docs"),
            ("host", "docs.example.com"),
            ("url", "/docs/intro"),
        ],
    )
    def test_every_scope_kind_plans(self, kind, value) -> None:
        result = plan(scope_kind=kind, scope_value=value)
        assert result.scope_kind == kind
        assert result.estimated_objects > 0

    def test_the_parametrized_cases_cover_every_supported_kind(self) -> None:
        """Guards the sweep above against a scope kind added without a case."""
        covered = {"release", "tag", "prefix", "host", "url"}
        assert covered == set(PURGE_SCOPE_KINDS)

    def test_an_unknown_scope_kind_is_refused(self) -> None:
        with pytest.raises(SlateCacheRefusedError) as excinfo:
            plan(scope_kind="everything")
        assert excinfo.value.code == "purge-scope-unbounded"


class TestPrefixScope:
    """The scope most likely to widen by accident."""

    def test_a_prefix_selects_only_matching_routes(self) -> None:
        result = plan(scope_value="/docs/")
        assert result.sample_routes == ["/docs/api", "/docs/api/auth", "/docs/intro"]
        assert result.estimated_objects == 3

    def test_an_underscore_in_a_route_is_not_a_wildcard(self) -> None:
        """Handed to SQL LIKE unescaped, `/docs_` would match `/docsX` and widen the purge."""
        result = plan(scope_value="/docs_internal")
        assert result.sample_routes == ["/docs_internal/secret"]

    def test_a_percent_in_a_scope_is_literal(self) -> None:
        with pytest.raises(SlateCacheRefusedError) as excinfo:
            plan(scope_value="/docs%")
        assert excinfo.value.code == "purge-scope-empty"

    def test_prefix_comparison_matches_the_rule_matcher(self) -> None:
        """`/docs` selects `/docs_internal` here exactly as it would in a rule matcher."""
        result = plan(scope_value="/docs")
        assert "/docs_internal/secret" in result.sample_routes


class TestUrlScope:
    """A URL scope is one object, and says so."""

    def test_an_absolute_url_is_reduced_to_its_path(self) -> None:
        result = plan(scope_kind="url", scope_value="https://docs.example.com/docs/intro")
        assert result.estimated_objects == 1
        assert result.sample_routes == ["/docs/intro"]

    def test_a_bare_path_works_too(self) -> None:
        result = plan(scope_kind="url", scope_value="/docs/intro")
        assert result.sample_routes == ["/docs/intro"]

    def test_a_url_naming_nothing_on_the_release_is_refused(self) -> None:
        with pytest.raises(SlateCacheRefusedError) as excinfo:
            plan(scope_kind="url", scope_value="/nope")
        assert excinfo.value.code == "purge-scope-empty"

    def test_a_root_url_with_no_path_becomes_root(self) -> None:
        result = plan(scope_kind="url", scope_value="https://docs.example.com")
        assert result.sample_routes == ["/"]


class TestRefusals:
    """Refusing beats interpreting generously when the subject is a blast radius."""

    @pytest.mark.parametrize("value", ["", "   "])
    def test_an_empty_scope_value_is_refused_as_unbounded(self, value) -> None:
        with pytest.raises(SlateCacheRefusedError) as excinfo:
            plan(scope_value=value)
        assert excinfo.value.code == "purge-scope-unbounded"

    def test_a_scope_matching_nothing_is_refused_rather_than_estimated_at_zero(self) -> None:
        """A no-op purge run during an incident reads as "done" and costs the outage time."""
        with pytest.raises(SlateCacheRefusedError) as excinfo:
            plan(scope_value="/nonexistent")
        assert excinfo.value.code == "purge-scope-empty"

    def test_an_empty_route_inventory_is_refused(self) -> None:
        with pytest.raises(SlateCacheRefusedError) as excinfo:
            plan(routes=[])
        assert excinfo.value.code == "purge-scope-empty"

    def test_the_refusal_sentence_says_what_to_do(self) -> None:
        with pytest.raises(SlateCacheRefusedError) as excinfo:
            plan(scope_value="")
        assert "Name a release, tag, prefix, host or URL" in str(excinfo.value)


class TestEstimateProvenance:
    """A number an operator cannot check is a number they should not act on."""

    @pytest.mark.parametrize(
        "basis",
        ["changed-pages", "artifact-manifest", "domain-inventory", "rule-tags", "single-url"],
    )
    def test_the_basis_is_carried_through_and_explained(self, basis) -> None:
        result = plan(basis=basis)
        assert result.estimate_basis == basis
        assert len(result.coverage) > 20

    def test_changed_pages_states_what_it_does_not_cover(self) -> None:
        """The under-count is the honest part: unchanged pages are cached too."""
        assert "Unchanged pages" in plan(basis="changed-pages").coverage

    def test_an_unknown_basis_still_gets_a_sentence(self) -> None:
        assert plan(basis="something-new").coverage


class TestSampleAndTruncation:
    """The sample is a summary, not the inventory it summarizes."""

    def test_routes_are_deduplicated_and_ordered(self) -> None:
        result = plan(routes=["/docs/b", "/docs/a", "/docs/b"], scope_value="/docs")
        assert result.sample_routes == ["/docs/a", "/docs/b"]
        assert result.estimated_objects == 2

    def test_a_large_scope_is_sampled_and_flagged(self) -> None:
        routes = [f"/docs/page-{i:04d}" for i in range(500)]
        result = plan(routes=routes, scope_value="/docs")
        assert result.estimated_objects == 500, "the estimate counts everything"
        assert len(result.sample_routes) == 50, "the sample is bounded"
        assert result.truncated is True

    def test_a_small_scope_is_not_flagged_as_truncated(self) -> None:
        assert plan(scope_value="/docs/").truncated is False

    def test_the_sample_is_a_prefix_of_the_ordered_scope(self) -> None:
        routes = [f"/docs/page-{i:04d}" for i in range(60)]
        result = plan(routes=routes, scope_value="/docs")
        assert result.sample_routes == sorted(routes)[:50]


class TestDeterminism:
    """Same inputs, same estimate — including the sample."""

    def test_planning_twice_gives_the_same_plan(self) -> None:
        assert plan() == plan()

    def test_input_order_does_not_change_the_plan(self) -> None:
        assert plan(routes=list(reversed(ROUTES))) == plan(routes=ROUTES)

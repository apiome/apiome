"""The pure half of the Contracts landing's integrations list — PFX-8.1 (#7298).

:mod:`app.pact_integrations` with no database: the query checks (every refusal carries its code),
the kind / verdict / pending rules, the environments both sides share, the counts and the
status-strip examples, the filters, the search and the page.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.pact_integrations import (
    ATTENTION_EXAMPLES,
    CODE_FILTER_INVALID,
    CODE_PAGE_INVALID,
    CODE_SEARCH_INVALID,
    DEFAULT_LIMIT,
    MAX_INTEGRATIONS,
    MAX_LIMIT,
    MAX_SEARCH_LENGTH,
    IntegrationFacts,
    IntegrationsError,
    IntegrationsQuery,
    build_page,
    classify,
    parse_query,
)


def _facts(consumer: str = "web", provider: str = "api", **extra: Any) -> IntegrationFacts:
    """A pair's facts; the handle doubles as the name and the id."""
    return IntegrationFacts(
        provider=provider,
        provider_name=provider.title(),
        consumer=consumer,
        consumer_name=consumer.title(),
        provider_id=f"id-{provider}",
        consumer_id=f"id-{consumer}",
        consumer_version="1.0.0",
        pact_version_sha="a" * 64,
        **extra,
    )


# --- the query ------------------------------------------------------------------------------------


def test_an_empty_query_reads_as_every_integration_on_the_first_page() -> None:
    assert parse_query() == IntegrationsQuery(search=None, filter="all", limit=DEFAULT_LIMIT, offset=0)


def test_search_text_is_trimmed_and_lower_cased_and_blank_reads_as_none() -> None:
    assert parse_query(search="  Billing ").search == "billing"
    assert parse_query(search="   ").search is None


@pytest.mark.parametrize(
    "kwargs, code",
    [
        ({"filter": "red"}, CODE_FILTER_INVALID),
        ({"filter": ""}, CODE_FILTER_INVALID),
        ({"search": "x" * (MAX_SEARCH_LENGTH + 1)}, CODE_SEARCH_INVALID),
        ({"search": "bad\x00text"}, CODE_SEARCH_INVALID),
        ({"limit": 0}, CODE_PAGE_INVALID),
        ({"limit": MAX_LIMIT + 1}, CODE_PAGE_INVALID),
        ({"offset": -1}, CODE_PAGE_INVALID),
        ({"offset": MAX_INTEGRATIONS + 1}, CODE_PAGE_INVALID),
    ],
)
def test_every_refused_query_names_its_code(kwargs: Any, code: str) -> None:
    with pytest.raises(IntegrationsError) as caught:
        parse_query(**kwargs)
    assert caught.value.code == code
    assert str(caught.value)


def test_an_unknown_filter_names_the_ones_that_exist() -> None:
    with pytest.raises(IntegrationsError, match="all, failing, stale, bidirectional, mine"):
        parse_query(filter="red")


# --- the rules ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "extra, verdict",
    [
        ({"latest_success": False, "stale": True}, "failing"),
        ({"latest_success": True, "stale": True}, "stale"),
        ({"latest_success": True}, "verified"),
        ({}, "no-provider-contract"),
        ({"provider_has_contract": True}, "unverified"),
    ],
)
def test_the_verdict_takes_the_first_rule_that_matches(extra: Any, verdict: str) -> None:
    assert classify(_facts(**extra)).verdict == verdict


@pytest.mark.parametrize(
    "extra, kind",
    [
        ({"latest_kind": "bidirectional", "latest_success": True}, "bidirectional"),
        ({"latest_kind": "native", "latest_success": True, "provider_has_contract": True}, "pact"),
        ({"provider_has_contract": True}, "bidirectional"),
        ({}, "pact"),
    ],
)
def test_the_kind_follows_the_newest_verdict_then_the_provider_contract(extra: Any, kind: str) -> None:
    assert classify(_facts(**extra)).kind == kind


def test_a_pact_the_provider_never_passed_natively_is_pending() -> None:
    assert classify(_facts(latest_success=False, latest_kind="native")).pending is True
    assert classify(_facts(latest_success=True, latest_kind="native", native_success=True)).pending is False


def test_a_bidirectional_integration_is_never_pending() -> None:
    assert classify(_facts(latest_kind="bidirectional", latest_success=True)).pending is False


def test_only_the_environments_both_sides_run_in_are_listed_sorted() -> None:
    row = classify(
        _facts(
            consumer_environments=frozenset({"production", "staging", "dev"}),
            provider_environments=frozenset({"staging", "production", "qa"}),
        )
    )
    assert row.environments == ["production", "staging"]


def test_mine_means_a_team_of_the_caller_owns_either_side() -> None:
    assert classify(_facts(), frozenset({"id-web"})).mine is True
    assert classify(_facts(), frozenset({"id-api"})).mine is True
    assert classify(_facts(), frozenset({"id-other"})).mine is False
    assert classify(_facts()).mine is False


def test_the_newest_result_carries_the_provider_version_and_when() -> None:
    row = classify(_facts(latest_success=True, latest_at="2026-11-26T10:00:00+00:00", provider_version="2.7.0"))
    assert (row.provider_version, row.verified_at) == ("2.7.0", "2026-11-26T10:00:00+00:00")


# --- the page -------------------------------------------------------------------------------------


def _workspace() -> list:
    return [
        _facts("orders-ui", "billing", latest_success=False, latest_kind="bidirectional"),
        _facts("mobile", "payments", latest_success=True, latest_kind="native", native_success=True, stale=True),
        _facts("checkout", "payments"),
        _facts("orders-ui", "orders-api", latest_success=True, latest_kind="native", native_success=True),
        _facts("billing", "ledger", provider_has_contract=True),
    ]


def test_rows_come_worst_verdict_first_then_by_name() -> None:
    page = build_page(_workspace(), parse_query())
    assert [(row.consumer, row.verdict) for row in page.integrations] == [
        ("orders-ui", "failing"),
        ("mobile", "stale"),
        ("checkout", "no-provider-contract"),
        ("billing", "unverified"),
        ("orders-ui", "verified"),
    ]


def test_the_counts_cover_every_pair_whatever_the_filter() -> None:
    page = build_page(_workspace(), parse_query(filter="failing", search="orders"))
    counts = page.counts
    assert (counts.integrations, counts.verified, counts.failing, counts.stale) == (5, 1, 1, 1)
    assert (counts.no_provider_contract, counts.unverified, counts.bidirectional) == (1, 1, 2)
    # checkout → payments has no result; orders-ui → billing is bi-directional (never pending).
    assert counts.pending == 1
    assert page.total == 1


def test_the_attention_lists_name_the_pairs_of_each_strip_category() -> None:
    attention = build_page(_workspace(), parse_query()).attention
    assert [ref.consumer for ref in attention.failing] == ["orders-ui"]
    assert [ref.consumer for ref in attention.stale] == ["mobile"]
    assert [ref.consumer for ref in attention.no_provider_contract] == ["checkout"]
    assert [ref.consumer for ref in attention.pending] == ["checkout"]


def test_the_attention_lists_name_at_most_a_few_pairs() -> None:
    many = [_facts(f"c{index}", "api", latest_success=False) for index in range(ATTENTION_EXAMPLES + 4)]
    page = build_page(many, parse_query())
    assert len(page.attention.failing) == ATTENTION_EXAMPLES
    assert page.counts.failing == ATTENTION_EXAMPLES + 4


@pytest.mark.parametrize(
    "chip, consumers",
    [
        ("failing", ["orders-ui"]),
        ("stale", ["mobile"]),
        ("bidirectional", ["orders-ui", "billing"]),
    ],
)
def test_each_filter_chip_narrows_the_rows(chip: str, consumers: list) -> None:
    page = build_page(_workspace(), parse_query(filter=chip))
    assert [row.consumer for row in page.integrations] == consumers


def test_the_mine_chip_lists_the_pairs_a_team_of_the_caller_owns() -> None:
    page = build_page(_workspace(), parse_query(filter="mine"), owned=frozenset({"id-payments"}))
    assert [row.consumer for row in page.integrations] == ["mobile", "checkout"]
    assert page.counts.mine == 2


def test_the_search_matches_handles_and_names_of_either_side() -> None:
    assert [row.provider for row in build_page(_workspace(), parse_query(search="PAYM")).integrations] == [
        "payments",
        "payments",
    ]
    assert build_page(_workspace(), parse_query(search="Ledger")).total == 1
    assert build_page(_workspace(), parse_query(search="nothing")).total == 0


def test_the_page_is_cut_from_the_matching_rows() -> None:
    page = build_page(_workspace(), parse_query(limit=2, offset=2))
    assert [row.consumer for row in page.integrations] == ["checkout", "billing"]
    assert (page.total, page.offset, page.limit) == (5, 2, 2)


def test_a_capped_read_says_how_many_pairs_it_left_out() -> None:
    page = build_page(_workspace(), parse_query(), omitted=7, pacticipants=9, environments=3)
    assert (page.truncated, page.omitted_integrations) == (True, 7)
    assert (page.pacticipants, page.environments) == (9, 3)
    assert build_page(_workspace(), parse_query()).truncated is False


def test_an_empty_workspace_answers_an_empty_page() -> None:
    page = build_page([], parse_query())
    assert page.integrations == [] and page.total == 0 and page.counts.integrations == 0

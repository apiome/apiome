"""Consumer-version selectors — PFX-1.3 (#6916).

The pure part of ``for-verification`` (:mod:`app.pact_selectors`), against one fixture of
publications for the provider *Ledger API*:

============  =====  ============  ==========  ========================
consumer      seq    version       branches    tags
============  =====  ============  ==========  ========================
Billing        1     b1            main        prod
Billing        2     b2            main        —
Billing        3     b3            feat/x      —
Billing        4     b4            main        rc
Checkout       5     c1            master      prod
Checkout       6     c2            develop     —
============  =====  ============  ==========  ========================

Billing's main branch is ``main``; Checkout's is ``master``. ``b1`` and ``b2`` published the same
pact (``sha-a``), so selecting both yields one pact with two reasons.

Asserted: each selector kind selects what the Pact Broker would; fallbacks apply per consumer;
results merge per content; the broker's defaults apply when no selector is sent; ambiguous and
malformed selectors are refused with the broker's message and a pointer; notices, short
descriptions and URL metadata use the broker's wording and encoding.
"""

from __future__ import annotations

import base64
import datetime
from typing import Any, Dict, List
from urllib.parse import parse_qsl

import pytest

from app.pact_publication import PactPublicationError
from app.pact_selectors import (
    CODE_SELECTOR_INVALID,
    MAX_SELECTORS,
    ConsumerVersionSelector,
    ForVerificationQuery,
    PactCandidate,
    VerifiablePact,
    build_notices,
    encode_metadata,
    inclusion_reason,
    is_pending,
    latest_per_consumer,
    parse_for_verification_request,
    pending_reason,
    select_verifiable_pacts,
    short_description,
    verification_metadata,
)

PROVIDER = "Ledger API"
URL = "https://broker.example/pacts/provider/ledger-api/consumer/billing/pact-version/sha"


def _candidate(consumer: str, seq: int, number: str, sha: str, branches=(), tags=()) -> PactCandidate:
    main = {"billing": "main", "checkout": "master"}[consumer]
    return PactCandidate(
        consumer_id=f"id-{consumer}",
        consumer_slug=consumer,
        consumer_name=consumer.title(),
        consumer_main_branch=main,
        version_id=f"v-{number}",
        version_number=number,
        version_seq=seq,
        sha=sha,
        branches=tuple(branches),
        tags=tuple(tags),
    )


FIXTURE: List[PactCandidate] = [
    _candidate("billing", 1, "b1", "sha-a", ["main"], ["prod"]),
    _candidate("billing", 2, "b2", "sha-a", ["main"]),
    _candidate("billing", 3, "b3", "sha-b", ["feat/x"]),
    _candidate("billing", 4, "b4", "sha-c", ["main"], ["rc"]),
    _candidate("checkout", 5, "c1", "sha-d", ["master"], ["prod"]),
    _candidate("checkout", 6, "c2", "sha-e", ["develop"]),
]


def _select(*selectors: Dict[str, Any], **body: Any) -> List[VerifiablePact]:
    query = parse_for_verification_request({"consumerVersionSelectors": list(selectors), **body})
    return select_verifiable_pacts(FIXTURE, query)


def _versions(pacts: List[VerifiablePact]) -> List[str]:
    return [pact.candidate.version_number for pact in pacts]


# ---------------------------------------------------------------------------------------------
# One fixture test per selector kind
# ---------------------------------------------------------------------------------------------


def test_main_branch_selects_the_latest_version_of_each_consumer_from_its_own_main_branch() -> None:
    pacts = _select({"mainBranch": True})
    assert _versions(pacts) == ["b4", "c1"]
    assert short_description(pacts[0]) == "latest from main branch"


def test_branch_selects_the_latest_version_from_that_branch() -> None:
    pacts = _select({"branch": "main"})
    assert _versions(pacts) == ["b4"]
    assert short_description(pacts[0]) == "latest from branch main"
    assert _versions(_select({"branch": "feat/x"})) == ["b3"]


def test_matching_branch_uses_the_provider_version_branch() -> None:
    pacts = _select({"matchingBranch": True}, providerVersionBranch="develop")
    assert _versions(pacts) == ["c2"]
    assert pacts[0].selected_by[0].selector.matching_branch is True
    assert short_description(pacts[0]) == "latest from branch develop"


def test_fallback_branch_applies_per_consumer() -> None:
    # Billing has a pact from feat/x; Checkout does not and falls back to master.
    pacts = _select({"branch": "feat/x", "fallbackBranch": "master"})
    assert _versions(pacts) == ["b3", "c1"]
    assert pacts[0].selected_by[0].fallback is False
    assert pacts[1].selected_by[0].fallback is True
    assert short_description(pacts[1]) == "latest from branch master"
    assert "(fallback branch used as no pact was found from branch 'feat/x') (c1)" in inclusion_reason(
        pacts[1], URL, PROVIDER
    )


def test_fallback_to_main_branch_uses_each_consumers_main_branch() -> None:
    pacts = _select({"branch": "feat/x", "fallbackToMainBranch": True})
    assert _versions(pacts) == ["b3", "c1"]
    assert pacts[1].selected_by[0].branch == "master"


def test_latest_alone_selects_the_latest_version_of_each_consumer() -> None:
    pacts = _select({"latest": True})
    assert _versions(pacts) == ["b4", "c2"]
    assert short_description(pacts[0]) == "latest"
    assert "latest version of a consumer that has a pact with Ledger API (b4)" in inclusion_reason(
        pacts[0], URL, PROVIDER
    )


def test_tag_with_latest_selects_the_latest_tagged_version() -> None:
    pacts = _select({"tag": "prod", "latest": True})
    assert _versions(pacts) == ["b1", "c1"]
    assert short_description(pacts[0]) == "latest with tag prod"


def test_tag_without_latest_selects_every_tagged_version() -> None:
    pacts = _select({"tag": "prod"})
    assert _versions(pacts) == ["b1", "c1"]
    assert short_description(pacts[0]) == "one of prod"
    assert "all consumer versions tagged 'prod' (b1)" in inclusion_reason(pacts[0], URL, PROVIDER)


def test_fallback_tag_applies_per_consumer() -> None:
    pacts = _select({"tag": "rc", "latest": True, "fallbackTag": "prod"})
    assert _versions(pacts) == ["b4", "c1"]
    assert pacts[1].selected_by[0].fallback is True
    assert short_description(pacts[1]) == "latest with tag prod"
    assert "latest version tagged 'prod' (fallback tag used as no pact was found with tag 'rc') (c1)" in (
        inclusion_reason(pacts[1], URL, PROVIDER)
    )


def test_consumer_narrows_a_selector_by_name_or_handle() -> None:
    assert _versions(_select({"latest": True, "consumer": "Checkout"})) == ["c2"]
    assert _versions(_select({"mainBranch": True, "consumer": "billing"})) == ["b4"]
    assert _select({"latest": True, "consumer": "Nobody"}) == []
    pacts = _select({"mainBranch": True, "consumer": "Billing"})
    assert "latest version of Billing from the main branch 'main' (b4)" in inclusion_reason(pacts[0], URL, PROVIDER)


@pytest.mark.parametrize(
    "selector",
    [
        {"deployed": True},
        {"released": True},
        {"deployedOrReleased": True},
        {"environment": "production"},
        {"deployed": True, "environment": "production"},
    ],
)
def test_environment_selectors_select_nothing_when_nothing_is_deployed_or_released(
    selector: Dict[str, Any],
) -> None:
    assert _select(selector) == []


# Where the versions run (PFX-1.5): b1 is deployed to production, b4 and c2 to test, and c1 is
# released (and supported) in production.
DEPLOYED = [
    PactCandidate(**{**FIXTURE[0].__dict__, "deployed_to": ("production",)}),
    FIXTURE[1],
    FIXTURE[2],
    PactCandidate(**{**FIXTURE[3].__dict__, "deployed_to": ("test",)}),
    PactCandidate(**{**FIXTURE[4].__dict__, "released_in": ("production",)}),
    PactCandidate(**{**FIXTURE[5].__dict__, "deployed_to": ("test",)}),
]


def _select_deployed(*selectors: Dict[str, Any]) -> List[VerifiablePact]:
    query = parse_for_verification_request({"consumerVersionSelectors": list(selectors)})
    return select_verifiable_pacts(DEPLOYED, query)


def test_deployed_selects_every_version_currently_deployed_and_names_where() -> None:
    pacts = _select_deployed({"deployed": True})
    assert _versions(pacts) == ["b1", "b4", "c2"]
    assert [selected.environment for pact in pacts for selected in pact.selected_by] == [
        "production",
        "test",
        "test",
    ]
    assert short_description(pacts[0]) == "deployed to production"
    assert "consumer version(s) currently deployed to production (b1)" in inclusion_reason(pacts[0], URL, PROVIDER)


def test_deployed_to_one_environment_and_one_consumer() -> None:
    assert _versions(_select_deployed({"deployed": True, "environment": "test"})) == ["b4", "c2"]
    assert _versions(_select_deployed({"deployed": True, "environment": "test", "consumer": "Checkout"})) == ["c2"]
    assert _select_deployed({"deployed": True, "environment": "staging"}) == []


def test_released_selects_supported_releases_only() -> None:
    pacts = _select_deployed({"released": True})
    assert _versions(pacts) == ["c1"]
    assert short_description(pacts[0]) == "released in production"
    assert "released and supported in production (c1)" in inclusion_reason(pacts[0], URL, PROVIDER)


def test_environment_alone_selects_deployed_or_released_there() -> None:
    assert _versions(_select_deployed({"environment": "production"})) == ["b1", "c1"]
    assert _versions(_select_deployed({"deployedOrReleased": True, "environment": "production"})) == ["b1", "c1"]


def test_the_environment_found_goes_into_the_url_metadata() -> None:
    pacts = _select_deployed({"deployed": True, "consumer": "Billing", "environment": "production"})
    assert verification_metadata(pacts[0])["s"][0]["e"] == "production"
    pacts = _select_deployed({"deployed": True, "consumer": "Billing"})
    assert verification_metadata(pacts[0])["s"][0]["e"] == "production"


def test_the_defaults_include_what_is_deployed_and_released() -> None:
    query = parse_for_verification_request({})
    versions = _versions(select_verifiable_pacts(DEPLOYED, query))
    # The latest per consumer from its main branch (b4, c1), plus what runs somewhere (b1, c2).
    assert versions == ["b1", "b4", "c1", "c2"]


def test_deployed_or_released_is_split_into_a_deployed_and_a_released_selector() -> None:
    query = parse_for_verification_request(
        {"consumerVersionSelectors": [{"deployedOrReleased": True, "environment": "prod"}]}
    )
    assert [(s.deployed, s.released, s.environment) for s in query.selectors] == [
        (True, False, "prod"),
        (False, True, "prod"),
    ]


# ---------------------------------------------------------------------------------------------
# Merging, ordering, defaults
# ---------------------------------------------------------------------------------------------


def test_the_same_content_selected_twice_is_one_pact_with_both_reasons() -> None:
    pacts = _select({"tag": "prod", "latest": True, "consumer": "Billing"}, {"latest": True, "consumer": "Billing"})
    assert _versions(pacts) == ["b1", "b4"]
    # b1 (sha-a) and b2 (sha-a) are the same content: choosing b1 by tag and b2 another way merges.
    merged = select_verifiable_pacts(
        FIXTURE,
        ForVerificationQuery(
            selectors=(
                ConsumerVersionSelector(tag="prod", latest=True, consumer="Billing"),
                ConsumerVersionSelector(tag="prod", consumer="Billing"),
            )
        ),
    )
    assert len(merged) == 1 and len(merged[0].selected_by) == 2


def test_a_merged_pact_is_named_after_its_latest_consumer_version() -> None:
    query = ForVerificationQuery(
        selectors=(
            ConsumerVersionSelector(tag="prod", consumer="Billing"),
            ConsumerVersionSelector(branch="main", latest=True, consumer="Billing"),
        )
    )
    candidates = FIXTURE[:2]  # b1 and b2 share sha-a; b2 is the latest on main here.
    pacts = select_verifiable_pacts(candidates, query)
    assert len(pacts) == 1
    assert pacts[0].candidate.version_number == "b2"
    reason = inclusion_reason(pacts[0], URL, PROVIDER)
    assert "the consumer versions matching the following criteria:" in reason
    assert reason.endswith(
        "    * latest version of Billing from branch 'main' (b2)\n    * all Billing versions tagged 'prod' (b1)"
    )
    assert short_description(pacts[0]) == "latest from branch main, one of Billing prod"


def test_pacts_are_ordered_by_consumer_name_then_version() -> None:
    pacts = _select({"tag": "prod"}, {"latest": True})
    assert _versions(pacts) == ["b1", "b4", "c1", "c2"]


def test_no_selectors_means_each_consumers_main_branch_or_its_latest() -> None:
    pacts = select_verifiable_pacts(FIXTURE, parse_for_verification_request({}))
    assert _versions(pacts) == ["b4", "c1"]
    assert pacts[0].selected_by[0].selector.main_branch is True

    # A consumer without a main branch falls back to its overall latest version.
    without_main = [
        PactCandidate(**{**c.__dict__, "consumer_main_branch": None}) if c.consumer_slug == "checkout" else c
        for c in FIXTURE
    ]
    pacts = select_verifiable_pacts(without_main, ForVerificationQuery())
    assert _versions(pacts) == ["b4", "c2"]


def test_no_selectors_uses_a_tag_named_after_the_main_branch_when_no_branch_matches() -> None:
    candidates = [
        PactCandidate(**{**FIXTURE[4].__dict__, "branches": (), "tags": ("master",)}),
        FIXTURE[5],
    ]
    pacts = select_verifiable_pacts(candidates, ForVerificationQuery())
    assert _versions(pacts) == ["c1"]
    assert pacts[0].selected_by[0].selector.tag == "master"


def test_an_empty_provider_selects_nothing() -> None:
    assert select_verifiable_pacts([], ForVerificationQuery()) == []


def test_latest_per_consumer_keeps_the_highest_seq() -> None:
    latest = latest_per_consumer(FIXTURE, lambda c: True)
    assert sorted(c.version_number for c in latest) == ["b4", "c2"]


# ---------------------------------------------------------------------------------------------
# Refusals: ambiguous or malformed selectors are a 400 with a pointer
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("selector", "message"),
    [
        ({}, "must specify a value for environment or tag or branch"),
        ({"latest": False}, "must specify a value for environment or tag or branch"),
        ({"consumer": "Billing"}, "must specify a value for environment or tag or branch"),
        ({"mainBranch": True, "tag": "prod"}, "cannot specify mainBranch=true with any other criteria"),
        ({"mainBranch": True, "latest": False}, "cannot specify mainBranch=true with latest=false"),
        ({"matchingBranch": True, "tag": "x"}, "cannot specify matchingBranch=true with any other criteria"),
        ({"matchingBranch": True}, "the providerVersionBranch must be specified"),
        ({"tag": "prod", "branch": "main"}, "cannot specify both a tag and a branch"),
        ({"branch": "main", "environment": "prod"}, "cannot specify the field branch with the field environment"),
        (
            {"tag": "x", "latest": True, "deployed": True, "environment": "prod"},
            "cannot specify the fields latest/tag with the fields deployed/environment",
        ),
        ({"tag": "prod", "fallbackTag": "main"}, "fallbackTag can only be set if latest is true"),
        ({"latest": True, "fallbackTag": "main"}, "a tag must be specified when a fallbackTag is specified"),
        ({"latest": True, "fallbackBranch": "main"}, "a branch must be specified when a fallbackBranch"),
        ({"branch": "x", "fallbackBranch": "y", "latest": False}, "fallbackBranch can only be set if latest is true"),
        ({"latest": True, "fallbackToMainBranch": True}, "a branch must be specified when fallbackToMainBranch"),
        (
            {"branch": "x", "fallbackBranch": "y", "fallbackToMainBranch": True},
            "cannot specify both fallbackBranch and fallbackToMainBranch=true",
        ),
        ({"branch": "main", "latest": False}, "cannot specify a branch with latest=false"),
        ({"deployed": True, "released": True}, "cannot specify both deployed=true and released=true"),
        ({"deployed": True, "deployedOrReleased": True}, "cannot specify both deployed=true and deployedOrReleased"),
        ({"released": True, "deployedOrReleased": True}, "cannot specify both released=true and deployedOrReleased"),
    ],
)
def test_ambiguous_selectors_are_refused_with_the_brokers_message(selector: Dict[str, Any], message: str) -> None:
    with pytest.raises(PactPublicationError) as caught:
        parse_for_verification_request({"consumerVersionSelectors": [{"latest": True}, selector]})
    assert caught.value.code == CODE_SELECTOR_INVALID
    assert caught.value.pointer == "/consumerVersionSelectors/1"
    assert message in str(caught.value)


@pytest.mark.parametrize(
    ("body", "pointer"),
    [
        ([], ""),
        ({"consumerVersionSelectors": {"latest": True}}, "/consumerVersionSelectors"),
        ({"consumerVersionSelectors": ["latest"]}, "/consumerVersionSelectors/0"),
        ({"consumerVersionSelectors": [{"mainBranch": False}]}, "/consumerVersionSelectors/0/mainBranch"),
        ({"consumerVersionSelectors": [{"deployed": "yes"}]}, "/consumerVersionSelectors/0/deployed"),
        ({"consumerVersionSelectors": [{"latest": "true"}]}, "/consumerVersionSelectors/0/latest"),
        ({"consumerVersionSelectors": [{"tag": 7}]}, "/consumerVersionSelectors/0/tag"),
        ({"consumerVersionSelectors": [{"branch": "  "}]}, "/consumerVersionSelectors/0/branch"),
        ({"consumerVersionSelectors": [{"latest": True}] * (MAX_SELECTORS + 1)}, "/consumerVersionSelectors"),
        ({"providerVersionBranch": 3}, "/providerVersionBranch"),
        ({"providerVersionBranch": "  "}, "/providerVersionBranch"),
        ({"providerVersionBranch": "", "includePendingStatus": True}, "/providerVersionBranch"),
        ({"providerVersionTags": "main"}, "/providerVersionTags"),
        ({"providerVersionTags": [""]}, "/providerVersionTags"),
        ({"includePendingStatus": "true"}, "/includePendingStatus"),
        ({"includeWipPactsSince": "last week"}, "/includeWipPactsSince"),
        ({"includeWipPactsSince": 20260101}, "/includeWipPactsSince"),
    ],
)
def test_malformed_requests_are_refused_with_a_pointer(body: Any, pointer: str) -> None:
    with pytest.raises(PactPublicationError) as caught:
        parse_for_verification_request(body)
    assert caught.value.code == CODE_SELECTOR_INVALID
    assert caught.value.pointer == pointer


def test_an_empty_branch_is_tolerated_when_pending_and_wip_are_off() -> None:
    # The broker lets this through: clients that send "" without pending/WIP keep working.
    query = parse_for_verification_request({"providerVersionBranch": ""})
    assert query.provider_version_branch is None


def test_the_request_fields_are_read() -> None:
    query = parse_for_verification_request(
        {
            "providerVersionBranch": " main ",
            "providerVersionTags": ["dev", "dev", "prod"],
            "includePendingStatus": True,
            "includeWipPactsSince": "2026-01-31",
            "unknownField": "ignored",
        }
    )
    assert query.provider_version_branch == "main"
    assert query.provider_version_tags == ("dev", "prod")
    assert query.include_pending_status is True
    assert query.include_wip_pacts_since == datetime.date(2026, 1, 31)
    assert parse_for_verification_request(None) == ForVerificationQuery()
    assert parse_for_verification_request({"includeWipPactsSince": "2026-01-31T10:00:00Z"}).include_wip_pacts_since == (
        datetime.date(2026, 1, 31)
    )


def test_a_branch_selector_always_means_latest() -> None:
    query = parse_for_verification_request({"consumerVersionSelectors": [{"branch": "main"}, {"mainBranch": True}]})
    assert [s.latest for s in query.selectors] == [True, True]


# ---------------------------------------------------------------------------------------------
# Pending and notices
# ---------------------------------------------------------------------------------------------


def test_every_pact_is_pending_until_verification_results_exist() -> None:
    pacts = _select({"mainBranch": True})
    assert all(pact.pending for pact in pacts)
    assert is_pending(pacts[0], ForVerificationQuery()) is True


def test_without_include_pending_status_there_is_only_the_inclusion_notice() -> None:
    pact = _select({"mainBranch": True})[0]
    notices = build_notices(pact, URL, ForVerificationQuery(), PROVIDER)
    assert notices == [
        {
            "when": "before_verification",
            "text": (
                f"The pact at {URL} is being verified because the pact content belongs to the consumer version "
                "matching the following criterion:\n    * latest version from the main branch 'main' (b4)"
            ),
        }
    ]


def test_pending_notices_name_the_provider_branch() -> None:
    pact = _select({"mainBranch": True})[0]
    query = ForVerificationQuery(provider_version_branch="main", include_pending_status=True)
    notices = build_notices(pact, URL, query, PROVIDER)
    assert [notice["when"] for notice in notices] == [
        "before_verification",
        "before_verification",
        "after_verification:success_true_published_false",
        "after_verification:success_false_published_false",
        "after_verification:success_true_published_true",
        "after_verification:success_false_published_true",
    ]
    assert notices[1]["text"] == (
        "This pact is in pending state for this version of Ledger API because a successful verification result "
        "for a version of Ledger API from branch 'main' has not yet been published. If this verification fails, "
        "it will not cause the overall build to fail. Read more at https://docs.pact.io/go/pending"
    )
    assert notices[2]["text"] == (
        "This pact is still in pending state for any version of Ledger API from branch 'main' as the successful "
        "verification results have not yet been published."
    )
    assert notices[4]["text"].startswith(
        "This pact is no longer in pending state for any version of Ledger API from branch 'main', as a "
        "successful verification result has been published."
    )


def test_pending_notices_name_provider_tags_when_there_is_no_branch() -> None:
    pact = _select({"mainBranch": True})[0]
    one = ForVerificationQuery(provider_version_tags=("dev",), include_pending_status=True)
    two = ForVerificationQuery(provider_version_tags=("dev", "prod"), include_pending_status=True)
    none = ForVerificationQuery(include_pending_status=True)
    assert "for a version of Ledger API with tag 'dev' has not" in pending_reason(pact, one, PROVIDER)
    assert "for a versions of Ledger API with tag 'dev' and 'prod' has not" in pending_reason(pact, two, PROVIDER)
    assert "result for Ledger API has not yet been published" in pending_reason(pact, none, PROVIDER)
    assert "results with this tag have not" in build_notices(pact, URL, one, PROVIDER)[2]["text"]
    assert "results with these tags have not" in build_notices(pact, URL, two, PROVIDER)[2]["text"]


def test_a_verified_pact_says_a_failure_will_fail_the_build() -> None:
    pact = _select({"mainBranch": True})[0]
    pact.pending = False
    query = ForVerificationQuery(provider_version_branch="main", include_pending_status=True)
    notices = build_notices(pact, URL, query, PROVIDER)
    assert len(notices) == 2
    assert notices[1]["text"] == (
        "This pact has previously been successfully verified by a version of Ledger API from branch 'main'. If "
        "this verification fails, it will fail the build. Read more at https://docs.pact.io/go/pending"
    )


# ---------------------------------------------------------------------------------------------
# URL metadata
# ---------------------------------------------------------------------------------------------


def _decode(segment: str) -> List[tuple]:
    padded = segment + "=" * (-len(segment) % 4)
    return parse_qsl(base64.urlsafe_b64decode(padded).decode("utf-8"))


def test_metadata_is_the_brokers_nested_query_in_unpadded_url_safe_base64() -> None:
    pact = _select({"branch": "feat/x"})[0]
    metadata = verification_metadata(pact)
    assert metadata == {"s": [{"b": "feat/x", "l": True, "cv": "v-b3"}], "p": True}
    segment = encode_metadata(metadata)
    assert "=" not in segment and "/" not in segment and "+" not in segment
    assert _decode(segment) == [("s[][b]", "feat/x"), ("s[][l]", "true"), ("s[][cv]", "v-b3"), ("p", "true")]


def test_metadata_of_a_tag_selector_and_of_a_wip_pact() -> None:
    pact = _select({"tag": "prod"})[0]
    assert verification_metadata(pact) == {"s": [{"t": "prod", "cv": "v-b1"}], "p": True}
    pact.wip = True
    assert verification_metadata(pact) == {"w": True}
    assert _decode(encode_metadata({"w": True})) == [("w", "true")]


# --- The GET query string (PFX-1.8, #6921) ----------------------------------------------------


def test_the_get_query_string_reads_as_the_post_body() -> None:
    from app.pact_selectors import for_verification_body_from_query

    items = [
        ("provider_version_branch", "main"),
        ("provider_version_tags[]", "prod"),
        ("provider_version_tags[]", "test"),
        ("include_pending_status", "true"),
        ("include_wip_pacts_since", "2026-11-01"),
        ("consumer_version_selectors[][tag]", "prod"),
        ("consumer_version_selectors[][latest]", "true"),
        ("consumer_version_selectors[][tag]", "test"),
        ("consumer_version_selectors[][main_branch]", "true"),
        ("consumer_version_selectors[][deployed_or_released]", "true"),
        ("consumer_version_selectors[][unknown]", "x"),
        ("ignored", "1"),
    ]
    assert for_verification_body_from_query(items) == {
        "providerVersionBranch": "main",
        "providerVersionTags": ["prod", "test"],
        "includePendingStatus": True,
        "includeWipPactsSince": "2026-11-01",
        "consumerVersionSelectors": [
            {"tag": "prod", "latest": True},
            # A repeated field (`tag`) starts the next selector, as Rack reads `[][…]`.
            {"tag": "test", "mainBranch": True, "deployedOrReleased": True},
        ],
    }


def test_indexed_selectors_stay_apart() -> None:
    from app.pact_selectors import for_verification_body_from_query

    items = [
        ("consumer_version_selectors[1][main_branch]", "true"),
        ("consumer_version_selectors[0][tag]", "prod"),
        ("consumer_version_selectors[0][latest]", "true"),
    ]
    assert for_verification_body_from_query(items)["consumerVersionSelectors"] == [
        {"tag": "prod", "latest": True},
        {"mainBranch": True},
    ]


def test_an_empty_query_string_is_an_empty_body() -> None:
    from app.pact_selectors import for_verification_body_from_query, parse_for_verification_request

    assert for_verification_body_from_query([]) == {}
    assert parse_for_verification_request({}) == parse_for_verification_request(None)


def test_a_flag_that_is_not_true_or_false_is_left_for_the_validator() -> None:
    from app.pact_selectors import for_verification_body_from_query, parse_for_verification_request

    body = for_verification_body_from_query([("consumer_version_selectors[][latest]", "yes")])
    assert body == {"consumerVersionSelectors": [{"latest": "yes"}]}
    with pytest.raises(Exception, match="latest"):
        parse_for_verification_request(body)

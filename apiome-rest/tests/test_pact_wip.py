"""Work-in-progress pacts — PFX-1.7 (#6920).

Unit tests of :func:`app.pact_wip.select_wip_pacts`, the Pact Broker's WIP selection
(docs.pact.io/go/wip): head pacts per consumer branch and tag, minus explicitly selected pacts,
minus pacts published before ``includeWipPactsSince``, minus pacts no longer pending for the
verifying build — and the notices, flags and link metadata a WIP pact carries.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, Optional, Sequence

from app.pact_pending import NO_EVIDENCE, PactSuccesses, PendingEvidence
from app.pact_selectors import (
    PactCandidate,
    build_notices,
    parse_for_verification_request,
    select_verifiable_pacts,
    short_description,
    verification_metadata,
)
from app.pact_wip import head_pacts, select_wip_pacts

NOV = datetime.datetime(2026, 11, 10, 9, 0, tzinfo=datetime.timezone.utc)
OCT = datetime.datetime(2026, 10, 1, 9, 0, tzinfo=datetime.timezone.utc)


def _candidate(
    seq: int,
    sha: str,
    branches: Sequence[str] = (),
    tags: Sequence[str] = (),
    consumer: str = "billing-service",
    name: str = "Billing Service",
    published_at: Optional[datetime.datetime] = NOV,
) -> PactCandidate:
    return PactCandidate(
        consumer_id=f"id-{consumer}",
        consumer_slug=consumer,
        consumer_name=name,
        consumer_main_branch="main",
        version_id=f"v-{seq}",
        version_number=f"1.{seq}.0",
        version_seq=seq,
        sha=sha,
        branches=tuple(branches),
        tags=tuple(tags),
        published_at=published_at,
    )


MAIN = _candidate(1, "a" * 64, ["main"])
FEAT_OLD = _candidate(2, "b" * 64, ["feat/invoice"])
FEAT = _candidate(3, "c" * 64, ["feat/invoice"])
TAGGED = _candidate(4, "d" * 64, tags=["experiment"])
CANDIDATES = [MAIN, FEAT_OLD, FEAT, TAGGED]


def _query(**extra: Any):
    body: Dict[str, Any] = {
        "consumerVersionSelectors": [{"mainBranch": True}],
        "providerVersionBranch": "main",
        "includePendingStatus": True,
        "includeWipPactsSince": "2026-11-01",
    }
    body.update(extra)
    return parse_for_verification_request({key: value for key, value in body.items() if value is not None})


def _wip(query=None, evidence: PendingEvidence = NO_EVIDENCE, candidates=CANDIDATES):
    query = query or _query()
    explicit = select_verifiable_pacts(candidates, query, evidence)
    return explicit, select_wip_pacts(candidates, explicit, query, evidence)


def test_head_pacts_are_the_latest_of_each_branch_and_tag() -> None:
    heads = [(h.selector.branch, h.selector.tag, h.candidate.version_number) for h in head_pacts(CANDIDATES)]
    assert heads == [
        ("feat/invoice", None, "1.3.0"),
        ("main", None, "1.1.0"),
        (None, "experiment", "1.4.0"),
    ]


def test_wip_pacts_are_unselected_pending_heads() -> None:
    explicit, wip = _wip()
    assert [p.candidate.version_number for p in explicit] == ["1.1.0"]
    assert [p.candidate.version_number for p in wip] == ["1.3.0", "1.4.0"]
    assert all(p.wip and p.pending for p in wip)


def test_nothing_is_added_without_include_wip_pacts_since() -> None:
    assert _wip(_query(includeWipPactsSince=None))[1] == []


def test_nothing_is_added_without_a_provider_branch_or_tags() -> None:
    assert _wip(_query(providerVersionBranch=None))[1] == []
    tagged = _wip(_query(providerVersionBranch=None, providerVersionTags=["dev"]))[1]
    assert [p.candidate.version_number for p in tagged] == ["1.3.0", "1.4.0"]


def test_pacts_published_before_the_date_are_left_out() -> None:
    old = _candidate(5, "e" * 64, ["feat/old"], published_at=OCT)
    undated = _candidate(6, "f" * 64, ["feat/undated"], published_at=None)
    wip = _wip(candidates=[MAIN, old, undated])[1]
    assert wip == []
    on_the_day = _candidate(7, "9" * 64, ["feat/today"], published_at=datetime.datetime(2026, 11, 1, 0, 0))
    assert [p.candidate.version_number for p in _wip(candidates=[MAIN, on_the_day])[1]] == ["1.7.0"]


def test_a_pact_the_branch_verified_is_not_wip() -> None:
    evidence = PendingEvidence(
        successes={"c" * 64: PactSuccesses(branches=frozenset({"main"}), first_success_at=OCT)},
        branch_created_at=OCT - datetime.timedelta(days=30),
    )
    wip = _wip(evidence=evidence)[1]
    assert [p.candidate.version_number for p in wip] == ["1.4.0"]


def test_a_new_provider_branch_does_not_pull_in_pacts_verified_before_it_existed() -> None:
    # main verified the feature pact before feat-p was created: not WIP for feat-p.
    evidence = PendingEvidence(
        successes={"c" * 64: PactSuccesses(branches=frozenset({"main"}), first_success_at=OCT)},
        branch_created_at=NOV,
    )
    wip = _wip(_query(providerVersionBranch="feat-p"), evidence=evidence)[1]
    assert [p.candidate.version_number for p in wip] == ["1.4.0"]


def test_a_pact_selected_explicitly_is_never_also_wip() -> None:
    query = _query(consumerVersionSelectors=[{"mainBranch": True}, {"branch": "feat/invoice"}])
    explicit, wip = _wip(query)
    assert [p.candidate.version_number for p in explicit] == ["1.1.0", "1.3.0"]
    assert [p.candidate.version_number for p in wip] == ["1.4.0"]


def test_one_content_heading_a_branch_and_a_tag_is_one_wip_pact() -> None:
    both = _candidate(8, "8" * 64, ["feat/x"], ["experiment"])
    (pact,) = _wip(candidates=[MAIN, both])[1]
    assert short_description(pact) == "latest from branch feat/x, latest with tag experiment"


def test_wip_pacts_of_several_consumers_are_ordered_by_consumer() -> None:
    web = _candidate(9, "7" * 64, ["feat/a"], consumer="checkout-web", name="Checkout Web")
    app = _candidate(10, "6" * 64, ["feat/b"], consumer="admin-app", name="Admin App")
    wip = _wip(candidates=[MAIN, web, app])[1]
    assert [p.candidate.consumer_name for p in wip] == ["Admin App", "Checkout Web"]


def test_a_wip_pact_reads_as_wip_in_its_notices_and_metadata() -> None:
    query = _query(includePendingStatus=False)
    explicit, wip = _wip(query)
    pact = wip[0]
    notices = build_notices(pact, "https://broker/pact", query, "Ledger API")
    assert notices[0] == {
        "when": "before_verification",
        "text": (
            "The pact at https://broker/pact is being verified because it is a 'work in progress' pact (ie. it is "
            "the pact for the latest version of Billing Service from branch 'feat/invoice' and is still in pending "
            "state). Read more at https://docs.pact.io/go/wip"
        ),
    }
    # The pending notices come with a WIP pact even when includePendingStatus was not sent.
    assert notices[1]["text"].startswith("This pact is in pending state for this version of Ledger API")
    assert len(notices) == 6
    assert verification_metadata(pact) == {"w": True}
    assert len(build_notices(explicit[0], "https://broker/pact", query, "Ledger API")) == 1

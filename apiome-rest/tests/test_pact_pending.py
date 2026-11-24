"""The pending rule — PFX-1.7 (#6920).

Unit tests of :func:`app.pact_pending.pact_is_pending` and of the pending flag
:func:`app.pact_selectors.select_verifiable_pacts` gives each pact, including the two worked
scenarios of the Pact Broker's pending-pacts page (docs.pact.io/go/pending): the main-branch
lifecycle and the feature-branch lifecycle.
"""

from __future__ import annotations

import datetime
from typing import Dict, Optional, Sequence

from app.pact_pending import NO_EVIDENCE, PactSuccesses, PendingEvidence, pact_is_pending, pending_provider_tags
from app.pact_selectors import (
    PactCandidate,
    build_notices,
    parse_for_verification_request,
    select_verifiable_pacts,
    verification_metadata,
)

SHA = "a" * 64
T0 = datetime.datetime(2026, 11, 1, 12, 0, tzinfo=datetime.timezone.utc)


def _at(hours: int) -> datetime.datetime:
    return T0 + datetime.timedelta(hours=hours)


def _evidence(
    successes: Optional[Dict[str, PactSuccesses]] = None, branch_created_at: Optional[datetime.datetime] = None
) -> PendingEvidence:
    return PendingEvidence(successes=successes or {}, branch_created_at=branch_created_at)


def _verified(branches: Sequence[str] = (), tags: Sequence[str] = (), at: int = 0) -> Dict[str, PactSuccesses]:
    return {SHA: PactSuccesses(branches=frozenset(branches), tags=frozenset(tags), first_success_at=_at(at))}


# --- The rule ----------------------------------------------------------------------------------


def test_a_never_verified_pact_is_pending_for_every_kind_of_build() -> None:
    assert pact_is_pending(SHA, "main", (), NO_EVIDENCE)
    assert pact_is_pending(SHA, None, ("prod",), NO_EVIDENCE)
    assert pact_is_pending(SHA, None, (), NO_EVIDENCE)


def test_a_success_on_the_branch_ends_pending_for_that_branch() -> None:
    evidence = _evidence(_verified(["main"]), branch_created_at=_at(-10))
    assert not pact_is_pending(SHA, "main", (), evidence)


def test_a_branch_that_existed_before_the_success_elsewhere_stays_pending() -> None:
    # feat-x was created at -10; main verified at 0: feat-x has not shown it can satisfy the pact.
    evidence = _evidence(_verified(["main"], at=0), branch_created_at=_at(-10))
    assert pact_is_pending(SHA, "feat-x", (), evidence)


def test_a_branch_created_after_the_success_elsewhere_inherits_it() -> None:
    evidence = _evidence(_verified(["main"], at=0), branch_created_at=_at(5))
    assert not pact_is_pending(SHA, "feat-y", (), evidence)


def test_a_brand_new_branch_inherits_every_earlier_success() -> None:
    # The branch is not recorded yet: it is created after everything that already happened.
    evidence = _evidence(_verified(["main"], at=0), branch_created_at=None)
    assert not pact_is_pending(SHA, "feat-new", (), evidence)


def test_a_success_at_the_moment_the_branch_was_created_does_not_count() -> None:
    evidence = _evidence(_verified(["main"], at=0), branch_created_at=_at(0))
    assert pact_is_pending(SHA, "feat-x", (), evidence)


def test_tags_need_a_success_for_each_tag() -> None:
    evidence = _evidence(_verified(tags=["dev"]))
    assert not pact_is_pending(SHA, None, ("dev",), evidence)
    assert pact_is_pending(SHA, None, ("dev", "prod"), evidence)
    assert pending_provider_tags(SHA, ("dev", "prod"), evidence) == ["prod"]
    assert pending_provider_tags("b" * 64, ("dev",), evidence) == ["dev"]


def test_without_branch_or_tags_any_success_ends_pending() -> None:
    assert not pact_is_pending(SHA, None, (), _evidence(_verified(["anything"])))


def test_pending_is_per_content() -> None:
    evidence = _evidence(_verified(["main"]), branch_created_at=_at(-1))
    assert not pact_is_pending(SHA, "main", (), evidence)
    assert pact_is_pending("b" * 64, "main", (), evidence)


def test_a_branch_wins_over_tags() -> None:
    # A request with both is judged by its branch, as the broker does.
    evidence = _evidence(_verified(tags=["dev"]), branch_created_at=_at(-1))
    assert pact_is_pending(SHA, "main", ("dev",), evidence)


# --- The pending flag on selected pacts -----------------------------------------------------------


def _candidate(seq: int, sha: str, branches: Sequence[str] = ("main",)) -> PactCandidate:
    return PactCandidate(
        consumer_id="c-1",
        consumer_slug="billing-service",
        consumer_name="Billing Service",
        consumer_main_branch="main",
        version_id=f"v-{seq}",
        version_number=f"1.{seq}.0",
        version_seq=seq,
        sha=sha,
        branches=tuple(branches),
    )


_BODY = {
    "consumerVersionSelectors": [{"mainBranch": True}, {"deployedOrReleased": True}],
    "includePendingStatus": True,
}


def _pending(candidates: Sequence[PactCandidate], branch: str, evidence: PendingEvidence) -> bool:
    query = parse_for_verification_request({**_BODY, "providerVersionBranch": branch})
    (pact,) = select_verifiable_pacts(candidates, query, evidence)
    return pact.pending


def test_the_broker_docs_main_branch_lifecycle() -> None:
    old, new = "0" * 64, "1" * 64
    # 1. The consumer's main pact has been verified by provider main.
    history = {old: PactSuccesses(branches=frozenset({"main"}), first_success_at=_at(0))}
    evidence = _evidence(dict(history), branch_created_at=_at(-100))
    assert _pending([_candidate(1, old)], "main", evidence) is False
    # 2–3. The consumer publishes a new main pact the provider does not support yet: pending.
    candidates = [_candidate(1, old), _candidate(2, new)]
    assert _pending(candidates, "main", evidence) is True
    # 4–5. Provider main implements it and publishes a success: no longer pending.
    history[new] = PactSuccesses(branches=frozenset({"main"}), first_success_at=_at(10))
    assert _pending(candidates, "main", _evidence(history, branch_created_at=_at(-100))) is False


def test_the_broker_docs_feature_branch_lifecycle() -> None:
    new = "1" * 64
    candidates = [_candidate(2, new)]
    main_created, feat_created = _at(-100), _at(-5)
    # 1–3. Nobody has verified the new pact: pending on main and on feat-x.
    assert _pending(candidates, "main", _evidence(branch_created_at=main_created)) is True
    assert _pending(candidates, "feat-x", _evidence(branch_created_at=feat_created)) is True
    # 4–5. feat-x implements it and publishes a success: not pending for feat-x any more …
    history = {new: PactSuccesses(branches=frozenset({"feat-x"}), first_success_at=_at(0))}
    assert _pending(candidates, "feat-x", _evidence(history, branch_created_at=feat_created)) is False
    # 6. … but still pending for main, which existed before and has not verified it.
    assert _pending(candidates, "main", _evidence(history, branch_created_at=main_created)) is True
    # 7. feat-x is merged and main publishes a success: not pending for main.
    history[new] = PactSuccesses(branches=frozenset({"feat-x", "main"}), first_success_at=_at(0))
    assert _pending(candidates, "main", _evidence(history, branch_created_at=main_created)) is False


def test_a_failed_verification_never_ends_pending() -> None:
    # Only successes are evidence (the store reads successful results only): no entry, pending.
    assert _pending([_candidate(1, SHA)], "main", _evidence(branch_created_at=_at(-1))) is True


def test_a_verified_pact_reads_not_pending_in_notices_and_metadata() -> None:
    query = parse_for_verification_request({**_BODY, "providerVersionBranch": "main"})
    evidence = _evidence(_verified(["main"]), branch_created_at=_at(-1))
    (pact,) = select_verifiable_pacts([_candidate(1, SHA)], query, evidence)
    notices = build_notices(pact, "https://broker/pact", query, "Ledger API")
    assert [notice["when"] for notice in notices] == ["before_verification", "before_verification"]
    assert notices[1]["text"].startswith(
        "This pact has previously been successfully verified by a version of Ledger API from branch 'main'."
    )
    assert verification_metadata(pact)["p"] is False


def test_without_evidence_every_selected_pact_is_pending() -> None:
    query = parse_for_verification_request({**_BODY, "providerVersionBranch": "main"})
    (pact,) = select_verifiable_pacts([_candidate(1, SHA)], query)
    assert pact.pending is True

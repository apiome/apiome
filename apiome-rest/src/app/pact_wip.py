"""Work-in-progress pacts — PFX-1.7 (#6920).

A consumer working on a feature branch publishes a pact the provider's selectors do not ask for
(they ask for ``mainBranch`` and what is deployed). Without help, the provider only learns about
it once the consumer merges. A verifier that sends ``includeWipPactsSince`` also gets these
**work-in-progress** (WIP) pacts, verified as pending so they can never fail its build.

:func:`select_wip_pacts` is the Pact Broker's selection (docs.pact.io/go/wip), pure:

1. Take the **head pacts**: for each consumer, the pact of its latest version on each branch, and
   of its latest version with each tag.
2. Drop the pacts the request's selectors already chose (same consumer and content).
3. Drop pacts published before ``includeWipPactsSince``.
4. Keep only pacts still **pending** for the verifying build
   (:func:`app.pact_pending.pact_is_pending`) — so a pact verified on ``main`` before this provider
   branch was created is not pulled into a new branch, and one this branch has verified drops out.

A WIP pact is always ``pending: true`` and ``wip: true``; its link carries ``{"w": true}`` so the
result a verifier publishes records it as WIP. WIP pacts need a ``providerVersionBranch`` or
``providerVersionTags``, as the pending state they rest on does; without either none are added.
"""

from __future__ import annotations

import datetime
from typing import Dict, List, Sequence, Set, Tuple

from .pact_pending import PendingEvidence, pact_is_pending
from .pact_selectors import (
    ConsumerVersionSelector,
    ForVerificationQuery,
    PactCandidate,
    SelectedBy,
    VerifiablePact,
)

__all__ = ["head_pacts", "select_wip_pacts"]


def head_pacts(candidates: Sequence[PactCandidate]) -> List[SelectedBy]:
    """The latest publication of each consumer branch and each consumer tag.

    Args:
        candidates: The provider's publications.

    Returns:
        One :class:`SelectedBy` per (consumer, branch) and (consumer, tag), carrying a
        ``branch``/``tag`` + ``latest`` selector naming why it is a head.
    """
    by_branch: Dict[Tuple[str, str], PactCandidate] = {}
    by_tag: Dict[Tuple[str, str], PactCandidate] = {}
    for candidate in candidates:
        for branch in candidate.branches:
            key = (candidate.consumer_id, branch)
            if key not in by_branch or candidate.version_seq > by_branch[key].version_seq:
                by_branch[key] = candidate
        for tag in candidate.tags:
            key = (candidate.consumer_id, tag)
            if key not in by_tag or candidate.version_seq > by_tag[key].version_seq:
                by_tag[key] = candidate
    heads = [
        SelectedBy(ConsumerVersionSelector(branch=branch, latest=True), candidate)
        for (_consumer, branch), candidate in sorted(by_branch.items(), key=lambda item: item[0][1])
    ]
    heads.extend(
        SelectedBy(ConsumerVersionSelector(tag=tag, latest=True), candidate)
        for (_consumer, tag), candidate in sorted(by_tag.items(), key=lambda item: item[0][1])
    )
    return heads


def _published_since(candidate: PactCandidate, since: datetime.date) -> bool:
    """Whether the pact was published on or after ``since`` (a pact without a date is kept out)."""
    if candidate.published_at is None:
        return False
    return candidate.published_at.date() >= since


def select_wip_pacts(
    candidates: Sequence[PactCandidate],
    explicit: Sequence[VerifiablePact],
    query: ForVerificationQuery,
    evidence: PendingEvidence,
) -> List[VerifiablePact]:
    """The work-in-progress pacts to add to a for-verification response.

    Args:
        candidates: The provider's publications.
        explicit: The pacts the request's selectors chose (:func:`select_verifiable_pacts`).
        query: The checked request; nothing is added without ``include_wip_pacts_since``.
        evidence: The provider's verification history.

    Returns:
        The WIP pacts (``pending`` and ``wip`` set), one per consumer and content, ordered by
        consumer name and then consumer version — to follow the explicit pacts.
    """
    since = query.include_wip_pacts_since
    if since is None or not (query.provider_version_branch or query.provider_version_tags):
        return []
    chosen: Set[Tuple[str, str]] = {(pact.candidate.consumer_id, pact.candidate.sha) for pact in explicit}
    merged: Dict[Tuple[str, str], VerifiablePact] = {}
    for head in head_pacts(candidates):
        candidate = head.candidate
        key = (candidate.consumer_id, candidate.sha)
        if key in chosen or not _published_since(candidate, since):
            continue
        if not pact_is_pending(candidate.sha, query.provider_version_branch, query.provider_version_tags, evidence):
            continue
        pact = merged.get(key)
        if pact is None:
            pact = merged[key] = VerifiablePact(candidate=candidate, pending=True, wip=True)
        elif candidate.version_seq > pact.candidate.version_seq:
            pact.candidate = candidate
        pact.selected_by.append(head)
    return sorted(merged.values(), key=lambda p: (p.candidate.consumer_name.casefold(), p.candidate.version_seq))
